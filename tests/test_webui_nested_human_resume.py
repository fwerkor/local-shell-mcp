"""Integration: child tool approval survives graph checkpoint and root continuation."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import shared_database
from local_shell_mcp.webui import agent_runner, generation_routes
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig
from local_shell_mcp.webui.routes import _repo


@pytest.mark.asyncio
@pytest.mark.parametrize("crash_before_restart", [False, True])
async def test_approved_child_action_uses_nested_checkpoint_and_same_parent_run(
    tmp_path, monkeypatch, crash_before_restart,
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    database = shared_database(get_settings().state_dir)
    repository = AgentRepository(database)
    child = repository.create("local", {"name": "child", "provider": "openAI", "model": "child",
                                        "tools": ["file_write"]})
    parent = repository.create("local", {"name": "parent", "provider": "openAI", "model": "parent",
                                         "subagents": {"enabled": True, "allowSelf": False,
                                                       "agent_ids": [child["id"]]}})
    store = GenerationStore(database)
    job, _ = store.begin("local", {"text": "Ask child to edit a file"}, parent)
    _repo().save_setting("local", "agent.machine_policy.global", {"local": "write"})
    _repo().save_setting("local", "endpoints", {"agents": {
        "toolApproval": {"enabled": True, "ask": ["file_write"], "allow": ["subagent"]},
    }})
    monkeypatch.setattr(agent_runner, "provider_config", lambda _provider, model: ProviderConfig(
        "openai", model or "parent", "https://example.test", "",
    ))
    monkeypatch.setattr(generation_routes, "provider_config", lambda _provider, model: ProviderConfig(
        "openai", model or "parent", "https://example.test", "",
    ))
    parent_profile = ProviderConfig("openai", "parent", "https://example.test", "")
    requests = []

    async def model(profile, messages, **kwargs):
        requests.append((profile.model, list(messages)))
        if profile.model == "parent":
            if not any(message.get("role") == "tool" for message in messages):
                yield ModelToolCall("subagent-call", "subagent", {
                    "subagent_type": child["id"], "description": "Edit the document",
                })
            else:
                yield "The child task returned to the parent."
        elif not any(message.get("role") == "tool" for message in messages):
            yield ModelToolCall("write", "file_write", {
                "path": "should-not-exist.txt", "content": "unsafe",
            })
        else:
            yield "The write was rejected safely."

    monkeypatch.setattr(generation_routes, "stream_model_with_tools", model)
    await generation_routes._run_model("local", job, parent_profile, parent_agent=parent,
                                       granted_scopes=frozenset({"shell:read", "shell:write"}))
    action = store.pending_action("local", job.run_id)
    assert action is not None and "subagent:" in action["namespace"], action
    assert action["payload"]["type"] == "tool_approval"
    if crash_before_restart:
        store.claim_approval("local", job.run_id, action["actionId"],
                             [{"tool_call_id": "write", "decision": "reject"}])
        assert store.recover_claimed_resumes() == 1
        assert store.pending_action("local", job.run_id)["actionId"] == action["actionId"]
    app = Starlette(routes=generation_routes.generation_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                base_url="http://test") as client:
        response = await client.post("/api/agents/chat/resume", json={
            "conversationId": job.conversation_id, "actionId": action["actionId"],
            "decisions": [{"tool_call_id": "write", "decision": "reject"}],
        })
        assert response.status_code == 200, response.text
        tasks = list(generation_routes._TASKS.values())
        if tasks:
            await asyncio.wait_for(asyncio.gather(*tasks), 6)
    assert store.latest("local", job.conversation_id).status == "complete"
    assert any(model == "parent" and any(message.get("role") == "tool" for message in messages)
               for model, messages in requests)
    assert not (tmp_path / "should-not-exist.txt").exists()
    get_settings.cache_clear()
