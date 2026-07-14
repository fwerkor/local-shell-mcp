from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, BinaryIO

from .audit import audit
from .fs_ops import resolve_path
from .settings import get_settings
from .shell_ops import (
    check_command_policy,
    kill_shell,
    list_shells,
    read_shell,
    start_shell,
)

JOB_STORE_FILE_NAME = "jobs.json"
JOB_STORE_VERSION = 2
TERMINAL_STATUSES = {"succeeded", "failed", "exited", "stopped", "lost"}


def _utc() -> float:
    return time.time()


def _job_store_path() -> Path:
    return get_settings().state_dir / JOB_STORE_FILE_NAME


def _job_runtime_dir() -> Path:
    path = get_settings().state_dir / "jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_store() -> dict[str, Any]:
    path = _job_store_path()
    if not path.exists():
        return {"version": JOB_STORE_VERSION, "jobs": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": JOB_STORE_VERSION, "jobs": []}
    if not isinstance(data, dict):
        return {"version": JOB_STORE_VERSION, "jobs": []}
    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        jobs = []
    return {
        "version": JOB_STORE_VERSION,
        "jobs": [job for job in jobs if isinstance(job, dict)],
    }


def _save_store(store: dict[str, Any]) -> None:
    path = _job_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(store, indent=2, sort_keys=True), encoding="utf-8")
    with contextlib.suppress(OSError):
        tmp_path.chmod(0o600)
    tmp_path.replace(path)


def _new_job_id() -> str:
    return "job_" + uuid.uuid4().hex[:12]


def _shell_safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "-", value.strip())
    return cleaned[:48] or "job"


def _active_session_ids(shells: dict[str, Any]) -> set[str]:
    return {
        str(item.get("session_id"))
        for item in shells.get("sessions", [])
        if item.get("session_id")
    }


def _private_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    with contextlib.suppress(OSError):
        path.chmod(0o600)


def _attempt_paths(job_id: str, attempt: int) -> dict[str, Path]:
    root = _job_runtime_dir()
    stem = f"{job_id}-attempt-{attempt}"
    return {
        "command": root / f"{stem}.command",
        "log": root / f"{stem}.log",
        "status": root / f"{stem}.status.json",
    }


def _runner_argv(paths: dict[str, Path], cwd: Path) -> list[str]:
    settings = get_settings()
    arguments = [
        "job-runner",
        "--command-file",
        str(paths["command"]),
        "--log-file",
        str(paths["log"]),
        "--status-file",
        str(paths["status"]),
        "--cwd",
        str(cwd),
        "--shell",
        settings.shell_executable,
        "--max-log-bytes",
        str(max(1, settings.max_job_log_bytes)),
    ]
    if getattr(sys, "frozen", False):
        return [sys.executable, *arguments]
    return [sys.executable, "-m", "local_shell_mcp.main", *arguments]


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _runner_command(argv: list[str], shell: str) -> str:
    name = Path(shell).name.lower()
    powershell = "power" + "shell"
    if name in {powershell + ".exe", powershell, "pwsh.exe", "pwsh"}:
        return "& " + " ".join(_powershell_quote(value) for value in argv)
    if name in {"cmd.exe", "cmd"}:
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


def _prepare_attempt(
    job_id: str, attempt: int, command: str, cwd: str
) -> tuple[dict[str, Path], str]:
    check_command_policy(command)
    resolved_cwd = resolve_path(cwd, must_exist=True)
    paths = _attempt_paths(job_id, attempt)
    _private_write_text(paths["command"], command)
    paths["log"].unlink(missing_ok=True)
    paths["status"].unlink(missing_ok=True)
    argv = _runner_argv(paths, resolved_cwd)
    return paths, _runner_command(argv, get_settings().shell_executable)


