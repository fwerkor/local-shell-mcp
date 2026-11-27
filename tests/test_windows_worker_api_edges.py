"""Windows worker lifecycle API contracts with mocked OS boundaries."""
from __future__ import annotations

import contextlib
import ctypes
import errno
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from local_shell_mcp import remote_worker_bootstrap as bootstrap
from local_shell_mcp import remote_worker_cli as cli
from local_shell_mcp import remote_worker_service as service


@pytest.mark.parametrize("stage", ["success", "create", "configure", "assign"])
def test_windows_job_object_api_contract(monkeypatch, stage):
    monkeypatch.setattr(bootstrap, "_is_windows", lambda: True)
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_MANAGED", "1")
    kernel = MagicMock()
    kernel.CreateJobObjectW.return_value = 0 if stage == "create" else 123
    kernel.GetCurrentProcess.return_value = 456
    kernel.SetInformationJobObject.return_value = stage != "configure"
    kernel.AssignProcessToJobObject.return_value = stage != "assign"
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)

    assert bootstrap._bind_windows_supervisor_lifetime() is (stage == "success")
    if stage == "create":
        kernel.SetInformationJobObject.assert_not_called()
    else:
        handle, info, limits, size = kernel.SetInformationJobObject.call_args.args
        assert (handle, info) == (123, 9)
        assert limits._obj.BasicLimitInformation.LimitFlags == 0x2000
        assert size == ctypes.sizeof(limits._obj)
    if stage in {"success", "assign"}:
        kernel.AssignProcessToJobObject.assert_called_once_with(123, 456)
    else:
        kernel.AssignProcessToJobObject.assert_not_called()
    if stage in {"configure", "assign"}:
        kernel.CloseHandle.assert_called_once_with(123)
    else:
        kernel.CloseHandle.assert_not_called()


def test_unmanaged_windows_does_not_create_job(monkeypatch):
    monkeypatch.setattr(bootstrap, "_is_windows", lambda: True)
    monkeypatch.delenv("LOCAL_SHELL_MCP_WORKER_MANAGED", raising=False)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: pytest.fail("created job"), raising=False)
    assert not bootstrap._bind_windows_supervisor_lifetime()


@pytest.mark.parametrize("error", [None, errno.EACCES, errno.EAGAIN, errno.EIO])
def test_windows_region_lock_ownership(monkeypatch, tmp_path, error):
    calls = []

    def locking(fd, mode, count):
        calls.append((mode, count))
        if error and mode == 1:
            raise OSError(error, "locking")

    monkeypatch.setattr(bootstrap, "_is_windows", lambda: True)
    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(locking=locking, LK_NBLCK=1, LK_UNLCK=2))
    lock = tmp_path / "lock"
    if error == errno.EIO:
        with pytest.raises(OSError), bootstrap._windows_region_lock(lock):
            pytest.fail("unexpected lock acquisition")
    else:
        with bootstrap._windows_region_lock(lock) as acquired:
            assert acquired is (error is None)
    assert calls == ([(1, 1), (2, 1)] if error is None else [(1, 1)])


@pytest.mark.parametrize("supervisor_free,worker_free", [(False, True), (True, False), (True, True)])
def test_supervisor_claims_both_locks_before_start(monkeypatch, tmp_path, supervisor_free, worker_free):
    events = []

    @contextlib.contextmanager
    def lock(path):
        events.append(path.name)
        yield supervisor_free if path.name == "worker-supervisor.lock" else worker_free

    monkeypatch.setattr(bootstrap, "_state_dir", lambda: tmp_path)
    monkeypatch.setattr(bootstrap, "_windows_region_lock", lock)
    monkeypatch.setattr(bootstrap, "_bind_windows_supervisor_lifetime", lambda: events.append("bind"))
    monkeypatch.setattr(bootstrap, "main", lambda: events.append("run") or 0)
    expected = ["worker-supervisor.lock"]
    if supervisor_free:
        expected.append("worker.lock")
    if supervisor_free and worker_free:
        expected += ["bind", "run"]
    assert bootstrap._run_supervisor() == (0 if supervisor_free and worker_free else 73)
    assert events == expected


def test_rollback_refuses_live_worker(monkeypatch, tmp_path):
    @contextlib.contextmanager
    def lock(path):
        yield False

    monkeypatch.setattr(bootstrap, "_windows_region_lock", lock)
    monkeypatch.setattr(bootstrap, "_rollback", lambda *args: pytest.fail("rolled back live worker"))
    with pytest.raises(RuntimeError, match="holds its lock"):
        bootstrap._rollback_stopped_worker(tmp_path)


@pytest.mark.parametrize("status", ["live", "exited", "missing", "wait-error"])
def test_native_pid_probe_closes_handle(monkeypatch, status):
    api = MagicMock()
    api.WAIT_TIMEOUT = 258
    api.OpenProcess.return_value = 42
    api.WaitForSingleObject.return_value = 258 if status == "live" else 0
    if status == "missing":
        api.OpenProcess.side_effect = OSError("no process")
    if status == "wait-error":
        api.WaitForSingleObject.side_effect = OSError("wait failed")
    monkeypatch.setitem(sys.modules, "_winapi", api)
    if status == "wait-error":
        with pytest.raises(OSError):
            service._windows_pid_is_running(99)
    else:
        assert service._windows_pid_is_running(99) is (status == "live")
    api.OpenProcess.assert_called_once_with(0x00100000, False, 99)
    if status == "missing":
        api.CloseHandle.assert_not_called()
    else:
        api.CloseHandle.assert_called_once_with(42)


