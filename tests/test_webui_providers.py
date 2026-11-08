"""Model adapters are network-free in tests and do not import at bootstrap."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import pytest

from local_shell_mcp.webui.providers import ProviderConfig, provider_config, stream_model


def test_provider_url_guard_and_environment(monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODEL_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.delenv("LOCAL_SHELL_MCP_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    selected = provider_config("ollama", "gemma3")
    assert selected.url == "http://127.0.0.1:11434/v1/chat/completions"
    assert selected.model == "gemma3"
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODEL_BASE_URL", "http://untrusted.invalid/v1")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODEL_API_KEY", "secret")
    with pytest.raises(ValueError, match="HTTPS"):
        provider_config("openAI")
    with pytest.raises(ValueError, match="Unsupported provider"):
        provider_config("unknown")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "token")
    assert provider_config("anthropic").provider == "anthropic"
    monkeypatch.setenv("GOOGLE_API_KEY", "google-secret")
    assert provider_config("google").provider == "google"
    with pytest.raises(ValueError, match="Unsupported Gemini"):
        provider_config("google", "../../../unsafe")


async def _collect(stream: AsyncIterator[str]) -> list[str]:
    return [part async for part in stream]


def _mock_client(monkeypatch, frames, captured):
    original = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, text="\n\n".join(frames) + "\n\n", headers={"content-type": "text/event-stream"})

    def factory(**kwargs):
        return original(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_openai_chat_stream_parses_multiple_chunks(monkeypatch):
    captured: dict = {}
    frames = [
        'data: {"choices":[{"delta":{"content":"Hello"}}]}',
        'data: {"choices":[{"delta":{"content":" world"}}]}',
        'data: [DONE]',
    ]
    _mock_client(monkeypatch, frames, captured)
    config = ProviderConfig("openai", "test-model", "https://api.example.invalid/v1/chat/completions", "private")
    actual = await _collect(stream_model(config, [{"role": "user", "content": "Hi"}]))
    assert actual == ["Hello", " world"]
    assert captured["request"].headers["authorization"] == "Bearer private"
    body = json.loads(captured["request"].content)
    assert body["messages"][0]["role"] == "user"
    assert body["stream"] is True


@pytest.mark.asyncio
async def test_anthropic_stream_and_system_message(monkeypatch):
    captured: dict = {}
    _mock_client(monkeypatch, [
        'data: {"type":"message_start"}',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"text"}}',
    ], captured)
    config = ProviderConfig("anthropic", "claude-test", "https://api.example.invalid/v1/messages", "secret")
    actual = await _collect(stream_model(config, [{"role": "system", "content": "Be concise"},
                                                  {"role": "user", "content": "Hello"}]))
    assert actual == ["text"]
    assert captured["request"].headers["x-api-key"] == "secret"
    payload = json.loads(captured["request"].content)
    assert payload["system"] == "Be concise"
    assert payload["messages"] == [{"role": "user", "content": "Hello"}]


@pytest.mark.asyncio
async def test_gemini_stream_and_model_roles(monkeypatch):
    captured: dict = {}
    _mock_client(monkeypatch, [
        'data: {"candidates":[{"content":{"parts":[{"text":"token"}]}}]}',
    ], captured)
    config = ProviderConfig("google", "gemini-test", "https://api.example.invalid:443/path", "google-key")
    result = await _collect(stream_model(config, [
        {"role": "system", "content": "Be concise"},
        {"role": "assistant", "content": "Okay"},
        {"role": "user", "content": "Hello"},
    ]))
    assert result == ["token"]
    assert captured["request"].headers["x-goog-api-key"] == "google-key"
    payload = json.loads(captured["request"].content)
    assert payload["systemInstruction"]["parts"][0]["text"] == "Be concise"
    assert [item["role"] for item in payload["contents"]] == ["model", "user"]


@pytest.mark.asyncio
async def test_provider_error_does_not_echo_secrets(monkeypatch):
    captured: dict = {}
    _mock_client(monkeypatch, ['data: {"error":{"message":"secret rejected"}}'], captured)
    config = ProviderConfig("openai", "test", "https://api.example.invalid/v1/chat/completions", "very-private")
    with pytest.raises(RuntimeError, match="Model provider rejected") as exc:
        await _collect(stream_model(config, [{"role": "user", "content": "Hello"}]))
    assert "very-private" not in str(exc.value)
