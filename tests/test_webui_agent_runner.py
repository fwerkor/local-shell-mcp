"""Integrated source Agent execution with real LSM tools, human review and SQLite."""

import asyncio

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import shared_database
from local_shell_mcp.webui import agent_runner, generation_routes
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.agent_runtime import AgentSuspended, RuntimeSafetyError
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig
from local_shell_mcp.webui.routes import _repo


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    database = shared_database(get_settings().state_dir)
    store = GenerationStore(database)
    profile = ProviderConfig("openai", "test", "https://test.invalid", "")
    monkeypatch.setattr(agent_runner, "provider_config", lambda kind, model: profile)
    monkeypatch.setattr(generation_routes, "provider_config", lambda kind, model: profile)
    _repo().save_setting("local", "agent.machine_policy.global", {"local": "write"})
    yield tmp_path, database, store, profile
    get_settings.cache_clear()


async def _wait_tasks():
    tasks = list(generation_routes._TASKS.values())
    if tasks:
        await asyncio.wait_for(asyncio.gather(*tasks), 5)


@pytest.mark.asyncio
async def test_real_batch_edit_and_reject_resume_updates_only_reviewed_file(runtime, monkeypatch):
    root, database, store, profile = runtime
    agent = AgentRepository(database).create("local", {
        "name": "Writer", "provider": "openAI", "model": "test", "tools": ["file_write"],
    })
    _repo().save_setting("local", "endpoints", {"agents": {"toolApproval": {
        "enabled": True, "ask": ["file_write"],
    }}})
    generation, _ = store.begin("local", {"text": "write two files"}, agent)
    requests = 0

    async def model(profile, history, **kwargs):
        nonlocal requests
        requests += 1
        if requests == 1:
            yield "Checking with you first."
            yield ModelToolCall("first", "file_write", {"path": "old.txt", "content": "old"})
            yield ModelToolCall("second", "file_write", {"path": "rejected.txt", "content": "no"})
        else:
            messages = [message for message in history if message.get("role") == "tool"]
            assert len(messages) == 2
            assert messages[1]["content"] == "Blocked: keep it unchanged"
            yield "Completed approved edits."

    monkeypatch.setattr(generation_routes, "stream_model_with_tools", model)
    await generation_routes._run_model("local", generation, profile, parent_agent=agent,
                                       granted_scopes=frozenset({"shell:read", "shell:write"}))
    pending = store.pending_action("local", generation.run_id)
    assert len(pending["payload"]["action_requests"]) == 2
    assert not (root / "old.txt").exists()
    app = Starlette(routes=generation_routes.generation_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/agents/chat/resume", json={
            "conversationId": generation.conversation_id, "actionId": pending["actionId"],
            "decisions": [{"tool_call_id": "first", "decision": "edit",
                           "editedArguments": {"path": "reviewed.txt", "content": "approved"}},
                          {"tool_call_id": "second", "decision": "reject", "reason": "keep it unchanged"}],
        })
        assert response.status_code == 200, response.text
        await _wait_tasks()
    assert (root / "reviewed.txt").read_text() == "approved"
    assert not (root / "old.txt").exists() and not (root / "rejected.txt").exists()
    assert store.latest("local", generation.conversation_id).status == "complete"
    assert store.approved_review("local", generation.run_id) is None
    final = store.events("local", generation.run_id)[-1][1]["responseMessage"]["text"]
    assert final == "Checking with you first.Completed approved edits."


@pytest.mark.asyncio
async def test_completed_native_call_is_not_reexecuted_after_node_checkpoint_restart(runtime, monkeypatch):
    _, database, store, profile = runtime
    generation, _ = store.begin("local", {"text": "read"})
    count = 0
    texts = []

    async def model(profile, history, **kwargs):
        if history[-1].get("role") != "tool":
            yield ModelToolCall("once", "file_read", {"path": "input.txt"})
        else:
            yield "done"

    async def text_model(*args, **kwargs):
        yield "unused"

    async def execute(*args, **kwargs):
        nonlocal count
        count += 1
        return "native result"

    async def emit(text):
        texts.append(text)

    from local_shell_mcp.webui import lsm_tool_registry
    monkeypatch.setattr(lsm_tool_registry, "call_tool", execute)
    runner = AgentRunner("local", generation, database, store, scopes={"shell:read", "shell:write"},
                         grant_expires=None, stream_tools=model, stream_text=text_model, on_text=emit, profile=profile)
    original_save = runner._save

    async def crash_after_tools(state, calls):
        if not calls and state.messages[-1].get("role") == "tool":
            raise OSError("process stopped after result write")
        await original_save(state, calls)

    runner._save = crash_after_tools
    with pytest.raises(OSError, match="process stopped"):
        await runner.run(store.history("local", generation.conversation_id))
    assert count == 1
    restarted = AgentRunner("local", generation, database, store, scopes={"shell:read", "shell:write"},
                            grant_expires=None, stream_tools=model, stream_text=text_model, on_text=emit, profile=profile)
    messages = await restarted.run([])
    assert count == 1 and messages[-1]["content"] == "done"
    assert texts == ["done"]