@pytest.mark.parametrize("running,installed,updated,failure", [
    (True, True, True, False), (True, True, False, False),
    (True, True, False, True), (False, True, True, False),
    (False, False, True, False), (False, False, False, True),
])
def test_windows_update_stops_before_mutating_cache(monkeypatch, running, installed, updated, failure):
    monkeypatch.setattr(cli.sys, "platform", "win32")
    events = []
    monkeypatch.setattr(cli, "_load_config_or_migrate", lambda: {"server": "https://s"})
    monkeypatch.setattr(cli, "service_status", lambda: {"running": running, "installed": installed})
    monkeypatch.setattr(cli, "stop_service", lambda: events.append("stop"))
    monkeypatch.setattr(cli, "start_service", lambda: events.append("start"))
    monkeypatch.setattr(cli, "_prepare_windows_maintenance", lambda: events.append("prepare"))
    monkeypatch.setattr(cli, "install_launcher", lambda: events.append("launcher"))
    monkeypatch.setattr(cli, "refresh_installed_service_definition", lambda: events.append("refresh"))

    def install(server, force=False):
        events.append("install")
        if failure:
            raise OSError("failed download")
        return {"updated": updated}

    monkeypatch.setattr(cli, "install_or_update_runtime", install)
    args = cli._parser().parse_args(["update"])
    if failure:
        with pytest.raises(OSError, match="failed download"):
            cli._run_command(args)
    else:
        cli._run_command(args)
    expected = (["stop"] if running or installed else []) + ["prepare", "install"]
    if not failure:
        expected += ["launcher"] + (["refresh"] if updated else [])
    if running:
        expected += ["start"]
    assert events == expected


def test_windows_start_running_service_is_idempotent(monkeypatch):
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli, "service_status", lambda: {"running": True})
    monkeypatch.setattr(cli, "_prepare_worker_start", lambda: pytest.fail("changed running service"))
    cli._run_command(cli._parser().parse_args(["start"]))


@pytest.mark.parametrize("installed", [False, True])
def test_windows_install_service_prepares_stopped_runtime(monkeypatch, installed):
    monkeypatch.setattr(cli.sys, "platform", "win32")
    events = []
    monkeypatch.setattr(cli, "_load_config_or_migrate", lambda: {"server": "https://s"})
    monkeypatch.setattr(cli, "service_status", lambda: {"running": False, "installed": installed})
    monkeypatch.setattr(cli, "stop_service", lambda: events.append("stop"))
    monkeypatch.setattr(cli, "_prepare_windows_maintenance", lambda: events.append("prepare"))
    monkeypatch.setattr(cli, "install_or_update_runtime", lambda server: events.append("install"))
    monkeypatch.setattr(cli, "install_service", lambda start: events.append(("service", start)) or {})
    cli._run_command(cli._parser().parse_args(["install-service", "--no-start"]))
    assert events == (["stop"] if installed else []) + ["prepare", "install", ("service", False)]


def test_frozen_supervisor_uses_explicit_state_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap.sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path))
    assert bootstrap._state_dir() == tmp_path


def test_supervisor_cli_dispatch(monkeypatch):
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli, "is_frozen_app", lambda: True)
    monkeypatch.setattr(cli, "_run_supervisor", lambda: 73)
    with pytest.raises(SystemExit) as exc:
        cli._run_command(cli._parser().parse_args(["_supervise"]))
    assert exc.value.code == 73


def test_supervisor_exception_does_not_spawn_until_child_stops(monkeypatch, tmp_path):
    (tmp_path / "runtime").mkdir()
    monkeypatch.setattr(bootstrap, "_state_dir", lambda: tmp_path)
    monkeypatch.setattr(bootstrap, "needs_worker_reaper", lambda: False)
    monkeypatch.setattr(bootstrap.signal, "signal", lambda *args: None)
    process = SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(bootstrap.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(bootstrap, "_wait_for_worker", MagicMock(side_effect=OSError("poll failed")))
    monkeypatch.setattr(bootstrap, "_terminate_worker", MagicMock(side_effect=subprocess.TimeoutExpired("worker", 1)))
    assert bootstrap.main() == 1
    bootstrap._terminate_worker.assert_called_once_with(process)

@pytest.mark.parametrize("platform,frozen", [("linux", True), ("win32", False)])
def test_supervisor_cli_rejects_public_invocation(monkeypatch, platform, frozen):
    monkeypatch.setattr(cli.sys, "platform", platform)
    monkeypatch.setattr(cli, "is_frozen_app", lambda: frozen)
    monkeypatch.setattr(cli, "_run_supervisor", lambda: pytest.fail("launched supervisor"))
    with pytest.raises(ValueError, match="standalone executable"):
        cli._run_command(cli._parser().parse_args(["_supervise"]))
