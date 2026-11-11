"""Test native dedup inspection and additive Worker RPC compatibility."""
from __future__ import annotations

import asyncio

import pytest

from local_shell_mcp import jobs, remote
from local_shell_mcp.settings import get_settings
from local_shell_mcp.shell_ops import kill_shell, lookup_shell_idempotency, start_shell


@pytest.fixture
def native_state(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_python_scripts_use_deterministic_immutable_native_paths(native_state):
    first = jobs.write_durable_python_script("print('ok')", "durable-key")
    assert first.exists()
    assert jobs.write_durable_python_script("print('ok')", "durable-key") == first
    with pytest.raises(ValueError, match="different Python code"):
        jobs.write_durable_python_script("print('changed')", "durable-key")
    other = jobs.write_durable_python_script("pass")
    assert other.exists() and other != first
    jobs.discard_unreferenced_python_script(other)
    assert not other.exists()
    assert first.read_text() == "print('ok')"


@pytest.mark.asyncio
async def test_managed_job_idempotency_and_worker_lookup(native_state):
    invoked = []

    async def handler(context, payload):
        invoked.append(payload)
        await asyncio.sleep(0.05)
        return {"ok": True}

    jobs.register_managed_job_handler("durable-idem-test", handler)
    created = await jobs.start_managed_job("durable-idem-test", {"a": 1}, idempotency_key="managed-unique")
    replay = await jobs.start_managed_job("durable-idem-test", {"a": 1}, idempotency_key="managed-unique")
    assert created["job_id"] == replay["job_id"]
    assert jobs.lookup_job_idempotency("managed-unique")["job_id"] == created["job_id"]
    assert (await remote._execute_job_worker_tool("job_lookup_idempotency", {
        "idempotency_key": "managed-unique"}))["job_id"] == created["job_id"]
    assert jobs.lookup_job_idempotency("not-yet-seen")["job_id"] is None
    with pytest.raises(ValueError, match="Unknown"):
        jobs.lookup_job_idempotency("managed-unique", "invalid")
    with pytest.raises(ValueError, match="idempotency"):
        jobs.lookup_job_idempotency("")
    with pytest.raises(ValueError, match="different"):
        await jobs.start_managed_job("durable-idem-test", {"a": 2}, idempotency_key="managed-unique")
    for _ in range(50):
        if (await jobs.get_job(created["job_id"]))["job"]["status"] == "succeeded":
            break
        await asyncio.sleep(0.03)
    assert invoked == [{"a": 1}]


@pytest.mark.asyncio
async def test_shell_lookup_is_read_only_and_worker_compatible(native_state):
    original = await start_shell(name="durable-probe", idempotency_key="durable-shell-key")
    try:
        found = lookup_shell_idempotency("durable-shell-key")
        assert found["session_id"] == original["session_id"]
        remote_found = await remote._execute_shell_worker_tool(
            "shell_lookup_idempotency", {"idempotency_key": "durable-shell-key"})
        assert remote_found["session_id"] == original["session_id"]
        assert lookup_shell_idempotency("unknown-shell")["session_id"] is None
        with pytest.raises(ValueError, match="Unknown"):
            lookup_shell_idempotency("durable-shell-key", "bad")
        with pytest.raises(ValueError, match="Invalid"):
            lookup_shell_idempotency(" ")
    finally:
        await kill_shell(original["session_id"])


@pytest.mark.asyncio
async def test_worker_native_persisted_call_uses_key_only_if_provided(monkeypatch):
    observed = []

    async def fake_job(*args, **kwargs):
        observed.append((args, kwargs))
        return {"job_id": "job-1", "timed_out": True}

    async def fake_python(*args):
        observed.append(args)
        return {"job_id": "job-2", "timed_out": True}

    monkeypatch.setattr(remote, "run_job_with_timeout", fake_job)
    monkeypatch.setattr(remote, "_run_python", fake_python)
    await remote._execute_command_worker_tool("run_shell_persist_tool", {
        "command": "sleep 1", "cwd": ".", "idempotency_key": "key1"})
    await remote._execute_command_worker_tool("run_python_persist_tool", {
        "code": "pass", "idempotency_key": "key2"})
    assert observed[0][-1] == {"idempotency_key": "key1"}
    assert observed[1][-1] == "key2"
