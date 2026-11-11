"""Real Python run-loop paths for delegation, handoff, malformed calls and errors."""

from __future__ import annotations

import json

import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import shared_database
from local_shell_mcp.webui import agent_runner, generation_routes
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig


@pytest.fixture
def active_generation(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    database = shared_database(get_settings().state_dir)
    store = GenerationStore(database)
    profile = ProviderConfig("openai", "fake", "http://127.0.0.1:11434/v1/chat/completions", "")
    yield database, store, profile
    get_settings.cache_clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["subagent", "handoff"])
async def test_real_generation_run_loop_uses_original_subagent_and_handoff(active_generation, monkeypatch, mode):
    database, store, profile = active_generation
    agents = AgentRepository(database)
    child = agents.create("local", {"name": "Child", "provider": "openAI", "model": "child",
                                      "instructions": "Help with reports"})
    fields = {"name": "Parent", "provider": "openAI", "model": "fake", "instructions": "Use a specialist"}
    if mode == "subagent":
        fields["subagents"] = {"enabled": True, "allowSelf": False, "agent_ids": [child["id"]]}
    else:
        fields["edges"] = [{"from": "", "to": child["id"], "edgeType": "handoff"}]
    parent = agents.create("local", fields)
    generation, _ = store.begin("local", {"text": "Summarize private parent context"}, parent)
    observed = []

    async def model(profile, history, **kwargs):
        names = {item["function"]["name"] for item in kwargs["tools"]}
        assert "delegate_agent" not in names and "handoff_agent" not in names
        observed.append((profile.model, history.copy()))
        if profile.model == "child":
            if mode == "subagent":
                assert history[-1]["content"] == "Give a concise summary"
                assert all("private parent context" not in str(message) for message in history)
            yield "Child summary."
        elif any(message.get("role") == "tool" for message in history):
            assert history[-1]["content"] == "Child summary."
            yield "Final parent summary."
        elif mode == "subagent":
            assert "subagent" in names
            schema = next(tool["function"]["parameters"] for tool in kwargs["tools"]
                          if tool["function"]["name"] == "subagent")
            child_type = schema["properties"]["subagent_type"]["enum"][0]
            yield ModelToolCall("call-child", "subagent", {
                "subagent_type": child_type, "description": "Give a concise summary",
            })
        else:
            name = "transfer_to_" + child["id"]
            assert name in names
            yield ModelToolCall("call-child", name, {})

    monkeypatch.setattr(generation_routes, "stream_model_with_tools", model)
    monkeypatch.setattr(agent_runner, "provider_config", lambda kind, model: ProviderConfig(
        "openai", model, "https://test.invalid", ""))
    await generation_routes._run_model("local", generation, profile, parent_agent=parent,
                                       instructions=parent["instructions"], granted_scopes=frozenset({"shell:read"}))
    assert store.latest("local", generation.conversation_id).status == "complete"
    final = store.events("local", generation.run_id)[-1][1]["responseMessage"]["text"]
    assert final == ("Child summary." if mode == "handoff" else "Final parent summary.")
    assert any(model == "child" for model, _ in observed)
    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM agent_checkpoints").fetchone()[0] >= 3


@pytest.mark.asyncio
@pytest.mark.parametrize("behavior", [
    "repeated_tools", "invalid_ask_user", "invalid_options", "invalid_mcp_arguments",
    "multiple_delegates", "orphaned_external_approval", "oversized_call",
])
async def test_generation_rejects_invalid_model_tool_actions(active_generation, monkeypatch, behavior):
    database, store, profile = active_generation
    generation, _ = store.begin("local", {"conversationId": "new", "text": "Do the task"})
    async def misbehaving(profile, history, **kwargs):
        if behavior == "repeated_tools":
            yield ModelToolCall("x", "file_read", {"path": "missing"})
        elif behavior == "invalid_ask_user":
            yield ModelToolCall("x", "ask_user_question", {"question": ""})
        elif behavior == "invalid_options":
            yield ModelToolCall("x", "ask_user_question", {"question": "Choose", "options": ["wrong"]})
        elif behavior == "invalid_mcp_arguments":
            yield ModelToolCall("x", "mcp_tool_call", {"name": "missing", "arguments": []})
        elif behavior == "multiple_delegates":
            for key in ("one", "two"):
                yield ModelToolCall(key, "delegate_agent", {"agent_id": "agent_test", "task": "thing"})
        elif behavior == "orphaned_external_approval":
            yield ModelToolCall("x", "mcp_tool_call", {"name": "test:read", "arguments": {}})
        elif behavior == "oversized_call":
            yield ModelToolCall("x", "ask_user_question", {"question": "a" * 3000})

    monkeypatch.setattr(generation_routes, "stream_model_with_tools", misbehaving)
    if behavior == "orphaned_external_approval":
        from local_shell_mcp.webui.routes import _repo
        _repo().save_setting("local", "conversation.permissions." + generation.conversation_id, {"mcp": False})
    await generation_routes._run_model(
        "local", generation, profile, native_file_tools=behavior == "repeated_tools",
        ask_user_enabled=behavior in {"invalid_ask_user", "invalid_options", "oversized_call"},
        mcp_enabled=behavior in {"invalid_mcp_arguments", "orphaned_external_approval"},
        parent_agent={"subagents": ["agent_test"]} if behavior == "multiple_delegates" else None,
        granted_scopes=frozenset({"shell:read", "shell:write", "shell:execute"}),
    )
    assert store.latest("local", generation.conversation_id).status == "error"
    last = store.events("local", generation.run_id)[-1][1]
    assert last["final"] is True
    assert "error" in last


