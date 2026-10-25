"""Context budgeting, resumable summaries, provider failures and raw history isolation."""
from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from local_shell_mcp import hosted_chat
from local_shell_mcp.hosted_chat_context import (
    compact_messages,
    context_messages,
    context_window,
    estimate_tokens,
    validate_context,
)
from local_shell_mcp.settings import get_settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    # CI runs as an unprivileged user; never create the default /workspace.
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "file")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_context_window_validation_and_estimator():
    for value in (True, "32768", 8191, 1_000_001, 0, None):
        with pytest.raises(ValueError, match="Context window"):
            context_window(value)
    assert context_window(8192) == 8192
    assert estimate_tokens("你好" * 1000) > 800
    assert estimate_tokens("a" * 1000) > 300
    for record in ("bad", {"through": 8, "summary": "x"}, {"through": -1},
                   {"through": True, "summary": "x"}, {"through": 2},
                   {"through": 0, "summary": "x" * 8001}):
        with pytest.raises(ValueError, match="Invalid saved context"):
            validate_context(record, 3)


def history(turns: int, size: int = 380) -> list[dict]:
    return [part for i in range(turns) for part in (
        {"role": "user", "content": f"Request {i}: " + ("substantial context " * size)},
        {"role": "assistant", "content": f"Done {i}: /repo/feature_{i}.py"},
    )]


@pytest.mark.asyncio
async def test_auto_compact_preserves_latest_turn_and_entire_persisted_history():
    original = history(12, size=95)
    transcript = deepcopy(original)
    summaries = []

    async def summarize(previous, batch):
        summaries.append((previous, batch))
        return f"Recap {len(summaries)}: constraints and files preserved /repo/file.py"

    updated = await compact_messages(transcript, None, 8192, "system", [], summarize)
    assert updated is not None
    assert 0 < updated["through"] < len(transcript) - 1
    assert updated["through"] % 2 == 0
    assert summaries
    prompt = context_messages("system", transcript, updated)
    assert "Recap" in prompt[1]["content"]
    assert prompt[-1] == transcript[-1]
    assert prompt[2]["role"] == "user"
    assert transcript == original
    # A new turn can update the durable summary without re-sending old raw turns.
    previous_cut = updated["through"]
    more = [*transcript, *history(10, size=95)]
    next_context = await compact_messages(more, updated, 8192, "system", [], summarize)
    assert next_context and next_context["through"] > previous_cut
    assert any(previous.startswith("Recap") for previous, _ in summaries)
    assert len(context_messages("system", more, next_context)) < len(more)
    assert more[:len(original)] == original


@pytest.mark.asyncio
async def test_manual_compact_and_no_history_behavior():
    transcript = history(4, size=2)
    calls = []

    async def summarize(previous, batch):
        calls.append((previous, batch))
        return "Updated memory"

    assert await compact_messages(transcript, None, 32768, "system", [], summarize) is None
    compacted = await compact_messages(transcript, None, 32768, "system", [], summarize, force=True)
    assert compacted and compacted["summary"] == "Updated memory"
    assert compacted["through"] >= 2
    assert len(calls) == 1
    assert await compact_messages(history(1), None, 32768, "system", [], summarize, force=True) is None


@pytest.mark.asyncio
async def test_compact_provider_failure_does_not_change_stored_context_or_history():
    transcript = history(10, size=200)
    saved = {"summary": "Previous memory", "through": 2}
    baseline = deepcopy((transcript, saved))

    async def fail(_previous, _batch):
        raise TimeoutError("model unavailable")

    with pytest.raises(TimeoutError):
        await compact_messages(transcript, saved, 8192, "system", [], fail)
    assert (transcript, saved) == baseline
    async def bad(_previous, _batch):
        return " "
    with pytest.raises(ValueError, match="summary"):
        await compact_messages(transcript, saved, 8192, "system", [], bad)
    assert (transcript, saved) == baseline


@pytest.mark.asyncio
async def test_oversized_recent_turn_refused_without_silent_dropping():
    recent = [{"role": "user", "content": "x" * 40000}]
    async def unused(*_):
        raise AssertionError("should not summarize latest turn")
    with pytest.raises(ValueError, match="context window"):
        await compact_messages(recent, None, 8192, "system", [], unused)
    with pytest.raises(ValueError, match="context window"):
        await compact_messages([*history(2), *recent], None, 8192, "system", [], unused)


@pytest.mark.asyncio
async def test_agent_loop_compacts_and_checkpoints_separately(monkeypatch):
    requests = []
    context_checkpoints = []
    transcript_checkpoints = []

    @asynccontextmanager
    async def fake_mcp(*_, **__):
        yield SimpleNamespace(calls=[])

    class FakeHttp:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            return None

    async def candidates(endpoint):
        return [(endpoint + "/chat/completions", {}, {})]

    async def model_response(http, url, headers, extensions, payload):
        del http, url, headers, extensions
        requests.append(deepcopy(payload))
        if payload["messages"][0]["content"].startswith("Summarize"):
            return {"choices": [{"message": {"content": "Goal: finish code; Files: /repo/important.py"}}]}
        return {"choices": [{"message": {"content": "Final response"}}]}

    monkeypatch.setattr(hosted_chat, "mcp_session", fake_mcp)
    monkeypatch.setattr(hosted_chat.httpx, "AsyncClient", lambda **kwargs: FakeHttp())
    monkeypatch.setattr(hosted_chat, "model_request_targets", candidates)
    monkeypatch.setattr(hosted_chat, "model_response_json", model_response)

    full = [*history(8, size=200), {"role": "user", "content": "Next step"}]

    async def checkpoint(messages, events):
        transcript_checkpoints.append(deepcopy(messages))
        assert events == []

    async def checkpoint_context(value):
        context_checkpoints.append(deepcopy(value))

    result = await hosted_chat.complete_turn(
        base_url="http://controller", bearer="", endpoint="https://example.org/v1",
        key="key", model="model", messages=full, tools_enabled=False,
        context_size=8192, checkpoint=checkpoint, context_checkpoint=checkpoint_context,
    )
    assert context_checkpoints and context_checkpoints[-1]["through"] > 0
    assert transcript_checkpoints[-1] == [*full, {"role": "assistant", "content": "Final response"}]
    normal_requests = [p for p in requests if p["messages"][0]["content"].startswith("You are")]
    assert len(normal_requests) == 1
    assert normal_requests[0]["messages"][1]["content"].startswith("Conversation recap")
    assert normal_requests[0]["messages"][-1]["content"] == "Next step"
    assert len(normal_requests[0]["messages"]) < len(full)
    assert result["messages"][-1]["content"] == "Final response"
