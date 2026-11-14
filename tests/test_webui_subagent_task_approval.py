"""Detached child approval deny keeps parent HITL namespace and native ACL intact."""
from __future__ import annotations

import asyncio
import json

import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import agent_runner
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig
from local_shell_mcp.webui.routes import _repo
from local_shell_mcp.webui.subagent_task_host import SQLiteSubagentTaskHost, shutdown_subagent_tasks


@pytest.mark.asyncio
async def test_detached_child_denies_file_write_requiring_parent_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    monkeypatch.setattr(agent_runner, "provider_config", lambda kind, model: ProviderConfig(
        "openai", model, "https://stub.invalid", ""))
    database = SQLiteDatabase(get_settings().state_dir)
    repo, store = AgentRepository(database), GenerationStore(database)
    child = repo.create("local", {"name": "writer", "provider": "openAI", "model": "writer",
                                  "tools": ["file_write"]})
    parent = repo.create("local", {"name": "parent", "provider": "openAI", "model": "parent",
                                   "tools": [], "subagents": {"enabled": True, "allowSelf": False,
                                                              "agent_ids": [child["id"]]}})
    _repo().save_setting("local", "agent.machine_policy.global", {"local": "write"})
    _repo().save_setting("local", "endpoints", {"agents": {"toolApproval": {
        "enabled": True, "ask": ["file_write"], "allow": ["subagent"],
    }}})
    seen = []

    async def model(profile, messages, **kwargs):
        seen.append(profile.model)
        if profile.model == "parent":
            if any(item.get("role") == "tool" for item in messages):
                yield "parent is done"
            else:
                yield ModelToolCall("delegate-write", "subagent", {
                    "subagent_type": child["id"], "description": "Write to protected file",
                    "run_in_background": True,
                })
        elif not any(item.get("role") == "tool" for item in messages):
            yield ModelToolCall("requested-write", "file_write", {
                "path": "must-not-exist.txt", "content": "not-approved",
            })
        else:
            assert "Blocked: Approval required" in messages[-1]["content"]
            yield "approval denied"

    async def emit(_text):
        return None

    generation, _ = store.begin("local", {"text": "child write"}, parent)
    root_runner = AgentRunner("local", generation, database, store,
                              scopes=frozenset({"shell:read", "shell:write"}), grant_expires=None,
                              stream_tools=model, stream_text=model, on_text=emit, agent=parent)
    parent_result = await root_runner.run(store.history("local", generation.conversation_id))
    handle = json.loads(next(item["content"] for item in parent_result if item.get("role") == "tool"))
    host = SQLiteSubagentTaskHost(database, "local", generation.conversation_id,
                                  stream_tools=model, stream_text=model)
    for _ in range(100):
        child_task = host._get(handle["background_task_id"])
        if child_task and child_task["status"] != "running":
            break
        await asyncio.sleep(.03)
    assert child_task["status"] == "completed", child_task["error"]
    assert json.loads(await host.check({"background_task_id": child_task["id"]}))["result"] == "approval denied"
    assert not (tmp_path / "must-not-exist.txt").exists()
    assert store.pending_action("local", child_task["child_run_id"]) is None
    assert seen.count("writer") == 2
    await shutdown_subagent_tasks()
    get_settings.cache_clear()