@pytest.mark.asyncio
async def test_external_tool_failure_is_returned_without_leaking_secrets(active_generation, monkeypatch):
    _, store, profile = active_generation
    generation, _ = store.begin("local", {"text": "Use tool"})

    async def rejected_call(*args, **kwargs):
        raise RuntimeError("Bearer a-private-secret")

    async def model(profile, history, **kwargs):
        if history[-1].get("role") == "tool":
            assert "RuntimeError" in history[-1]["content"]
            yield "The external tool could not be called."
        else:
            yield ModelToolCall("call-one", "mcp_tool_call", {"name": "test:tool", "arguments": {}})

    from local_shell_mcp.webui import nested_mcp

    monkeypatch.setattr(nested_mcp, "approved_call", rejected_call)
    monkeypatch.setattr(generation_routes, "stream_model_with_tools", model)
    await generation_routes._run_model("local", generation, profile, mcp_enabled=True,
                                       granted_scopes=frozenset({"shell:read", "shell:execute"}))
    assert store.latest("local", generation.conversation_id).status == "complete"
    final_events = json.dumps(store.events("local", generation.run_id))
    assert "Bearer a-private-secret" not in final_events
    assert "The external tool could not be called." in final_events


@pytest.mark.asyncio
async def test_generation_http_bad_identifiers_and_non_active_abort(active_generation, monkeypatch):
    import httpx
    from starlette.applications import Starlette

    _, store, profile = active_generation
    monkeypatch.setattr(generation_routes, "provider_config", lambda *_: profile)
    app = Starlette(routes=generation_routes.generation_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/agents/chat", json={"agent_id": ["invalid"], "text": "hello"})
        assert response.status_code == 400
        response = await client.post("/api/agents/chat", json={"projectId": ["invalid"], "text": "hello"})
        assert response.status_code == 400
        assert (await client.post("/api/agents/chat/resume", json={"conversationId": 4})).status_code == 400
        assert (await client.post("/api/agents/chat/resume", json={"conversationId": "missing"})).status_code == 404
        generation, _ = store.begin("local", {"conversationId": "new", "text": "abort this"})
        response = await client.post("/api/agents/chat/abort", json={
            "conversationId": generation.conversation_id,
            "generationCreatedAt": generation.generation_created_at,
        })
        assert response.status_code == 200
        assert store.latest("local", generation.conversation_id).status == "aborted"
        response = await client.post("/api/agents/chat/resume", json={"conversationId": generation.conversation_id,
                                                                        "actionId": "continue"})
        assert response.status_code == 409


@pytest.mark.asyncio
async def test_generation_resume_rejects_invalid_human_action_and_inactive_state(active_generation, monkeypatch):
    import httpx
    from starlette.applications import Starlette

    _, store, profile = active_generation
    monkeypatch.setattr(generation_routes, "provider_config", lambda *_: profile)
    generation, _ = store.begin("local", {"conversationId": "new", "text": "continue"})
    pending = {"actionId": "one", "payload": {"type": "ask_user_question", "tool_call_id": "ask"}}
    assert store.pause_for_question("local", generation.run_id, pending, [], "partial")
    app = Starlette(routes=generation_routes.generation_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = "/api/agents/chat/resume"
        assert (await client.post(url, json={"conversationId": generation.conversation_id,
                                             "actionId": ""})).status_code == 400
        assert (await client.post(url, json={"conversationId": generation.conversation_id,
                                             "actionId": "one", "generationCreatedAt": -1})).status_code == 409
        assert (await client.post(url, json={"conversationId": generation.conversation_id,
                                             "actionId": "outdated"})).status_code == 409
        assert store.pending_action("local", generation.run_id)["actionId"] == "one"


@pytest.mark.asyncio
async def test_agent_without_machine_access_still_has_session_tools(active_generation, monkeypatch):
    _, store, profile = active_generation
    generation, _ = store.begin("local", {"conversationId": "new", "text": "Respond plainly"})

    async def session_tools_model(profile, history, **kwargs):
        assert {item["function"]["name"] for item in kwargs["tools"]} == {
            "session_manage", "plan_manage",
        }
        yield "Plain chat works."

    monkeypatch.setattr(generation_routes, "stream_model_with_tools", session_tools_model)
    await generation_routes._run_model(
        "local", generation, profile,
        parent_agent={"id": "agent_empty", "subagents": [], "instructions": "Act normally"},
    )
    assert store.latest("local", generation.conversation_id).status == "complete"
    assert store.events("local", generation.run_id)[-1][1]["responseMessage"]["text"] == "Plain chat works."
