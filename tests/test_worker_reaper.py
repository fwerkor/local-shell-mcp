from __future__ import annotations

import ctypes
import errno
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_shell_mcp import remote_worker_bootstrap as bootstrap
from local_shell_mcp import remote_worker_cli as cli

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux orphan adoption")


def test_reaper_selection(monkeypatch):
    monkeypatch.delenv("LOCAL_SHELL_MCP_WORKER_BOOTSTRAPPED", raising=False)
    monkeypatch.delenv(bootstrap._REAPER_PID_ENV, raising=False)
    monkeypatch.setattr(os, "getpid", lambda: 1)
    assert bootstrap.needs_worker_reaper()
    monkeypatch.setattr(os, "getpid", lambda: 2)
    monkeypatch.setattr(os, "getppid", lambda: 1)
    assert not bootstrap.needs_worker_reaper()
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_BOOTSTRAPPED", "1")
    assert bootstrap.needs_worker_reaper()
    monkeypatch.setenv(bootstrap._REAPER_PID_ENV, "1")
    assert not bootstrap.needs_worker_reaper()
    monkeypatch.delenv(bootstrap._REAPER_PID_ENV)
    monkeypatch.setattr(os, "getppid", lambda: 3)
    assert not bootstrap.needs_worker_reaper()
    monkeypatch.setattr(sys, "platform", "darwin")
    assert not bootstrap.needs_worker_reaper()


@pytest.mark.parametrize("args", [["run"], ["connect", "--server", "http://example.com", "--invite-stdin"]])
def test_worker_cli_dispatches_reaper(monkeypatch, args):
    monkeypatch.setattr(cli, "needs_worker_reaper", lambda: True)
    calls = []
    monkeypatch.setattr(cli, "supervise_worker", lambda argv: calls.append(argv) or 42)
    with pytest.raises(SystemExit) as exc:
        cli.run_worker_cli(args)
    assert exc.value.code == 42
    assert calls == [[*cli._worker_run_exec_argv()[:-1], *args]]


def test_bootstrap_dispatches_reaper(monkeypatch):
    monkeypatch.setattr(bootstrap, "needs_worker_reaper", lambda: True)
    calls = []
    monkeypatch.setattr(bootstrap, "supervise_worker", lambda argv: calls.append(argv) or 42)
    assert bootstrap.main() == 42
    assert calls == [[sys.executable, str(Path(bootstrap.__file__).resolve())]]


@pytest.mark.parametrize(
    ("pid", "lock_fd", "status", "expected"),
    [(1, None, 42 << 8, 42), (20, "9", signal.SIGTERM, 143)],
)
def test_supervisor_reaps_and_forwards_signals(monkeypatch, pid, lock_fd, status, expected):
    monkeypatch.setattr(os, "getpid", lambda: pid)
    monkeypatch.delenv(bootstrap._LOCK_FD_ENV, raising=False)
    if lock_fd:
        monkeypatch.setenv(bootstrap._LOCK_FD_ENV, lock_fd)
    prctl_calls = []
    monkeypatch.setattr(
        ctypes, "CDLL",
        lambda *args, **kwargs: SimpleNamespace(prctl=lambda *args: prctl_calls.append(args) or 0),
    )

    signals = (signal.SIGCHLD, signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGQUIT)
    original_handlers = dict.fromkeys(signals, signal.SIG_IGN)
    handlers = original_handlers.copy()

    def install_handler(sig, handler):
        previous = handlers[sig]
        handlers[sig] = handler
        return previous

    monkeypatch.setattr(signal, "signal", install_handler)
    child = SimpleNamespace(pid=21, returncode=None)
    closed = []
    forwarded = []

    def spawn(argv, *, env, pass_fds, preexec_fn):
        assert argv == ["worker"]
        assert (preexec_fn is None) == (pid == 1)
        assert env[bootstrap._REAPER_PID_ENV] == str(pid)
        assert pass_fds == ((int(lock_fd),) if lock_fd else ())
        assert handlers[signal.SIGCHLD] == signal.SIG_DFL
        handlers[signal.SIGTERM](signal.SIGTERM, None)
        return child

    def kill(target, sig):
        forwarded.append((target, sig))
        if sig == signal.SIGHUP:
            raise ProcessLookupError

    def waitpid(target, options):
        assert (target, options) == (-1, 0)
        if len(forwarded) == 1:
            handlers[signal.SIGHUP](signal.SIGHUP, None)
            return 22, 17 << 8
        return child.pid, status

    monkeypatch.setattr(subprocess, "Popen", spawn)
    monkeypatch.setattr(os, "close", closed.append)
    monkeypatch.setattr(os, "kill", kill)
    monkeypatch.setattr(os, "waitpid", waitpid)
    assert bootstrap.supervise_worker(["worker"]) == expected
    assert child.returncode == os.waitstatus_to_exitcode(status)
    assert prctl_calls == ([] if pid == 1 else [(36, 1, 0, 0, 0)])
    assert closed == ([int(lock_fd)] if lock_fd else [])
    assert bootstrap._LOCK_FD_ENV not in os.environ
    assert forwarded == [(21, signal.SIGTERM), (21, signal.SIGHUP)]
    assert handlers == original_handlers


