"""Exercise the standalone supervisor without requiring a broken remote node."""
from __future__ import annotations

import json
import os
import signal
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_shell_mcp import remote_worker_bootstrap as bootstrap


def _fake_process(code: int = 0):
    proc = SimpleNamespace(returncode=code, terminated=False, killed=False)
    proc.poll = lambda: code
    proc.wait = lambda timeout=None: code
    proc.terminate = lambda: setattr(proc, "terminated", True)
    proc.kill = lambda: setattr(proc, "killed", True)
    return proc


def _supervisor(tmp_path, monkeypatch):
    (tmp_path / "runtime").mkdir()
    monkeypatch.setattr(bootstrap, "_state_dir", lambda: tmp_path)
    monkeypatch.setattr(bootstrap.signal, "signal", lambda *args: None)
    monkeypatch.setattr(bootstrap.time, "sleep", lambda *args: None)
    monkeypatch.delenv("LOCAL_SHELL_MCP_WORKER_LOCK_FD", raising=False)
    monkeypatch.delenv("LOCAL_SHELL_MCP_WORKER_BOOTSTRAPPED", raising=False)


def _pending_trial(tmp_path):
    (tmp_path / "runtime").mkdir(exist_ok=True)
    (tmp_path / "runtime" / "version.txt").write_text("broken")
    previous = tmp_path / "runtime.previous"
    previous.mkdir()
    (previous / "version.txt").write_text("proven")
    (tmp_path / "config.json").write_text(json.dumps({"runtime_digest": "broken", "runtime_version": "v2"}))
    (tmp_path / "runtime.pending.json").write_text(json.dumps({"previous_digest": "proven", "previous_version": "v1"}))


def test_main_launches_worker_with_clean_runtime_environment(tmp_path, monkeypatch):
    _supervisor(tmp_path, monkeypatch)
    seen = []

    def spawn(argv, **kwargs):
        seen.append((argv, kwargs))
        return _fake_process()

    monkeypatch.setattr(bootstrap.subprocess, "Popen", spawn)
    assert bootstrap.main() == 0
    assert len(seen) == 1
    argv, kwargs = seen[0]
    assert argv[-3:] == ["-m", "local_shell_mcp.remote_worker", "run"]
    assert kwargs["env"]["LOCAL_SHELL_MCP_WORKER_BOOTSTRAPPED"] == "1"
    assert kwargs["env"]["LOCAL_SHELL_MCP_WORKER_STATE_DIR"] == str(tmp_path)
    assert kwargs["env"]["PYTHONPATH"].split(os.pathsep)[0] == str(tmp_path / "runtime")


def test_main_retries_failed_worker_without_a_retry_limit(tmp_path, monkeypatch):
    _supervisor(tmp_path, monkeypatch)
    attempts = []
    delays = []
    monkeypatch.setattr(bootstrap.time, "sleep", lambda sec: delays.append(sec))

    def spawn(*args, **kwargs):
        attempts.append(1)
        return _fake_process(1 if len(attempts) <= 9 else 0)

    monkeypatch.setattr(bootstrap.subprocess, "Popen", spawn)
    assert bootstrap.main() == 0
    assert len(attempts) == 10
    assert max(delays) == 30.0


def test_main_restores_failed_trial_then_reconnects(tmp_path, monkeypatch):
    _supervisor(tmp_path, monkeypatch)
    _pending_trial(tmp_path)
    seen = []

    def spawn(*args, **kwargs):
        seen.append(1)
        return _fake_process(1 if len(seen) == 1 else 0)

    monkeypatch.setattr(bootstrap.subprocess, "Popen", spawn)
    assert bootstrap.main() == 0
    assert len(seen) == 2
    assert (tmp_path / "runtime" / "version.txt").read_text() == "proven"
    assert json.loads((tmp_path / "config.json").read_text())["runtime_digest"] == "proven"
    assert not (tmp_path / "runtime.pending.json").exists()


def test_main_recovers_trial_interrupted_before_start(tmp_path, monkeypatch):
    _supervisor(tmp_path, monkeypatch)
    _pending_trial(tmp_path)
    (tmp_path / "runtime.attempted").write_text("1")
    seen = []

    def spawn(*args, **kwargs):
        assert (tmp_path / "runtime" / "version.txt").read_text() == "proven"
        seen.append(True)
        return _fake_process()

    monkeypatch.setattr(bootstrap.subprocess, "Popen", spawn)
    assert bootstrap.main() == 0
    assert seen == [True]


