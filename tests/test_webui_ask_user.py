"""Durable Ask User pause and answer resume over the original React SSE contract."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui import agent_routes, generation_routes
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig


@pytest.mark.asyncio
async def test_ask_user_halts_and_resumes_same_sqlite_generation(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.delenv("LOCAL_SHELL_MCP_STATE_BACKEND", raising=False)
    get_settings.cache_clear()
    calls: list[list[str]] = []

    async def mock_agent(profile, history, *, tools, **kwargs):
        calls.append([tool["function"]["name"] for tool in tools])
        if not any(message.get("role") == "tool" for message in history):
            yield ModelToolCall("ask-call-1", "ask_user", {
                "question": "Which file should I inspect?",
                "options": [{"label": "README", "value": "README.md"}],
            })
        else:
            assert history[-1] == {"role": "tool", "tool_call_id": "ask-call-1", "content": "README.md"}
            yield "I will inspect README.md."

    monkeypatch.setattr(generation_routes, "provider_config", lambda *_: ProviderConfig(
        "openai", "mock", "http://127.0.0.1:11434/v1/chat/completions", "",
    ))
    monkeypatch.setattr(generation_routes, "stream_model_with_tools", mock_agent)
    app = Starlette(routes=[*generation_routes.generation_routes(), *agent_routes.agent_routes()])
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post("/api/agents", json={
                "name": "Asker", "provider": "openAI", "model": "mock", "tools": ["ask_user"],
            })
            assert created.status_code == 201, created.text
            agent_id = created.json()["id"]
            response = await client.post("/api/agents/chat", json={
                "conversationId": "new", "text": "Help me choose a file", "agent_id": agent_id,
            })
            assert response.status_code == 202, response.text
            cid = response.json()["conversationId"]
            for _ in range(100):
                status = (await client.get(f"/api/agents/chat/status/{cid}")).json()
                if status.get("status") == "requires_action":
                    break
                await asyncio.sleep(0.02)
            assert status["status"] == "requires_action", status
            pending = status["pendingAction"]
            assert pending["payload"]["type"] == "ask_user_question"
            assert pending["payload"]["question"]["question"] == "Which file should I inspect?"
            assert pending["payload"]["tool_call_id"] == "ask-call-1"
            assert pending["conversationId"] == cid
            repo = generation_routes._generation_store()
            generation = repo.latest("local", cid)
            assert repo.pending_action("local", generation.run_id) == pending
            assert any(event.get("event") == "on_pending_action" for _, event in repo.events("local", generation.run_id))
            assert (await client.post("/api/agents/chat", json={
                "conversationId": cid, "text": "another request",
            })).status_code == 409
            assert (await client.post("/api/agents/chat/resume", json={
                "conversationId": cid, "actionId": "wrong", "answer": "README.md",
            })).status_code == 409
            assert (await client.post("/api/agents/chat/resume", json={
                "conversationId": cid, "actionId": pending["actionId"], "answer": "",
            })).status_code == 400
            result = await client.post("/api/agents/chat/resume", json={
                "conversationId": cid, "actionId": pending["actionId"], "answer": "README.md",
            })
            assert result.status_code == 200, result.text
            for _ in range(100):
                status = (await client.get(f"/api/agents/chat/status/{cid}")).json()
                if status.get("status") in {"complete", "error"}:
                    break
                await asyncio.sleep(0.02)
            assert status["status"] == "complete", status
            assert "pendingAction" not in status
            assert calls == [["session_manage", "plan_manage", "ask_user"]] * 2
            latest = repo.latest("local", cid)
            assert latest.run_id == generation.run_id
            assert repo.pending_action("local", latest.run_id) is None
            events = repo.events("local", latest.run_id)
            assert events[-1][1]["responseMessage"]["text"] == "I will inspect README.md."
            assert (await client.post("/api/agents/chat/resume", json={
                "conversationId": cid, "actionId": pending["actionId"], "answer": "README.md",
            })).status_code == 409
    finally:
        await generation_routes.shutdown_generations()
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_pending_ask_user_survives_store_recreation_and_abort(tmp_path, monkeypatch):
    from local_shell_mcp.sqlite_store import SQLiteDatabase
    from local_shell_mcp.webui.generations import GenerationStore

    database = SQLiteDatabase(tmp_path / "state")
    first = GenerationStore(database)
    pending_run, created = first.begin("alice", {"text": "Choose a file", "conversationId": "new"})
    assert created
    pending = {
        "actionId": "question-1", "streamId": pending_run.conversation_id,
        "payload": {"type": "ask_user_question", "tool_call_id": "call-1",
                    "question": {"question": "Where?"}},
    }
    prompt = [{"role": "user", "content": "Choose a file"},
              {"role": "assistant", "content": None,
               "tool_calls": [{"id": "call-1", "type": "function",
                               "function": {"name": "ask_user", "arguments": "{}"}}]}]
    assert first.pause_for_question("alice", pending_run.run_id, pending, prompt, "partial reply")
    # A new process opening the same SQLite database can fetch the pending
    # question; no in-memory task or browser connection is needed.
    after_restart = GenerationStore(SQLiteDatabase(tmp_path / "state"))
    assert after_restart.pending_action("alice", pending_run.run_id) == pending
    assert after_restart.pending_action("bob", pending_run.run_id) is None
    assert after_restart.recover_orphans() == 0
    assert after_restart.latest("alice", pending_run.conversation_id).status == "requires_action"
    with pytest.raises(KeyError):
        after_restart.answer_question("bob", pending_run.run_id, "question-1", "README.md")
    with pytest.raises(ValueError, match="Stale"):
        after_restart.answer_question("alice", pending_run.run_id, "another-action", "README.md")
    with pytest.raises(ValueError, match="non-empty"):
        after_restart.answer_question("alice", pending_run.run_id, "question-1", "")
    resumed, history, partial = after_restart.answer_question(
        "alice", pending_run.run_id, "question-1", "README.md",
    )
    assert resumed.run_id == pending_run.run_id
    assert partial == "partial reply"
    assert history[-1] == {"role": "tool", "tool_call_id": "call-1", "content": "README.md"}
    with pytest.raises(KeyError):
        after_restart.answer_question("alice", pending_run.run_id, "question-1", "duplicate")
    assert after_restart.get("alice", pending_run.run_id).status == "running"
    assert after_restart.finish("alice", pending_run.run_id, status="complete", text="finished")
    assert after_restart.events("alice", pending_run.run_id)[-1][1]["final"] is True


@pytest.mark.asyncio
async def test_paused_generation_can_be_aborted_without_resuming(tmp_path, monkeypatch):
    from local_shell_mcp.sqlite_store import SQLiteDatabase
    from local_shell_mcp.webui.generations import GenerationStore

    database = SQLiteDatabase(tmp_path / "state")
    store = GenerationStore(database)
    job, _ = store.begin("local", {"text": "Please choose"})
    pending = {"actionId": "1", "payload": {"type": "ask_user_question", "tool_call_id": "call"}}
    assert store.pause_for_question("local", job.run_id, pending, [], "")
    assert store.finish("local", job.run_id, status="aborted")
    assert store.latest("local", job.conversation_id).status == "aborted"
    assert store.pending_action("local", job.run_id) is None
    assert store.events("local", job.run_id)[-1][1]["aborted"] is True
