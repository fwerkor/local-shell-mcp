"""Context budgeting, resumable summaries, provider failures and raw history isolation."""
from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from local_shell_mcp import hosted_chat
from local_shell_mcp.hosted_chat_context import (
    abbreviate_summary_input,
    compact_messages,
    context_messages,
    context_window,
    estimate_tokens,
    summary_tokens,
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


@pytest.mark.asyncio
async def test_grown_multibyte_summary_cannot_be_saved_over_token_budget():
    from copy import deepcopy

    # Even a syntactically valid 8K-character recap can exceed the context
    # budget after UTF-8 encoding, when the tail was sized for an empty recap.
    messages = [
        {"role": "user", "content": "older " * 1600},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "latest " * 600},
    ]
    before = deepcopy(messages)
    async def summarize(_old, _text):
        return "语" * 8000

    with pytest.raises(ValueError, match="context window"):
        await compact_messages(messages, None, 8192, "system", [], summarize, force=True)
    assert messages == before


@pytest.mark.asyncio
async def test_valid_new_summary_stays_within_budget_after_compacting():
    from local_shell_mcp.hosted_chat_context import context_messages, estimate_tokens

    messages = [
        {"role": "user", "content": "old " * 1600},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "latest " * 600},
    ]
    async def summarize(_old, _text):
        return "Small summary /repo/project.py"

    context = await compact_messages(messages, None, 8192, "system", [], summarize, force=True)
    assert context
    assert estimate_tokens({"messages": context_messages("system", messages, context), "tools": []}) <= int(8192 * 0.8)


@pytest.mark.asyncio
async def test_multibyte_recap_and_tool_output_fit_summarizer_request_budget():
    old_recap = "😀" * 8000
    messages = [
        {"role": "user", "content": "previous turn"},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "inspect screenshot"},
        {"role": "tool", "content": "🧪" * 40000 + " state_id=abc123"},
        {"role": "assistant", "content": "inspected"},
        {"role": "user", "content": "next turn"},
    ]
    before = deepcopy(messages)
    requests = []

    async def summarize(previous, batch):
        requests.append((previous, batch))
        assert summary_tokens(previous, batch) <= int(32768 * 0.8)
        return "recap with state_id=abc123"

    updated = await compact_messages(
        messages, {"summary": old_recap, "through": 2},
        32768, "system", [], summarize, force=True,
    )
    assert updated and updated["through"] == 5
    assert requests
    assert any("[oversized message abbreviated for summary]" in batch for _, batch in requests)
    assert any("state_id=abc123" in batch for _, batch in requests)
    assert messages == before


def test_abbreviated_summary_input_never_exceeds_utf8_budget():
    recap = "😀" * 8000
    text = "🧪" * 40000 + " final-marker"
    budget = int(32768 * 0.8)
    shortened = abbreviate_summary_input(recap, text, budget)
    assert summary_tokens(recap, shortened) <= budget
    assert shortened.startswith("🧪")
    assert shortened.endswith("final-marker")
    assert len(shortened) < len(text)
    with pytest.raises(ValueError, match="summarizer context window"):
        abbreviate_summary_input(recap, text, int(8192 * 0.8))


