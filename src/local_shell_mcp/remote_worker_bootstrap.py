"""Standalone worker supervisor, copied outside the upgradeable runtime.

This file must use only the Python standard library.  The installed copy stays
unchanged during a trial upgrade, so even an unimportable bundle can be rolled
back and the worker can reconnect without external access to the machine.
"""
from __future__ import annotations

import contextlib
import errno
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

_REAPER_PID_ENV = "LOCAL_SHELL_MCP_WORKER_REAPER_PID"
_LOCK_FD_ENV = "LOCAL_SHELL_MCP_WORKER_LOCK_FD"
_RESTART_PROTOCOL_ENV = "LOCAL_SHELL_MCP_WORKER_RESTART_PROTOCOL"
_INITIAL_RUNTIME_ENV = "LOCAL_SHELL_MCP_WORKER_INITIAL_RUNTIME"
_WORKER_RESTART_EXIT = 75
_WORKER_LOCK_BUSY_EXIT = 73


class WorkerRestartRequested(BaseException):
    """Unwind the worker, including its lock, before asking the supervisor to restart."""



def needs_worker_reaper() -> bool:
    if sys.platform != "linux":
        return False
    if os.getpid() == 1:
        return True
    # An old standalone bootstrap may itself be PID 1. Its newly upgraded
    # worker must adopt descendants rather than relying on that old bootstrap.
    return (
        os.getppid() == 1
        and os.environ.get("LOCAL_SHELL_MCP_WORKER_BOOTSTRAPPED") == "1"
        and os.environ.get(_REAPER_PID_ENV) != str(os.getppid())
    )


def supervise_worker(argv: list[str]) -> int:
    """Own orphan reaping in a separate process, never in the worker's event loop."""
    supervisor_pid = os.getpid()
    child_setup = None
    if supervisor_pid != 1:
        import ctypes

        # PR_SET_CHILD_SUBREAPER: adopt orphaned descendants before the legacy
        # PID 1 bootstrap does. No privileges are needed on Linux.
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(36, 1, 0, 0, 0) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))

        def child_setup() -> None:
            # A legacy bootstrap can SIGKILL this reaper during rollback.
            # Bind the actual worker lifetime to the reaper, including the
            # race where the parent dies before prctl is installed.
            if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
                error = ctypes.get_errno()
                raise OSError(error, os.strerror(error))
            if os.getppid() != supervisor_pid:
                os.kill(os.getpid(), signal.SIGKILL)

    env = os.environ.copy()
    env[_REAPER_PID_ENV] = str(os.getpid())
    inherited_lock = env.get(_LOCK_FD_ENV)
    pass_fds = (int(inherited_lock),) if inherited_lock else ()
    process: subprocess.Popen | None = None
    queued_signals: list[int] = []

    def forward(signum: int, frame: object) -> None:  # noqa: ARG001
        if process is None:
            queued_signals.append(signum)
        elif process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(process.pid, signum)

    previous = {}
    try:
        previous[signal.SIGCHLD] = signal.signal(signal.SIGCHLD, signal.SIG_DFL)
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGQUIT):
            previous[sig] = signal.signal(sig, forward)
        process = subprocess.Popen(argv, env=env, pass_fds=pass_fds, preexec_fn=child_setup)
        if inherited_lock:
            # The worker must be the sole owner of the inherited flock.
            os.close(int(inherited_lock))
            os.environ.pop(_LOCK_FD_ENV, None)
        for signum in queued_signals:
            forward(signum, None)
        # This dedicated process owns exactly one tracked child. All other
        # children were adopted from it. Never run this loop in the worker
        # itself: waitpid(-1) would race subprocess/asyncio there.
        while True:
            pid, status = os.waitpid(-1, 0)
            if pid == process.pid:
                process.returncode = os.waitstatus_to_exitcode(status)
                return (
                    process.returncode
                    if process.returncode >= 0
                    else 128 - process.returncode
                )
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _is_windows() -> bool:
    return os.name == "nt"


def _state_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(os.environ["LOCAL_SHELL_MCP_WORKER_STATE_DIR"])
    return Path(__file__).resolve().parent


def _restore_metadata(state: Path, metadata: dict) -> None:
    config = state / "config.json"
    if not config.exists():
        return
    data = json.loads(config.read_text(encoding="utf-8"))
    data["runtime_digest"] = metadata.get("previous_digest", "")
    data["runtime_version"] = metadata.get("previous_version", "")
    temp = state / f"config.rollback.{os.getpid()}.tmp"
    temp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with contextlib.suppress(OSError):
        temp.chmod(config.stat().st_mode & 0o777)
    os.replace(temp, config)


