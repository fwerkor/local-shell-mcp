"""Actual Python AgentRunner fencing under competing Controller wakeup claims."""
from __future__ import annotations

import asyncio

import pytest
from wakeup_helpers import begin_automatic
from wakeup_helpers import environment as environment

from local_shell_mcp.webui import generation_routes
from local_shell_mcp.webui.agent_runner import AgentRunner
from local_shell_mcp.webui.agent_runtime import RuntimeSafetyError
from local_shell_mcp.webui.subagent_task_host import shutdown_subagent_tasks
from local_shell_mcp.webui.subagent_wakeup import _now


@pytest.mark.asyncio
async def test_true_agent_runner_rechecks_claim_token_and_owner_scoped_root_run(environment):
    db, repo, store, child, parent, parent_run = environment
    host, task_id, generation = await begin_automatic(environment)
    with db.connect() as conn:
        token = conn.execute("SELECT lease_owner FROM subagent_wakeups WHERE task_id=?",
                             (task_id,)).fetchone()[0]

    async def model(*args, **kwargs):
        yield "hello"

    async def emit(_chunk):
        pass

    runner = AgentRunner("local", generation, db, store, scopes=frozenset(),
                         grant_expires=None, stream_tools=model, stream_text=model,
                         on_text=emit, agent=parent, wakeup_lease=(task_id, token))
    runner._check_grant()
    with db.connect() as conn:
        conn.execute("UPDATE subagent_wakeups SET lease_owner='other-controller-token' "
                     "WHERE task_id=?", (task_id,))
    with pytest.raises(RuntimeSafetyError, match="lease"):
        runner._check_grant()
    with db.connect() as conn:
        conn.execute("UPDATE subagent_wakeups SET lease_owner=?,lease_until=? "
                     "WHERE task_id=?", (token, _now() - 1, task_id))
    with pytest.raises(RuntimeSafetyError, match="lease"):
        runner._check_grant()
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_old_controller_cannot_emit_or_finish_after_wakeup_lease_takeover(environment, monkeypatch):
    db, repo, store, child, parent, parent_run = environment
    host, task_id, generation = await begin_automatic(environment)
    with db.connect() as conn:
        token = conn.execute("SELECT lease_owner FROM subagent_wakeups WHERE task_id=?",
                             (task_id,)).fetchone()[0]
    entered = asyncio.Event()
    finish_model = asyncio.Event()

    async def model(profile, history, **kwargs):
        entered.set()
        await finish_model.wait()
        yield "old-owner-token-must-never-emit"

    monkeypatch.setattr(generation_routes, "_database", lambda: db)
    monkeypatch.setattr(generation_routes, "stream_model", model)
    monkeypatch.setattr(generation_routes, "stream_model_with_tools", model)
    from local_shell_mcp.webui.providers import ProviderConfig

    profile = ProviderConfig("openai", "parent", "https://example.invalid", "")
    await generation_routes._start_task("local", generation, profile, parent,
                                        wakeup_lease=(task_id, token))
    assert await asyncio.wait_for(entered.wait(), 8)
    with db.connect() as conn:
        conn.execute("UPDATE subagent_wakeups SET lease_owner='second-owner',"
                     "lease_until=? WHERE task_id=?", (_now() + 120_000, task_id))
    finish_model.set()
    current = generation_routes._TASKS[generation.run_id]
    await asyncio.wait_for(current, 8)
    assert store.get("local", generation.run_id).status == "running"
    assert not any("old-owner-token-must-never-emit" in str(event)
                   for _, event in store.events("local", generation.run_id))
    await shutdown_subagent_tasks()