def test_supervisor_reports_subreaper_setup_error(monkeypatch):
    monkeypatch.setattr(os, "getpid", lambda: 20)
    monkeypatch.setattr(ctypes, "CDLL", lambda *args, **kwargs: SimpleNamespace(prctl=lambda *args: -1))
    monkeypatch.setattr(ctypes, "get_errno", lambda: errno.EPERM)
    with pytest.raises(OSError) as exc:
        bootstrap.supervise_worker(["worker"])
    assert exc.value.errno == errno.EPERM


def test_supervisor_restores_signal_handlers_on_spawn_failure(monkeypatch):
    monkeypatch.setattr(os, "getpid", lambda: 1)
    previous = {sig: signal.getsignal(sig) for sig in (
        signal.SIGCHLD, signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGQUIT,
    )}

    def spawn(*args, **kwargs):
        raise FileNotFoundError("worker")

    monkeypatch.setattr(subprocess, "Popen", spawn)
    with pytest.raises(FileNotFoundError, match="worker"):
        bootstrap.supervise_worker(["worker"])
    assert {sig: signal.getsignal(sig) for sig in previous} == previous


def _reaper_command(worker_script: str) -> list[str]:
    return [
        sys.executable, "-c",
        "import sys; from local_shell_mcp.remote_worker_bootstrap import supervise_worker; "
        "raise SystemExit(supervise_worker([sys.executable, '-c', sys.argv[1]]))",
        worker_script,
    ]


def test_reaps_real_orphans_without_stealing_worker_exit_status():
    worker = r"""
import os, subprocess, sys, time
# A launcher exits after starting a detached child, like tmux and job helpers.
launcher = '''
import os, sys
pid = os.fork()
if pid == 0:
    os.setsid()
    os._exit(17)
print(pid, flush=True)
'''
for _ in range(12):
    result = subprocess.run([sys.executable, '-c', launcher], capture_output=True, text=True, check=True)
    pid = int(result.stdout)
    deadline = time.monotonic() + 3
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        assert time.monotonic() < deadline, f"orphan {pid} was not reaped"
        time.sleep(.01)
    # The worker remains responsible for its own direct children.
    assert subprocess.run([sys.executable, '-c', 'raise SystemExit(23)']).returncode == 23
raise SystemExit(42)
"""
    result = subprocess.run(_reaper_command(worker), capture_output=True, text=True, timeout=20)
    assert result.returncode == 42, result.stderr


