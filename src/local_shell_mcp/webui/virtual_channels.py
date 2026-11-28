"""Dispatch logical models through a DAG of virtual and physical channels."""
from __future__ import annotations

import time
from collections import OrderedDict
from contextlib import aclosing
from dataclasses import dataclass, replace
from functools import cache

STRATEGIES = ("priority", "round_robin", "weighted_round_robin", "least_connections", "least_latency")


class VirtualUnavailable(RuntimeError):
    """No member currently accepts the request; normal model backoff applies."""


@dataclass
class Health:
    active: int = 0
    cooldown: float = 0
    latency: float | None = None


_health: dict[tuple, Health] = {}
_cursors: dict[tuple, int] = {}
_affinity: OrderedDict = OrderedDict()


def member_key(member):
    return member["channel"], member["model"]


def direct_members(value, model, *, lookup=None):
    from .provider_profiles import profile

    if lookup is None:
        def lookup(channel):
            return profile(channel, effective=False)
    for member in (value.get("routes") or {}).get(model, []):
        try:
            stored = lookup(member["channel"])
            if member["model"] in stored["models"]:
                yield member, stored
        except ValueError:
            continue


def physical_members(value, model, *, lookup=None):
    """Visit each reachable physical model once; never follow a cyclic branch."""
    if lookup is None:
        from .provider_profiles import profile

        @cache
        def lookup(channel):
            return profile(channel, effective=False)
    visited = set()
    leaves = set()

    def walk(node, target, path):
        name = node["name"]
        key = (name, target)
        if name in path or key in visited:
            return
        visited.add(key)
        for member, stored in direct_members(node, target, lookup=lookup):
            if stored["provider"] == "virtual":
                yield from walk(stored, member["model"], path | {name})
            elif member_key(member) not in leaves:
                leaves.add(member_key(member))
                yield member, stored

    yield from walk(value, model, set())


def context_windows(value):
    result = {}
    for model in value["models"]:
        members = list(physical_members(value, model))
        limits = [(stored.get("model_contexts") or {}).get(member["model"]) for member, stored in members]
        if limits and all(type(limit) is int and limit > 0 for limit in limits):
            result[model] = min(limits)
    return result


def choose(value, model, candidates, session=None):
    key = (value["name"], model)
    affinity_key = (*key, session)
    if value.get("session_affinity", True) and affinity_key[-1] is not None:
        previous = _affinity.get(affinity_key)
        if previous is not None:
            for member in candidates:
                if member_key(member) == previous:
                    return member
    strategy = value["strategy"]
    if strategy == "priority":
        return candidates[0]
    if strategy == "least_connections":
        return min(candidates, key=lambda m: _health[member_key(m)].active)
    if strategy == "least_latency":
        # Sample unobserved members before comparing exponentially smoothed TTFT.
        return min(candidates, key=lambda m: (
            _health[member_key(m)].latency is not None,
            _health[member_key(m)].latency or 0,
            _health[member_key(m)].active))
    # A cursor is scoped to the virtual model, not the channel as a whole.
    total = sum(m["weight"] if strategy == "weighted_round_robin" else 1 for m in candidates)
    cursor = _cursors.get(key, 0) % total
    _cursors[key] = (cursor + 1) % total
    for member in candidates:
        cursor -= member["weight"] if strategy == "weighted_round_robin" else 1
        if cursor < 0:
            return member
    return candidates[-1]


def cooldown_for(error):
    import httpx

    from .agent_runtime import _retryable_model_error
    from .model_oauth import ReauthorizationRequired
    from .provider_errors import ProviderStreamError

    if isinstance(error, ReauthorizationRequired):
        return 300
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        if status == 429:
            from .agent_runtime import _model_retry_delay
            return _model_retry_delay(error, 0) if error.response.headers.get("Retry-After") else 60
        if status in (401, 402, 403):
            return 300
        if status == 404:
            return 60
    if isinstance(error, ProviderStreamError) and error.code in {
        "insufficient_quota", "quota_exceeded", "billing_hard_limit_reached",
        "usage_limit_reached", "authentication_error", "invalid_api_key", "permission_denied",
        "model_not_found",
    }:
        return 300
    if _retryable_model_error(error):
        return 10
    return None


def scoped_messages(messages, scope):
    """Keep provider-native signed reasoning only on its originating route."""
    result = []
    for message in messages:
        if message.get("role") != "assistant":
            result.append(message)
            continue
        item = message.copy()
        if "reasoning" in item:
            item["reasoning"] = [
                part for part in item["reasoning"]
                if part.get("type") == "responses_item" or part.get("route_scope") == scope
            ]
        if "tool_calls" in item:
            calls = []
            for call in item["tool_calls"]:
                metadata = call.get("provider_data") or {}
                if "thoughtSignature" in metadata and metadata.get("route_scope") != scope:
                    call = {**call, "provider_data": {
                        k: v for k, v in metadata.items() if k not in {"thoughtSignature", "route_scope"}
                    }}
                calls.append(call)
            item["tool_calls"] = calls
        result.append(item)
    return result