@pytest.mark.asyncio
async def test_suspended_question_uses_checkpoint_and_same_tool_id_after_new_runner(runtime):
    _, database, store, profile = runtime
    generation, _ = store.begin("local", {"text": "ask"})
    text = []

    async def model(profile, history, **kwargs):
        if history[-1].get("role") == "tool":
            assert history[-1]["tool_call_id"] == "question"
            yield "answer received"
        else:
            yield ModelToolCall("question", "ask_user_question", {"questions": [{"id": "format", "question": "Which format?"}]})

    async def emit(chunk):
        text.append(chunk)

    arguments = dict(scopes=set(), grant_expires=None, stream_tools=model, stream_text=model,
                     on_text=emit, profile=profile, ask_user_enabled=True)
    first = AgentRunner("local", generation, database, store, **arguments)
    with pytest.raises(AgentSuspended):
        await first.run(store.history("local", generation.conversation_id))
    pending = store.pending_action("local", generation.run_id)
    _, history, _ = store.answer_question("local", generation.run_id, pending["actionId"],
                                          {"answers": {"format": "Markdown"}})
    second = AgentRunner("local", generation, database, store, resume_history=history, **arguments)
    await second.run(history)
    assert text == ["answer received"]


@pytest.mark.asyncio
async def test_unknown_unselected_tool_and_expired_grant_never_dispatch(runtime):
    _, database, store, profile = runtime
    generation, _ = store.begin("local", {"text": "safe"})

    async def model(*args, **kwargs):
        yield ModelToolCall("wrong", "run_shell", {"command": "touch never"})

    async def emit(text):
        pass

    agent = {"id": "agent_test", "tools": []}
    runner = AgentRunner("local", generation, database, store, scopes={"shell:read", "shell:write", "shell:execute"},
                         grant_expires=None, stream_tools=model, stream_text=model, on_text=emit, profile=profile, agent=agent)
    with pytest.raises(RuntimeSafetyError, match="not enabled"):
        await runner.run(store.history("local", generation.conversation_id))
    expired = AgentRunner("local", generation, database, store, scopes=set(), grant_expires=1,
                          stream_tools=model, stream_text=model, on_text=emit, profile=profile)
    with pytest.raises(RuntimeSafetyError, match="expired"):
        await expired.run([])


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["ask_user_question", "mcp_tool_call", "subagent", "delegate_agent"])
async def test_model_cannot_pause_or_execute_an_unselected_optional_tool(runtime, name):
    _, database, store, profile = runtime
    generation, _ = store.begin("local", {"text": "safe"})
    _repo().save_setting("local", "endpoints", {"agents": {"toolApproval": {"enabled": True}}})

    async def model(*args, **kwargs):
        yield ModelToolCall("unselected", name, {"question": "Do it?"})

    async def emit(text):
        pass

    runner = AgentRunner("local", generation, database, store, scopes={"shell:read", "shell:write"},
                         grant_expires=None, stream_tools=model, stream_text=model, on_text=emit, profile=profile,
                         agent={"id": "agent_test", "tools": []})
    with pytest.raises(RuntimeSafetyError, match="not enabled"):
        await runner.run(store.history("local", generation.conversation_id))
    assert store.pending_action("local", generation.run_id) is None


@pytest.mark.asyncio
async def test_completed_model_checkpoint_never_invokes_provider_again(runtime):
    _, database, store, profile = runtime
    generation, _ = store.begin("local", {"text": "finish"})
    calls = []
    text = []

    async def model(*args, **kwargs):
        calls.append(True)
        yield "completed response"

    async def emit(chunk):
        text.append(chunk)

    options = dict(scopes=set(), grant_expires=None, stream_tools=model, stream_text=model,
                   on_text=emit, profile=profile)
    first = AgentRunner("local", generation, database, store, **options)
    await first.run(store.history("local", generation.conversation_id))
    reopened = AgentRunner("local", generation, database, store, **options)
    await reopened.run([])
    assert calls == [True] and text == ["completed response"]
    assert reopened.partial_text == "completed response"


