"""Native task lease, revocation and recovery tests using the real SQLite store."""
from __future__ import annotations

import json
import sys
import time

import pytest

from local_shell_mcp import jobs, tools
from local_shell_mcp.settings import get_settings
from local_shell_mcp.shell_ops import quote_shell_argument, quote_shell_executable
from local_shell_mcp.webui import durable_tasks as durable
from local_shell_mcp.webui import lsm_tool_registry as registry
from local_shell_mcp.webui.providers import ModelToolCall
from local_shell_mcp.webui.routes import _repo

SCOPES = {"shell:read", "shell:write", "shell:execute", "remote:use"}


@pytest.fixture
def bound(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "true")
    monkeypatch.setattr(registry, "_AUTHORIZATION_RECHECK_SECONDS", 0.02)
    get_settings.cache_clear()
    registry._registry_for_state.cache_clear()
    repo = _repo()
    cids = []
    for index in range(2):
        cid = repo.create_conversation("local", {"title": str(index)})["conversationId"]
        repo.save_setting("local", "agent.machine_policy.conversation." + cid,
                          {"local": "write", "worker1": "write", "worker2": "write"})
        with repo.database.connect() as db:
            db.execute("INSERT INTO runs(id,conversation_id,status,state,created_at,updated_at) "
                       "VALUES(?,?,'running','{}',?,?)", ("run-" + str(index), cid, 1, 1))
        cids.append(cid)
    yield repo, cids, tmp_path
    registry._registry_for_state.cache_clear()
    get_settings.cache_clear()


def rows():
    with durable._database().connect() as db:
        return [dict(x) for x in db.execute("SELECT * FROM agent_durable_tasks ORDER BY created_at")]


def command(code):
    return quote_shell_executable(sys.executable) + " -c " + quote_shell_argument(code)


async def call(cid, index, name, args, *, run="run-0", scopes=SCOPES, expires=None):
    return json.loads(await registry.call_tool(
        "local", cid, ModelToolCall(index, name, args),
        run_id=run, granted_scopes=set(scopes), grant_expires=expires,
    ))


@pytest.mark.asyncio
async def test_creation_intent_is_durable_before_native_tool_invocation(bound, monkeypatch):
    _, (cid, _), _ = bound
    seen = []

    async def fake_start(command, cwd=".", name=None, idempotency_key=None):
        assert idempotency_key.startswith("agent-")
        existing = rows()
        assert len(existing) == 1 and existing[0]["state"] in {"reserved", "active"}
        assert existing[0]["idempotency_key"] == idempotency_key
        seen.append(idempotency_key)
        return {"job_id": "genuine-job-123", "status": "running"}

    monkeypatch.setattr(tools, "start_job", fake_start)
    result = await call(cid, "native", "job_start", {"command": "echo hello"})
    assert result["data"]["job_id"] == "genuine-job-123"
    assert rows()[0]["state"] == "active"
    assert rows()[0]["native_id"] == "genuine-job-123"
    # Replaying the exact same Agent tool call reuses the persisted key.
    again = await call(cid, "native", "job_start", {"command": "echo hello"})
    assert again["data"]["job_id"] == "genuine-job-123"
    assert seen == [seen[0], seen[0]]
    with pytest.raises(PermissionError, match="cannot change"):
        await call(cid, "native", "job_start", {"command": "echo changed"})


@pytest.mark.asyncio
async def test_cross_conversation_control_is_rejected_and_revocation_is_targeted(bound):
    repo, (cid, other), _ = bound
    first = await call(cid, "one", "job_start", {"command": command("import time; time.sleep(9)")})
    second = await call(other, "two", "job_start", {"command": command("import time; time.sleep(9)")}, run="run-1")
    first_id, second_id = first["data"]["job_id"], second["data"]["job_id"]
    assert first_id != second_id
    try:
        with pytest.raises(PermissionError, match="does not belong"):
            await call(cid, "stop-other", "job_stop", {"job_id": second_id})
        with pytest.raises(PermissionError, match="does not belong"):
            await call(cid, "retry-other", "job_retry", {"job_id": second_id})
        repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "none"})
        assert durable.mark_revoked("local") == 1
        assert await durable.sweep() == 1
        assert rows()[0]["state"] == "stopped"
        assert rows()[1]["state"] == "active"
        assert (await jobs.get_job(second_id))["job"]["status"] in {"running", "starting"}
    finally:
        await jobs.stop_job(second_id)
        await jobs.stop_job(first_id)


@pytest.mark.asyncio
async def test_crash_after_native_create_before_response_is_recovered_without_reexecution(bound):
    repo, (cid, _), _ = bound
    cmd = command("import time; time.sleep(8)")
    intent = durable.reserve("local", cid, "run-0", "pending", "job_start",
                            {"command": cmd}, SCOPES, None)
    native = await jobs.start_job(cmd, idempotency_key=intent.key)
    try:
        assert rows()[0]["native_id"] is None
        assert jobs.lookup_job_idempotency(intent.key)["job_id"] == native["job_id"]
        repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "read"})
        assert durable.mark_revoked("local") == 1
        assert await durable.sweep() == 1
        assert rows()[0]["native_id"] == native["job_id"]
        assert rows()[0]["state"] == "stopped"
    finally:
        await jobs.stop_job(native["job_id"])


@pytest.mark.asyncio
async def test_foreign_native_idempotency_key_cannot_be_claimed(bound):
    _, (cid, _), _ = bound
    native = await jobs.start_job(command("import time; time.sleep(8)"), idempotency_key="external-key")
    try:
        with pytest.raises(PermissionError, match="unowned task"):
            await call(cid, "collision", "job_start",
                       {"command": command("import time; time.sleep(8)"),
                        "idempotency_key": "external-key"})
        assert rows()[0]["state"] == "foreign"
        assert (await jobs.get_job(native["job_id"]))["job"]["job_id"] == native["job_id"]
    finally:
        await jobs.stop_job(native["job_id"])


