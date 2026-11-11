"""Dependency-light streaming model providers for the unified Python WebUI.

httpx is imported only when a model request is made. Model credentials are
server-side SQLite settings (with environment defaults), not part of an Agent's serialized config.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import quote, urlsplit


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model: str
    url: str
    token: str
    timeout_s: float = 180.0


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
    """Resolve the retained client's direct endpoint and saved Agent consistently."""
    selected = (agent or {}).get("provider") or payload.get("provider")
    if selected:
        return str(selected)
    endpoint = payload.get("endpoint")
    return str(endpoint) if endpoint in {"openai", "anthropic", "google", "gemini"} else "openai"


def provider_config(provider: str, model: str | None = None) -> ProviderConfig:
    from .provider_profiles import profile

    kind = provider.strip().lower()
    if kind in {"openai-compatible", "custom", "ollama", "azureopenai"}:
        kind = "openai"
    if kind == "gemini":
        kind = "google"
    if kind not in {"openai", "anthropic", "google"}:
        raise ValueError(f"Unsupported provider: {provider}")
    value = profile(kind)
    token, base = value.get("api_key", ""), value["base_url"]
    name = model or value["models"][0]
    if kind == "openai":
        if not token and urlsplit(base).hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("An OpenAI-compatible model API key is required")
        url = _require_https_or_loopback(base.rstrip("/") + "/chat/completions")
    elif kind == "anthropic":
        if not token:
            raise ValueError("ANTHROPIC_API_KEY is required")
        url = _require_https_or_loopback(base.rstrip("/") + "/messages")
    else:
        if not token:
            raise ValueError("GOOGLE_KEY or GOOGLE_API_KEY is required")
        if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for char in name):
            raise ValueError("Unsupported Gemini model identifier")
        url = _require_https_or_loopback(base.rstrip("/") + f"/models/{quote(name)}:streamGenerateContent?alt=sse")
    return ProviderConfig(kind, name, url, token)


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


def _messages_for_google(messages: list[dict]) -> tuple[list[dict], str]:
    items: list[dict] = []
    systems: list[str] = []
    for item in messages:
        content = str(item.get("content") or "")
        role = item.get("role")
        if role == "system":
            systems.append(content)
        elif role in {"user", "assistant"}:
            items.append({"role": "model" if role == "assistant" else "user", "parts": [{"text": content}]})
    return items, "\n".join(systems)


def _messages_for_anthropic(messages: list[dict]) -> tuple[list[dict], str]:
    systems = [str(item.get("content") or "") for item in messages if item.get("role") == "system"]
    items = [item for item in messages if item.get("role") in {"user", "assistant"}]
    return items, "\n".join(systems)


