"""Dispatch a logical model to existing physical channels."""
from __future__ import annotations

import time
from collections import OrderedDict
from contextlib import aclosing
from dataclasses import dataclass, replace

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


def physical_members(value, model):
    from .provider_profiles import profile

    for member in (value.get("routes") or {}).get(model, []):
        try:
            stored = profile(member["channel"], effective=False)
            if stored["provider"] == "virtual" or member["model"] not in stored["models"]:
                continue
            yield member, stored
        except ValueError:
            continue


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
    from .provider_responses import ResponsesStreamError

    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        if status == 429:
            from .agent_runtime import _model_retry_delay
            return _model_retry_delay(error, 0) if error.response.headers.get("Retry-After") else 60
        if status in (401, 402, 403):
            return 300
        if status == 404:
            return 60
    if isinstance(error, ResponsesStreamError) and error.code in {
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

    value = profile(config.virtual_channel)
    tried = set()
    last_error = None
    while True:
        candidates = []
        for member, _ in physical_members(value, config.model):
            key = member_key(member)
            health = _health.setdefault(key, Health())
            if key not in tried and health.cooldown <= time.monotonic():
                candidates.append(member)
        if not candidates:
            raise VirtualUnavailable("No available member for virtual model " + config.model) from last_error
        member = choose(value, config.model, candidates, config.virtual_session)
        key = member_key(member)
        tried.add(key)
        health = _health[key]
        try:
            actual = provider_config(*key)
        except ValueError as exc:
            health.cooldown = time.monotonic() + 60
            last_error = exc
            continue
        scope = _scope(actual)
        prepared = scoped_messages(messages, scope)
        emitted = False
        start = time.monotonic()
        health.active += 1
        try:
            if tools is not None:
                source = stream_model_with_tools(actual, prepared, tools=tools, **kwargs)
            elif actual.provider in {"anthropic", "google"} and kwargs.get("emit_finish_reason"):
                source = stream_native_tools(actual, prepared, tools=[], **kwargs)
            else:
                source = stream_model(actual, prepared, **kwargs)
            async with aclosing(source):
                async for event in source:
                    if not emitted:
                        elapsed = time.monotonic() - start
                        health.latency = elapsed if health.latency is None else health.latency * .8 + elapsed * .2
                        emitted = True
                    if isinstance(event, ModelUsage):
                        event = replace(event, channel=key[0], model=key[1])
                    elif isinstance(event, ModelThought) and event.kind != "responses_item":
                        event = replace(event, provider_data={**(event.provider_data or {}), "route_scope": scope})
                    elif isinstance(event, ModelToolCall) and (event.provider_data or {}).get("thoughtSignature"):
                        event = replace(event, provider_data={**event.provider_data, "route_scope": scope})
                    yield event
            if value.get("session_affinity", True) and config.virtual_session is not None:
                affinity_key = (value["name"], config.model, config.virtual_session)
                _affinity[affinity_key] = key
                _affinity.move_to_end(affinity_key)
                while len(_affinity) > 8192:
                    _affinity.popitem(last=False)
            return
        except Exception as exc:
            delay = cooldown_for(exc)
            if delay is not None:
                health.cooldown = time.monotonic() + delay
            # Once output is visible, replay would duplicate text/tool proposals.
            if emitted or delay is None:
                raise
            last_error = exc
        finally:
            health.active -= 1