def test_forwards_sigterm_and_preserves_signal_exit_code(tmp_path):
    ready = tmp_path / "ready"
    worker = f"import pathlib, time; pathlib.Path({str(ready)!r}).touch(); time.sleep(30)"
    process = subprocess.Popen(_reaper_command(worker))
    try:
        deadline = time.monotonic() + 10
        while not ready.exists():
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(.01)
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=5) == 128 + signal.SIGTERM
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_pid_namespace_reaps_tmux_servers(tmp_path):
    if not shutil.which("unshare") or not shutil.which("tmux"):
        pytest.skip("unshare and tmux are required")
    namespace = ["unshare", "--user", "--map-root-user", "--pid", "--fork", "--mount-proc"]
    probe = subprocess.run([*namespace, "true"], capture_output=True, timeout=5)
    if probe.returncode != 0:
        pytest.skip("PID namespace creation is unavailable")
    worker = r"""
import os, subprocess, sys, time
from pathlib import Path
assert os.getppid() == 1
socket = sys.argv[1]
tmux = ['tmux', '-f', '/dev/null', '-S', socket]
for _ in range(12):
    subprocess.run([*tmux, 'new-session', '-d', '-s', 'repro', 'sleep 30'], check=True)
    pid = int(subprocess.check_output([*tmux, 'display-message', '-p', '#{pid}']))
    subprocess.run([*tmux, 'kill-server'], check=True)
    deadline = time.monotonic() + 3
    while Path(f'/proc/{pid}').exists():
        assert time.monotonic() < deadline, f'tmux server {pid} was not reaped'
        time.sleep(.01)
# Check every adopted child, not just the server.
deadline = time.monotonic() + 3
while True:
    zombies = subprocess.check_output(['ps', '-eo', 'ppid,stat'], text=True)
    if not any(line.split()[0] == '1' and line.split()[1].startswith('Z')
               for line in zombies.splitlines()[1:] if line.strip()):
        break
    assert time.monotonic() < deadline, zombies
    time.sleep(.01)
print('12 tmux lifecycles; no PID 1 zombies')
"""
    supervisor = (
        "import os, sys; "
        "from local_shell_mcp.remote_worker_bootstrap import needs_worker_reaper, supervise_worker; "
        "assert os.getpid() == 1 and needs_worker_reaper(); "
        "raise SystemExit(supervise_worker([sys.executable, '-c', sys.argv[1], sys.argv[2]]))"
    )
    result = subprocess.run(
        [*namespace, sys.executable, "-c", supervisor, worker, str(tmp_path / "tmux.sock")],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "12 tmux lifecycles; no PID 1 zombies" in result.stdout


def test_reaper_passes_and_relinquishes_inherited_lock(tmp_path):
    import fcntl

    lock_path = tmp_path / "worker.lock"
    with lock_path.open("w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        worker = """
import os, time
fd = int(os.environ['LOCAL_SHELL_MCP_WORKER_LOCK_FD'])
os.fstat(fd)
deadline = time.monotonic() + 3
while os.path.exists(f'/proc/{os.getppid()}/fd/{fd}'):
    assert time.monotonic() < deadline, 'supervisor retained the inherited lock'
    time.sleep(.01)
raise SystemExit(19)
"""
        env = os.environ.copy()
        env[bootstrap._LOCK_FD_ENV] = str(lock.fileno())
        result = subprocess.run(
            _reaper_command(worker), env=env, pass_fds=(lock.fileno(),),
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 19, result.stderr


def test_forced_reaper_death_kills_worker(tmp_path):
    import fcntl

    ready = tmp_path / "ready"
    lock_path = tmp_path / "worker.lock"
    worker = f"""
import fcntl, pathlib, signal, time
lock = open({str(lock_path)!r}, 'w')
fcntl.flock(lock, fcntl.LOCK_EX)
signal.signal(signal.SIGTERM, signal.SIG_IGN)
pathlib.Path({str(ready)!r}).touch()
time.sleep(60)
"""
    process = subprocess.Popen(_reaper_command(worker))
    try:
        deadline = time.monotonic() + 10
        while not ready.exists():
            assert process.poll() is None and time.monotonic() < deadline
            time.sleep(.01)
        process.kill()
        process.wait(timeout=5)
        with lock_path.open("r") as lock:
            deadline = time.monotonic() + 5
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    assert time.monotonic() < deadline, "worker survived forced reaper termination"
                    time.sleep(.01)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
