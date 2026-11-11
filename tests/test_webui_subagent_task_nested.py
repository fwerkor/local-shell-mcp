"""Nested detached AgentRunner lineage and depth do not create another scheduler."""
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
from local_shell_mcp.webui.subagent_task_host import SQLiteSubagentTaskHost, shutdown_subagent_tasks


@pytest.mark.asyncio
async def test_nested_background_child_run_uses_root_scope_and_depth(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr(agent_runner, "provider_config", lambda kind, model: ProviderConfig(
        "openai", model, "https://stub.invalid", ""))
    database = SQLiteDatabase(get_settings().state_dir)
    repo, store = AgentRepository(database), GenerationStore(database)
    leaf = repo.create("local", {"name": "leaf", "provider": "openAI", "model": "leaf", "tools": []})
    middle = repo.create("local", {"name": "middle", "provider": "openAI", "model": "middle", "tools": [],
                                   "subagents": {"enabled": True, "allowSelf": False,
                                                 "agent_ids": [leaf["id"]]}})
    root = repo.create("local", {"name": "root", "provider": "openAI", "model": "root", "tools": [],
                                 "subagents": {"enabled": True, "allowSelf": False,
                                               "agent_ids": [middle["id"]]}})
    trace = []

    async def model(profile, messages, **kwargs):
        trace.append(profile.model)
        if profile.model == "root" and not any(m.get("role") == "tool" for m in messages):
            yield ModelToolCall("middle-call", "subagent", {
                "subagent_type": middle["id"], "description": "Run middle",
                "run_in_background": True,
            })
        elif profile.model == "middle" and not any(m.get("role") == "tool" for m in messages):
            yield ModelToolCall("leaf-call", "subagent", {
                "subagent_type": leaf["id"], "description": "Run leaf",
                "run_in_background": True,
            })
        else:
            yield profile.model + " complete"

    generation, _ = store.begin("local", {"text": "root command"}, root)

    async def quiet(_chunk):
        return None

    runner = AgentRunner("local", generation, database, store, scopes=frozenset(),
                         grant_expires=None, stream_tools=model, stream_text=model,
                         on_text=quiet, agent=root)
    result = await runner.run(store.history("local", generation.conversation_id))
    handle = json.loads(next(m["content"] for m in result if m.get("role") == "tool"))
    host = SQLiteSubagentTaskHost(database, "local", generation.conversation_id,
                                  stream_tools=model, stream_text=model)
    for _ in range(100):
        if len(host.list()) == 2 and all(task["status"] == "completed" for task in host.list()):
            break
        await asyncio.sleep(.03)
    tasks = host.list()
    assert len(tasks) == 2, (tasks, trace)
    assert {task["subagentType"] for task in tasks} == {middle["id"], leaf["id"]}
    middle_task = host._get(handle["background_task_id"])
    leaf_task = next(host._get(task["taskId"]) for task in tasks if task["subagentType"] == leaf["id"])
    assert leaf_task["parent_run_id"] == middle_task["child_run_id"]
    assert leaf_task["parent_conversation_id"] == generation.conversation_id
    assert leaf_task["parent_agent_id"] == middle["id"]
    assert trace.count("root") == 2 and trace.count("middle") == 2 and trace.count("leaf") == 1
    assert json.loads(await host.check({"background_task_id": leaf_task["id"]}))["result"] == "leaf complete"
    await shutdown_subagent_tasks()
    get_settings.cache_clear()

@pytest.mark.asyncio
async def test_detached_graph_team_parallel_join_uses_designated_result(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr(agent_runner, "provider_config", lambda kind, model: ProviderConfig(
        "openai", model, "https://stub.invalid", ""))
    database = SQLiteDatabase(get_settings().state_dir)
    repo, store = AgentRepository(database), GenerationStore(database)
    members = [repo.create("local", {"name": name, "provider": "openAI", "model": name, "tools": []})
               for name in ("entry", "left", "right", "result")]
    entry, left, right, result = members
    lead = repo.create("local", {"name": "lead", "provider": "openAI", "model": "lead", "tools": []})
    definition = {"type": "team", "name": "Background team", "description": "parallel join",
                  "agent_ids": [member["id"] for member in members],
                  "entry_agent_id": entry["id"], "result_agent_id": result["id"],
                  "edges": [
                      {"from": entry["id"], "to": [left["id"], right["id"]],
                       "edgeType": "direct"},
                      {"from": [left["id"], right["id"]], "to": result["id"],
                       "edgeType": "direct"},
                  ]}
    lead = repo.update("local", lead["id"], {"subagents": {"enabled": True,
                        "allowSelf": False, "agent_ids": [], "graphs": [definition]}})
    models = []

    async def model(profile, messages, **kwargs):
        models.append(profile.model)
        if profile.model == "lead":
            if any(msg.get("role") == "tool" for msg in messages):
                yield "lead after dispatch"
            else:
                yield ModelToolCall("team-call", "subagent", {"subagent_type": "team",
                    "description": "Work together", "run_in_background": True})
        elif profile.model == "result":
            assert any(msg.get("content") == "left reply" for msg in messages)
            assert any(msg.get("content") == "right reply" for msg in messages)
            yield "designated team final"
        else:
            yield profile.model + " reply"

    generation, _ = store.begin("local", {"text": "team research"}, lead)

    async def quiet(_text):
        return None

    runner = AgentRunner("local", generation, database, store, scopes=frozenset(),
                         grant_expires=None, stream_tools=model, stream_text=model,
                         on_text=quiet, agent=lead)
    parent = await runner.run(store.history("local", generation.conversation_id))
    handle = json.loads(next(item["content"] for item in parent if item.get("role") == "tool"))
    host = SQLiteSubagentTaskHost(database, "local", generation.conversation_id,
                                  stream_tools=model, stream_text=model)
    for _ in range(100):
        row = host._get(handle["background_task_id"])
        if row and row["status"] != "running":
            break
        await asyncio.sleep(.03)
    result_row = host._get(handle["background_task_id"])
    assert result_row["status"] == "completed", (result_row["error"], models)
    claimed = json.loads(await host.check({"background_task_id": handle["background_task_id"]}))
    assert claimed["result"] == "designated team final"
    assert set(models) == {"entry", "left", "right", "result", "lead"}
    await shutdown_subagent_tasks()
    get_settings.cache_clear()
