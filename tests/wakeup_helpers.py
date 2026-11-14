"""Shared isolated source wakeup fixture and real SQLite child generation helpers."""
from __future__ import annotations

import asyncio
import json

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ProviderConfig
from local_shell_mcp.webui.subagent_task_host import SQLiteSubagentTaskHost
from local_shell_mcp.webui.subagent_wakeup import process_wakeups
from local_shell_mcp.webui.subagents import SubagentInvocation, build_subagent_configs


@pytest.fixture
def environment(tmp_path, monkeypatch):
    from local_shell_mcp.settings import get_settings
    from local_shell_mcp.webui import agent_runner, providers

    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr(providers, "provider_config", lambda provider, model=None: ProviderConfig(
        "openai", model or "stub", "https://example.invalid", ""))
    # AgentRunner captures this imported function at module load time, unlike
    # the fresh provider import in the wakeup dispatcher.
    monkeypatch.setattr(agent_runner, "provider_config", providers.provider_config)
    database = SQLiteDatabase(tmp_path / ".local-shell-mcp")
    repository = AgentRepository(database)
    child = repository.create("local", {"name": "child", "provider": "openAI", "model": "child", "tools": []})
    parent = repository.create("local", {"name": "parent", "provider": "openAI", "model": "parent",
                                         "tools": [], "subagents": {"enabled": True, "agent_ids": [child["id"]]}})
    store = GenerationStore(database)
    generation, _ = store.begin("local", {"text": "delegate"}, parent)
    yield database, repository, store, child, parent, generation
    get_settings.cache_clear()


async def make_task(env, *, call_id="sub-1", slow=False):
    database, repo, store, child, parent, generation = env
    gate = asyncio.Event()

    async def model(profile, history, **kwargs):
        if slow:
            await gate.wait()
        yield "child result"

    config = build_subagent_configs("local", parent, database)[0]
    invocation = SubagentInvocation(
        agent=config.agent, messages=[{"role": "user", "content": "research"}],
        selected_tools=(), max_turns=config.max_turns,
        recursion_limit=config.max_turns * 3, remaining_depth=0,
        scopes=frozenset(), grant_expires=None,
        owner="local", conversation_id=generation.conversation_id,
        parent_run_id=generation.run_id, parent_tool_call_id=call_id,
        subagent_type=child["id"], child_configs=(), parent_agent_id=parent["id"],
    )
    host = SQLiteSubagentTaskHost(database, "local", generation.conversation_id,
                                  stream_tools=model, stream_text=model)
    response = json.loads(await host.start(invocation))
    return host, response["background_task_id"], gate


async def completed(host, task_id):
    for _ in range(120):
        row = host._get(task_id)
        if row["status"] != "running":
            return row
        await asyncio.sleep(.025)
    pytest.fail("Child task did not finish")


async def wait_admission():
    await asyncio.sleep(.28)


async def begin_automatic(env, *, dispatch=None):
    db, repo, store, child, parent, parent_run = env
    host, task_id, _ = await make_task(env)
    await completed(host, task_id)
    store.finish("local", parent_run.run_id, status="complete", text="Parent complete")
    await wait_admission()
    dispatched = []

    async def capture(owner, generation, profile, agent, **kwargs):
        dispatched.append((generation, kwargs))
        if dispatch is not None:
            await dispatch(owner, generation, profile, agent, **kwargs)

    assert await process_wakeups(db, dispatch=capture) == 1
    return host, task_id, dispatched[0][0]
