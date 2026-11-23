"""No implicit agent-step or output-token caps when the user leaves limits empty."""

import json

import httpx
import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.agent_runtime import AgentContext, AgentLoopState, run_agent_loop
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.providers import ProviderConfig, stream_model, stream_model_with_tools


@pytest.mark.asyncio
async def test_unconfigured_agent_can_continue_past_legacy_step_limit():
    state = AgentLoopState(
        AgentContext(ProviderConfig("openai", "test", "https://example.invalid", ""), [], {}),
        [{"role": "user", "content": "continue"}],
        step=100,
    )

    async def stream(_profile, _history, **kwargs):
        assert kwargs == {"temperature": None}
        yield "finished"

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("unreachable")
        yield ""

    async def on_text(_text):
        pass

    result = await run_agent_loop(
        state, stream_tools=forbidden, stream_text=stream,
        dispatch=forbidden, on_text=on_text,
    )
    assert state.step == 101
    assert result[-1] == {"role": "assistant", "content": "finished"}


def test_clearing_saved_agent_limit_persists_unlimited(tmp_path):
    repo = AgentRepository(SQLiteDatabase(tmp_path / "state"))
    agent = repo.create("owner", {
        "provider": "openai", "model": "test", "recursion_limit": 25,
    })
    assert agent["recursion_limit"] == 25
    agent = repo.update("owner", agent["id"], {"recursion_limit": None})
    assert agent["recursion_limit"] is None
    assert repo.get("owner", agent["id"])["recursion_limit"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,tools", [
    ("openai", False),
    ("openai", True),
    ("google", False),
    ("google", True),
])
async def test_provider_receives_no_output_token_cap_unless_configured(provider, tools, monkeypatch):
    sent = []
    original = httpx.AsyncClient

    def handler(request):
        sent.append(json.loads(request.content))
        if provider == "openai":
            event = {"choices": [{"delta": {"content": "ok"}}]}
        else:
            event = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
        return httpx.Response(
            200, text="data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n",
            headers={"content-type": "text/event-stream"},
        )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(handler), **kwargs,
    ))
    config = ProviderConfig(provider, "test", "https://provider.invalid", "secret")
    messages = [{"role": "user", "content": "hello"}]
    if tools:
        declarations = [{"type": "function", "function": {
            "name": "do_work", "description": "test",
            "parameters": {"type": "object", "properties": {}},
        }}]
        items = [item async for item in stream_model_with_tools(
            config, messages, tools=declarations,
        )]
    else:
        items = [item async for item in stream_model(config, messages)]
    assert "ok" in items
    assert len(sent) == 1
    if provider == "openai":
        assert "max_completion_tokens" not in sent[0]
    else:
        assert "maxOutputTokens" not in sent[0]["generationConfig"]


@pytest.mark.asyncio
async def test_explicit_large_output_limit_is_not_silently_clamped(monkeypatch):
    sent = []
    original = httpx.AsyncClient

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(
            200, text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n',
            headers={"content-type": "text/event-stream"},
        )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(handler), **kwargs,
    ))
    config = ProviderConfig("openai", "test", "https://provider.invalid", "secret")
    assert "ok" in [item async for item in stream_model(
        config, [{"role": "user", "content": "hello"}], max_tokens=200000,
    )]
    assert sent[0]["max_completion_tokens"] == 200000
