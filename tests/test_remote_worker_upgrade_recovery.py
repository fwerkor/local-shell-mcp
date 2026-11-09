"""Recovery regressions for worker upgrades, including unimportable bundles."""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from local_shell_mcp import remote_worker_bootstrap as bootstrap
from local_shell_mcp import remote_worker_installer as installer
from local_shell_mcp import remote_worker_state as state


def _runtime(root: Path, worker_code: str) -> None:
    package = root / "local_shell_mcp"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "remote_worker.py").write_text(worker_code, encoding="utf-8")


def _bundle(worker_code: str) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for filename, content in (
            ("local_shell_mcp/__init__.py", ""),
            ("local_shell_mcp/remote_worker.py", worker_code),
        ):
            data = content.encode("utf-8")
            info = tarfile.TarInfo(filename)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("LOCAL_SHELL_MCP_WORKER_BOOTSTRAPPED", raising=False)
    state.write_worker_config(
        server="https://example.test", name="worker", workdir=str(tmp_path),
        runtime_digest="previous-digest", runtime_version="previous-version",
    )
    _runtime(state.worker_runtime_dir(), 'print("PREVIOUS_CONNECTED", flush=True)\n')
    state.install_launcher()


def _mock_bundle(monkeypatch: pytest.MonkeyPatch, code: str) -> str:
    payload = _bundle(code)
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(
        installer, "fetch_manifest",
        lambda server: {"sha256": digest, "bundle_version": "bad-version", "url": "/bundle"},
    )
    monkeypatch.setattr(installer, "_fetch_bytes", lambda url, timeout=60: payload)
    return digest


def _run_supervisor() -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    # Deliberately omit local source imports: the bootstrap must work without
    # any local_shell_mcp modules available outside the runtime.
    env["PYTHONPATH"] = str(state.worker_runtime_dir())
    return subprocess.run(
        [sys.executable, str(state.worker_bootstrap_path())],
        env=env, capture_output=True, text=True, timeout=12, check=False,
    )