def _read_status(job: dict[str, Any]) -> dict[str, Any] | None:
    raw_path = job.get("status_path")
    if not raw_path:
        return None
    try:
        payload = json.loads(Path(str(raw_path)).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _refresh_job_status(
    job: dict[str, Any], active_sessions: set[str], now: float | None = None
) -> dict[str, Any]:
    status = str(job.get("status") or "unknown")
    if status != "running":
        return job
    status_payload = _read_status(job)
    session_id = str(job.get("session_id") or "")
    if status_payload is None and session_id in active_sessions:
        return job

    updated = now or _utc()
    if status_payload is None:
        job.update(
            {
                "status": "lost",
                "updated_at": updated,
                "completed_at": updated,
                "exit_code": None,
                "error": "job session exited without a completion record",
            }
        )
        return job

    exit_code = status_payload.get("exit_code")
    job.update(
        {
            "status": "succeeded" if exit_code == 0 else "failed",
            "updated_at": float(status_payload.get("completed_at") or updated),
            "completed_at": float(status_payload.get("completed_at") or updated),
            "exit_code": exit_code,
            "error": status_payload.get("error"),
            "log_truncated": bool(status_payload.get("log_truncated", False)),
            "output_bytes": int(status_payload.get("output_bytes") or 0),
        }
    )
    return job


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job.get("job_id"),
        "name": job.get("name"),
        "status": job.get("status"),
        "command": job.get("command"),
        "cwd": job.get("cwd"),
        "session_id": job.get("session_id"),
        "backend": job.get("backend"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "last_started_at": job.get("last_started_at"),
        "completed_at": job.get("completed_at"),
        "exit_code": job.get("exit_code"),
        "error": job.get("error"),
        "log_truncated": bool(job.get("log_truncated", False)),
        "output_bytes": int(job.get("output_bytes") or 0),
        "attempts": job.get("attempts", 1),
    }


def _find_job(store: dict[str, Any], job_id: str) -> dict[str, Any]:
    for job in store.get("jobs", []):
        if job.get("job_id") == job_id:
            return job
    raise KeyError(f"job not found: {job_id}")


def _read_log_tail(path: str | None, lines: int) -> str:
    if not path:
        return ""
    target = Path(path)
    if not target.is_file():
        return ""
    max_bytes = max(1, get_settings().max_job_log_bytes)
    size = target.stat().st_size
    with target.open("rb") as handle:
        if size > max_bytes:
            handle.seek(size - max_bytes)
        data = handle.read(max_bytes)
    text = data.decode("utf-8", errors="replace")
    if lines > 0:
        split = text.splitlines()
        text = "\n".join(split[-max(1, lines) :])
        if data.endswith((b"\n", b"\r")) and text:
            text += "\n"
    return text


async def start_job(
    command: str, cwd: str = ".", name: str | None = None
) -> dict[str, Any]:
    job_id = _new_job_id()
    display_name = name or job_id
    paths, runner_command = _prepare_attempt(job_id, 1, command, cwd)
    shell_name = _shell_safe_name(f"{display_name}-{job_id}")
    shell = await start_shell(cwd, shell_name, runner_command)
    now = _utc()
    job = {
        "job_id": job_id,
        "name": display_name,
        "status": "running",
        "command": command,
        "cwd": cwd,
        "session_id": shell["session_id"],
        "backend": shell.get("backend"),
        "command_path": str(paths["command"]),
        "log_path": str(paths["log"]),
        "status_path": str(paths["status"]),
        "created_at": now,
        "updated_at": now,
        "last_started_at": now,
        "completed_at": None,
        "exit_code": None,
        "attempts": 1,
    }
    store = _load_store()
    store["jobs"].append(job)
    _save_store(store)
    audit("job_start", job_id=job_id, session=shell["session_id"], cwd=cwd)
    return _public_job(job)


async def list_jobs(include_finished: bool = True) -> dict[str, Any]:
    store = _load_store()
    active = _active_session_ids(await list_shells())
    now = _utc()
    jobs = [_refresh_job_status(job, active, now) for job in store.get("jobs", [])]
    _save_store(store)
    rows = [
        _public_job(job)
        for job in jobs
        if include_finished or job.get("status") not in TERMINAL_STATUSES
    ]
    rows.sort(key=lambda item: float(item.get("created_at") or 0), reverse=True)
    counts: dict[str, int] = {}
    for job in jobs:
        status = str(job.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return {"jobs": rows, "counts": counts}


async def tail_job(job_id: str, lines: int = 200) -> dict[str, Any]:
    store = _load_store()
    active = _active_session_ids(await list_shells())
    job = _refresh_job_status(_find_job(store, job_id), active)
    _save_store(store)
    output = _read_log_tail(job.get("log_path"), lines)
    if not output and job.get("status") == "running":
        try:
            tail = await read_shell(str(job["session_id"]), lines)
            output = str(tail.get("output", ""))
        except Exception as exc:
            job["status"] = "lost"
            job["updated_at"] = _utc()
            job["completed_at"] = job["updated_at"]
            job["error"] = str(exc)
            _save_store(store)
    result = {"job": _public_job(job), "output": output}
    if job.get("status") in TERMINAL_STATUSES:
        result["message"] = (
            f"job completed with exit code {job.get('exit_code')}"
            if job.get("exit_code") is not None
            else f"job is {job.get('status')}"
        )
    return result


async def stop_job(job_id: str) -> dict[str, Any]:
    store = _load_store()
    active = _active_session_ids(await list_shells())
    job = _refresh_job_status(_find_job(store, job_id), active)
    killed = False
    stderr = ""
    if job.get("status") == "running":
        result = await kill_shell(str(job["session_id"]))
        killed = bool(result.get("killed"))
        stderr = str(result.get("stderr") or "")
        job["status"] = "stopped" if killed else "lost"
        job["updated_at"] = _utc()
        job["completed_at"] = job["updated_at"]
        job["exit_code"] = None
    _save_store(store)
    audit("job_stop", job_id=job_id, session=job.get("session_id"), killed=killed)
    return {"job": _public_job(job), "killed": killed, "stderr": stderr}


async def retry_job(job_id: str) -> dict[str, Any]:
    store = _load_store()
    active = _active_session_ids(await list_shells())
    job = _refresh_job_status(_find_job(store, job_id), active)
    if job.get("status") == "running":
        raise RuntimeError(f"job is still running: {job_id}")
    attempts = int(job.get("attempts") or 1) + 1
    paths, runner_command = _prepare_attempt(
        job_id, attempts, str(job["command"]), str(job.get("cwd") or ".")
    )
    shell_name = _shell_safe_name(
        f"{job.get('name') or job_id}-{job_id}-{attempts}"
    )
    shell = await start_shell(
        str(job.get("cwd") or "."), shell_name, runner_command
    )
    now = _utc()
    job.update(
        {
            "status": "running",
            "session_id": shell["session_id"],
            "backend": shell.get("backend"),
            "command_path": str(paths["command"]),
            "log_path": str(paths["log"]),
            "status_path": str(paths["status"]),
            "updated_at": now,
            "last_started_at": now,
            "completed_at": None,
            "exit_code": None,
            "error": None,
            "log_truncated": False,
            "output_bytes": 0,
            "attempts": attempts,
        }
    )
    _save_store(store)
    audit(
        "job_retry",
        job_id=job_id,
        session=shell["session_id"],
        attempts=attempts,
    )
    return _public_job(job)


def _runner_shell_args(shell: str, command: str) -> list[str]:
    name = Path(shell).name.lower()
    powershell = "power" + "shell"
    if name in {powershell + ".exe", powershell, "pwsh.exe", "pwsh"}:
        return [shell, "-NoProfile", "-NonInteractive", "-Command", command]
    if name in {"cmd.exe", "cmd"}:
        return [shell, "/S", "/C", command]
    return [shell, "-lc", command]


def _compact_log(handle: BinaryIO, max_bytes: int) -> bool:
    handle.flush()
    size = handle.tell()
    if size <= max_bytes:
        return False
    handle.seek(max(0, size - max_bytes))
    tail = handle.read(max_bytes)
    handle.seek(0)
    handle.write(tail)
    handle.truncate()
    handle.seek(0, os.SEEK_END)
    handle.flush()
    return True


def _write_runner_status(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    try:
        _private_write_text(temporary, json.dumps(payload, indent=2, sort_keys=True))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def run_job_runner_cli(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--command-file", required=True)
    parser.add_argument("--log-file", required=True)
    parser.add_argument("--status-file", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--shell", required=True)
    parser.add_argument("--max-log-bytes", type=int, required=True)
    args = parser.parse_args(argv)

    command_path = Path(args.command_file)
    log_path = Path(args.log_file)
    status_path = Path(args.status_file)
    max_log_bytes = max(1, int(args.max_log_bytes))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    output_bytes = 0
    truncated = False
    exit_code: int | None = None
    error: str | None = None
    try:
        command = command_path.read_text(encoding="utf-8")
        process = subprocess.Popen(  # noqa: S603
            _runner_shell_args(args.shell, command),
            cwd=args.cwd,
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if process.stdout is None:
            raise RuntimeError("job process did not expose stdout")
        with log_path.open("w+b") as log:
            with contextlib.suppress(OSError):
                log_path.chmod(0o600)
            while True:
                chunk = process.stdout.read(65536)
                if not chunk:
                    break
                output_bytes += len(chunk)
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
                log.write(chunk)
                log.flush()
                if log.tell() > max_log_bytes * 2:
                    truncated = _compact_log(log, max_log_bytes) or truncated
            exit_code = process.wait()
            truncated = _compact_log(log, max_log_bytes) or truncated
    except BaseException as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
        print(error, file=sys.stderr, flush=True)
        if exit_code is None:
            exit_code = 127
    finally:
        _write_runner_status(
            status_path,
            {
                "completed_at": _utc(),
                "exit_code": exit_code,
                "error": error,
                "log_truncated": truncated,
                "output_bytes": output_bytes,
            },
        )
    raise SystemExit(exit_code if exit_code is not None else 127)