async def stream_virtual(config, messages, *, tools=None, **kwargs):
    from .provider_profiles import profile

    value = profile(config.virtual_channel, effective=False)
    # Agent overrides and previously saved settings can bypass conversation admission.
    if kwargs.get("temperature") is not None and kwargs["temperature"] > 1:
        from .sampling import validate_channel_sampling

        validate_channel_sampling({"temperature": kwargs["temperature"]}, config.virtual_channel, config.model)

    # All branches of one dispatch share the attempted physical leaves. A DAG
    # can reach the same provider/model through multiple independent pools.
    tried = set()
    profiles = {value["name"]: value}

    def lookup(channel):
        if channel not in profiles:
            profiles[channel] = profile(channel, effective=False)
        return profiles[channel]

    def available(node, target, path, memo, now):
        key = (node["name"], target)
        if node["name"] in path:
            return False
        if key not in memo:
            memo[key] = any(eligible(member, stored, path | {node["name"]}, memo, now)
                            for member, stored in direct_members(node, target, lookup=lookup))
        return memo[key]

    def eligible(member, stored, path, memo, now):
        key = member_key(member)
        if stored["provider"] == "virtual":
            return available(stored, key[1], path, memo, now)
        return key not in tried and _health.setdefault(key, Health()).cooldown <= now

    async def route(node, target, path):
        key = (node["name"], target)
        health = _health.setdefault(key, Health())
        health.active += 1
        started = time.monotonic()
        emitted = False
        try:
            async with aclosing(dispatch(node, target, path | {node["name"]})) as source:
                async for event in source:
                    if not emitted:
                        record_latency(health, started)
                        emitted = True
                    yield event
        finally:
            health.active -= 1

    async def dispatch(node, target, path):
        last_error = None
        exhausted = set()
        while True:
            memo = {}
            now = time.monotonic()
            candidates = []
            children = {}
            for member, stored in direct_members(node, target, lookup=lookup):
                key = member_key(member)
                if key not in exhausted and eligible(member, stored, path, memo, now):
                    candidates.append(member)
                    children[key] = stored
                    _health.setdefault(key, Health())
            if not candidates:
                raise VirtualUnavailable("No available member for virtual model " + target) from last_error
            member = choose(node, target, candidates, config.virtual_session)
            key = member_key(member)
            exhausted.add(key)
            stored = children[key]
            nested = stored["provider"] == "virtual"
            emitted = False
            try:
                if nested:
                    source = route(stored, key[1], path)
                else:
                    tried.add(key)
                    source = stream_physical(key)
                async with aclosing(source):
                    async for event in source:
                        emitted = True
                        yield event
                if node.get("session_affinity", True) and config.virtual_session is not None:
                    affinity_key = (node["name"], target, config.virtual_session)
                    _affinity[affinity_key] = key
                    _affinity.move_to_end(affinity_key)
                    while len(_affinity) > 8192:
                        _affinity.popitem(last=False)
                return
            except VirtualUnavailable as exc:
                # A child pool has exhausted its usable leaves. Do not impose
                # a separate cooldown on the pool: its leaves may recover first.
                if emitted:
                    raise
                last_error = exc

    async def stream_physical(key):
        from .provider_responses import _scope
        from .provider_tool_protocols import stream_native_tools
        from .providers import (
            ModelThought,
            ModelToolCall,
            ModelUsage,
            provider_config,
            stream_model,
            stream_model_with_tools,
        )

        health = _health[key]
        try:
            actual = replace(provider_config(*key), session_id=config.session_id)
        except ValueError as exc:
            health.cooldown = time.monotonic() + 60
            raise VirtualUnavailable("Unavailable physical model " + key[1]) from exc
        scope = _scope(actual)
        prepared = scoped_messages(messages, scope)
        emitted = False
        start = time.monotonic()
        health.active += 1
        try:
            options = dict(kwargs)
            if tools is not None:
                transport = stream_model_with_tools
                options["tools"] = tools
            elif actual.provider in {"anthropic", "google"} and kwargs.get("emit_finish_reason"):
                transport = stream_native_tools
                options["tools"] = []
            else:
                transport = stream_model
            if config.virtual_stream_wrapper is not None:
                source = config.virtual_stream_wrapper(transport, actual, prepared, physical_member=key, **options)
            else:
                source = transport(actual, prepared, **options)
            async with aclosing(source):
                async for event in source:
                    if not emitted:
                        record_latency(health, start)
                        emitted = True
                    if isinstance(event, ModelUsage):
                        event = replace(event, channel=key[0], model=key[1])
                    elif isinstance(event, ModelThought) and event.kind != "responses_item":
                        event = replace(event, provider_data={**(event.provider_data or {}), "route_scope": scope})
                    elif isinstance(event, ModelToolCall) and (event.provider_data or {}).get("thoughtSignature"):
                        event = replace(event, provider_data={**event.provider_data, "route_scope": scope})
                    yield event
        except Exception as exc:
            delay = cooldown_for(exc)
            if delay is not None:
                health.cooldown = time.monotonic() + delay
            if emitted or delay is None:
                raise
            raise VirtualUnavailable("Unavailable physical model " + key[1]) from exc
        finally:
            health.active -= 1

    async with aclosing(route(value, config.model, set())) as source:
        async for event in source:
            yield event


def record_latency(health, start):
    elapsed = time.monotonic() - start
    health.latency = elapsed if health.latency is None else health.latency * .8 + elapsed * .2