def _rollback(state: Path) -> bool:
    pending = state / "runtime.pending.json"
    previous = state / "runtime.previous"
    runtime = state / "runtime"
    metadata = json.loads(pending.read_text(encoding="utf-8"))
    if not previous.is_dir():
        # Either the old runtime was never moved, or it was restored just
        # before a crash. In both cases its metadata needs to be restored.
        if runtime.is_dir():
            _restore_metadata(state, metadata)
            pending.unlink(missing_ok=True)
            (state / "runtime.attempted").unlink(missing_ok=True)
        return False
    failed = state / f"runtime.failed.{os.getpid()}"
    if failed.exists():
        shutil.rmtree(failed)
    if runtime.exists():
        runtime.replace(failed)
    try:
        previous.replace(runtime)
    except BaseException:
        if not runtime.exists() and failed.exists():
            failed.replace(runtime)
        raise
    _restore_metadata(state, metadata)
    pending.unlink(missing_ok=True)
    (state / "runtime.attempted").unlink(missing_ok=True)
    shutil.rmtree(failed, ignore_errors=True)
    print("Status: failed worker upgrade rolled back; reconnecting with previous runtime", file=sys.stderr, flush=True)
    return True


_TRIAL_START_TIMEOUT_S = 120.0


@contextlib.contextmanager
def _windows_region_lock(path: Path):
    """Acquire a process-owned byte range without waiting or inheriting it."""
    if not _is_windows():
        yield True
        return
    import msvcrt

    with path.open("a+b", buffering=0) as handle:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN} and getattr(exc, "winerror", None) not in {32, 33}:
                raise
            yield False
            return
        try:
            yield True
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _windows_supervisor_lock(state: Path):
    """Serialize Windows supervisors before they can mutate upgrade journals."""
    return _windows_region_lock(state / "worker-supervisor.lock")


def _rollback_stopped_worker(state: Path) -> bool:
    # On Windows an old venv redirector can exit while a descendant still
    # owns worker.lock. Never swap its runtime while that process is alive.
    with _windows_region_lock(state / "worker.lock") as acquired:
        if not acquired:
            raise RuntimeError("cannot roll back while another Windows worker holds its lock")
        return _rollback(state)


def _run_supervisor() -> int:
    state = _state_dir()
    state.mkdir(parents=True, exist_ok=True)
    with _windows_supervisor_lock(state) as acquired:
        if not acquired:
            print("Status: another Windows worker supervisor is active", file=sys.stderr, flush=True)
            return _WORKER_LOCK_BUSY_EXIT
        with _windows_region_lock(state / "worker.lock") as worker_free:
            if not worker_free:
                print("Status: another Windows worker still holds its lock", file=sys.stderr, flush=True)
                return _WORKER_LOCK_BUSY_EXIT
        _bind_windows_supervisor_lifetime()
        return main()


def _bind_windows_supervisor_lifetime() -> bool:
    """Make managed descendants die if the actual supervisor is terminated.

    Assign the supervisor before spawning any children, avoiding the race
    between assigning a venv redirector to a job and its spawning Python.
    The non-inheritable job handle intentionally lives until process exit.
    """
    if not _is_windows() or os.environ.get("LOCAL_SHELL_MCP_WORKER_MANAGED") != "1":
        return False
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimits),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    ]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL

    job = kernel.CreateJobObjectW(None, None)
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
    if (
        job
        and kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
        and kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess())
    ):
        return True
    error = ctypes.get_last_error()
    if job:
        kernel.CloseHandle(job)
    # Some hosts already run inside a restrictive job. Service stop still
    # explicitly cleans its verified process tree and checks the worker lock.
    print(f"Warning: could not contain Windows worker process tree (error {error})",
          file=sys.stderr, flush=True)
    return False


