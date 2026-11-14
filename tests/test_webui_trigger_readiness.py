"""Exact original completion readiness defer + durable SQLite expedited wakeup."""
from __future__ import annotations

import pytest
from wakeup_helpers import completed, make_task, wait_admission
from wakeup_helpers import environment as environment

from local_shell_mcp.webui.subagent_task_host import shutdown_subagent_tasks
from local_shell_mcp.webui.subagent_wakeup import _now, process_wakeups


@pytest.mark.asyncio
async def test_child_terminal_sqlite_transaction_expedites_waiting_parent_delivery(environment):
    db, repo, store, child, parent, parent_run = environment
    host, task_id, allow_child_finish = await make_task(environment, slow=True)
    store.finish("local", parent_run.run_id, status="complete", text="Parent finished")
    await wait_admission()
    assert await process_wakeups(db, dispatch=lambda *args, **kwargs: None) == 0
    with db.connect() as conn:
        deferred = conn.execute("SELECT attempts,next_attempt_at FROM subagent_wakeups WHERE task_id=?",
                                (task_id,)).fetchone()
        assert deferred["attempts"] == 0
        assert deferred["next_attempt_at"] >= _now() + 3_000
    allow_child_finish.set()
    assert (await completed(host, task_id))["status"] == "completed"
    with db.connect() as conn:
        ready = conn.execute("SELECT next_attempt_at FROM subagent_wakeups WHERE task_id=?",
                             (task_id,)).fetchone()[0]
        assert ready is None  # SQL terminal trigger, no sleeping for a stale 5s deadline
    published = []

    async def dispatch(_owner, generation, *_args, **_kwargs):
        published.append(generation.run_id)

    assert await process_wakeups(db, dispatch=dispatch) == 1
    assert len(published) == 1
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_parent_settlement_sqlite_transaction_expedites_waiting_child(environment):
    db, repo, store, child, parent, parent_run = environment
    host, task_id, _ = await make_task(environment)
    assert (await completed(host, task_id))["status"] == "completed"
    await wait_admission()
    assert await process_wakeups(db, dispatch=lambda *args, **kwargs: None) == 0
    with db.connect() as conn:
        row = conn.execute("SELECT attempts,next_attempt_at FROM subagent_wakeups WHERE task_id=?",
                           (task_id,)).fetchone()
        assert row["attempts"] == 0 and row["next_attempt_at"] >= _now() + 3_000
    store.finish("local", parent_run.run_id, status="complete", text="Parent finished")
    with db.connect() as conn:
        assert conn.execute("SELECT next_attempt_at FROM subagent_wakeups WHERE task_id=?",
                            (task_id,)).fetchone()[0] is None
    scheduled = []

    async def dispatch(_owner, generation, *_args, **_kwargs):
        scheduled.append(generation.run_id)

    assert await process_wakeups(db, dispatch=dispatch) == 1
    assert len(scheduled) == 1
    await shutdown_subagent_tasks()
