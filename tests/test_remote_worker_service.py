from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_shell_mcp import remote_worker_service as service


def _configure(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("PATH", "/usr/bin")


def test_install_and_manage_systemd_service(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(service, "service_kind", lambda: "systemd")

    def fake_run(command, *, check=True):
        calls.append((command, check))
        output = "active\n" if "is-active" in command else ""
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(service, "_run", fake_run)
    result = service.install_service(start=True)
    assert result["kind"] == "systemd"
    assert service._systemd_unit_path().exists()  # noqa: SLF001
    assert "Environment=LOCAL_SHELL_MCP_WORKER_MANAGED=1" in service._systemd_unit_path().read_text()
    assert any(command[:3] == ["systemctl", "--user", "enable"] for command, _ in calls)

    status = service.service_status()
    assert status["installed"] is True
    assert status["running"] is True
    service.stop_service()
    service.start_service()
    removed = service.uninstall_service()
    assert removed["uninstalled"] is True
    assert not service._systemd_unit_path().exists()  # noqa: SLF001


def test_systemd_detection_requires_a_working_user_manager(monkeypatch):
    monkeypatch.setattr(service.platform, "system", lambda: "Linux")
    monkeypatch.setattr(service.shutil, "which", lambda name: "/usr/bin/systemctl")
    monkeypatch.setattr(
        service,
        "_run",
        lambda command, check=False: subprocess.CompletedProcess(command, 1, stdout="", stderr="no bus"),
    )
    assert service.service_kind() == "process"


def test_service_kind_detects_launchd_and_process(monkeypatch):
    monkeypatch.setattr(service.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(service.shutil, "which", lambda name: "/bin/launchctl")
    assert service.service_kind() == "launchd"
    monkeypatch.setattr(service.shutil, "which", lambda name: None)
    assert service.service_kind() == "process"


def test_launchd_install_start_and_status(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(service, "service_kind", lambda: "launchd")
    monkeypatch.setattr(service.os, "getuid", lambda: 501, raising=False)

    def fake_run(command, *, check=True):
        calls.append((command, check))
        return subprocess.CompletedProcess(command, 0, stdout="loaded", stderr="")

    monkeypatch.setattr(service, "_run", fake_run)
    service.install_service(start=True)
    assert service._launchd_plist_path().exists()  # noqa: SLF001
    assert b"LOCAL_SHELL_MCP_WORKER_MANAGED" in service._launchd_plist_path().read_bytes()
    assert service.service_status()["running"] is True
    service.start_service()
    service.stop_service()
    assert any(command[1] == "bootstrap" for command, _ in calls if command[0] == "launchctl")


def test_process_fallback_start_stop_and_stale_pid(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(service, "service_kind", lambda: "process")
    process = SimpleNamespace(pid=123, terminate=lambda: None)
    popen_calls = []

    def fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        return process

    monkeypatch.setattr(service.subprocess, "Popen", fake_popen)
    running = {123: True}
    monkeypatch.setattr(service, "_pid_is_running", lambda pid: running.get(pid, False))
    monkeypatch.setattr(
        service,
        "_process_identity",
        lambda pid: "worker-identity" if running.get(pid, False) else None,
    )
    signals = []

    def fake_kill(pid, sig):
        signals.append((pid, sig))
        running[pid] = False

    monkeypatch.setattr(service.os, "kill", fake_kill)
    service.install_service(start=True)
    record = json.loads(service.worker_pid_path().read_text(encoding="utf-8"))
    assert record == {"identity": "worker-identity", "pid": 123, "version": 1}
    assert popen_calls[0][0][0][-3:] == ["local_shell_mcp.main", "worker", "run"]
    assert "PYTHONPATH" in popen_calls[0][1]["env"]
    assert service.service_status()["running"] is True
    service.stop_service()
    assert signals
    assert not service.worker_pid_path().exists()

    service.worker_pid_path().write_text(
        json.dumps({"version": 1, "pid": 999, "identity": "old"}), encoding="utf-8"
    )
    monkeypatch.setattr(service, "_process_identity", lambda pid: "different")
    assert service.service_status()["pid"] is None
    assert not service.worker_pid_path().exists()


def test_worker_run_lock_rejects_duplicate_and_reports_owner(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    with (
        service.worker_run_lock(),
        pytest.raises(service.WorkerAlreadyRunningError, match="already running"),
        service.worker_run_lock(),
    ):
        pass

    assert service.worker_lock_path().exists()
    with service.worker_run_lock():
        pass


def test_managed_worker_waits_for_existing_lock(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_MANAGED", "1")
    attempts = 0
    sleeps = []

    def fake_lock(handle):  # noqa: ANN001, ARG001
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise BlockingIOError

    monkeypatch.setattr(service, "_lock_worker_file", fake_lock)
    monkeypatch.setattr(service, "_unlock_worker_file", lambda handle: None)
    monkeypatch.setattr(service.time, "sleep", sleeps.append)

    with service.worker_run_lock():
        pass

    assert attempts == 2
    assert sleeps == [5.0]


def test_worker_run_lock_recovers_after_process_exit(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    environment = os.environ.copy()
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (source_root, environment.get("PYTHONPATH", "")) if part
    )
    code = """
import os
from local_shell_mcp.remote_worker_service import worker_run_lock

lock = worker_run_lock()
lock.__enter__()
os._exit(0)
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

    with service.worker_run_lock():
        pass


def test_worker_run_lock_survives_reexec(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    script = tmp_path / "reexec-lock.py"
    script.write_text(
        """
import os
import sys

from local_shell_mcp.remote_worker_service import prepare_worker_lock_reexec, worker_run_lock

if os.environ.get("LSM_LOCK_REEXEC_STAGE") == "2":
    with worker_run_lock():
        print("lock inherited", flush=True)
else:
    with worker_run_lock():
        os.environ["LSM_LOCK_REEXEC_STAGE"] = "2"
        prepare_worker_lock_reexec()
        os.execv(sys.executable, [sys.executable, __file__])
""",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (source_root, environment.get("PYTHONPATH", "")) if part
    )

    completed = subprocess.run(
        [sys.executable, str(script)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "lock inherited"


def test_process_environment_scrubs_inherited_worker_scope(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", "/stale/workspace")
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER", "false")
    env = service._process_environment()  # noqa: SLF001
    assert "LOCAL_SHELL_MCP_WORKSPACE_ROOT" not in env
    assert "LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER" not in env
    assert env["LOCAL_SHELL_MCP_WORKER_STATE_DIR"] == str((tmp_path / "state").resolve())
    assert env["LOCAL_SHELL_MCP_WORKER_MANAGED"] == "1"


def test_process_fallback_is_reported_without_native_service_file(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    service.install_launcher()
    monkeypatch.setattr(service, "service_kind", lambda: "systemd")
    monkeypatch.setattr(service, "_read_pid", lambda: 77)
    status = service.service_status()
    assert status["kind"] == "process"
    assert status["installed"] is True
    assert status["running"] is True
    assert status["pid"] == 77


def test_legacy_pid_is_migrated_only_after_identity_verification(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    service.worker_pid_path().parent.mkdir(parents=True)
    service.worker_pid_path().write_text("42\n", encoding="utf-8")
    monkeypatch.setattr(service, "_process_identity", lambda pid: "verified")
    assert service._read_pid() == 42  # noqa: SLF001
    record = json.loads(service.worker_pid_path().read_text(encoding="utf-8"))
    assert record["identity"] == "verified"


def test_process_identity_helpers(monkeypatch):
    monkeypatch.setattr(service, "_is_worker_command", lambda command: True)
    if service.Path("/proc").is_dir():
        identity = service._linux_process_identity(os.getpid())  # noqa: SLF001
        assert identity and identity.startswith("linux:")

    monkeypatch.setattr(
        service,
        "_run",
        lambda command, check=False: subprocess.CompletedProcess(
            command,
            0,
            stdout="Mon Jul 16 12:00:00 2026 python -m local_shell_mcp.main worker run\n",
            stderr="",
        ),
    )
    assert service._posix_process_identity(10).startswith("posix:")  # noqa: SLF001

    monkeypatch.setattr(service.shutil, "which", lambda name: "powershell")
    monkeypatch.setattr(
        service,
        "_run",
        lambda command, check=False: subprocess.CompletedProcess(
            command,
            0,
            stdout="20260716120000|python -m local_shell_mcp.main worker run\n",
            stderr="",
        ),
    )
    assert service._windows_process_identity(10).startswith("windows:")  # noqa: SLF001


def test_process_identity_dispatch_and_rejections(monkeypatch):
    monkeypatch.setattr(service, "_pid_is_running", lambda pid: False)
    assert service._process_identity(1) is None  # noqa: SLF001
    monkeypatch.setattr(service, "_pid_is_running", lambda pid: True)
    monkeypatch.setattr(service.platform, "system", lambda: "Windows")
    monkeypatch.setattr(service, "_windows_process_identity", lambda pid: "windows-id")
    assert service._process_identity(1) == "windows-id"  # noqa: SLF001
    monkeypatch.setattr(service.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(service, "_posix_process_identity", lambda pid: "posix-id")
    assert service._process_identity(1) == "posix-id"  # noqa: SLF001


def test_start_process_rejects_unverifiable_child(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    terminated = []
    process = SimpleNamespace(pid=55, terminate=lambda: terminated.append(True))
    monkeypatch.setattr(service, "_read_pid", lambda: None)
    monkeypatch.setattr(service.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(service, "_process_identity", lambda pid: None)
    monkeypatch.setattr(service.time, "sleep", lambda delay: None)
    with pytest.raises(RuntimeError, match="could not be verified"):
        service._start_process()  # noqa: SLF001
    assert terminated


def test_low_level_service_helpers(monkeypatch):
    captured = []
    monkeypatch.setattr(
        service.subprocess,
        "run",
        lambda command, **kwargs: captured.append((command, kwargs))
        or subprocess.CompletedProcess(command, 0, stdout="ok", stderr=""),
    )
    assert service._run(["tool"]).stdout == "ok"  # noqa: SLF001
    assert captured[0][1]["capture_output"] is True

    monkeypatch.delattr(service.os, "getuid", raising=False)
    assert service._user_id() == 0  # noqa: SLF001
    monkeypatch.setattr(service.shutil, "which", lambda name: None)
    assert service._systemd_user_available() is False  # noqa: SLF001

    monkeypatch.setattr(service.platform, "system", lambda: "Linux")
    monkeypatch.setattr(service, "_systemd_user_available", lambda: True)
    assert service.service_kind() == "systemd"


def test_pid_and_command_validation(monkeypatch):
    assert service._pid_is_running(0) is False  # noqa: SLF001
    monkeypatch.setattr(service.os, "kill", lambda pid, sig: None)
    assert service._pid_is_running(3) is True  # noqa: SLF001
    monkeypatch.setattr(service.os, "kill", lambda pid, sig: (_ for _ in ()).throw(OSError()))
    assert service._pid_is_running(3) is False  # noqa: SLF001

    assert service._is_worker_command("python -m local_shell_mcp.main worker run") is True  # noqa: SLF001
    assert service._is_worker_command("python -m local_shell_mcp.remote_worker run") is True  # noqa: SLF001
    assert service._is_worker_command("python something else") is False  # noqa: SLF001


def test_process_identity_failure_branches(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "Path", lambda value: tmp_path / str(value).lstrip("/"))
    assert service._linux_process_identity(1) is None  # noqa: SLF001

    proc = tmp_path / "proc" / "2"
    proc.mkdir(parents=True)
    (proc / "stat").write_text("invalid", encoding="utf-8")
    (proc / "cmdline").write_bytes(b"not-worker\0")
    assert service._linux_process_identity(2) is None  # noqa: SLF001

    (proc / "stat").write_text("2 (worker) S short", encoding="utf-8")
    (proc / "cmdline").write_bytes(b"python\0-m\0local_shell_mcp.main\0worker\0run\0")
    assert service._linux_process_identity(2) is None  # noqa: SLF001

    monkeypatch.setattr(service.shutil, "which", lambda name: None)
    assert service._windows_process_identity(1) is None  # noqa: SLF001
    monkeypatch.setattr(service.shutil, "which", lambda name: "powershell")
    monkeypatch.setattr(
        service,
        "_run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 1, stdout="", stderr="bad"),
    )
    assert service._windows_process_identity(1) is None  # noqa: SLF001
    monkeypatch.setattr(
        service,
        "_run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, stdout="|not-worker", stderr=""),
    )
    assert service._windows_process_identity(1) is None  # noqa: SLF001
    assert service._posix_process_identity(1) is None  # noqa: SLF001


def test_read_pid_missing_and_malformed(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    assert service._read_pid() is None  # noqa: SLF001
    service.worker_pid_path().parent.mkdir(parents=True)
    service.worker_pid_path().write_text("not-json-or-pid", encoding="utf-8")
    assert service._read_pid() is None  # noqa: SLF001
    assert not service.worker_pid_path().exists()


def test_start_process_returns_when_already_running(monkeypatch):
    monkeypatch.setattr(service, "_read_pid", lambda: 99)
    monkeypatch.setattr(service.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("spawned"))
    service._start_process()  # noqa: SLF001


def test_windows_process_start_branch(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    process = SimpleNamespace(pid=77, terminate=lambda: None)
    captured = []
    monkeypatch.setattr(service, "_read_pid", lambda: None)
    monkeypatch.setattr(
        service,
        "os",
        SimpleNamespace(name="nt", environ=os.environ, pathsep=os.pathsep),
    )
    monkeypatch.setattr(service.subprocess, "CREATE_NEW_PROCESS_GROUP", 1, raising=False)
    monkeypatch.setattr(service.subprocess, "DETACHED_PROCESS", 2, raising=False)
    monkeypatch.setattr(
        service.subprocess,
        "Popen",
        lambda *args, **kwargs: captured.append(kwargs) or process,
    )
    monkeypatch.setattr(service, "_process_identity", lambda pid: "verified")
    written = []
    monkeypatch.setattr(service, "_write_pid", lambda pid, identity: written.append((pid, identity)))
    service._start_process()  # noqa: SLF001
    assert captured[0]["creationflags"] == 3
    assert "start_new_session" not in captured[0]
    assert written == [(77, "verified")]


def test_stop_process_force_kills_only_verified_pid(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(service, "_read_pid", lambda: 42)
    monkeypatch.setattr(service, "_pid_is_running", lambda pid: True)
    monkeypatch.setattr(service.time, "sleep", lambda delay: None)
    signals = []
    monkeypatch.setattr(service.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    service._stop_process()  # noqa: SLF001
    assert len(signals) == 2


def test_install_without_start_and_launchd_retry_paths(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(service, "install_launcher", lambda: tmp_path / "launcher")
    monkeypatch.setattr(service, "ensure_user_bin_on_path", lambda: [])
    monkeypatch.setattr(service, "_stop_process", lambda: None)
    calls = []
    monkeypatch.setattr(
        service,
        "_run",
        lambda command, check=True: calls.append((command, check))
        or subprocess.CompletedProcess(command, 1 if "kickstart" in command else 0, stdout="", stderr=""),
    )

    monkeypatch.setattr(service, "service_kind", lambda: "systemd")
    result = service.install_service(start=False)
    assert result["started"] is False
    assert not any("--now" in command for command, _ in calls)

    monkeypatch.setattr(service, "service_kind", lambda: "launchd")
    service._write_launchd_plist()  # noqa: SLF001
    service.start_service()
    assert any(command[1] == "bootstrap" for command, _ in calls if command[0] == "launchctl")


def test_uninstall_removes_launchd_plist(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(service, "service_kind", lambda: "process")
    monkeypatch.setattr(service, "stop_service", lambda: {})
    plist = service._write_launchd_plist()  # noqa: SLF001
    assert plist.exists()
    service.uninstall_service()
    assert not plist.exists()