def test_machine_grants_and_run_abort_are_durable(bound):
    repo, (cid, _), _ = bound
    first = durable.reserve("local", cid, "run-0", "a", "job_start",
                            {"command": "echo a", "machine": "worker1"}, SCOPES, None)
    assert first.key
    assert rows()[0]["machine"] == "worker1"
    with pytest.raises(PermissionError, match="already owned"):
        durable.reserve("local", cid, "run-0", "b", "job_start",
                        {"command": "echo b", "machine": "worker1", "idempotency_key": first.key},
                        SCOPES, None)
    durable.cancel_run("local", "run-0")
    assert durable.is_run_cancelled("run-0")
    assert rows()[0]["state"] == "cancel_pending"
    with pytest.raises(PermissionError, match="cancelled"):
        durable.reserve("local", cid, "run-0", "c", "job_start", {"command": "echo"}, SCOPES, None)
    # An unrelated conversation and its run are unchanged.
    assert not durable.is_run_cancelled("run-1")
    assert repo.conversation("local", cid) is not None


@pytest.mark.asyncio
async def test_worker_disconnect_cancel_retry_preserves_other_machines(bound, monkeypatch):
    repo, (cid, other), _ = bound
    active = {}
    attempts = []
    online = False

    async def worker(settings, machine, tool, args, **kwargs):
        nonlocal online
        attempts.append((machine, tool))
        if tool == "job_start":
            key = args["idempotency_key"]
            active.setdefault((machine, key), "real-" + machine + "-" + str(len(active)))
            return tools._ok({"job_id": active[(machine, key)]})
        if tool == "job_lookup_idempotency":
            return tools._ok({"job_id": active.get((machine, args["idempotency_key"]))})
        if tool == "job_stop":
            if not online:
                return tools._handled_error(ConnectionError("worker offline"))
            return tools._ok({"job_id": args["job_id"], "status": "stopped"})
        raise AssertionError(tool)

    monkeypatch.setattr(tools, "_remote_call", worker)
    a = await call(cid, "w1", "job_start", {"machine": "worker1", "command": "sleep 5"})
    b = await call(other, "w2", "job_start", {"machine": "worker2", "command": "sleep 5"}, run="run-1")
    assert a["data"]["job_id"] != b["data"]["job_id"]
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"worker1": "none", "local": "write"})
    durable.mark_revoked("local")
    assert await durable.sweep() == 0
    assert rows()[0]["state"] == "cancel_pending"
    assert rows()[1]["state"] == "active"
    with durable._database().connect() as db:
        db.execute("UPDATE agent_durable_tasks SET next_attempt_at=NULL WHERE state='cancel_pending'")
    online = True
    assert await durable.sweep() == 1
    assert rows()[0]["state"] == "stopped"
    assert rows()[1]["state"] == "active"
    assert ("worker1", "job_stop") in attempts
    assert ("worker2", "job_stop") not in attempts


@pytest.mark.asyncio
async def test_expired_grant_and_project_override(bound, monkeypatch):
    repo, (cid, _), _ = bound
    intent = durable.reserve("local", cid, "run-0", "exp", "job_start",
                            {"command": "echo expiration"}, SCOPES, int(time.time()) + 90)
    durable.bind(intent, {"ok": True, "data": {"job_id": "exp-id"}})
    with durable._database().connect() as db:
        db.execute("UPDATE agent_durable_tasks SET grant_expires=? WHERE id=?",
                   (int(time.time()) - 1, intent.id))
    assert durable.mark_revoked("local") == 1
    assert rows()[0]["state"] == "cancel_pending"
    # Controller scope latches revocation even after a policy is restored.
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "write"})
    assert rows()[0]["state"] == "cancel_pending"
    project = repo.create_project("local", "limited")
    repo.update_conversation("local", cid, {"projectId": project["id"]})
    repo.save_setting("local", "agent.machine_policy.project." + project["id"], {"local": "read"})
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {})
    intent2 = durable.reserve("local", cid, "run-0", "project", "job_start", {"command": "echo"}, SCOPES, None)
    assert intent2.key
    assert durable.mark_revoked("local") >= 1
    assert {row["state"] for row in rows()} == {"cancel_pending"}


@pytest.mark.asyncio
async def test_shell_journal_lookup_and_native_stop(bound):
    repo, (cid, _), _ = bound
    result = await call(cid, "interactive", "shell_start", {"cwd": ".", "name": "agent-revoke-test"})
    shell_id = result["data"]["session_id"]
    try:
        assert rows()[0]["native_id"] == shell_id
        assert durable._kind("shell_start") == "shell"
        assert durable._kind("job_retry") == "retry"
        assert durable._payload(([], {"ok": True, "data": {"session_id": shell_id}}))["session_id"] == shell_id
        assert durable._payload("invalid") == {}
        repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "none"})
        durable.mark_revoked("local")
        assert await durable.sweep() == 1
        assert rows()[0]["state"] == "stopped"
    finally:
        from local_shell_mcp.shell_ops import kill_shell
        await kill_shell(shell_id)


@pytest.mark.asyncio
async def test_uncertain_intent_never_guesses_an_id_or_starts_a_job(bound):
    repo, (cid, _), _ = bound
    durable.reserve("local", cid, "run-0", "never-created", "job_start", {"command": "touch should-not-exist"}, SCOPES, None)
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "none"})
    durable.mark_revoked("local")
    assert await durable.sweep() == 0
    assert rows()[0]["native_id"] is None
    assert rows()[0]["last_error"] == "native ID not yet confirmed"
    assert rows()[0]["state"] == "cancel_pending"
