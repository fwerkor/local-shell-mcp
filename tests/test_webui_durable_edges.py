"""Fault injection at the native durable-task reconciliation boundary."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui import durable_tasks as durable
from local_shell_mcp.webui.routes import _repo

SCOPES = {"shell:read", "shell:write", "shell:execute", "remote:use"}


@pytest.fixture
def policy(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "true")
    get_settings.cache_clear()
    repo = _repo()
    cid = repo.create_conversation("owner", {"title": "edge"})["conversationId"]
    repo.save_setting("owner", "agent.machine_policy.global", {"local": "write", "worker": "write"})
    with repo.database.connect() as db:
        db.execute("INSERT INTO runs(id,conversation_id,status,state,created_at,updated_at) "
                   "VALUES('run',?,'running','{}',1,1)", (cid,))
    yield repo, cid
    get_settings.cache_clear()


def all_rows():
    with durable._database().connect() as db:
        return [dict(r) for r in db.execute("SELECT * FROM agent_durable_tasks ORDER BY created_at")]


def intent(cid, call="call", name="job_start", args=None, expires=None):
    return durable.reserve("owner", cid, "run", call, name, args or {"command": "true"}, SCOPES, expires)


def test_requirement_classification_transfer_and_managed_retry(monkeypatch):
    from local_shell_mcp import jobs

    assert durable._requirements("remote_transfer", {"source_machine": "worker"}) == {
        "worker": "read", "local": "write"}
    assert durable._requirements("remote_transfer", {"source_machine": "worker", "destination_machine": "worker"}) == {
        "worker": "write"}
    monkeypatch.setattr(jobs, "job_retry_machine_requirements", lambda _job: [
        ("worker", "read"), ("worker", "write"), ("local", "read")])
    assert durable._requirements("job_retry", {"job_id": "j"}) == {"local": "write", "worker": "write"}
    assert durable._requirements("job_retry", {"job_id": "j", "machine": "worker"}) == {"worker": "write"}


def test_reject_invalid_creation_and_replayed_identity(policy):
    repo, cid = policy
    for name, args in [("file_read", {}), ("run_python", {"code": "pass"})]:
        with pytest.raises(ValueError, match="Not a durable"):
            intent(cid, name=name, args=args)
    for key in ["", " abc ", "x" * 257, 7]:
        with pytest.raises(PermissionError, match="caller-supplied idempotency"):
            intent(cid, name="job_start", args={"command": "true", "idempotency_key": key})
    with pytest.raises(PermissionError, match="Conversation ownership"):
        durable.reserve("owner", "missing", "run", "a", "job_start", {"command": "true"}, SCOPES, None)
    with pytest.raises(PermissionError, match="Generation can no longer"):
        durable.reserve("owner", cid, "not-a-run", "b", "job_start", {"command": "true"}, SCOPES, None)
    held = intent(cid)
    assert intent(cid).id == held.id
    with pytest.raises(PermissionError, match="cannot change"):
        intent(cid, args={"command": "false"})
    with durable._database().connect() as db:
        db.execute("UPDATE agent_durable_tasks SET state='cancel_pending' WHERE id=?", (held.id,))
    with pytest.raises(PermissionError, match="cancelled"):
        intent(cid)
    with pytest.raises(PermissionError, match="revoked"):
        durable.check_intent(held)
    repo.save_setting("owner", "agent.machine_policy.global", {"local": "none"})
    assert durable.mark_revoked("owner") == 0


def test_identity_bind_failure_paths_and_wrapped_result(policy):
    _, cid = policy
    held = intent(cid)
    assert durable.bind(held, {"ok": True, "data": {"info": "no task"}}) is False
    assert durable._payload(42) == {}
    assert durable._payload(SimpleNamespace(model_dump=lambda **_: {"ok": True, "data": {"job_id": "j"}})) == {"job_id": "j"}
    assert durable._payload({"structuredContent": {"data": {"job": {"job_id": "k"}}}}) == {"job_id": "k"}
    assert durable._payload({"structured_content": {"job_id": "z"}}) == {"job_id": "z"}
    assert durable.bind(held, {"job_id": "task-a"}) is True
    assert durable.bind(held, {"job_id": "task-a"}) is True
    with pytest.raises(PermissionError, match="identity changed"):
        durable.bind(held, {"job_id": "different"})
    another = intent(cid, call="another")
    with pytest.raises(PermissionError, match="belongs to another"):
        durable.bind(another, {"job_id": "task-a"})
    with pytest.raises(PermissionError, match="does not belong"):
        durable.owned("owner", cid, "job_stop", {"job_id": "different"})
    with pytest.raises(PermissionError, match="required"):
        durable.owned("owner", cid, "job_stop", {})
    durable.owned("owner", cid, "job_stop", {"job_id": "task-a"})
    durable.mark_stopped("owner", cid, "job_stop", {"job_id": "task-a"})
    assert all_rows()[0]["state"] == "stopped"
    assert durable.owned("owner", cid, "job_list", {}) is None
    assert durable.mark_stopped("owner", cid, "job_list", {}) is None


def test_abort_and_session_owner_and_expires(policy):
    repo, cid = policy
    intent(cid)
    with pytest.raises(PermissionError, match="owner mismatch"):
        durable.cancel_run("another", "run")
    assert durable.is_run_cancelled("run") is False
    durable.cancel_run("owner", "run")
    assert durable.is_run_cancelled("run") is True
    assert all_rows()[0]["state"] == "cancel_pending"
    assert durable._revoked(all_rows()[0])
    with repo.database.connect() as db:
        db.execute("UPDATE runs SET status='aborted' WHERE id='run'")
    with pytest.raises(PermissionError, match="no longer"):
        intent(cid, call="post-abort")
    # Deleted conversation still revokes, without guessing a task ID.
    repo.delete_conversation("owner", cid)
    assert durable._revoked(all_rows()[0])


def test_restart_preserves_background_job_but_explicit_abort_revokes_it(policy):
    repo, cid = policy
    native = intent(cid)
    assert all_rows()[0]["state"] == "reserved"
    with repo.database.connect() as db:
        db.execute("UPDATE runs SET status='interrupted' WHERE id='run'")
    # Recovery of interrupted generation state is not an authorization revoke.
    assert durable.mark_revoked("owner") == 0
    assert not durable._revoked(all_rows()[0])
    with pytest.raises(PermissionError, match="generation"):
        durable.check_intent(native)
    assert all_rows()[0]["state"] == "reserved"
    # A recorded explicit abort is distinct from a Controller restart.
    with repo.database.connect() as db:
        db.execute("UPDATE runs SET status='aborted' WHERE id='run'")
    assert durable.mark_revoked("owner") == 1
    assert durable._revoked(all_rows()[0])
    assert all_rows()[0]["state"] == "cancel_pending"


@pytest.mark.asyncio
async def test_lookup_error_and_stop_statuses(policy, monkeypatch):
    from local_shell_mcp import tools

    _, cid = policy
    held = intent(cid, name="shell_start", args={"name": "probe", "machine": "worker"})
    row = all_rows()[0]
    calls = []

    async def remote(_settings, machine, name, arguments, **_kwargs):
        calls.append((machine, name, arguments))
        if name == "shell_lookup_idempotency":
            return {"ok": True, "data": {"session_id": "native-shell"}}
        if name == "shell_kill":
            return {"ok": True, "data": {"killed": True}}
        return {"ok": False}

    monkeypatch.setattr(tools, "_remote_call", remote)
    assert await durable._lookup(row) == "native-shell"
    assert calls[0][1] == "shell_lookup_idempotency"
    assert durable.bind(held, {"session_id": "native-shell"})
    row = all_rows()[0]
    assert await durable._stop(row)
    assert calls[-1][1] == "shell_kill"
    monkeypatch.setattr(tools, "_remote_call", lambda *args, **kwargs: _failure())

    async def _failure():
        return {"ok": False, "data": {"status": "error"}}

    with pytest.raises(RuntimeError, match="lookup"):
        await durable._lookup(row)
    assert not await durable._stop(row)
    row["native_id"] = None
    assert await durable._stop(row) is False


@pytest.mark.asyncio
async def test_stop_requires_actual_native_terminal_status(policy, monkeypatch):
    from local_shell_mcp import tools

    _, cid = policy
    job = intent(cid, call="job-status", args={"command": "true", "machine": "worker"})
    durable.bind(job, {"job_id": "native-job"})
    shell = intent(cid, call="shell-status", name="shell_start", args={"machine": "worker"})
    durable.bind(shell, {"session_id": "native-shell"})
    job_row, shell_row = all_rows()
    reply = {"ok": True, "data": {"job": {"status": "stopping"}, "killed": False}}

    async def remote(_settings, _machine, _tool, _args, **_kwargs):
        return reply

    monkeypatch.setattr(tools, "_remote_call", remote)
    assert not await durable._stop(job_row)
    reply = {"ok": True, "data": {"job": {"status": "stopped"}, "killed": False}}
    assert await durable._stop(job_row)
    # Already-exited native jobs are complete, even when nothing was killed.
    reply = {"ok": True, "data": {"job": {"status": "exited"}, "killed": False}}
    assert await durable._stop(job_row)
    reply = {"ok": True, "data": {"killed": False}}
    assert not await durable._stop(shell_row)
    reply = {"ok": True, "data": {"killed": True}}
    assert await durable._stop(shell_row)
    reply = {"ok": False, "data": {"killed": True}}
    assert not await durable._stop(shell_row)
    reply = {"ok": True, "data": {"job": {"status": "running"}}}
    assert not await durable._stop(job_row)


@pytest.mark.asyncio
async def test_offline_retries_and_service_restarts(policy, monkeypatch):
    repo, cid = policy
    held = intent(cid, name="job_start", args={"command": "true", "machine": "worker"})
    durable.bind(held, {"job_id": "native-worker-id"})
    repo.save_setting("owner", "agent.machine_policy.global", {"worker": "none", "local": "write"})
    assert durable.mark_revoked("owner") == 1
    observations = []

    async def failed(row):
        observations.append(row["native_id"])
        raise ConnectionError("offline")

    monkeypatch.setattr(durable, "_stop", failed)
    assert await durable.sweep() == 0
    assert all_rows()[0]["state"] == "cancel_pending"
    assert all_rows()[0]["last_error"] == "ConnectionError"
    # Recover the SQLite state from a newly instantiated repository.
    from local_shell_mcp.sqlite_store import shared_database

    shared_database.cache_clear()
    assert all_rows()[0]["native_id"] == "native-worker-id"
    with durable._database().connect() as db:
        db.execute("UPDATE agent_durable_tasks SET next_attempt_at=NULL")
    async def succeeds(row):
        observations.append(row["native_id"])
        return True

    monkeypatch.setattr(durable, "_stop", succeeds)
    assert await durable.sweep() == 1
    assert all_rows()[0]["state"] == "stopped"
    assert observations == ["native-worker-id", "native-worker-id"]


@pytest.mark.asyncio
async def test_scheduler_exits_on_cancel_and_logs_other_errors(monkeypatch):
    visited = asyncio.Event()
    async def faulty():
        visited.set()
        raise RuntimeError("temporary")

    monkeypatch.setattr(durable, "sweep", faulty)
    monkeypatch.setattr(durable, "_POLL", 0.01)
    task = asyncio.create_task(durable.serve())
    await asyncio.wait_for(visited.wait(), timeout=3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
