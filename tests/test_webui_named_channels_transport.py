"""Named-provider HTTP transport and Builder sampling contract regression."""

from __future__ import annotations

import json

import httpx
import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui.agent_runtime import AgentContext, AgentLoopState, run_agent_loop
from local_shell_mcp.webui.provider_profiles import _validate
from local_shell_mcp.webui.providers import provider_config, stream_model
from local_shell_mcp.webui.routes import _repo


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,path,header,payload_key,frame", [
    ("openai", "/v1/chat/completions", "authorization", "top_p",
     'data: {"choices":[{"delta":{"content":"ok"}}]}'),
    ("anthropic", "/v1/messages", "x-api-key", "top_p",
     'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"ok"}}'),
    ("google", "/v1beta/models/gemini-model:streamGenerateContent", "x-goog-api-key", "topP",
     'data: {"candidates":[{"content":{"parts":[{"text":"ok"}]}}]}'),
])
async def test_named_channel_real_http_transport_uses_independent_auth_and_parameters(
    tmp_path, monkeypatch, kind, path, header, payload_key, frame
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    get_settings.cache_clear()
    try:
        name = "Research " + kind
        config = _validate({"name": name, "provider": kind,
                            "base_url": "https://gateway.invalid/v1beta" if kind == "google" else "https://gateway.invalid/v1",
                            "models": ["gemini-model"], "api_key": "secret-" + kind})
        _repo().save_setting("__lsm_controller__", "model.channel." + name, config)
        seen = []
        original = httpx.AsyncClient

        def reply(request):
            seen.append(request)
            return httpx.Response(200, text=frame + "\n\n", headers={"content-type": "text/event-stream"})

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(reply), **kw))
        output = [item async for item in stream_model(provider_config(name),
                  [{"role": "user", "content": "Hello"}], max_tokens=144, top_p=0.73, temperature=0.4)]
        assert output == ["ok"]
        assert len(seen) == 1
        sent = seen[0]
        assert sent.url.path == path
        assert sent.headers[header] == (("Bearer " if kind == "openai" else "") + "secret-" + kind)
        body = json.loads(sent.content)
        params = body["generationConfig"] if kind == "google" else body
        assert params[payload_key] == 0.73
        assert params["temperature"] == 0.4
        assert params["maxOutputTokens" if kind == "google" else "max_tokens" if kind == "anthropic" else "max_completion_tokens"] == 144
        assert body["model"] == "gemini-model" if kind != "google" else "model" not in body
        assert "secret-" + kind not in str(body)
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_agent_builder_camel_case_sampling_values_reach_tool_model():
    from local_shell_mcp.webui.providers import ProviderConfig

    expected = {"tools": [{"type": "function", "function": {"name": "plan_manage"}}],
                "max_tokens": 256, "temperature": 0.6, "top_p": 0.8}
    called = []

    async def tool_stream(_config, _history, **kwargs):
        called.append(kwargs)
        yield "ok"

    async def no_tools(*args, **kwargs):
        raise AssertionError("Expected Builder to retain its native tool mode")
        yield "never"  # pragma: no cover

    async def ignore(_message):
        pass

    state = AgentLoopState(AgentContext(
        ProviderConfig("openai", "model", "https://gateway.invalid/v1", "secret"),
        expected["tools"], {"maxTokens": 256, "topP": 0.8, "temperature": 0.6}
    ), [{"role": "user", "content": "Hello"}])
    await run_agent_loop(state, stream_tools=tool_stream, stream_text=no_tools,
                         dispatch=no_tools, on_text=ignore)
    assert called == [expected]
    assert state.completed is True
