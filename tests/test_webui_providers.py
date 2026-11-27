"""Model adapters are network-free in tests and do not import at bootstrap."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import pytest

from local_shell_mcp.webui.providers import (
    ModelFinish,
    ProviderConfig,
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
    with pytest.raises(RuntimeError, match="provider generation failed") as exc:
        await _collect(stream_model(config, [{"role": "user", "content": "Hello"}]))
    assert "very-private" not in str(exc.value)


@pytest.mark.asyncio
async def test_loopback_openai_with_no_key_omits_authorization(monkeypatch):
    captured = {}
    _mock_client(monkeypatch, ['data: {"choices":[{"delta":{"content":"ok"}}]}', 'data: [DONE]'], captured)
    config = ProviderConfig("openai", "local", "http://127.0.0.1:11434/v1/chat/completions", "")
    assert await _collect(stream_model(config, [{"role": "user", "content": "hi"}])) == ["ok"]
    assert "authorization" not in captured["request"].headers


def test_provider_configuration_does_not_require_writable_default_workspace(tmp_path, monkeypatch):
    from pathlib import Path

    original = Path.mkdir

    def deny_default_workspace(path, *args, **kwargs):
        if path == Path("/workspace"):
            raise PermissionError("Default workspace is not writable")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", deny_default_workspace)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODEL_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.delenv("LOCAL_SHELL_MCP_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert provider_config("ollama", "local-model").model == "local-model"
    assert (tmp_path / ".local-shell-mcp" / "lsm.sqlite3").is_file()


@pytest.mark.asyncio
async def test_openai_stream_stop_reason_is_available_only_when_requested(monkeypatch):
    captured = {}
    _mock_client(monkeypatch, [
        'data: {"choices":[{"delta":{"content":"Partial summary"}}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"length"}]}',
        'data: [DONE]',
    ], captured)
    profile = ProviderConfig('openai', 'test-model', 'https://api.example.invalid/v1/chat/completions', 'key')
    messages = [{'role': 'user', 'content': 'Summarize'}]
    assert await _collect(stream_model(profile, messages)) == ['Partial summary']
    assert await _collect(stream_model(profile, messages, emit_finish_reason=True)) == [
        'Partial summary', ModelFinish('openai', 'length')]


@pytest.mark.asyncio
@pytest.mark.parametrize("with_tools", [False, True])
@pytest.mark.parametrize("base, expected", [
    ("https://opencode.ai/inference/go/openai/v1", "conversation-1"),
    ("https://opencode.ai/inference/openai/v1", "conversation-1"),
    ("https://opencode.ai.example.invalid/inference/go/openai/v1", None),
    ("https://example.invalid/v1", None),
])
async def test_model_session_headers(monkeypatch, with_tools, base, expected):
    from local_shell_mcp.webui.providers import (
        MODEL_USER_AGENT,
        bind_model_session,
        stream_model_with_tools,
    )

    captured = {}
    _mock_client(monkeypatch, ['data: {"choices":[{"delta":{"content":"OK"}}]}',
                               'data: [DONE]'], captured)
    config = bind_model_session(
        ProviderConfig("openai", "test", base + "/chat/completions", "key"), "conversation-1")
    messages = [{"role": "user", "content": "Hi"}]
    if with_tools:
        tools = [{"type": "function", "function": {"name": "test", "parameters": {"type": "object"}}}]
        await _collect(stream_model_with_tools(config, messages, tools=tools))
    else:
        await _collect(stream_model(config, messages))
    headers = captured["request"].headers
    assert headers["user-agent"] == MODEL_USER_AGENT
    assert headers.get("x-opencode-session") == expected
    assert headers.get("x-opencode-client") == ("local-shell-mcp" if expected else None)


def test_model_session_binding_is_stable_and_isolates_tasks():
    from local_shell_mcp.webui.providers import bind_model_session, model_request_headers

    config = ProviderConfig("openai", "test", "https://opencode.ai/inference/go/openai/v1/chat/completions", "key")
    parent = bind_model_session(config, "conversation-1")
    child = bind_model_session(parent, "conversation-1", "/subagent:call-1")
    assert child.session_id == bind_model_session(config, "conversation-1", "/subagent:call-1").session_id
    assert child.session_id != parent.session_id
    assert child.session_id != bind_model_session(config, "conversation-1", "automatic-memory").session_id
    assert child.session_id != bind_model_session(config, "conversation-2", "/subagent:call-1").session_id
    assert config.session_id is None
    assert "x-opencode-session" not in model_request_headers(config)
    assert model_request_headers(config)["x-opencode-client"] == "local-shell-mcp"
