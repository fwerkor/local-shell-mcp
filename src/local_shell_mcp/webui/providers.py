"""Dependency-light streaming model providers for the unified Python WebUI.

httpx is imported only when a model request is made. Model credentials are
server-side SQLite settings (with environment defaults), not part of an Agent's serialized config.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from urllib.parse import quote, urlsplit


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model: str
    url: str
    token: str
    timeout_s: float = 180.0
    include_usage: bool = False
    sampling: dict = field(default_factory=dict)


def _require_https_or_loopback(value: str) -> str:
    parsed = urlsplit(value)
    if not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Invalid model provider URL")
    if parsed.scheme == "https":
        return value
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return value
    raise ValueError("A model provider must use HTTPS or the local loopback interface")


def selected_provider(payload: dict, agent: dict | None = None) -> str:
    """Use the exact configured endpoint identity for history and Agents."""
    selected = (agent or {}).get("provider") or payload.get("provider")
    if selected:
        return str(selected)
    endpoint = payload.get("endpoint")
    return str(endpoint) if isinstance(endpoint, str) and endpoint not in {"agents", ""} else "openai"


def provider_config(provider: str, model: str | None = None) -> ProviderConfig:
    from .provider_profiles import profile

    value = profile(provider)
    kind = value["provider"]
    token, base = value.get("api_key", ""), value["base_url"]
    if not model and not value["models"]:
        raise ValueError("No available models in this channel")
    name = model or value["models"][0]
    if kind == "openai":
        if not token and urlsplit(base).hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("An OpenAI-compatible model API key is required")
        url = _require_https_or_loopback(base.rstrip("/") + "/chat/completions")
    elif kind == "anthropic":
        if not token:
            raise ValueError("ANTHROPIC_API_KEY is required")
        url = _require_https_or_loopback(base.rstrip("/") + "/messages")
    elif kind == "google":
        if not token:
            raise ValueError("GOOGLE_KEY or GOOGLE_API_KEY is required")
        if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for char in name):
            raise ValueError("Unsupported Gemini model identifier")
        url = _require_https_or_loopback(base.rstrip("/") + f"/models/{quote(name)}:streamGenerateContent?alt=sse")
    else:
        raise ValueError("Unsupported model provider")
    return ProviderConfig(kind, name, url, token,
                          include_usage=kind == 'openai' and (
                              value.get('include_usage') is not False),
                          sampling=(value.get('model_sampling') or {}).get(name, {}))


async def _data_frames(response) -> AsyncIterator[str]:
    """Parse multi-line SSE data frames, ignoring comments and heartbeat lines."""
    data: list[str] = []
    async for raw in response.aiter_lines():
        line = raw.rstrip("\r")
        if line == "":
            if data:
                yield "\n".join(data)
                data.clear()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
    if data:
        yield "\n".join(data)


@asynccontextmanager
async def _provider_stream(client, url: str, *, body: dict, headers: dict):
    """Request streaming usage where supported; retry only explicit unsupported-option errors.

    A 4xx caused by a key, model, or tool schema is never retried or hidden.
    The fallback starts before any tokens have been delivered to the caller.
    """
    async with client.stream("POST", url, json=body, headers=headers) as response:
        if response.status_code in {400, 422} and 'stream_options' in body:
            problem = (await response.aread())[:4096].lower()
            if b'stream_options' in problem or b'include_usage' in problem:
                without_usage = {key: value for key, value in body.items() if key != 'stream_options'}
                async with client.stream("POST", url, json=without_usage, headers=headers) as retry:
                    retry.raise_for_status()
                    yield retry
                return
        response.raise_for_status()
        yield response


def _openai_messages(messages: list[dict]) -> list[dict]:
    """Return the model wire DTO without steer-only UI metadata."""
    from .mcp_projection import openai_wire_messages

    return openai_wire_messages(messages)


def _messages_for_google(messages: list[dict]) -> tuple[list[dict], str]:
    from .provider_tool_protocols import native_messages

    return native_messages(messages, "google")


def _messages_for_anthropic(messages: list[dict]) -> tuple[list[dict], str]:
    from .provider_tool_protocols import native_messages

    return native_messages(messages, "anthropic")


def _anthropic_omits_sampling_parameters(model: str) -> bool:
    """Match LibreChat model-aware sampling restrictions for newer Claude models.

    Builder hides incompatible controls but retains saved Agent parameters.
    Accept both Claude version naming formats; do not parse model dates as minors.
    """
    if re.search(r"claude-(?:fable|mythos)[-.]?\d", model):
        return True
    for family, minimum in (("opus", (4, 7)), ("sonnet", (5, 0)), ("haiku", (5, 5))):
        expressions = (
            rf"claude-{family}[-.]?(\d+)(?:[-.](\d{{1,2}})(?!\d))?",
            rf"claude-(\d+)(?:[-.](\d{{1,2}})(?!\d))?-{family}",
        )
        for expression in expressions:
            match = re.search(expression, model)
            if match and (int(match[1]), int(match[2] or 0)) >= minimum:
                return True
    return False


@dataclass(frozen=True)
class ModelFinish:
    """Provider-reported stop reason, emitted only to explicit summary callers."""
    provider: str
    reason: str


@dataclass(frozen=True)
class ModelUsage:
    """Confirmed provider token counts, never a local token estimate."""
    provider: str
    input_tokens: int
    output_tokens: int


def _usage_frame(provider: str, event: dict, previous: ModelUsage | None = None) -> ModelUsage | None:
    if provider == 'openai':
        usage = event.get('usage')
        if not isinstance(usage, dict):
            return previous
        raw_input = usage.get('prompt_tokens', usage.get('input_tokens'))
        raw_output = usage.get('completion_tokens', usage.get('output_tokens'))
    elif provider == 'anthropic':
        kind = event.get('type')
        if kind == 'message_start':
            metadata = event.get('message')
            usage = metadata.get('usage') if isinstance(metadata, dict) else None
        elif kind == 'message_delta':
            usage = event.get('usage')
        else:
            return previous
        if not isinstance(usage, dict):
            return previous
        raw_input = usage.get('input_tokens', previous.input_tokens if previous else None)
        if 'input_tokens' in usage and kind == 'message_start' and type(raw_input) is int:
            # Anthropic reports cache reads/writes separately from ordinary
            # input_tokens. Counts include all provider-confirmed input, while
            # cache billing remains an independent accounting problem.
            cached_read = usage.get('cache_read_input_tokens', 0)
            cached_write = usage.get('cache_creation_input_tokens', 0)
            if type(cached_read) is not int or type(cached_write) is not int:
                return previous
            raw_input += cached_read + cached_write
        raw_output = usage.get('output_tokens', previous.output_tokens if previous else None)
    else:
        usage = event.get('usageMetadata')
        if not isinstance(usage, dict):
            return previous
        raw_input = usage.get('promptTokenCount')
        raw_output = usage.get('candidatesTokenCount')
    if (type(raw_input) is not int or raw_input < 0 or raw_input > 10**12
            or type(raw_output) is not int or raw_output < 0 or raw_output > 10**12):
        return previous
    return ModelUsage(provider, raw_input, raw_output)


def _openai_reasoning_fragments(delta: dict) -> list[str]:
    """Extract visible reasoning from common OpenAI-compatible chat deltas.

    Prefer the single text field when vendors also send structured copies;
    encrypted reasoning, signatures and token counts are not readable text.
    """
    for key in ("reasoning_content", "reasoning"):
        value = delta.get(key)
        if isinstance(value, str) and value:
            return [value]
    details = delta.get("reasoning_details")
    if not isinstance(details, list):
        return []
    return [part["text"] for part in details if isinstance(part, dict)
            and part.get("type") in {"reasoning.text", "text"}
            and isinstance(part.get("text"), str) and part["text"]]


async def stream_model(
    config: ProviderConfig,
    messages: list[dict],
    *,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    emit_finish_reason: bool = False,
) -> AsyncIterator[str | ModelUsage | ModelFinish | ModelThought]:
    """Stream user-visible answer text without buffering the provider response."""
    import httpx

    from .mcp_projection import openai_wire_messages, project_artifact_messages

    headers = {"accept": "text/event-stream", "content-type": "application/json"}
    body: dict = {"model": config.model, "stream": True}
    if config.provider == "openai":
        if config.token:
            headers["Authorization"] = f"Bearer {config.token}"
        # Local OpenAI-compatible servers may run without an API key. An
        # empty `Bearer ` value is illegal HTTP and breaks streaming.
        body["messages"] = openai_wire_messages(project_artifact_messages(messages, config.provider))
        if max_tokens is not None:
            body["max_completion_tokens"] = max_tokens
        if config.include_usage:
            body['stream_options'] = {'include_usage': True}
        if temperature is not None:
            body["temperature"] = temperature
        if top_p is not None:
            body["top_p"] = top_p
    elif config.provider == "anthropic":
        headers["x-api-key"] = config.token
        headers["anthropic-version"] = "2023-06-01"
        items, instructions = _messages_for_anthropic(messages)
        body = {"model": config.model, "messages": items, "max_tokens": max_tokens if max_tokens is not None else 16384, "stream": True}
        if instructions:
            body["system"] = instructions
        if not _anthropic_omits_sampling_parameters(config.model):
            if temperature is not None:
                body["temperature"] = temperature
            if top_p is not None:
                body["top_p"] = top_p
    elif config.provider == "google":
        headers["x-goog-api-key"] = config.token
        items, instructions = _messages_for_google(messages)
        body = {"contents": items, "generationConfig": {}}
        if max_tokens is not None:
            body["generationConfig"]["maxOutputTokens"] = max_tokens
        if instructions:
            body["systemInstruction"] = {"parts": [{"text": instructions}]}
        if temperature is not None:
            body["generationConfig"]["temperature"] = temperature
        if top_p is not None:
            body["generationConfig"]["topP"] = top_p
    else:
        raise ValueError("Unsupported model provider")
    timeout = httpx.Timeout(connect=20, read=config.timeout_s, write=30, pool=10)
    usage_snapshot = None
    finish_reason = None
    async with (
        httpx.AsyncClient(timeout=timeout) as http,
        _provider_stream(http, config.url, body=body, headers=headers) as response,
    ):
        async for frame in _data_frames(response):
            if frame == "[DONE]":
                break
            try:
                event = json.loads(frame)
            except json.JSONDecodeError:
                continue
            if "error" in event:
                raise RuntimeError("Model provider rejected the generation request")
            usage_snapshot = _usage_frame(config.provider, event, usage_snapshot)
            if config.provider == "openai":
                for choice in event.get("choices", []):
                    if isinstance(choice.get('finish_reason'), str):
                        finish_reason = choice['finish_reason']
                    delta = choice.get("delta") or {}
                    for thought in _openai_reasoning_fragments(delta):
                        yield ModelThought("thinking", text=thought)
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        yield content
                    elif isinstance(content, list):
                        for part in content:
                            if isinstance(part, dict) and isinstance(part.get("text"), str):
                                yield part["text"]
            elif config.provider == "anthropic":
                if event.get('type') == 'message_delta':
                    reason = (event.get('delta') or {}).get('stop_reason')
                    if isinstance(reason, str):
                        finish_reason = reason
                if event.get("type") == "content_block_delta":
                    delta = event.get("delta") or {}
                    if delta.get("type") == "thinking_delta" and isinstance(delta.get("thinking"), str):
                        yield ModelThought("thinking", text=delta["thinking"])
                    elif delta.get("type") == "signature_delta" and isinstance(delta.get("signature"), str):
                        yield ModelThought("signature", signature=delta["signature"])
                    text = delta.get("text")
                    if isinstance(text, str) and text:
                        yield text
            else:
                for candidate in event.get("candidates", []):
                    if isinstance(candidate.get('finishReason'), str):
                        finish_reason = candidate['finishReason']
                    for part in (candidate.get("content") or {}).get("parts", []):
                        text = part.get("text")
                        if isinstance(text, str) and text:
                            if part.get("thought"):
                                yield ModelThought("thinking", text=text)
                            else:
                                yield text

    if usage_snapshot is not None:
        yield usage_snapshot
    if emit_finish_reason:
        yield ModelFinish(config.provider, finish_reason or 'unknown')


@dataclass(frozen=True)
class ModelThought:
    """Provider reasoning event stored in canonical history, never UI answer text."""
    kind: str
    text: str = ""
    signature: str = ""
    data: str = ""


@dataclass(frozen=True)
class ModelToolCall:
    """A complete model-requested function call, never partial SSE input."""

    call_id: str
    name: str
    arguments: dict
    provider_data: dict | None = None

    def history_metadata(self) -> dict:
        return {"provider_data": self.provider_data} if self.provider_data else {}


async def stream_model_with_tools(
    config: ProviderConfig,
    messages: list[dict],
    *,
    tools: list[dict],
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
) -> AsyncIterator[str | ModelToolCall | ModelUsage]:
    """Stream OpenAI text and reconstruct complete tool calls, bounded by size.

    Unsupported providers do not receive tool declarations. Their ordinary
    text-stream behavior is preserved until their native tool protocols exist.
    """
    if tools and config.provider in {"anthropic", "google"}:
        from .provider_tool_protocols import stream_native_tools

        async for event in stream_native_tools(config, messages, tools=tools, max_tokens=max_tokens, temperature=temperature, top_p=top_p):
            yield event
        return
    if not tools or config.provider != "openai":
        async for event in stream_model(config, messages, max_tokens=max_tokens, temperature=temperature, top_p=top_p):
            yield event
        return

    import httpx

    from .mcp_projection import openai_wire_messages, project_artifact_messages

    messages = openai_wire_messages(project_artifact_messages(messages, config.provider))
    headers = {"accept": "text/event-stream", "content-type": "application/json"}
    if config.token:
        headers["Authorization"] = f"Bearer {config.token}"
    body: dict = {
        "model": config.model, "stream": True, "messages": messages,
        "tools": tools,
        "tool_choice": "auto", "parallel_tool_calls": True,
    }
    if max_tokens is not None:
        body["max_completion_tokens"] = max_tokens
    if config.include_usage:
        body['stream_options'] = {'include_usage': True}
    if temperature is not None:
        body["temperature"] = temperature
    if top_p is not None:
        body["top_p"] = top_p
    timeout = httpx.Timeout(connect=20, read=config.timeout_s, write=30, pool=10)
    pending: dict[int, dict[str, str]] = {}
    usage_snapshot = None
    async with (
        httpx.AsyncClient(timeout=timeout) as client,
        _provider_stream(client, config.url, body=body, headers=headers) as response,
    ):
        async for frame in _data_frames(response):
            if frame == "[DONE]":
                break
            try:
                event = json.loads(frame)
            except json.JSONDecodeError:
                continue
            if "error" in event:
                raise RuntimeError("Model provider rejected the generation request")
            usage_snapshot = _usage_frame(config.provider, event, usage_snapshot)
            for choice in event.get("choices", []):
                delta = choice.get("delta") or {}
                for thought in _openai_reasoning_fragments(delta):
                    yield ModelThought("thinking", text=thought)
                content = delta.get("content")
                if isinstance(content, str) and content:
                    yield content
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and isinstance(part.get("text"), str):
                            yield part["text"]
                for fragment in delta.get("tool_calls") or []:
                    index = fragment.get("index")
                    if type(index) is not int or index < 0:
                        raise ValueError("Invalid model tool call index")
                    tool = pending.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    if fragment.get("id"):
                        tool["id"] += str(fragment["id"])
                    function = fragment.get("function") or {}
                    tool["name"] += str(function.get("name") or "")
                    tool["arguments"] += str(function.get("arguments") or "")
    for index in sorted(pending):
        tool = pending[index]
        if not tool["id"] or not tool["name"]:
            raise ValueError("Incomplete model tool call")
        try:
            params = json.loads(tool["arguments"] or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON in model tool call") from exc
        if not isinstance(params, dict):
            raise ValueError("Model tool arguments must be an object")
        yield ModelToolCall(tool["id"], tool["name"], params)
    if usage_snapshot is not None:
        yield usage_snapshot