@pytest.mark.parametrize("size", [8192, 16384])
@pytest.mark.asyncio
async def test_full_mcp_catalog_fits_small_windows_via_discovery(size, monkeypatch):
    """The actual 48-tool catalog must never block a short 8K/16K chat."""
    from local_shell_mcp.hosted_chat_tools import TOOL_SEARCH_NAME
    from local_shell_mcp.tools import build_mcp

    available = [hosted_chat.tool_schema(t) for t in
                 hosted_chat.visible_tools(await build_mcp().list_tools())]
    assert len(available) >= 40
    transcript = [{"role": "user", "content": "Run a shell command"}]
    assert estimate_tokens({"messages": [
        {"role": "system", "content": hosted_chat.chat_prompt()}, *transcript],
        "tools": available}) > int(size * 0.8)

    calls = []
    requests = []
    saved = []

    class FakeSession:
        async def list_tools(self):
            class Tool:
                def __init__(self, schema):
                    self.schema = schema

                def model_dump(self, **_):
                    return {
                        "name": self.schema["function"]["name"],
                        "description": self.schema["function"]["description"],
                        "inputSchema": self.schema["function"]["parameters"],
                    }
            return SimpleNamespace(tools=[Tool(s) for s in available])

        async def call_tool(self, name, args, **_):
            calls.append((name, args))
            return SimpleNamespace(isError=False, model_dump=lambda **_: {
                "content": [{"type": "text", "text": "command executed"}], "isError": False,
            })

    @asynccontextmanager
    async def fake_mcp(*_, **__):
        yield FakeSession()

    class FakeHttp:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            pass

    async def candidates(endpoint):
        return [(endpoint + "/chat/completions", {}, {})]

    def call(name, args, call_id):
        import json
        return {"id": call_id, "type": "function", "function": {
            "name": name, "arguments": json.dumps(args),
        }}

    async def reply(_http, _url, _headers, _ext, payload):
        requests.append(deepcopy(payload))
        assert estimate_tokens({"messages": payload["messages"],
                                "tools": payload.get("tools", [])}) <= int(size * 0.8)
        schemas = {s["function"]["name"] for s in payload.get("tools", [])}
        if len(requests) == 1:
            assert schemas == {TOOL_SEARCH_NAME}
            searches = [call(TOOL_SEARCH_NAME, {"query": "run_shell"}, "search")]
            if size == 8192:
                searches.append(call(TOOL_SEARCH_NAME, {"query": "file_read"}, "search2"))
            message = {"tool_calls": searches, "content": ""}
        elif len(requests) == 2:
            assert "run_shell" in schemas
            commands = [call("run_shell", {"command": "echo ok"}, "run")]
            if size == 8192:
                assert "file_read" in schemas
                commands.append(call("file_read", {"path": "sample.txt"}, "read"))
            message = {"tool_calls": commands, "content": ""}
        else:
            message = {"content": "Completed"}
        return {"choices": [{"message": message}]}

    async def checkpoint(messages, events):
        saved.append((deepcopy(messages), deepcopy(events)))

    monkeypatch.setattr(hosted_chat, "mcp_session", fake_mcp)
    monkeypatch.setattr(hosted_chat.httpx, "AsyncClient", lambda **_: FakeHttp())
    monkeypatch.setattr(hosted_chat, "model_request_targets", candidates)
    monkeypatch.setattr(hosted_chat, "model_response_json", reply)

    output = await hosted_chat.complete_turn(
        base_url="http://controller", bearer="", endpoint="https://example.org/v1",
        key="key", model="test-model", messages=transcript, tools_enabled=True,
        context_size=size, session_id="s_123", checkpoint=checkpoint,
    )
    assert len(requests) == 3
    expected = [("run_shell", {"command": "echo ok", "logical_session_id": "s_123"})]
    if size == 8192:
        expected.append(("file_read", {"path": "sample.txt", "logical_session_id": "s_123"}))
    assert calls == expected
    assert output["messages"][-1]["content"] == "Completed"
    names = [e["name"] for e in output["events"]]
    assert names == ([TOOL_SEARCH_NAME, TOOL_SEARCH_NAME, "run_shell", "file_read"]
                     if size == 8192 else [TOOL_SEARCH_NAME, "run_shell"])
    assert saved[-1][0] == output["messages"]
    assert "matches" in output["events"][0]["result"]["content"][0]["text"]


def test_tool_discovery_does_not_leak_hidden_tools_and_is_budgeted():
    from local_shell_mcp.hosted_chat_tools import (
        TOOL_SEARCH_NAME,
        choose_tool_schemas,
        discover_tools,
    )

    def schema(name, description="Edit files"):
        return {"type": "function", "function": {
            "name": name, "description": description,
            "parameters": {"type": "object", "properties": {}},
        }}

    tools = [schema("file_edit"), schema("file_read"), schema("file_write")]
    tools.extend(schema(f"other_{i}", "large" * 500) for i in range(40))
    info, names = discover_tools("file edit", tools, 8192)
    assert names[0] == "file_edit"
    assert all(name in {s["function"]["name"] for s in tools} for name in names)
    assert "secret_tool" not in str(info)
    prompt = [{"role": "user", "content": "edit a file"}]
    chosen = choose_tool_schemas(tools, prompt, 8192, names)
    assert chosen[0]["function"]["name"] == TOOL_SEARCH_NAME
    assert "file_edit" in [s["function"]["name"] for s in chosen]
    assert estimate_tokens({"messages": prompt, "tools": chosen}) <= int(8192 * 0.8)
    with pytest.raises(ValueError, match="query"):
        discover_tools("", tools, 8192)