async def stream_model(
    config: ProviderConfig,
    messages: list[dict],
    *,
    max_tokens: int = 2048,
    temperature: float | None = None,
) -> AsyncIterator[str]:
    """Stream user-visible answer text without buffering the provider response."""
    import httpx

    headers = {"accept": "text/event-stream", "content-type": "application/json"}
    body: dict = {"model": config.model, "stream": True}
    if config.provider == "openai":
        if config.token:
            headers["Authorization"] = f"Bearer {config.token}"
        # Local OpenAI-compatible servers may run without an API key. An
        # empty `Bearer ` value is illegal HTTP and breaks streaming.
        body["messages"] = messages
        body["max_completion_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature
    elif config.provider == "anthropic":
        headers["x-api-key"] = config.token
        headers["anthropic-version"] = "2023-06-01"
        items, instructions = _messages_for_anthropic(messages)
        body = {"model": config.model, "messages": items, "max_tokens": max_tokens, "stream": True}
        if instructions:
            body["system"] = instructions
        if temperature is not None:
            body["temperature"] = temperature
    elif config.provider == "google":
        headers["x-goog-api-key"] = config.token
        items, instructions = _messages_for_google(messages)
        body = {"contents": items, "generationConfig": {"maxOutputTokens": max_tokens}}
        if instructions:
            body["systemInstruction"] = {"parts": [{"text": instructions}]}
        if temperature is not None:
            body["generationConfig"]["temperature"] = temperature
    else:
        raise ValueError("Unsupported model provider")
    timeout = httpx.Timeout(connect=20, read=config.timeout_s, write=30, pool=10)
    async with (
        httpx.AsyncClient(timeout=timeout) as http,
        http.stream("POST", config.url, json=body, headers=headers) as response,
    ):
        response.raise_for_status()
        async for frame in _data_frames(response):
            if frame == "[DONE]":
                return
            try:
                event = json.loads(frame)
            except json.JSONDecodeError:
                continue
            if "error" in event:
                raise RuntimeError("Model provider rejected the generation request")
            if config.provider == "openai":
                for choice in event.get("choices", []):
                    content = choice.get("delta", {}).get("content")
                    if isinstance(content, str) and content:
                        yield content
                    elif isinstance(content, list):
                        for part in content:
                            if isinstance(part, dict) and isinstance(part.get("text"), str):
                                yield part["text"]
            elif config.provider == "anthropic":
                if event.get("type") == "content_block_delta":
                    text = event.get("delta", {}).get("text")
                    if isinstance(text, str) and text:
                        yield text
            else:
                for candidate in event.get("candidates", []):
                    for part in (candidate.get("content") or {}).get("parts", []):
                        text = part.get("text")
                        if isinstance(text, str) and text:
                            yield text


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
    max_tokens: int = 2048,
    temperature: float | None = None,
) -> AsyncIterator[str | ModelToolCall]:
    """Stream OpenAI text and reconstruct complete tool calls, bounded by size.

    Unsupported providers do not receive tool declarations. Their ordinary
    text-stream behavior is preserved until their native tool protocols exist.
    """
    if tools and config.provider in {"anthropic", "google"}:
        from .provider_tool_protocols import stream_native_tools

        async for event in stream_native_tools(config, messages, tools=tools, max_tokens=max_tokens, temperature=temperature):
            yield event
        return
    if not tools or config.provider != "openai":
        async for text in stream_model(config, messages, max_tokens=max_tokens, temperature=temperature):
            yield text
        return

    import httpx

    headers = {"accept": "text/event-stream", "content-type": "application/json"}
    if config.token:
        headers["Authorization"] = f"Bearer {config.token}"
    body: dict = {
        "model": config.model, "stream": True, "messages": messages,
        "max_completion_tokens": max_tokens, "tools": tools,
        "tool_choice": "auto", "parallel_tool_calls": False,
    }
    if temperature is not None:
        body["temperature"] = temperature
    timeout = httpx.Timeout(connect=20, read=config.timeout_s, write=30, pool=10)
    pending: dict[int, dict[str, str]] = {}
    async with (
        httpx.AsyncClient(timeout=timeout) as client,
        client.stream("POST", config.url, headers=headers, json=body) as response,
    ):
        response.raise_for_status()
        async for frame in _data_frames(response):
            if frame == "[DONE]":
                break
            try:
                event = json.loads(frame)
            except json.JSONDecodeError:
                continue
            if "error" in event:
                raise RuntimeError("Model provider rejected the generation request")
            for choice in event.get("choices", []):
                delta = choice.get("delta") or {}
                content = delta.get("content")
                if isinstance(content, str) and content:
                    yield content
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and isinstance(part.get("text"), str):
                            yield part["text"]
                for fragment in delta.get("tool_calls") or []:
                    index = fragment.get("index")
                    if type(index) is not int or not 0 <= index < 4:
                        raise ValueError("Invalid model tool call index")
                    tool = pending.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    if fragment.get("id"):
                        tool["id"] += str(fragment["id"])
                    function = fragment.get("function") or {}
                    tool["name"] += str(function.get("name") or "")
                    tool["arguments"] += str(function.get("arguments") or "")
                    if len(tool["id"]) > 128 or len(tool["name"]) > 128 or len(tool["arguments"]) > 8192:
                        raise ValueError("Model tool call exceeds allowed size")
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
