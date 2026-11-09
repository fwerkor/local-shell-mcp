"""Standalone worker supervisor, copied outside the upgradeable runtime.

This file must use only the Python standard library.  The installed copy stays
unchanged during a trial upgrade, so even an unimportable bundle can be rolled
back and the worker can reconnect without external access to the machine.
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


def _state_dir() -> Path:
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


def _wait_for_worker(process: subprocess.Popen[bytes], pending: Path) -> int:
    """Bound startup time even when a bad worker hangs instead of exiting."""
    trial_started: float | None = None
    while process.poll() is None:
        if pending.exists():
            if trial_started is None:
                trial_started = time.monotonic()
            if time.monotonic() - trial_started >= _TRIAL_START_TIMEOUT_S:
                print("Status: upgraded worker did not establish a controller poll; rolling back", file=sys.stderr, flush=True)
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                return 1
        else:
            trial_started = None
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=1)
    return int(process.returncode or 0)


def main() -> int:
    state = _state_dir()
    pending = state / "runtime.pending.json"
    attempted = state / "runtime.attempted"
    delay = 1.0
    active_process: subprocess.Popen | None = None

    def stop_worker(signum: int, frame: object) -> None:  # noqa: ARG001
        if active_process is not None and active_process.poll() is None:
            active_process.terminate()
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, stop_worker)
    while True:
        try:
            if pending.exists() and attempted.exists():
                _rollback(state)
            if pending.exists():
                # Survives abrupt termination of this supervisor or the host.
                attempted.write_text("1\n", encoding="utf-8")
            runtime = state / "runtime"
            env = os.environ.copy()
            env["LOCAL_SHELL_MCP_WORKER_BOOTSTRAPPED"] = "1"
            env["LOCAL_SHELL_MCP_WORKER_STATE_DIR"] = str(state)
            env["PYTHONPATH"] = str(runtime) + (
                os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
            )
            inherited_lock = env.get("LOCAL_SHELL_MCP_WORKER_LOCK_FD", "")
            kwargs = {}
            if inherited_lock and os.name != "nt":
                kwargs["pass_fds"] = (int(inherited_lock),)
            elif inherited_lock and os.name == "nt":
                kwargs["close_fds"] = False
            worker_python = sys.executable
            if os.name == "nt" and Path(worker_python).name.lower() == "pythonw.exe":
                # A scheduled task uses pythonw, whose stdout/stderr may be
                # None. Start the child without a console but retain logs.
                python = str(Path(worker_python).with_name("python.exe"))
                if Path(python).is_file():
                    worker_python = python
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                kwargs["stdout"] = (state / "worker.log").open("ab")
                kwargs["stderr"] = subprocess.STDOUT
            try:
                process = subprocess.Popen(
                    [worker_python, "-m", "local_shell_mcp.remote_worker", "run"],
                    env=env, **kwargs,
                )
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
            # Any exit before controller-acknowledged readiness is a failed
            # trial, including a clean exit or a crash from an import error.
            if pending.exists():
                _rollback(state)
                time.sleep(min(delay, 30.0))
                delay = min(delay * 2, 30.0)
                continue
            if exit_code == 0:
                return 0
            print(f"Status: worker exited ({exit_code}); reconnecting", file=sys.stderr, flush=True)
            time.sleep(min(delay, 30.0))
            delay = min(delay * 2, 30.0)
        except KeyboardInterrupt:
            if active_process is not None and active_process.poll() is None:
                active_process.terminate()
            return 130
        except Exception as exc:  # noqa: BLE001
            print(f"Status: worker supervisor recovery failed: {exc}", file=sys.stderr, flush=True)
            if pending.exists():
                try:
                    _rollback(state)
                except Exception as rollback_error:  # noqa: BLE001
                    print(f"Status: worker rollback failed: {rollback_error}", file=sys.stderr, flush=True)
            # Never permanently give up if the running runtime cannot start.
            time.sleep(min(delay, 30.0))
            delay = min(delay * 2, 30.0)


if __name__ == "__main__":
    raise SystemExit(main())
