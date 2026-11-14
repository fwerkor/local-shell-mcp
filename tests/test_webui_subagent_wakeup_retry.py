"""Pinned source triggers/engine.ts retry jitter, fencing and dead-letter tests."""
from __future__ import annotations

import json

import pytest
from wakeup_helpers import completed, make_task, wait_admission
from wakeup_helpers import environment as environment

from local_shell_mcp.webui.subagent_task_host import shutdown_subagent_tasks
from local_shell_mcp.webui.subagent_wakeup import (
    _MAX_ATTEMPTS,
    _dispatch_failure,
    _retry_at,
    assert_wakeup_lease,
    process_wakeups,
)


def test_original_retry_half_jitter_base_exponential_and_five_minute_cap():
    start = 10_000
    assert _retry_at(1, start, random_half=0) == start + 500
    assert _retry_at(1, start, random_half=.5) == start + 750
    assert _retry_at(2, start, random_half=0) == start + 1_000
    assert _retry_at(3, start, random_half=.5) == start + 3_000
    assert _retry_at(30, start, random_half=0) == start + 150_000
    assert _retry_at(30, start, random_half=.5) == start + 225_000
    with pytest.raises(ValueError):
        _retry_at(0, start)
    assert _MAX_ATTEMPTS == 8


@pytest.mark.asyncio
async def test_failure_is_durable_and_lease_token_fenced_across_eight_attempts(environment):
    db, repo, store, child, parent, parent_run = environment
    host, task_id, _ = await make_task(environment)
    await completed(host, task_id)
    store.finish("local", parent_run.run_id, status="complete", text="Parent complete")
    await wait_admission()
    seen = []

    async def fail(_owner, generation, *args, **kwargs):
        seen.append((generation.run_id, kwargs["wakeup_lease"]))
        raise OSError("do not expose sensitive error body")

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        assert await process_wakeups(db, dispatch=fail) == 0
        assert len(seen) == attempt
        run_id, (claimed_id, token) = seen[-1]
        assert claimed_id == task_id
        with db.connect() as conn:
            state = conn.execute("SELECT * FROM subagent_wakeups WHERE task_id=?",
                                 (task_id,)).fetchone()
            assert state["attempts"] == attempt
            history = json.loads(state["failure_history"])
            assert len(history) == attempt
            assert history[-1]["errorType"] == "OSError"
            assert "sensitive" not in state["error"]
            assert state["run_id"] == run_id == seen[0][0]
            assert state["status"] == ("dead" if attempt == _MAX_ATTEMPTS else "dispatched")
            assert conn.execute("SELECT count(*) FROM runs WHERE conversation_id=?",
                                (parent_run.conversation_id,)).fetchone()[0] == 2
            if attempt < _MAX_ATTEMPTS:
                assert state["next_attempt_at"] is not None
                # A stale actor cannot append, nor can it mark the attempt failed.
                with pytest.raises(Exception, match="lease"):
                    assert_wakeup_lease(db, "local", run_id, (task_id, token))
                before = dict(state)
                assert _dispatch_failure(db, task_id, run_id, token, RuntimeError("stale")) is True
                assert dict(conn.execute("SELECT * FROM subagent_wakeups WHERE task_id=?",
                                         (task_id,)).fetchone()) == before
                conn.execute("UPDATE subagent_wakeups SET next_attempt_at=0 WHERE task_id=?", (task_id,))
    assert all(run == seen[0][0] for run, _ in seen)
    assert len({token for _, (_, token) in seen}) == _MAX_ATTEMPTS
    with db.connect() as conn:
        claimed = conn.execute("SELECT result_claimed FROM subagent_tasks WHERE id=?", (task_id,)).fetchone()
        assert claimed[0] == 0  # Dead letter releases child result to manual claimant
    assert json.loads(await host.check({"background_task_id": task_id}))["result"] == "child result"
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_retry_deadline_and_expired_claim_are_independent(environment):
    db, repo, store, child, parent, parent_run = environment
    host, task_id, _ = await make_task(environment)
    await completed(host, task_id)
    store.finish("local", parent_run.run_id, status="complete", text="Parent complete")
    await wait_admission()
    runs = []

    async def fail(_owner, generation, *args, **kwargs):
        runs.append(generation.run_id)
        raise RuntimeError("temporary scheduler outage")

    assert await process_wakeups(db, dispatch=fail) == 0
    assert len(runs) == 1
    for _ in range(3):
        assert await process_wakeups(db, dispatch=fail) == 0
    assert len(runs) == 1  # attempt budget not consumed while cooling down
    with db.connect() as conn:
        conn.execute("UPDATE subagent_wakeups SET next_attempt_at=0 WHERE task_id=?", (task_id,))
    assert await process_wakeups(db, dispatch=fail) == 0
    assert runs == [runs[0], runs[0]]
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_original_dead_letter_requeue_is_new_lane_tail_and_new_root_generation(environment):
    from local_shell_mcp.webui.subagent_wakeup import get_dead_wakeups, requeue_dead_wakeup

    db, repo, store, child, parent, parent_run = environment
    host, task_id, _ = await make_task(environment)
    await completed(host, task_id)
    store.finish("local", parent_run.run_id, status="complete", text="Parent complete")
    await wait_admission()
    seen = []

    async def dispatch_fail(_owner, generation, *args, **kwargs):
        seen.append(generation.run_id)
        raise OSError("offline")

    for _ in range(_MAX_ATTEMPTS):
        assert await process_wakeups(db, dispatch=dispatch_fail) == 0
        with db.connect() as conn:
            conn.execute("UPDATE subagent_wakeups SET next_attempt_at=0 WHERE task_id=?",
                         (task_id,))
    assert len(get_dead_wakeups(db, "local")) == 1
    assert get_dead_wakeups(db, "not-owner") == []
    assert requeue_dead_wakeup(db, "not-owner", task_id) is False
    assert requeue_dead_wakeup(db, "local", task_id) is True
    assert requeue_dead_wakeup(db, "local", task_id) is False
    await wait_admission()
    fresh = []

    async def dispatch_new(_owner, generation, *args, **kwargs):
        fresh.append(generation.run_id)

    assert await process_wakeups(db, dispatch=dispatch_new) == 1
    assert len(fresh) == 1 and fresh[0] != seen[0]
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM runs WHERE conversation_id=?",
                            (parent_run.conversation_id,)).fetchone()[0] == 3
        resumed = conn.execute("SELECT requeue_count,run_id,status FROM subagent_wakeups "
                               "WHERE task_id=?", (task_id,)).fetchone()
        assert (resumed["requeue_count"], resumed["run_id"], resumed["status"]) == (
            1, fresh[0], "dispatched")
    await shutdown_subagent_tasks()