def _terminate_worker(process: subprocess.Popen) -> None:
    # On Windows Popen may be tracking a venv redirector, not the process
    # holding the lock. Kill the tree while its root PID is still valid.
    if _is_windows() and process.poll() is None:
        windows = os.environ.get("SYSTEMROOT") or os.environ.get("WINDIR")
        executable = str(Path(windows) / "System32" / "taskkill.exe") if windows else "taskkill"
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            subprocess.run(
                [executable, "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _wait_for_worker(process: subprocess.Popen[bytes], pending: Path) -> int:
    """Bound startup time even when a bad worker hangs instead of exiting."""
    trial_started: float | None = None
    while process.poll() is None:
        if pending.exists() and (
            not _is_windows() or pending.with_name("runtime.attempted").exists()
        ):
            if trial_started is None:
                trial_started = time.monotonic()
            if time.monotonic() - trial_started >= _TRIAL_START_TIMEOUT_S:
                print("Status: upgraded worker did not establish a controller poll; rolling back", file=sys.stderr, flush=True)
                _terminate_worker(process)
                return 1
        else:
            trial_started = None
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=1)
    return int(process.returncode or 0)


def main() -> int:
    if needs_worker_reaper():
        return supervise_worker([sys.executable, str(Path(__file__).resolve())])
    state = _state_dir()
    pending = state / "runtime.pending.json"
    attempted = state / "runtime.attempted"
    delay = 1.0
    active_process: subprocess.Popen | None = None
    initial_runtime = os.environ.pop(_INITIAL_RUNTIME_ENV, None)
    # A foreground invocation may import a freshly downloaded temporary bundle
    # (or a wheel) rather than the persistent cache. Keep that selection until
    # an explicitly requested upgrade; use it again if the first trial fails.
    use_initial_runtime = bool(initial_runtime)
    trial_from_initial = False

    def stop_worker(signum: int, frame: object) -> None:  # noqa: ARG001
        if active_process is not None and active_process.poll() is None:
            _terminate_worker(active_process)
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, stop_worker)
    while True:
        try:
            if pending.exists() and attempted.exists():
                _rollback_stopped_worker(state)
            if not pending.exists():
                # A crash between confirming a healthy runtime and removing
                # the attempt marker must not poison the next upgrade.
                attempted.unlink(missing_ok=True)
            if pending.exists():
                # Survives abrupt termination of this supervisor or the host.
                attempted.write_text("1\n", encoding="utf-8")
                if use_initial_runtime:
                    trial_from_initial = True
                    use_initial_runtime = False
            runtime = state / "runtime"
            if use_initial_runtime and not pending.exists():
                runtime = Path(initial_runtime)
            env = os.environ.copy()
            env["LOCAL_SHELL_MCP_WORKER_BOOTSTRAPPED"] = "1"
            env[_RESTART_PROTOCOL_ENV] = "1"
            env["LOCAL_SHELL_MCP_WORKER_STATE_DIR"] = str(state)
            env["PYTHONPATH"] = str(runtime) + (
                os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
            )
            # Old Windows runtimes may have left a CRT fd number in the
            # environment; it is not a transferable lock or even a valid fd.
            if _is_windows():
                env.pop(_LOCK_FD_ENV, None)
                os.environ.pop(_LOCK_FD_ENV, None)
            inherited_lock = env.get(_LOCK_FD_ENV, "")
            kwargs = {}
            if inherited_lock:
                kwargs["pass_fds"] = (int(inherited_lock),)
            worker_python = sys.executable
            if _is_windows() and Path(worker_python).name.lower() == "pythonw.exe":
                # A scheduled task uses pythonw, whose stdout/stderr may be
                # None. Start the child without a console but retain logs.
                python = str(Path(worker_python).with_name("python.exe"))
                if Path(python).is_file():
                    worker_python = python
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                kwargs["stdout"] = (state / "worker.log").open("ab")
                kwargs["stderr"] = subprocess.STDOUT
            try:
                argv = (
                    [worker_python, "worker", "run"] if getattr(sys, "frozen", False)
                    else [worker_python, "-m", "local_shell_mcp.remote_worker", "run"]
                )
                process = subprocess.Popen(argv, env=env, **kwargs)
            finally:
                if "stdout" in kwargs:
                    kwargs["stdout"].close()
            active_process = process
            if inherited_lock:
                # Only the spawned worker should own the inherited lock. New
                # attempts reacquire it normally after that child exits.
                os.close(int(inherited_lock))
                os.environ.pop("LOCAL_SHELL_MCP_WORKER_LOCK_FD", None)
            exit_code = _wait_for_worker(process, pending)
            active_process = None
            # A healthy old worker creates the pending journal before
            # requesting a restart. Only the next child is a trial.
            if exit_code == _WORKER_LOCK_BUSY_EXIT and _is_windows():
                # Another live worker may own the candidate and its journal.
                # A contender must never roll back another process's runtime.
                return exit_code
            if exit_code == _WORKER_RESTART_EXIT and not attempted.exists():
                trial_from_initial = use_initial_runtime and pending.exists()
                use_initial_runtime = False
                delay = 1.0
                continue
            # Any exit from a trial before controller-acknowledged readiness
            # is a failed trial, including a second restart request.
            if pending.exists():
                _rollback_stopped_worker(state)
                use_initial_runtime = use_initial_runtime or trial_from_initial
                trial_from_initial = False
                time.sleep(min(delay, 30.0))
                delay = min(delay * 2, 30.0)
                continue
            trial_from_initial = False
            if exit_code in {0, _WORKER_LOCK_BUSY_EXIT}:
                return exit_code
            print(f"Status: worker exited ({exit_code}); reconnecting", file=sys.stderr, flush=True)
            time.sleep(min(delay, 30.0))
            delay = min(delay * 2, 30.0)
        except KeyboardInterrupt:
            if active_process is not None and active_process.poll() is None:
                _terminate_worker(active_process)
            return 130
        except Exception as exc:  # noqa: BLE001
            print(f"Status: worker supervisor recovery failed: {exc}", file=sys.stderr, flush=True)
            if active_process is not None:
                try:
                    if active_process.poll() is None:
                        _terminate_worker(active_process)
                except (OSError, subprocess.TimeoutExpired) as stop_error:
                    print(f"Status: could not stop worker: {stop_error}", file=sys.stderr, flush=True)
                    return 1
                active_process = None
            if pending.exists():
                try:
                    _rollback_stopped_worker(state)
                    use_initial_runtime = use_initial_runtime or trial_from_initial
                    trial_from_initial = False
                except Exception as rollback_error:  # noqa: BLE001
                    print(f"Status: worker rollback failed: {rollback_error}", file=sys.stderr, flush=True)
            # Never permanently give up if the running runtime cannot start.
            time.sleep(min(delay, 30.0))
            delay = min(delay * 2, 30.0)


if __name__ == "__main__":
    raise SystemExit(_run_supervisor())
