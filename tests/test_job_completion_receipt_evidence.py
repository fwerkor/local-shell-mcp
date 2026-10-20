"""Missing completion receipts should retain bounded, non-sensitive diagnostics."""

import builtins
from pathlib import Path

import pytest

from local_shell_mcp import jobs


@pytest.mark.parametrize(
    ("payload", "state"),
    [
        (None, "missing"),
        ("{bad", "invalid_json"),
        ('["not an object"]', "invalid_shape"),
        ('{"exit_code":0}', "valid"),
    ],
)
def test_lost_shell_audits_receipt_state_once(tmp_path: Path, monkeypatch, payload, state):
    path = tmp_path / "attempt.status.json"
    if payload is not None:
        path.write_text(payload)
    # Simulate a race in which reconciliation saw no valid receipt before an
    # external writer made the receipt visible to the diagnostic snapshot.
    monkeypatch.setattr(jobs, "_read_status", lambda _job: None)
    recorded = []
    monkeypatch.setattr(jobs, "audit", lambda event, **data: recorded.append((event, data)))
    job = {
        "job_id": "job_1", "kind": "shell", "status": "running",
        "session_id": "ended", "attempts": 2, "status_path": str(path),
    }
    jobs._refresh_job_status(job, set(), now=10)
    jobs._refresh_job_status(job, set(), now=11)
    assert job["status"] == "lost"
    assert job["error"] == "job session exited without a completion record"
    assert recorded == [("job_completion_receipt_unavailable", {
        "job_id": "job_1", "session": "ended", "attempt": 2,
        "receipt_state": state,
    })]


def test_receipt_diagnostics_never_expose_receipt_content(tmp_path, monkeypatch):
    path = tmp_path / "receipt"
    path.write_text('{"private_token":"sensitive-token"}')
    captured = []
    monkeypatch.setattr(jobs, "audit", lambda event, **fields: captured.append((event, fields)))
    jobs._audit_missing_completion_receipt({"job_id": "abc", "status_path": str(path)})
    assert captured[0][1]["receipt_state"] == "valid"
    assert "sensitive-token" not in str(captured)


def test_receipt_diagnostics_distinguish_missing_path_unreadable_encoding(tmp_path, monkeypatch):
    path = tmp_path / "receipt"
    assert jobs._completion_receipt_state(None) == "no_path"
    assert jobs._completion_receipt_state(path) == "missing"
    path.write_bytes(b"\xff")
    assert jobs._completion_receipt_state(path) == "invalid_encoding"
    monkeypatch.setattr(Path, "read_text", lambda *_a, **_k: (_ for _ in ()).throw(PermissionError()))
    assert jobs._completion_receipt_state(path) == "unreadable"


def test_audit_outage_does_not_block_job_reconciliation(monkeypatch):
    monkeypatch.setattr(jobs, "audit", lambda *_a, **_k: (_ for _ in ()).throw(OSError()))
    row = {"kind": "shell", "status": "running", "session_id": "gone"}
    assert jobs._refresh_job_status(row, set(), now=10)["status"] == "lost"


def test_healthy_or_active_jobs_do_not_emit_missing_receipt(monkeypatch):
    recorded = []
    monkeypatch.setattr(jobs, "audit", lambda event, **fields: recorded.append(event))
    row = {"kind": "shell", "status": "running", "session_id": "active"}
    jobs._refresh_job_status(row, {"active"}, now=10)
    assert row["status"] == "running" and not recorded


@pytest.mark.parametrize("entrypoint", ["worker", "frozen"])
def test_runner_startup_failure_keeps_private_diagnostic(tmp_path, monkeypatch, entrypoint):
    from local_shell_mcp import main as controller_main
    from local_shell_mcp import remote_worker

    dispatch = remote_worker.main if entrypoint == "worker" else controller_main.main

    receipt = tmp_path / "job.status.json"

    def broken_runner(_args):
        raise RuntimeError("TOKEN_SHOULD_NOT_BE_LOGGED")

    monkeypatch.setattr(jobs, "run_job_runner_cli", broken_runner)
    with pytest.raises(RuntimeError, match="TOKEN_SHOULD_NOT_BE_LOGGED"):
        dispatch(["job-runner", "--status-file", str(receipt)])
    path = tmp_path / "job.status.json.runner-error.json"
    evidence = path.read_text()
    assert "RuntimeError" in evidence
    assert "broken_runner" in evidence
    assert "TOKEN_SHOULD_NOT_BE_LOGGED" not in evidence
    if jobs.os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
    # A completed runner should not leave a false startup-failure artifact.
    receipt.write_text('{"exit_code":1}')
    path.unlink()
    with pytest.raises(RuntimeError):
        dispatch(["job-runner", "--status-file", str(receipt)])
    assert not path.exists()


