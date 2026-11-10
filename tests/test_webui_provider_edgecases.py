"""Provider error/sse variants and secrets isolation for three model families."""

from __future__ import annotations

import json

import httpx
import pytest

from local_shell_mcp.webui.providers import (
    ProviderConfig,
    _require_https_or_loopback,
    provider_config,
    stream_model,
)


@pytest.fixture(autouse=True)
def _controller_state(tmp_path, monkeypatch):
    from local_shell_mcp.settings import get_settings

    # Provider configuration now consults the Controller's SQLite settings.
    # Keep that real startup state in a writable test-owned workspace.
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize("url", [
    "http://model.example/v1", "ftp://example.com/v1", "https://user:pass@example.test/v1",
    "https://example.test/v1#secrets", "not a URL", "/v1/chat/completions",
])
def test_refuse_insecure_or_ambiguous_model_endpoints(url):
    with pytest.raises(ValueError, match="URL|HTTPS"):
        _require_https_or_loopback(url)


def test_model_provider_env_validation(monkeypatch):
    monkeypatch.delenv("LOCAL_SHELL_MCP_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("LOCAL_SHELL_MCP_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_KEY", raising=False)
    with pytest.raises(ValueError, match="API key"):
        provider_config("openAI")
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        provider_config("anthropic")
    with pytest.raises(ValueError, match="GOOGLE"):
        provider_config("google")
    monkeypatch.setenv("OPENAI_API_KEY", "private")
    assert provider_config("openAI", "custom-model").url == "https://api.openai.com/v1/chat/completions"
    monkeypatch.setenv("GOOGLE_KEY", "key")
    assert provider_config("gemini", "gemini-2.5-flash").url.endswith("gemini-2.5-flash:streamGenerateContent?alt=sse")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
    assert provider_config("anthropic").model.startswith("claude")


def _fake_client(monkeypatch, frames, *, code=200):
    original = httpx.AsyncClient
    records = []

    def reply(request):
        records.append(request)
        return httpx.Response(code, text="\n\n".join(frames), headers={"content-type": "text/event-stream"})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(reply), **kwargs))
    return records


async def _collect(stream):
    return [fragment async for fragment in stream]


@pytest.mark.asyncio
async def test_openai_content_lists_and_malformed_sse_frames(monkeypatch):
    records = _fake_client(monkeypatch, [
        ": heartbeat",
        "data: not-a-json-object",
        'data: {"choices":[{"delta":{"content":[{"text":"first"},{"text":" second"}]}}]}',
        "data: [DONE]",
        'data: {"choices":[{"delta":{"content":"ignored"}}]}',
    ])
    config = ProviderConfig("openai", "model", "https://mock.example.test/v1/chat/completions", "key")
    assert await _collect(stream_model(config, [{"role": "user", "content": "hello"}], temperature=0.5)) == ["first", " second"]
    assert json.loads(records[0].content)["temperature"] == 0.5


@pytest.mark.asyncio
async def test_multiline_anthropic_without_system_prompt(monkeypatch):
    records = _fake_client(monkeypatch, [
        'data: {"type":"content_block_delta",\ndata: "delta":{"text":"hello"}}',
    ])
    config = ProviderConfig("anthropic", "claude", "https://mock.example.test/v1/messages", "key")
    assert await _collect(stream_model(config, [{"role": "user", "content": "hi"}], temperature=0.9)) == ["hello"]
    assert "system" not in json.loads(records[0].content)
    assert json.loads(records[0].content)["temperature"] == 0.9


@pytest.mark.asyncio
async def test_gemini_without_system_and_nontext_part(monkeypatch):
    records = _fake_client(monkeypatch, [
        'data: {"candidates":[{"content":{"parts":[{"text":"some"},{"binary":"ignored"}]}}]}',
    ])
    config = ProviderConfig("google", "gemini", "https://mock.example.test/generate", "key")
    assert await _collect(stream_model(config, [{"role": "user", "content": "hi"}], temperature=0.2)) == ["some"]
    body = json.loads(records[0].content)
    assert "systemInstruction" not in body
    assert body["generationConfig"]["temperature"] == 0.2


@pytest.mark.asyncio
async def test_unexpected_provider_and_upstream_http_failure_are_bounded(monkeypatch):
    _fake_client(monkeypatch, [], code=503)
    with pytest.raises(httpx.HTTPStatusError):
        await _collect(stream_model(ProviderConfig("openai", "mock", "https://mock.example.test/v1", "secret"),
                                    [{"role": "user", "content": "hi"}]))
    with pytest.raises(ValueError, match="Unsupported model provider"):
        await _collect(stream_model(ProviderConfig("unsupported", "mock", "https://mock.example.test/v1", "secret"), []))