def test_main_retries_spawn_error_and_preserves_running_runtime(tmp_path, monkeypatch):
    _supervisor(tmp_path, monkeypatch)
    attempts = []

    def spawn(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError("temporary spawn failure")
        return _fake_process()

    monkeypatch.setattr(bootstrap.subprocess, "Popen", spawn)
    assert bootstrap.main() == 0
    assert len(attempts) == 2


def test_main_keeps_running_when_rollback_temporarily_fails(tmp_path, monkeypatch):
    _supervisor(tmp_path, monkeypatch)
    _pending_trial(tmp_path)
    original = bootstrap._rollback
    retries = []

    def rollback(state):
        retries.append(1)
        if len(retries) == 1:
            raise OSError("temporary rollback failure")
        return original(state)

    monkeypatch.setattr(bootstrap, "_rollback", rollback)
    monkeypatch.setattr(bootstrap.subprocess, "Popen", lambda *args, **kwargs: _fake_process())
    assert bootstrap.main() == 0
    assert len(retries) == 2
    assert (tmp_path / "runtime" / "version.txt").read_text() == "proven"


def test_main_handles_keyboard_interrupt_by_stopping_child(tmp_path, monkeypatch):
    _supervisor(tmp_path, monkeypatch)
    proc = _fake_process()
    proc.poll = lambda: None
    monkeypatch.setattr(bootstrap.subprocess, "Popen", lambda *args, **kwargs: proc)

    def interrupted(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(bootstrap, "_wait_for_worker", interrupted)
    assert bootstrap.main() == 130
    assert proc.terminated


def test_main_propagates_sigterm_to_child(tmp_path, monkeypatch):
    _supervisor(tmp_path, monkeypatch)
    handlers = {}
    monkeypatch.setattr(bootstrap.signal, "signal", lambda sig, callback: handlers.setdefault(sig, callback))
    proc = _fake_process()
    proc.poll = lambda: None
    monkeypatch.setattr(bootstrap.subprocess, "Popen", lambda *args, **kwargs: proc)
    monkeypatch.setattr(bootstrap, "_wait_for_worker", lambda *args: handlers[signal.SIGTERM](signal.SIGTERM, None))
    with pytest.raises(SystemExit, match="143"):
        bootstrap.main()
    assert proc.terminated


@pytest.mark.skipif(os.name == "nt", reason="POSIX lock inheritance uses pass_fds")
def test_main_passes_and_relinquishes_inherited_lock(tmp_path, monkeypatch):
    _supervisor(tmp_path, monkeypatch)
    read_fd, write_fd = os.pipe()
    os.set_inheritable(read_fd, True)
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_LOCK_FD", str(read_fd))
    captured = []

    def spawn(argv, **kwargs):
        captured.append(kwargs)
        return _fake_process()

    monkeypatch.setattr(bootstrap.subprocess, "Popen", spawn)
    try:
        assert bootstrap.main() == 0
        assert captured[0]["pass_fds"] == (read_fd,)
        assert "LOCAL_SHELL_MCP_WORKER_LOCK_FD" not in os.environ
        with pytest.raises(OSError):
            os.fstat(read_fd)
    finally:
        os.close(write_fd)


def test_rollback_handles_backup_without_candidate_and_stale_failed_folder(tmp_path):
    _pending_trial(tmp_path)
    (tmp_path / "runtime").rename(tmp_path / "runtime.removed")
    stale = tmp_path / f"runtime.failed.{os.getpid()}"
    stale.mkdir()
    (stale / "stale.txt").write_text("stale")
    assert bootstrap._rollback(tmp_path)
    assert (tmp_path / "runtime" / "version.txt").read_text() == "proven"
    assert not stale.exists()


def test_rollback_restores_candidate_when_restore_raises(tmp_path, monkeypatch):
    _pending_trial(tmp_path)
    real_replace = Path.replace

    def fail_for_backup(path, target):
        if path == tmp_path / "runtime.previous":
            raise OSError("failed to replace previous")
        return real_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_for_backup)
    with pytest.raises(OSError, match="failed to replace previous"):
        bootstrap._rollback(tmp_path)
    assert (tmp_path / "runtime" / "version.txt").read_text() == "broken"
    assert (tmp_path / "runtime.previous" / "version.txt").read_text() == "proven"


def test_rollback_without_runtime_defers_recovery(tmp_path):
    (tmp_path / "runtime.pending.json").write_text("{}")
    assert bootstrap._rollback(tmp_path) is False
    assert (tmp_path / "runtime.pending.json").exists()


def test_restore_metadata_missing_config_is_noop(tmp_path):
    bootstrap._restore_metadata(tmp_path, {"previous_digest": "abc"})
    assert not (tmp_path / "config.json").exists()


def test_wait_for_worker_success_and_timeout_kill(tmp_path, monkeypatch):
    proc = _fake_process()
    seen = []

    def poll():
        seen.append(1)
        return None if len(seen) == 1 else 0

    proc.poll = poll
    assert bootstrap._wait_for_worker(proc, tmp_path / "missing-pending") == 0
    (tmp_path / "pending.json").write_text("{}")
    proc = _fake_process(1)
    proc.poll = lambda: None
    proc.wait = lambda timeout=None: (_ for _ in ()).throw(subprocess.TimeoutExpired("worker", timeout))
    proc.kill = lambda: setattr(proc, "killed", True)
    monkeypatch.setattr(bootstrap, "_TRIAL_START_TIMEOUT_S", 0)
    # A hung process may ignore graceful termination; it is forcibly killed.
    with pytest.raises(subprocess.TimeoutExpired):
        bootstrap._wait_for_worker(proc, tmp_path / "pending.json")
    assert proc.terminated
    assert proc.killed


def test_state_directory_is_install_script_directory():
    assert bootstrap._state_dir() == Path(bootstrap.__file__).resolve().parent
    assert bootstrap._is_windows() == (os.name == "nt")


def test_windows_pythonw_starts_python_and_captures_log(tmp_path, monkeypatch):
    _supervisor(tmp_path, monkeypatch)
    pythonw = tmp_path / "pythonw.exe"
    python = tmp_path / "python.exe"
    pythonw.touch()
    python.touch()
    monkeypatch.setattr(bootstrap, "_is_windows", lambda: True)
    monkeypatch.setattr(bootstrap.sys, "executable", str(pythonw))
    calls = []

    def spawn(argv, **kwargs):
        calls.append((argv, kwargs))
        assert not kwargs["stdout"].closed
        return _fake_process()

    monkeypatch.setattr(bootstrap.subprocess, "Popen", spawn)
    assert bootstrap.main() == 0
    argv, kwargs = calls[0]
    assert argv[0] == str(python)
    assert "creationflags" in kwargs
    assert kwargs["stderr"] == subprocess.STDOUT
    assert kwargs["stdout"].closed
    assert (tmp_path / "worker.log").exists()


def test_windows_pythonw_can_fallback_to_pythonw_if_python_missing(tmp_path, monkeypatch):
    _supervisor(tmp_path, monkeypatch)
    pythonw = tmp_path / "pythonw.exe"
    pythonw.touch()
    monkeypatch.setattr(bootstrap, "_is_windows", lambda: True)
    monkeypatch.setattr(bootstrap.sys, "executable", str(pythonw))
    captured = []
    monkeypatch.setattr(bootstrap.subprocess, "Popen", lambda argv, **kwargs: captured.append(argv) or _fake_process())
    assert bootstrap.main() == 0
    assert captured[0][0] == str(pythonw)


def test_windows_worker_receives_inherited_lock(tmp_path, monkeypatch):
    _supervisor(tmp_path, monkeypatch)
    read_fd, write_fd = os.pipe()
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_LOCK_FD", str(read_fd))
    monkeypatch.setattr(bootstrap, "_is_windows", lambda: True)
    captured = []
    monkeypatch.setattr(bootstrap.subprocess, "Popen", lambda argv, **kwargs: captured.append(kwargs) or _fake_process())
    try:
        assert bootstrap.main() == 0
        assert captured[0]["close_fds"] is False
        with pytest.raises(OSError):
            os.fstat(read_fd)
    finally:
        os.close(write_fd)


def test_wait_for_worker_survives_initial_trial_without_timeout(tmp_path, monkeypatch):
    pending = tmp_path / "runtime.pending.json"
    pending.write_text("{}")
    monkeypatch.setattr(bootstrap, "_TRIAL_START_TIMEOUT_S", 60)
    proc = _fake_process()
    ticks = []
    proc.poll = lambda: None if len(ticks) < 3 else 0
    proc.wait = lambda timeout=None: ticks.append(1)
    assert bootstrap._wait_for_worker(proc, pending) == 0
    assert len(ticks) == 3


def test_wait_for_worker_kills_stuck_child_after_grace_timeout(tmp_path, monkeypatch):
    pending = tmp_path / "runtime.pending.json"
    pending.write_text("{}")
    monkeypatch.setattr(bootstrap, "_TRIAL_START_TIMEOUT_S", 0)
    proc = _fake_process()
    proc.poll = lambda: None
    waits = []

    def wait(timeout=None):
        waits.append(timeout)
        if timeout == 10:
            raise subprocess.TimeoutExpired("worker", 10)
        return -9

    proc.wait = wait
    assert bootstrap._wait_for_worker(proc, pending) == 1
    assert waits == [10, None]
    assert proc.terminated and proc.killed


def test_main_retries_when_trial_rollback_fails_twice(tmp_path, monkeypatch):
    _supervisor(tmp_path, monkeypatch)
    _pending_trial(tmp_path)
    original = bootstrap._rollback
    calls = []

    def flaky(state):
        calls.append(1)
        if len(calls) < 3:
            raise OSError("rollback temporarily unavailable")
        return original(state)

    monkeypatch.setattr(bootstrap, "_rollback", flaky)
    # Stop via clean worker after the recovery cycle completes.
    monkeypatch.setattr(bootstrap.subprocess, "Popen", lambda *args, **kwargs: _fake_process(0))
    assert bootstrap.main() == 0
    assert len(calls) == 3
    assert (tmp_path / "runtime" / "version.txt").read_text() == "proven"


def test_restore_metadata_keeps_writing_if_chmod_is_unsupported(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text('{"runtime_digest":"stale"}')
    monkeypatch.setattr(Path, "chmod", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("unsupported")))
    bootstrap._restore_metadata(tmp_path, {"previous_digest": "proven", "previous_version": "v1"})
    assert json.loads(config.read_text())["runtime_digest"] == "proven"
