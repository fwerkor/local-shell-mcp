"""Regression coverage for mutation failures and uncertain cancellation outcomes."""

import asyncio
from contextlib import contextmanager

import pytest

from local_shell_mcp import jobs
from local_shell_mcp.settings import get_settings


@pytest.fixture
def job_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    get_settings.cache_clear()
    active = set()

    async def start(cwd, name, command):
        active.add(name)
        return {"session_id": name, "backend": "fake"}

    async def sessions():
        return {"sessions": [{"session_id": item} for item in active]}

    async def kill(session_id):
        active.discard(session_id)
        return {"killed": True}

    monkeypatch.setattr(jobs, "start_shell", start)
    monkeypatch.setattr(jobs, "list_shells", sessions)
    monkeypatch.setattr(jobs, "kill_shell", kill)
    yield active
    get_settings.cache_clear()


@pytest.mark.parametrize("key", ["", "   ", "x" * 257])
async def test_invalid_idempotency_keys_do_not_reserve_jobs(job_runtime, key):
    with pytest.raises(ValueError, match="idempotency_key"):
        await jobs.start_job("echo once", idempotency_key=key)
    with jobs._store_transaction() as store:
        assert store["jobs"] == []
    assert not job_runtime


@pytest.mark.parametrize("action", ["start", "retry", "stop"])
@pytest.mark.parametrize("inspection_fails", [False, True])
async def test_cancelled_mutation_keeps_uncertain_shell_visible(
    job_runtime, monkeypatch, action, inspection_fails
):
    entered = asyncio.Event()
    release = asyncio.Event()
    if action != "start":
        original = await jobs.start_job("echo original")
        if action == "retry":
            job_runtime.clear()
            with jobs._store_transaction() as store:
                jobs._find_job(store, original["job_id"])["status"] = "failed"

    async def slow_start(cwd, name, command):
        job_runtime.add(name)
        entered.set()
        await release.wait()
        return {"session_id": name, "backend": "fake"}

    async def unsuccessful_kill(session_id):
        if action == "stop":
            entered.set()
            await release.wait()
        raise RuntimeError("termination unavailable")

    async def failed_inspection():
        raise RuntimeError("session inspection unavailable")

    monkeypatch.setattr(jobs, "start_shell", slow_start)
    monkeypatch.setattr(jobs, "kill_shell", unsuccessful_kill)
    if action == "start":
        operation = jobs.start_job("echo cancelled")
    elif action == "retry":
        operation = jobs.retry_job(original["job_id"])
    else:
        operation = jobs.stop_job(original["job_id"])
    task = asyncio.create_task(operation)
    try:
        await asyncio.wait_for(entered.wait(), 2)
        if inspection_fails:
            monkeypatch.setattr(jobs, "list_shells", failed_inspection)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    with jobs._store_transaction() as store:
        row = store["jobs"][0]
        assert row["status"] == "running"
        assert row["session_id"] in job_runtime
        assert row["completed_at"] is None
        assert "operation_id" not in row
        assert "pending_attempt" not in row
        if action == "retry":
            assert row["attempts"] == 2
        if inspection_fails:
            assert "inspection unavailable" in row["error"]
        elif action != "stop":
            assert "shell may still be running" in row["error"]
    assert not jobs._ACTIVE_JOB_OPERATIONS


async def test_managed_retry_launch_failure_is_recorded_and_replay_does_not_launch_again(
    job_runtime, monkeypatch
):
    launches = []
    monkeypatch.setitem(jobs._MANAGED_JOB_HANDLERS, "recovery-test", object())

    def launch(job_id, kind, payload, log_path):
        launches.append(job_id)
        raise RuntimeError("worker launch failed")

    monkeypatch.setattr(jobs, "_launch_managed_job", launch)
    with jobs._store_transaction() as store:
        store["jobs"].append(
            {
                "job_id": "managed-recovery",
                "kind": "managed",
                "status": "failed",
                "managed_kind": "recovery-test",
                "managed_payload": {},
                "attempts": 1,
            }
        )
    with pytest.raises(RuntimeError, match="worker launch failed"):
        await jobs.retry_job("managed-recovery", idempotency_key="retry-once")
    replay = await jobs.retry_job("managed-recovery", idempotency_key="retry-once")
    assert replay["status"] == "failed"
    assert replay["attempts"] == 2
    assert replay["exit_code"] == 1
    assert "worker launch failed" in replay["error"]
    assert launches == ["managed-recovery"]


async def test_retry_commit_failure_kills_new_shell_and_preserves_original_attempt(
    job_runtime, monkeypatch
):
    original = await jobs.start_job("echo original")
    job_runtime.clear()
    with jobs._store_transaction() as store:
        jobs._find_job(store, original["job_id"])["status"] = "failed"
    transaction = jobs._store_transaction
    fail_commit = False

    @contextmanager
    def failing_transaction():
        nonlocal fail_commit
        if fail_commit:
            fail_commit = False
            raise OSError("commit unavailable")
        with transaction() as store:
            yield store

    async def start(cwd, name, command):
        nonlocal fail_commit
        job_runtime.add(name)
        fail_commit = True
        return {"session_id": name, "backend": "fake"}

    monkeypatch.setattr(jobs, "_store_transaction", failing_transaction)
    monkeypatch.setattr(jobs, "start_shell", start)
    with pytest.raises(OSError, match="commit unavailable"):
        await jobs.retry_job(original["job_id"])
    with transaction() as store:
        row = jobs._find_job(store, original["job_id"])
        assert row["status"] == "failed"
        assert row["attempts"] == 1
        assert "retry commit failed" in row["error"]
        assert "pending_attempt" not in row
        assert "operation_id" not in row
    assert not job_runtime
    assert not jobs._ACTIVE_JOB_OPERATIONS
    assert not jobs._attempt_paths(original["job_id"], 2)["command"].exists()


@pytest.mark.parametrize("outcome", ["failed", "cancelled"])
async def test_cancellation_settles_failed_or_cancelled_side_effect(outcome):
    async def side_effect():
        if outcome == "failed":
            raise RuntimeError("side effect failed")
        raise asyncio.CancelledError

    task = asyncio.create_task(side_effect())
    assert await jobs._settle_task_after_cancellation(task) is None
    assert task.done()