def test_failed_upgrade_restores_previous_runtime_and_reconnects_forever(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _mock_bundle(monkeypatch, 'raise ImportError("upgrade is unusable")\n')
    saved_bootstrap = state.worker_bootstrap_path().read_bytes()

    for _ in range(2):
        installer.install_or_update_runtime("https://example.test")
        assert (state.worker_state_dir() / "runtime.previous").is_dir()
        assert (state.worker_state_dir() / "runtime.pending.json").is_file()
        state.install_launcher()
        assert state.worker_bootstrap_path().read_bytes() == saved_bootstrap

        result = _run_supervisor()
        assert result.returncode == 0, result.stderr
        assert "PREVIOUS_CONNECTED" in result.stdout
        assert "rolled back" in result.stderr
        assert state.read_worker_config()["runtime_digest"] == "previous-digest"
        assert state.read_worker_config()["runtime_version"] == "previous-version"
        assert not (state.worker_state_dir() / "runtime.pending.json").exists()
        assert not (state.worker_state_dir() / "runtime.previous").exists()
        assert not (state.worker_state_dir() / "runtime.attempted").exists()


def test_interrupted_startup_rolls_back_before_launch(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _mock_bundle(monkeypatch, 'raise ImportError("cannot import")\n')
    installer.install_or_update_runtime("https://example.test")
    (state.worker_state_dir() / "runtime.attempted").write_text("1\n", encoding="utf-8")

    result = _run_supervisor()
    assert result.returncode == 0
    assert "PREVIOUS_CONNECTED" in result.stdout
    assert "cannot import" not in result.stderr
    assert state.read_worker_config()["runtime_digest"] == "previous-digest"


def test_good_worker_poll_commits_upgrade(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    digest = _mock_bundle(monkeypatch, 'print("UPGRADED", flush=True)\n')
    installer.install_or_update_runtime("https://example.test")
    assert state.read_worker_config()["runtime_digest"] == digest
    installer.confirm_runtime_healthy()
    assert not (state.worker_state_dir() / "runtime.pending.json").exists()
    assert not (state.worker_state_dir() / "runtime.previous").exists()
    result = _run_supervisor()
    assert result.returncode == 0
    assert "UPGRADED" in result.stdout
    assert "rolled back" not in result.stderr


def test_upgrade_install_failure_keeps_previous_runtime(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _mock_bundle(monkeypatch, 'print("new")\n')
    original = installer.update_runtime_metadata

    def fail_metadata(digest: str, version: str):
        raise OSError("metadata write failed")

    monkeypatch.setattr(installer, "update_runtime_metadata", fail_metadata)
    with pytest.raises(OSError, match="metadata write failed"):
        installer.install_or_update_runtime("https://example.test")
    assert (state.worker_runtime_dir() / "local_shell_mcp" / "remote_worker.py").read_text() == (
        'print("PREVIOUS_CONNECTED", flush=True)\n'
    )
    assert not (state.worker_state_dir() / "runtime.pending.json").exists()
    monkeypatch.setattr(installer, "update_runtime_metadata", original)


def test_trial_timeout_terminates_hung_candidate(tmp_path, monkeypatch):
    pending = tmp_path / "runtime.pending.json"
    pending.write_text(json.dumps({"candidate_digest": "broken"}), encoding="utf-8")
    monkeypatch.setattr(bootstrap, "_TRIAL_START_TIMEOUT_S", 0.0)

    class Hanging:
        returncode = 1
        terminated = False
        def poll(self):
            return None
        def terminate(self):
            self.terminated = True
        def wait(self, timeout=None):
            return 1

    process = Hanging()
    assert bootstrap._wait_for_worker(process, pending) == 1
    assert process.terminated


def test_interrupted_rollback_completes_metadata_recovery(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _mock_bundle(monkeypatch, 'raise ImportError("bad")\n')
    installer.install_or_update_runtime("https://example.test")
    backup = state.worker_state_dir() / "runtime.previous"
    failed = state.worker_state_dir() / "runtime.failed.manual"
    state.worker_runtime_dir().replace(failed)
    backup.replace(state.worker_runtime_dir())
    # Simulate a crash after restoring the runtime directory but before
    # restoring config.json and removing the pending journal.
    assert not bootstrap._rollback(state.worker_state_dir())
    assert state.read_worker_config()["runtime_digest"] == "previous-digest"
    assert not (state.worker_state_dir() / "runtime.pending.json").exists()
    assert not (state.worker_state_dir() / "runtime.attempted").exists()


def test_bundle_includes_worker_recovery_bootstrap():
    from local_shell_mcp.remote_worker_routes import _WORKER_PYTHON_FILES

    assert "remote_worker_bootstrap.py" in _WORKER_PYTHON_FILES


@pytest.mark.asyncio
async def test_windows_service_bootstrap_is_refreshed_before_upgrade(monkeypatch, tmp_path):
    from local_shell_mcp import remote, remote_worker_service

    service_file = tmp_path / "worker-service.pyw"
    service_file.write_text("old script", encoding="utf-8")
    monkeypatch.setattr(remote.sys, "platform", "win32")
    monkeypatch.setattr(remote_worker_service, "_current_worker_is_managed", lambda: True)
    monkeypatch.setattr(remote_worker_service, "_windows_task_launcher_path", lambda: service_file)
    calls = []

    def refresh():
        calls.append("refresh-task-entrypoint")
        service_file.write_text("safe bootstrap", encoding="utf-8")

    monkeypatch.setattr(remote_worker_service, "_write_windows_task_launcher", refresh)
    monkeypatch.setattr(state, "install_launcher", lambda: calls.append("install-launcher"))

    def install(server):
        assert service_file.read_text(encoding="utf-8") == "safe bootstrap"
        calls.append("install-candidate")
        return {"version": "3.2.0"}

    monkeypatch.setattr(installer, "install_or_update_runtime", install)
    monkeypatch.setattr(remote, "_reexec_updated_worker_runtime", lambda: calls.append("reexec"))
    await remote._upgrade_worker_runtime("https://example.test", "3.2.0")
    assert calls == ["install-launcher", "refresh-task-entrypoint", "install-candidate", "reexec"]


def test_worker_reexec_inside_supervisor_avoids_nested_windows_supervisor(monkeypatch, tmp_path):
    from local_shell_mcp import remote, remote_worker_cli, remote_worker_service

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_BOOTSTRAPPED", "1")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(remote.sys, "platform", "win32")
    monkeypatch.setattr(remote_worker_service, "_current_worker_is_managed", lambda: True)
    monkeypatch.setattr(remote_worker_service, "_windows_task_launcher_path", lambda: tmp_path / "worker-service.pyw")
    monkeypatch.setattr(remote_worker_service, "prepare_worker_lock_reexec", lambda: None)
    monkeypatch.setattr(remote_worker_cli, "_worker_run_exec_argv", lambda: ["python", "-m", "local_shell_mcp.remote_worker", "run"])
    calls = []
    monkeypatch.setattr(remote.os, "execv", lambda executable, argv: calls.append(argv))
    remote._reexec_updated_worker_runtime()
    assert calls == [["python", "-m", "local_shell_mcp.remote_worker", "run"]]


@pytest.mark.skipif(os.name == "nt", reason="POSIX launcher is a shell script")
def test_installed_launcher_recovers_missing_new_runtime(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _mock_bundle(monkeypatch, 'raise ImportError("upgrade cannot start")\n')
    installer.install_or_update_runtime("https://example.test")
    # An upgrade fails after renaming the previous runtime but before writing
    # any valid new runtime. The shell launcher must still invoke the guard.
    bad = state.worker_state_dir() / "runtime.corrupt"
    state.worker_runtime_dir().replace(bad)
    result = subprocess.run(
        [str(state.worker_launcher_path()), "worker", "run"],
        env={**os.environ, "PYTHONPATH": ""},
        capture_output=True, text=True, check=False, timeout=12,
    )
    assert result.returncode == 0, result.stderr
    assert "PREVIOUS_CONNECTED" in result.stdout
    assert state.read_worker_config()["runtime_digest"] == "previous-digest"
