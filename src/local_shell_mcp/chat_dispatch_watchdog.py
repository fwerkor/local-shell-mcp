from __future__ import annotations

import argparse
import contextlib
import ctypes
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from .settings import get_settings
from .state_store import state_lock

DEFAULT_WATCHDOG_INTERVAL_S = 15
WATCHDOG_LOCK_KEY = "chat-dispatch-watchdog"
WATCHDOG_STATE_FILE = "chat-dispatch-watchdog.json"


def _bounded_interval(value: int | float) -> int:
    interval = int(value)
    if interval < 2 or interval > 3600:
        raise ValueError("watchdog interval must be between 2 and 3600 seconds")
    return interval


def _require_local_state(settings: Any) -> Path:
    if str(getattr(settings, "state_backend", "file")) != "file":
        raise RuntimeError("chat dispatch watchdog requires the local file state backend")
    if bool(getattr(settings, "stateless_controller", False)):
        raise RuntimeError("chat dispatch watchdog is unavailable on a stateless controller")
    root = Path(settings.state_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _state_path(settings: Any) -> Path:
    return _require_local_state(settings) / WATCHDOG_STATE_FILE


def _read_state_unlocked(settings: Any) -> dict[str, Any] | None:
    path = _state_path(settings)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _write_state_unlocked(settings: Any, state: dict[str, Any]) -> None:
    path = _state_path(settings)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information,
            False,
            int(pid),
        )
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def inspect_chat_dispatch_watchdog(
    settings: Any,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    current = time.time() if now is None else float(now)
    with state_lock(WATCHDOG_LOCK_KEY):
        state = _read_state_unlocked(settings)
    if state is None:
        return {"status": "stopped", "alive": False, "state_path": str(_state_path(settings))}
    pid = int(state.get("pid") or 0)
    alive = pid_exists(pid)
    heartbeat_at = float(state.get("heartbeat_at") or 0.0)
    interval_s = _bounded_interval(state.get("interval_s") or DEFAULT_WATCHDOG_INTERVAL_S)
    heartbeat_age_s = max(0.0, current - heartbeat_at) if heartbeat_at else None
    recorded = str(state.get("status") or "unknown")
    startup_age_s = max(0.0, current - float(state.get("started_at") or 0.0))
    if recorded == "starting" and startup_age_s <= 5.0:
        status = "starting"
    elif not alive and recorded not in {"stopped", "failed"}:
        status = "dead"
    elif (
        alive
        and recorded in {"running", "starting"}
        and heartbeat_age_s is not None
        and heartbeat_age_s > interval_s * 3
    ):
        status = "stale_live"
    else:
        status = recorded
    return {
        **state,
        "status": status,
        "alive": alive,
        "heartbeat_age_s": heartbeat_age_s,
        "state_path": str(_state_path(settings)),
    }


def _pythonw_executable() -> str:
    current = Path(sys.executable)
    if os.name == "nt":
        candidate = current.with_name("pythonw.exe")
        if candidate.is_file():
            return str(candidate)
    return str(current)


def ensure_chat_dispatch_watchdog(
    settings: Any,
    *,
    interval_s: int | None = None,
) -> dict[str, Any]:
    interval = _bounded_interval(
        interval_s
        if interval_s is not None
        else getattr(settings, "chat_dispatch_watchdog_interval_s", DEFAULT_WATCHDOG_INTERVAL_S)
    )
    _require_local_state(settings)
    existing = False
    with state_lock(WATCHDOG_LOCK_KEY):
        state = _read_state_unlocked(settings)
        if state is not None:
            recorded = str(state.get("status") or "")
            startup_age_s = max(0.0, time.time() - float(state.get("started_at") or 0.0))
            existing = (
                recorded in {"starting", "running", "stale_live"}
                and pid_exists(int(state.get("pid") or 0))
            ) or (
                recorded == "starting" and startup_age_s <= 5.0
            )
        if not existing:
            owner_id = f"chat-watchdog:{uuid.uuid4().hex}"
            command = [
                _pythonw_executable(),
                "-m",
                "local_shell_mcp.chat_dispatch_watchdog",
                "--run",
                "--owner-id",
                owner_id,
                "--interval",
                str(interval),
            ]
            env = os.environ.copy()
            env["LOCAL_SHELL_MCP_STATE_BACKEND"] = "file"
            env["LOCAL_SHELL_MCP_STATE_DIR"] = str(Path(settings.state_dir).resolve())
            configured_lws = str(getattr(settings, "chat_dispatch_lws_repo", None) or "").strip()
            if configured_lws:
                env["LOCAL_SHELL_MCP_CHAT_DISPATCH_LWS_REPO"] = configured_lws
            env["LOCAL_SHELL_MCP_CHAT_DISPATCH_MAX_WINDOWS"] = str(
                int(getattr(settings, "chat_dispatch_max_windows", 4))
            )
            env["LOCAL_SHELL_MCP_CHAT_DISPATCH_IDLE_CLOSE_S"] = str(
                int(getattr(settings, "chat_dispatch_idle_close_s", 90))
            )
            env["LOCAL_SHELL_MCP_CHAT_DISPATCH_WATCHDOG_INTERVAL_S"] = str(interval)
            source_root = Path(__file__).resolve().parents[2]
            source_path = str(source_root / "src")
            env["PYTHONPATH"] = source_path + (
                os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
            )
            log_path = _require_local_state(settings) / "chat-dispatch-watchdog.log"
            log_handle = log_path.open("ab", buffering=0)
            with contextlib.suppress(OSError):
                os.chmod(log_path, 0o600)
            kwargs: dict[str, Any] = {
                "stdin": subprocess.DEVNULL,
                "stdout": log_handle,
                "stderr": subprocess.STDOUT,
                "close_fds": True,
                "env": env,
                "cwd": str(source_root),
            }
            if os.name == "nt":
                kwargs["creationflags"] = (
                    getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                    | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                    | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                )
            else:
                kwargs["start_new_session"] = True
            try:
                process = subprocess.Popen(command, **kwargs)
            finally:
                log_handle.close()
            now = time.time()
            _write_state_unlocked(
                settings,
                {
                    "owner_id": owner_id,
                    "pid": process.pid,
                    "status": "starting",
                    "started_at": now,
                    "heartbeat_at": now,
                    "interval_s": interval,
                    "stop_requested": False,
                    "last_ensure_at": None,
                    "last_error": None,
                    "log_path": str(log_path),
                },
            )
    status = inspect_chat_dispatch_watchdog(settings)
    if existing:
        return {"started": False, **status}
    deadline = time.time() + 5.0
    while time.time() < deadline and status["status"] == "starting":
        time.sleep(0.05)
        status = inspect_chat_dispatch_watchdog(settings)
    return {"started": True, **status}


def stop_chat_dispatch_watchdog(
    settings: Any,
    *,
    wait_s: float = 5.0,
) -> dict[str, Any]:
    requested = False
    with state_lock(WATCHDOG_LOCK_KEY):
        state = _read_state_unlocked(settings)
        if state is not None:
            alive = pid_exists(int(state.get("pid") or 0))
            state["stop_requested"] = True
            state["status"] = "stopping" if alive else "dead"
            _write_state_unlocked(settings, state)
            requested = alive
    status = inspect_chat_dispatch_watchdog(settings)
    deadline = time.time() + max(0.0, min(float(wait_s), 30.0))
    while requested and time.time() < deadline and status["alive"]:
        time.sleep(0.05)
        status = inspect_chat_dispatch_watchdog(settings)
    return {"requested": requested, **status}


def _claim_watchdog(settings: Any, owner_id: str) -> bool:
    deadline = time.time() + 5.0
    while time.time() < deadline:
        with state_lock(WATCHDOG_LOCK_KEY):
            state = _read_state_unlocked(settings)
            if (
                state is not None
                and state.get("owner_id") == owner_id
                and state.get("status") == "starting"
            ):
                # Windows venv/pythonw redirectors may exit after spawning the real
                # interpreter. The unguessable owner token fences this exact reservation;
                # the worker replaces the transient launcher PID with its own durable PID.
                state["pid"] = os.getpid()
                state["status"] = "running"
                state["heartbeat_at"] = time.time()
                _write_state_unlocked(settings, state)
                return True
        time.sleep(0.05)
    return False


def run_chat_dispatch_watchdog(
    settings: Any,
    *,
    owner_id: str,
    interval_s: int,
) -> int:
    interval = _bounded_interval(interval_s)
    if not _claim_watchdog(settings, owner_id):
        return 3
    try:
        while True:
            with state_lock(WATCHDOG_LOCK_KEY):
                state = _read_state_unlocked(settings)
                if state is None or state.get("owner_id") != owner_id:
                    return 4
                if state.get("stop_requested"):
                    return 0
            error = None
            ensured_at = None
            try:
                from .chat_dispatch_bridge import manage_chat_dispatch

                status = manage_chat_dispatch(settings, action="status")
                if int(status.get("pending") or 0) > 0:
                    manage_chat_dispatch(settings, action="ensure")
                    ensured_at = time.time()
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"[:1000]
            with state_lock(WATCHDOG_LOCK_KEY):
                state = _read_state_unlocked(settings)
                if state is None or state.get("owner_id") != owner_id:
                    return 4
                state["status"] = "running"
                state["heartbeat_at"] = time.time()
                state["last_error"] = error
                if ensured_at is not None:
                    state["last_ensure_at"] = ensured_at
                _write_state_unlocked(settings, state)
            deadline = time.time() + interval
            while time.time() < deadline:
                time.sleep(min(0.5, max(0.0, deadline - time.time())))
                with state_lock(WATCHDOG_LOCK_KEY):
                    state = _read_state_unlocked(settings)
                if state is None or state.get("owner_id") != owner_id:
                    return 4
                if state.get("stop_requested"):
                    return 0
    finally:
        with state_lock(WATCHDOG_LOCK_KEY):
            state = _read_state_unlocked(settings)
            if state is not None and state.get("owner_id") == owner_id:
                state["status"] = "stopped"
                state["heartbeat_at"] = time.time()
                _write_state_unlocked(settings, state)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--owner-id", default="")
    parser.add_argument("--interval", type=int, default=DEFAULT_WATCHDOG_INTERVAL_S)
    args = parser.parse_args(argv)
    if not args.run or not args.owner_id:
        parser.error("--run and --owner-id are required")
    return run_chat_dispatch_watchdog(
        get_settings(),
        owner_id=args.owner_id,
        interval_s=args.interval,
    )


if __name__ == "__main__":
    raise SystemExit(main())