def test_runner_failure_evidence_is_pruned_with_job_attempt(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(jobs, "get_settings", lambda: SimpleNamespace(
        state_dir=tmp_path, stateless_controller=False,
    ))
    runtime = tmp_path / "jobs"
    runtime.mkdir()
    receipt = runtime / "job_123-attempt-1.status.json.runner-error.json"
    receipt.write_text("private diagnostic")
    jobs._remove_attempt_files("job_123")
    assert not receipt.exists()


def test_non_utf8_completion_receipt_becomes_lost_with_diagnostics(tmp_path, monkeypatch):
    path = tmp_path / "invalid.status.json"
    path.write_bytes(b"\xff\xfe")
    recorded = []
    monkeypatch.setattr(jobs, "audit", lambda event, **fields: recorded.append((event, fields)))
    row = {
        "job_id": "invalid", "status": "running", "kind": "shell",
        "session_id": "gone", "status_path": str(path),
    }
    assert jobs._refresh_job_status(row, set(), now=10)["status"] == "lost"
    assert recorded[0][1]["receipt_state"] == "invalid_encoding"


@pytest.mark.parametrize("entrypoint", ["worker", "frozen"])
def test_runner_import_time_failure_is_recorded(tmp_path, monkeypatch, entrypoint):
    from local_shell_mcp import main as controller_main
    from local_shell_mcp import remote_worker

    dispatch = remote_worker.main if entrypoint == "worker" else controller_main.main
    receipt = tmp_path / "crashed.status.json"
    original_import = builtins.__import__

    def fail_dependency(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 1 and name == "jobs" and "run_job_runner_cli" in (fromlist or ()):
            raise ImportError("startup secret should stay private")
        if level == 1 and name == "remote_worker_cli":
            raise AssertionError("worker CLI imported before Job dispatch")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fail_dependency)
    with pytest.raises(ImportError, match="startup secret"):
        dispatch(["job-runner", "--status-file", str(receipt)])

    sidecar = tmp_path / "crashed.status.json.runner-error.json"
    evidence = sidecar.read_text()
    assert "ImportError" in evidence
    assert "startup secret" not in evidence


def test_abandoned_retry_attempt_removes_completion_and_diagnostic_files(tmp_path):
    status = tmp_path / "job_123-attempt-2.status.json"
    paths = {
        "command": tmp_path / "job_123-attempt-2.command",
        "log": tmp_path / "job_123-attempt-2.log",
        "status": status,
    }
    for item in paths.values():
        item.write_text("existing")
    sidecar = status.with_name(status.name + ".runner-error.json")
    sidecar.write_text("diagnostic")
    jobs._remove_attempt_paths(paths)
    assert all(not item.exists() for item in paths.values())
    assert not sidecar.exists()


def test_attempt_restart_removes_stale_runner_evidence(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(jobs, "get_settings", lambda: SimpleNamespace(
        state_dir=tmp_path, shell_executable="bash", max_job_log_bytes=4096,
        shell_env_blocklist=[], shell_env_blocked_prefixes=[],
    ))
    monkeypatch.setattr(jobs, "check_command_policy", lambda _cmd: None)
    monkeypatch.setattr(jobs, "resolve_path", lambda _cwd, must_exist=False: tmp_path)
    status = tmp_path / "jobs" / "job123-attempt-1.status.json"
    status.parent.mkdir(parents=True)
    sidecar = status.with_name(status.name + ".runner-error.json")
    sidecar.write_text("stale evidence")
    paths, _command = jobs._prepare_attempt("job123", 1, "true", ".")
    assert paths["status"] == status
    assert not sidecar.exists()
    jobs._remove_attempt_paths(paths)