@pytest.mark.asyncio
async def test_trusted_requeue_does_not_reclaim_already_manually_claimed_child(environment):
    from local_shell_mcp.webui.subagent_wakeup import requeue_dead_wakeup

    db, repo, store, child, parent, parent_run = environment
    host, task_id, _ = await make_task(environment)
    await completed(host, task_id)
    store.finish("local", parent_run.run_id, status="complete", text="Parent complete")
    await wait_admission()

    async def failing(*args, **kwargs):
        raise RuntimeError("simulated dispatch crash")

    for _ in range(_MAX_ATTEMPTS):
        await process_wakeups(db, dispatch=failing)
        with db.connect() as conn:
            conn.execute("UPDATE subagent_wakeups SET next_attempt_at=0 WHERE task_id=?", (task_id,))
    assert json.loads(await host.check({"background_task_id": task_id}))["result"] == "child result"
    assert requeue_dead_wakeup(db, "local", task_id) is False
    await shutdown_subagent_tasks()


def test_preexisting_completion_wakeup_schema_migrates_without_losing_data(tmp_path):
    import sqlite3
    from pathlib import Path

    from local_shell_mcp.sqlite_store import SQLiteDatabase

    path = Path(tmp_path) / ".local-shell-mcp"
    path.mkdir()
    initial = path / "lsm.sqlite3"
    with sqlite3.connect(initial) as conn:
        conn.execute("CREATE TABLE subagent_wakeups (task_id TEXT PRIMARY KEY,owner TEXT,"
                     "parent_conversation_id TEXT,parent_run_id TEXT,parent_agent_id TEXT,"
                     "envelope TEXT,status TEXT,run_id TEXT,lease_owner TEXT,lease_until INTEGER,"
                     "error TEXT,created_at INTEGER,updated_at INTEGER)")
        conn.execute("INSERT INTO subagent_wakeups(task_id,owner,envelope,status) "
                     "VALUES('keep','local','{}','dead')")
    for _ in range(2):
        database = SQLiteDatabase(path)
        with database.connect() as conn:
            row = conn.execute("SELECT attempts,next_attempt_at,failure_history,requeue_count,status "
                               "FROM subagent_wakeups WHERE task_id='keep'").fetchone()
            assert (row["attempts"], row["next_attempt_at"], row["failure_history"],
                    row["requeue_count"], row["status"]) == (0, None, "[]", 0, "dead")