@pytest.mark.asyncio
async def test_auth_none_uses_native_scope_catalog_for_start_and_resume(runtime, monkeypatch):
    _, _, store, _ = runtime
    from local_shell_mcp.oauth import ALL_OAUTH_SCOPES
    from local_shell_mcp.webui.lsm_tool_registry import available_tools

    captured = []

    async def capture(*args, **kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(generation_routes, "_start_task", capture)
    app = Starlette(routes=generation_routes.generation_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/agents/chat", json={"text": "scope check"})
        assert response.status_code == 202
        cid = response.json()["conversationId"]
        assert captured[-1]["granted_scopes"] == frozenset(ALL_OAUTH_SCOPES)
        names = {tool["function"]["name"] for tool in available_tools(
            "local", cid, scopes=set(captured[-1]["granted_scopes"]),
        )}
        assert {"browser_session", "browser_snapshot", "link_list", "link_create"} <= names
        generation = store.latest("local", cid)
        pending = {"actionId": "scope-answer", "payload": {"type": "ask_user_question", "tool_call_id": "scope",
                   "questions": [{"id": "choice", "question": "Continue?"}]}}
        history = [{"role": "assistant", "tool_calls": [{"id": "scope", "type": "function",
                    "function": {"name": "ask_user_question", "arguments": "{}"}}]}]
        assert store.pause_for_question("local", generation.run_id, pending, history, "")
        response = await client.post("/api/agents/chat/resume", json={
            "conversationId": cid, "actionId": "scope-answer", "answers": {"choice": "yes"},
        })
        assert response.status_code == 200, response.text
        assert captured[-1]["granted_scopes"] == frozenset(ALL_OAUTH_SCOPES)


def test_oauth_grant_is_never_expanded_to_controller_scopes(runtime, monkeypatch):
    from types import SimpleNamespace

    from starlette.requests import Request

    from local_shell_mcp import settings

    monkeypatch.setattr(settings, "get_settings", lambda: SimpleNamespace(auth_mode="oauth"))
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": [], "state": {
        "principal": SimpleNamespace(claims={"scope": "shell:read", "exp": 123}),
    }})
    assert generation_routes._request_grant(request) == ({"shell:read"}, 123)
    missing = Request({"type": "http", "method": "POST", "path": "/", "headers": [], "state": {}})
    assert generation_routes._request_grant(missing) == (set(), None)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [70000, 500000])
@pytest.mark.parametrize("reviewed", [False, True])
async def test_native_result_remains_lossless_while_model_uses_source_ingestion_limit(runtime, monkeypatch, size, reviewed):
    import json

    from local_shell_mcp.webui.approval_runtime import truncate_approval_result

    root, database, store, profile = runtime
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_FILE_READ_BYTES", "1000000")
    get_settings.cache_clear()
    payload = "head:" + "x" * size + ":tail"
    (root / "native-large.txt").write_text(payload, encoding="utf-8")
    generation, _ = store.begin("local", {"text": "Read the native result"})
    received = []

    async def model(profile, history, **kwargs):
        if history[-1].get("role") != "tool":
            yield ModelToolCall("large", "file_read", {"path": "native-large.txt"})
        else:
            received.append(history[-1]["content"])
            yield "done"

    async def emit(text):
        pass

    runner = AgentRunner("local", generation, database, store, scopes={"shell:read"},
                         grant_expires=None, stream_tools=model, stream_text=model,
                         on_text=emit, profile=profile)
    if reviewed:
        _repo().save_setting("local", "endpoints", {"agents": {"toolApproval": {"enabled": True, "ask": ["file_read"]}}})
        with pytest.raises(AgentSuspended):
            await runner.run(store.history("local", generation.conversation_id))
        pending = store.pending_action("local", generation.run_id)
        _, history, partial, batch = store.claim_approval("local", generation.run_id, pending["actionId"],
            [{"tool_call_id": "large", "decision": "approve"}])
        runner = AgentRunner("local", generation, database, store, scopes={"shell:read"},
                             grant_expires=None, stream_tools=model, stream_text=model,
                             on_text=emit, profile=profile, approved_batch=batch, resume_history=history,
                             resume_namespace="", partial_text=partial)
        await runner.run(history)
    else:
        await runner.run(store.history("local", generation.conversation_id))
    raw = next(iter(runner.cache.values()))["output"]
    assert json.loads(raw)["data"]["content"] == payload
    assert received == [truncate_approval_result(raw, 400000)]
    if size < 400000:
        assert received[0] == raw
    else:
        assert "truncated:" in received[0] and ":tail" in received[0]
    saved = list(runner.saver.list(runner.config))
    assert any(write[2].get("content") == raw for checkpoint in saved
               for write in checkpoint["pendingWrites"] if isinstance(write[2], dict))
