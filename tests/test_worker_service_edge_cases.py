from __future__ import annotations

import os
import plistlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from edge_case_support import _FakeHandle

import local_shell_mcp.remote_worker_service as worker_service


def test_worker_lock_windows_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, int, int]] = []

    class FakeMsvcrt:
        LK_NBLCK = 1
        LK_UNLCK = 2

        @staticmethod
        def locking(fd: int, mode: int, count: int) -> None:
            calls.append((fd, mode, count))

    monkeypatch.setitem(sys.modules, "msvcrt", FakeMsvcrt)
    monkeypatch.setattr(worker_service.os, "name", "nt")
    handle = _FakeHandle()
    worker_service._lock_worker_file(handle)
    worker_service._unlock_worker_file(handle)
    assert calls == [(7, 1, 1), (7, 2, 1)]

def test_worker_lock_reexec_prepare_and_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    handle = _FakeHandle(11)
    calls: list[tuple[int, bool]] = []
    monkeypatch.setattr(worker_service, "_active_worker_lock_handle", handle)
    monkeypatch.setattr(
        worker_service.os, "set_inheritable", lambda fd, value: calls.append((fd, value))
    )

    assert worker_service.prepare_worker_lock_reexec() == 11
    assert os.environ[worker_service._WORKER_LOCK_FD_ENV] == "11"
    worker_service.cancel_worker_lock_reexec(11)
    assert worker_service._WORKER_LOCK_FD_ENV not in os.environ
    assert calls == [(11, True), (11, False)]

def test_adopt_worker_lock_handle_rejects_bad_descriptor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(worker_service._WORKER_LOCK_FD_ENV, "not-an-fd")
    assert worker_service._adopt_worker_lock_handle() is None
    assert worker_service._WORKER_LOCK_FD_ENV not in os.environ

def test_adopt_worker_lock_handle_accepts_inherited_descriptor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "lock"
    with path.open("w+b") as source:
        fd = os.dup(source.fileno())
    monkeypatch.setenv(worker_service._WORKER_LOCK_FD_ENV, str(fd))
    adopted = worker_service._adopt_worker_lock_handle()
    assert adopted is not None
    try:
        assert adopted.fileno() == fd
    finally:
        adopted.close()

@pytest.mark.parametrize(
    "payload",
    [
        {"ProgramArguments": "bad"},
        {"ProgramArguments": []},
        {"ProgramArguments": [123]},
        {"ProgramArguments": ["relative/worker"]},
    ],
)
def test_installed_launchd_launcher_rejects_invalid_payloads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, payload: dict[str, object]
) -> None:
    plist = tmp_path / "worker.plist"
    plist.write_bytes(plistlib.dumps(payload))
    monkeypatch.setattr(worker_service, "_launchd_plist_path", lambda: plist)
    assert worker_service._installed_launchd_launcher_path() is None

def test_installed_launchd_launcher_handles_missing_and_absolute_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plist = tmp_path / "worker.plist"
    monkeypatch.setattr(worker_service, "_launchd_plist_path", lambda: plist)
    assert worker_service._installed_launchd_launcher_path() is None

    launcher = tmp_path / "bin" / "local-shell-mcp"
    plist.write_bytes(plistlib.dumps({"ProgramArguments": [str(launcher)]}))
    assert worker_service._installed_launchd_launcher_path() == launcher

def test_windows_pythonw_executable_success_and_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    python = tmp_path / "python.exe"
    python.write_bytes(b"")
    monkeypatch.setattr(worker_service.sys, "executable", str(python))

    with pytest.raises(RuntimeError, match="pythonw.exe is required"):
        worker_service._windows_pythonw_executable()

    pythonw = tmp_path / "pythonw.exe"
    pythonw.write_bytes(b"")
    assert worker_service._windows_pythonw_executable() == pythonw.resolve()

def test_refresh_service_definition_launchd_and_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plist = tmp_path / "worker.plist"
    plist.write_bytes(plistlib.dumps({"ProgramArguments": [str(tmp_path / "old")]}))
    launcher = tmp_path / "launcher"
    written = tmp_path / "written.plist"

    monkeypatch.setattr(worker_service, "_launchd_plist_path", lambda: plist)
    monkeypatch.setattr(worker_service, "worker_launcher_path", lambda: launcher)
    monkeypatch.setattr(worker_service, "_write_launchd_plist", lambda path=None: written)
    monkeypatch.setattr(worker_service, "service_kind", lambda: "launchd")
    assert worker_service.refresh_installed_service_definition() == written

    service_file = tmp_path / "worker.pyw"
    monkeypatch.setattr(worker_service, "service_kind", lambda: "scheduled-task")
    monkeypatch.setattr(worker_service, "_windows_task_status", lambda: {"state": 1})
    monkeypatch.setattr(worker_service, "_write_windows_task_launcher", lambda: service_file)
    registered: list[Path] = []
    monkeypatch.setattr(worker_service, "_register_windows_task", registered.append)
    assert worker_service.refresh_installed_service_definition() == service_file
    assert registered == [service_file]

def test_process_identity_short_circuits_dead_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_service, "_pid_is_running", lambda pid: False)
    assert worker_service._process_identity(123) is None

def test_start_service_launchd_bootstraps_after_failed_kickstart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plist = tmp_path / "worker.plist"
    plist.write_text("x")
    monkeypatch.setattr(worker_service, "service_kind", lambda: "launchd")
    monkeypatch.setattr(worker_service, "_launchd_plist_path", lambda: plist)
    monkeypatch.setattr(worker_service, "_user_id", lambda: 501)
    commands: list[object] = []

    def fake_run(command, check=True):
        commands.append(command)
        return SimpleNamespace(returncode=1 if "kickstart" in command else 0, stdout="", stderr="")

    monkeypatch.setattr(worker_service, "_run", fake_run)
    monkeypatch.setattr(worker_service, "service_status", lambda: {"running": True})
    assert worker_service.start_service() == {"running": True}
    assert any("bootstrap" in command for command in commands)
