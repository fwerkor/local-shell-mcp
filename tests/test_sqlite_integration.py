"""Controller state integrations exercised with the default SQLite backend."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import DB_NAME
from local_shell_mcp.state_store import get_state_store


@pytest.fixture
def sqlite_controller(tmp_path: Path, monkeypatch):
    state = tmp_path / ".local-shell-mcp"
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(state))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.delenv("LOCAL_SHELL_MCP_STATE_BACKEND", raising=False)
    get_settings.cache_clear()
    try:
        yield state
    finally:
        get_settings.cache_clear()


def test_sessions_are_durable_in_shared_sqlite(sqlite_controller: Path) -> None:
    from local_shell_mcp.session_runtime import SessionRuntimeManager

    manager = SessionRuntimeManager()
    created = manager.manage("owner", action="start", label="research", objective="test SQLite")
    session_id = created["session_id"]
    manager.manage("owner", action="report", session_id=session_id, summary="task completed")
    restored = SessionRuntimeManager()
    record = restored.manage("owner", action="get", session_id=session_id)
    assert record["progress"]["summary"] == "task completed"
    assert (sqlite_controller / DB_NAME).is_file()
    assert not (sqlite_controller / "sessions" / f"{session_id}.json").exists()
    assert get_state_store().read_bytes(f"sessions/{session_id}.json") is not None


def test_audit_and_jobs_share_one_database(sqlite_controller: Path) -> None:
    from local_shell_mcp import audit, jobs

    audit.audit("sqlite_integration", task="migrate")
    raw = get_state_store().read_bytes("audit.jsonl")
    assert raw is not None
    assert any(json.loads(line).get("event") == "sqlite_integration" for line in raw.splitlines())
    assert not (sqlite_controller / "audit.jsonl").exists()
    payload = jobs._empty_store()
    jobs._save_store(payload)
    assert jobs._load_store()["version"] == payload["version"]
    assert get_state_store().read_bytes("jobs.json") is not None
    assert not (sqlite_controller / "jobs.json").exists()
    assert not (sqlite_controller / "jobs.json.bak").exists()


def test_dynamic_mcp_registry_stored_in_shared_db(sqlite_controller: Path) -> None:
    from local_shell_mcp.dynamic_mcp import DynamicMCPManager

    manager = DynamicMCPManager(sqlite_controller)
    manager._save({})
    assert manager._load() == {}
    assert get_state_store().read_bytes("dynamic-mcp.json") is not None
    assert not (sqlite_controller / "dynamic-mcp.json").exists()


def test_legacy_auth_and_worker_metadata_survive_automatic_import(sqlite_controller: Path) -> None:
    files = {
        "oauth-clients.json": b'{"version":1,"clients":{}}',
        "remote-workers.json": b'{"version":1,"workers":[]}',
        "remote-workers.generation": b"42",
        "audit.jsonl": b'{"event":"prior"}\n',
    }
    sqlite_controller.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (sqlite_controller / name).write_bytes(data)
    assert get_settings().state_backend == "sqlite"
    for name, data in files.items():
        assert get_state_store().read_bytes(name) == data
        assert (sqlite_controller / name).read_bytes() == data


def test_deferred_job_updates_recover_after_sqlite_cutover(sqlite_controller: Path) -> None:
    from local_shell_mcp import jobs

    job = {
        "job_id": "job_recover01", "status": "running", "output_bytes": 0,
        "log_truncated": False, "updated_at": 0,
    }
    jobs._save_store({"version": jobs.JOB_STORE_VERSION, "jobs": [job]})
    deferred_dir = sqlite_controller / "jobs" / "deferred"
    deferred_dir.mkdir(parents=True)
    identifier = "000001-rollback"
    deferred = deferred_dir / f"{identifier}.json"
    deferred.write_text(json.dumps({
        "version": jobs.MANAGED_DEFERRED_UPDATE_VERSION,
        "update_id": identifier,
        "job_id": job["job_id"],
        "operation": "append_log",
        "payload": {"bytes": 123, "truncated": False},
    }))
    with jobs._store_transaction() as store:
        assert store["jobs"][0]["output_bytes"] == 123
    assert jobs._load_store()["jobs"][0]["output_bytes"] == 123
    assert not deferred.exists()
    assert (sqlite_controller / "jobs" / "deferred").is_dir()
