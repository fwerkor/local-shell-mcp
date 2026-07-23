from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import errno
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, BinaryIO

from .audit import audit
from .fs_ops import resolve_path
from .settings import get_settings
from .shell_environment import filtered_subprocess_env
from .shell_ops import (
    check_command_policy,
    kill_shell,
    list_shells,
    read_shell,
    start_shell,
)

JOB_STORE_FILE_NAME = "jobs.json"
JOB_STORE_BACKUP_FILE_NAME = "jobs.json.bak"
JOB_STORE_VERSION = 2
JOB_STORE_LEGACY_VERSIONS = {1}
JOB_STORE_LOCK_TIMEOUT_S = 2.0
JOB_STORE_LOCK_RETRY_INTERVAL_S = 0.05
TERMINAL_STATUSES = {"succeeded", "failed", "exited", "stopped", "lost"}
_JOB_STORE_THREAD_LOCK = threading.RLock()
_ACTIVE_JOB_OPERATIONS: set[str] = set()
ManagedJobHandler = Callable[
    ["ManagedJobContext", dict[str, Any]], Awaitable[dict[str, Any] | None]
]
_MANAGED_JOB_HANDLERS: dict[str, ManagedJobHandler] = {}
_MANAGED_JOB_TASKS: dict[str, asyncio.Task[None]] = {}


def _utc() -> float:
    return time.time()


def _job_store_path() -> Path:
    return get_settings().state_dir / JOB_STORE_FILE_NAME


def _job_store_backup_path() -> Path:
    return get_settings().state_dir / JOB_STORE_BACKUP_FILE_NAME


def _empty_store() -> dict[str, Any]:
    return {"version": JOB_STORE_VERSION, "jobs": []}


def _job_runtime_dir() -> Path:
    path = get_settings().state_dir / "jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _job_store_lock_path() -> Path:
    path = get_settings().state_dir / "jobs.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _try_lock_store_file(handle: BinaryIO) -> bool:
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
            return False
        raise
    return True


def _lock_store_file(handle: BinaryIO, timeout_s: float | None = None) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()

    timeout_s = (
        JOB_STORE_LOCK_TIMEOUT_S
        if timeout_s is None
        else max(0.0, float(timeout_s))
    )
    deadline = time.monotonic() + timeout_s
    while not _try_lock_store_file(handle):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"timed out after {timeout_s:g}s acquiring the job store lock"
            )
        time.sleep(min(JOB_STORE_LOCK_RETRY_INTERVAL_S, remaining))


def _unlock_store_file(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _load_store_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"unsupported or invalid job store: {path}")
    version = data.get("version")
    if version != JOB_STORE_VERSION and version not in JOB_STORE_LEGACY_VERSIONS:
        raise ValueError(f"unsupported or invalid job store: {path}")
    rows = data.get("jobs")
    if not isinstance(rows, list):
        raise ValueError(f"job store jobs field is invalid: {path}")
    jobs = [job for job in rows if isinstance(job, dict)]
    if version != JOB_STORE_VERSION:
        audit(
            "job_store_migrated",
            path=str(path),
            from_version=version,
            to_version=JOB_STORE_VERSION,
            jobs=len(jobs),
        )
    return {
        "version": JOB_STORE_VERSION,
        "jobs": jobs,
    }


def _load_store() -> dict[str, Any]:
    path = _job_store_path()
    backup_path = _job_store_backup_path()
    if not path.exists() and not backup_path.exists():
        return _empty_store()

    main_error: Exception | None = None
    if path.exists():
        try:
            return _load_store_file(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            main_error = exc
            audit("job_store_unreadable", path=str(path), error=repr(exc))

    if backup_path.exists():
        try:
            store = _load_store_file(backup_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            audit("job_store_backup_unreadable", path=str(backup_path), error=repr(exc))
        else:
            audit("job_store_recovered", path=str(path), backup_path=str(backup_path))
            return store

    if main_error is not None or path.exists() or backup_path.exists():
        raise RuntimeError(
            "Job store is unreadable and no valid backup is available; refusing to reset it"
        ) from main_error
    return _empty_store()


def _remove_attempt_paths(paths: dict[str, Path] | None) -> None:
    if not paths:
        return
    for path in paths.values():
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)


def _remove_attempt_files(job_id: str, keep_attempt: int | None = None) -> None:
    if not job_id:
        return
    keep_stem = f"{job_id}-attempt-{keep_attempt}." if keep_attempt is not None else None
    for path in _job_runtime_dir().glob(f"{job_id}-attempt-*"):
        if keep_stem is not None and path.name.startswith(keep_stem):
            continue
        with contextlib.suppress(OSError):
            path.unlink()


def _prune_store(store: dict[str, Any]) -> None:
    jobs = [job for job in store.get("jobs", []) if isinstance(job, dict)]
    max_jobs = max(0, int(get_settings().max_jobs))
    active = [job for job in jobs if job.get("status") not in TERMINAL_STATUSES]
    finished = sorted(
        (job for job in jobs if job.get("status") in TERMINAL_STATUSES),
        key=lambda job: float(job.get("created_at") or 0),
        reverse=True,
    )
    keep_finished = finished[: max(0, max_jobs - len(active))]
    keep_ids = {id(job) for job in [*active, *keep_finished]}
    removed = [job for job in jobs if id(job) not in keep_ids]
    store["jobs"] = [job for job in jobs if id(job) in keep_ids]
    for job in removed:
        _remove_attempt_files(str(job.get("job_id") or ""))


def _save_store(store: dict[str, Any]) -> None:
    _prune_store(store)
    store["version"] = JOB_STORE_VERSION
    path = _job_store_path()
    backup_path = _job_store_backup_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(store, indent=2, sort_keys=True)
    tmp_path = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    backup_tmp_path = backup_path.with_name(backup_path.name + f".{uuid.uuid4().hex}.tmp")
    try:
        for temporary in (tmp_path, backup_tmp_path):
            temporary.write_text(payload, encoding="utf-8")
            with contextlib.suppress(OSError):
                temporary.chmod(0o600)
        os.replace(tmp_path, path)
        os.replace(backup_tmp_path, backup_path)
    finally:
        tmp_path.unlink(missing_ok=True)
        backup_tmp_path.unlink(missing_ok=True)


def _job_store_busy_error(lock_path: Path, *, lock_kind: str) -> TimeoutError:
    audit(
        "job_store_lock_timeout",
        path=str(lock_path),
        timeout_s=JOB_STORE_LOCK_TIMEOUT_S,
        lock_kind=lock_kind,
    )
    return TimeoutError(
        f"job store is busy: {lock_path}; another local-shell-mcp operation or process "
        "may be using the same state directory"
    )


@contextlib.contextmanager
def _store_transaction():  # noqa: ANN201
    lock_path = _job_store_lock_path()
    started = time.monotonic()
    if not _JOB_STORE_THREAD_LOCK.acquire(timeout=JOB_STORE_LOCK_TIMEOUT_S):
        raise _job_store_busy_error(lock_path, lock_kind="thread")
    try:
        with lock_path.open("a+b") as handle:
            with contextlib.suppress(OSError):
                lock_path.chmod(0o600)
            remaining = max(
                0.0, JOB_STORE_LOCK_TIMEOUT_S - (time.monotonic() - started)
            )
            try:
                _lock_store_file(handle, timeout_s=remaining)
            except TimeoutError as exc:
                raise _job_store_busy_error(lock_path, lock_kind="file") from exc
            try:
                store = _load_store()
                yield store
                _save_store(store)
            finally:
                _unlock_store_file(handle)
    finally:
        _JOB_STORE_THREAD_LOCK.release()


def _new_job_id() -> str:
    return "job_" + uuid.uuid4().hex[:12]


def _shell_safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "-", value.strip())[:48].strip(".-")
    return cleaned or "job"


def _active_session_ids(shells: dict[str, Any]) -> set[str]:
    return {
        str(item.get("session_id")) for item in shells.get("sessions", []) if item.get("session_id")
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
        "--env-blocklist-b64",
        _encode_runner_env_policy(settings.shell_env_blocklist),
        "--env-blocked-prefixes-b64",
        _encode_runner_env_policy(settings.shell_env_blocked_prefixes),
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


def _read_status_path(raw_path: Any) -> dict[str, Any] | None:
    if not raw_path:
        return None
    try:
        payload = json.loads(Path(str(raw_path)).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _read_status(job: dict[str, Any]) -> dict[str, Any] | None:
    return _read_status_path(job.get("status_path"))


def _apply_status_payload(
    job: dict[str, Any], status_payload: dict[str, Any], updated: float
) -> dict[str, Any]:
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


def _clear_pending_retry(job: dict[str, Any]) -> None:
    for key in (
        "pending_attempt",
        "pending_session_name",
        "pending_command_path",
        "pending_log_path",
        "pending_status_path",
    ):
        job.pop(key, None)


def _adopt_pending_retry(job: dict[str, Any]) -> None:
    attempt = job.get("pending_attempt")
    if attempt is not None:
        job["attempts"] = int(attempt)
    for pending_key, active_key in (
        ("pending_session_name", "session_id"),
        ("pending_command_path", "command_path"),
        ("pending_log_path", "log_path"),
        ("pending_status_path", "status_path"),
    ):
        value = job.get(pending_key)
        if value:
            job[active_key] = value


def _begin_job_operation(job: dict[str, Any], kind: str) -> str:
    operation_id = f"{kind}_{uuid.uuid4().hex}"
    _ACTIVE_JOB_OPERATIONS.add(operation_id)
    job["operation_id"] = operation_id
    job["operation_kind"] = kind
    job["operation_started_at"] = _utc()
    return operation_id


def _job_operation_matches(job: dict[str, Any], operation_id: str) -> bool:
    return str(job.get("operation_id") or "") == operation_id


def _job_operation_is_active(job: dict[str, Any], kind: str) -> bool:
    operation_id = str(job.get("operation_id") or "")
    return (
        bool(operation_id)
        and str(job.get("operation_kind") or "") == kind
        and operation_id in _ACTIVE_JOB_OPERATIONS
    )


def _clear_job_operation(job: dict[str, Any]) -> None:
    for key in ("operation_id", "operation_kind", "operation_started_at"):
        job.pop(key, None)


def _refresh_job_status(
    job: dict[str, Any], active_sessions: set[str], now: float | None = None
) -> dict[str, Any]:
    status = str(job.get("status") or "unknown")
    if status not in {"starting", "running", "stopping", "retrying"}:
        return job

    updated = now or _utc()
    if job.get("kind") == "managed":
        task = _MANAGED_JOB_TASKS.get(str(job.get("job_id") or ""))
        if task is not None and not task.done():
            return job
        job.update(
            {
                "status": "stopped" if status == "stopping" else "lost",
                "updated_at": updated,
                "completed_at": updated,
                "exit_code": None,
                "error": (
                    None
                    if status == "stopping"
                    else "managed job is no longer running; retry it to resume the operation"
                ),
            }
        )
        return job

    if status == "starting" and _job_operation_is_active(job, "start"):
        return job
    if status == "retrying" and _job_operation_is_active(job, "retry"):
        return job
    if status == "stopping" and _job_operation_is_active(job, "stop"):
        return job
    if status == "starting":
        status_payload = _read_status(job)
        session_id = str(job.get("session_id") or "")
        _clear_job_operation(job)
        if status_payload is not None:
            return _apply_status_payload(job, status_payload, updated)
        if session_id and session_id in active_sessions:
            job.update(
                {
                    "status": "running",
                    "updated_at": updated,
                    "completed_at": None,
                    "exit_code": None,
                    "error": "recovered job start after an interrupted state commit",
                }
            )
            return job
        job.update(
            {
                "status": "failed",
                "updated_at": updated,
                "completed_at": updated,
                "exit_code": None,
                "error": "job start was interrupted before a recoverable shell session was created",
            }
        )
        return job
    if status == "retrying":
        pending_session = str(job.get("pending_session_name") or "")
        status_payload = _read_status_path(job.get("pending_status_path"))
        if status_payload is not None:
            _adopt_pending_retry(job)
            _clear_pending_retry(job)
            return _apply_status_payload(job, status_payload, updated)
        if pending_session and pending_session in active_sessions:
            _adopt_pending_retry(job)
            _clear_pending_retry(job)
            job.update(
                {
                    "status": "running",
                    "updated_at": updated,
                    "completed_at": None,
                    "exit_code": None,
                    "error": "recovered retry attempt after an interrupted state commit",
                }
            )
            return job
        if job.get("pending_attempt") is not None:
            _adopt_pending_retry(job)
        _clear_pending_retry(job)
        job.update(
            {
                "status": "failed",
                "updated_at": updated,
                "completed_at": updated,
                "exit_code": None,
                "error": "retry was interrupted before a recoverable shell session was committed",
            }
        )
        return job

    status_payload = _read_status(job)
    session_id = str(job.get("session_id") or "")
    if status_payload is not None:
        return _apply_status_payload(job, status_payload, updated)

    if status == "stopping":
        if session_id in active_sessions:
            job.update(
                {
                    "status": "running",
                    "updated_at": updated,
                    "error": "recovered an interrupted stop request; the shell is still active",
                }
            )
        else:
            job.update(
                {
                    "status": "stopped",
                    "updated_at": updated,
                    "completed_at": updated,
                    "exit_code": None,
                    "error": None,
                }
            )
        return job

    if session_id in active_sessions:
        return job
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


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job.get("job_id"),
        "kind": job.get("kind", "shell"),
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
        "progress": job.get("progress"),
        "result": job.get("result"),
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


def register_managed_job_handler(kind: str, handler: ManagedJobHandler) -> None:
    normalized = kind.strip()
    if not normalized:
        raise ValueError("managed job kind must not be empty")
    existing = _MANAGED_JOB_HANDLERS.get(normalized)
    if existing is not None and existing is not handler:
        raise ValueError(f"managed job handler already registered: {normalized}")
    _MANAGED_JOB_HANDLERS[normalized] = handler


def _append_managed_log(path: str, message: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = message if message.endswith("\n") else message + "\n"
    max_bytes = max(1, int(get_settings().max_job_log_bytes))
    encoded = payload.encode("utf-8", errors="replace")
    with target.open("a+b") as handle:
        with contextlib.suppress(OSError):
            target.chmod(0o600)
        handle.write(encoded)
        handle.flush()
        truncated = _compact_log(handle, max_bytes)
    with _store_transaction() as store:
        job_id = target.name.split("-attempt-", 1)[0]
        with contextlib.suppress(KeyError):
            job = _find_job(store, job_id)
            job["output_bytes"] = int(job.get("output_bytes") or 0) + len(encoded)
            job["log_truncated"] = bool(job.get("log_truncated")) or truncated


def _update_managed_progress(job_id: str, progress: dict[str, Any]) -> None:
    with _store_transaction() as store:
        job = _find_job(store, job_id)
        if job.get("status") in {"starting", "running", "stopping", "retrying"}:
            job["progress"] = dict(progress)
            job["updated_at"] = _utc()


class ManagedJobContext:
    def __init__(self, job_id: str, log_path: str):
        self.job_id = job_id
        self.log_path = log_path

    async def log(self, message: str) -> None:
        await asyncio.to_thread(_append_managed_log, self.log_path, message)

    async def update_progress(self, **progress: Any) -> None:
        await asyncio.to_thread(_update_managed_progress, self.job_id, progress)


def _finish_managed_job(
    job_id: str,
    *,
    status: str,
    exit_code: int | None,
    error: str | None,
    result: dict[str, Any] | None = None,
) -> None:
    with _store_transaction() as store:
        job = _find_job(store, job_id)
        if job.get("status") not in {"starting", "running", "stopping", "retrying"}:
            return
        completed_at = _utc()
        job.update(
            {
                "status": status,
                "updated_at": completed_at,
                "completed_at": completed_at,
                "exit_code": exit_code,
                "error": error,
            }
        )
        if result is not None:
            job["result"] = result


async def _run_managed_job(
    job_id: str,
    kind: str,
    payload: dict[str, Any],
    log_path: str,
) -> None:
    context = ManagedJobContext(job_id, log_path)
    handler = _MANAGED_JOB_HANDLERS[kind]
    try:
        result = await handler(context, dict(payload))
    except asyncio.CancelledError:
        await asyncio.to_thread(_append_managed_log, log_path, "job cancelled")
        await asyncio.to_thread(
            _finish_managed_job,
            job_id,
            status="stopped",
            exit_code=None,
            error=None,
        )
        raise
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        await asyncio.to_thread(_append_managed_log, log_path, error)
        await asyncio.to_thread(
            _finish_managed_job,
            job_id,
            status="failed",
            exit_code=1,
            error=error,
        )
    else:
        await asyncio.to_thread(
            _finish_managed_job,
            job_id,
            status="succeeded",
            exit_code=0,
            error=None,
            result=result,
        )
    finally:
        _MANAGED_JOB_TASKS.pop(job_id, None)


def _launch_managed_job(
    job_id: str,
    kind: str,
    payload: dict[str, Any],
    log_path: str,
) -> None:
    task = asyncio.create_task(
        _run_managed_job(job_id, kind, payload, log_path),
        name=f"managed-job-{job_id}",
    )
    _MANAGED_JOB_TASKS[job_id] = task


async def start_managed_job(
    kind: str,
    payload: dict[str, Any],
    *,
    name: str | None = None,
    command: str | None = None,
) -> dict[str, Any]:
    normalized = kind.strip()
    if normalized not in _MANAGED_JOB_HANDLERS:
        raise ValueError(f"unknown managed job kind: {normalized}")
    job_id = _new_job_id()
    display_name = name or f"{normalized}-{job_id}"
    paths = _attempt_paths(job_id, 1)
    _private_write_text(paths["log"], "")
    now = _utc()
    job = {
        "job_id": job_id,
        "kind": "managed",
        "managed_kind": normalized,
        "managed_payload": dict(payload),
        "name": display_name,
        "status": "running",
        "command": command or normalized,
        "cwd": ".",
        "session_id": None,
        "backend": "managed",
        "command_path": None,
        "log_path": str(paths["log"]),
        "status_path": None,
        "created_at": now,
        "updated_at": now,
        "last_started_at": now,
        "completed_at": None,
        "exit_code": None,
        "error": None,
        "log_truncated": False,
        "output_bytes": 0,
        "attempts": 1,
    }
    try:
        with _store_transaction() as store:
            store["jobs"].append(job)
        _launch_managed_job(job_id, normalized, payload, str(paths["log"]))
    except BaseException:
        _remove_attempt_files(job_id)
        with contextlib.suppress(Exception), _store_transaction() as store:
            store["jobs"] = [row for row in store.get("jobs", []) if row.get("job_id") != job_id]
        raise
    audit("job_start", job_id=job_id, backend="managed", kind=normalized)
    return _public_job(job)


async def start_job(command: str, cwd: str = ".", name: str | None = None) -> dict[str, Any]:
    job_id = _new_job_id()
    display_name = name or job_id
    paths, runner_command = _prepare_attempt(job_id, 1, command, cwd)
    shell_name = _shell_safe_name(f"{display_name}-{job_id}")
    now = _utc()
    job = {
        "job_id": job_id,
        "name": display_name,
        "status": "starting",
        "command": command,
        "cwd": cwd,
        "session_id": shell_name,
        "backend": None,
        "command_path": str(paths["command"]),
        "log_path": str(paths["log"]),
        "status_path": str(paths["status"]),
        "created_at": now,
        "updated_at": now,
        "last_started_at": None,
        "completed_at": None,
        "exit_code": None,
        "attempts": 1,
    }
    operation_id = _begin_job_operation(job, "start")
    try:
        with _store_transaction() as store:
            store["jobs"].append(job)
    except BaseException:
        _ACTIVE_JOB_OPERATIONS.discard(operation_id)
        _remove_attempt_files(job_id)
        raise

    try:
        try:
            shell = await start_shell(cwd, shell_name, runner_command)
        except Exception as exc:
            _remove_attempt_files(job_id)
            with _store_transaction() as store:
                current = _find_job(store, job_id)
                if (
                    current.get("status") == "starting"
                    and _job_operation_matches(current, operation_id)
                ):
                    _clear_job_operation(current)
                    current["status"] = "failed"
                    current["updated_at"] = _utc()
                    current["completed_at"] = current["updated_at"]
                    current["error"] = f"start failed: {type(exc).__name__}: {exc}"
            raise

        changed_while_starting = False
        try:
            with _store_transaction() as store:
                current = _find_job(store, job_id)
                if (
                    current.get("status") != "starting"
                    or not _job_operation_matches(current, operation_id)
                ):
                    changed_while_starting = True
                else:
                    started_at = _utc()
                    _clear_job_operation(current)
                    current.update(
                        {
                            "status": "running",
                            "session_id": shell["session_id"],
                            "backend": shell.get("backend"),
                            "updated_at": started_at,
                            "last_started_at": started_at,
                            "error": None,
                        }
                    )
                public_job = _public_job(current)
        except Exception:
            with contextlib.suppress(Exception):
                await kill_shell(str(shell["session_id"]))
            _remove_attempt_files(job_id)
            raise
        if changed_while_starting:
            with contextlib.suppress(Exception):
                await kill_shell(str(shell["session_id"]))
            _remove_attempt_files(job_id)
            raise RuntimeError(f"job changed while starting: {job_id}")
        audit("job_start", job_id=job_id, session=shell["session_id"], cwd=cwd)
        return public_job
    finally:
        _ACTIVE_JOB_OPERATIONS.discard(operation_id)


async def list_jobs(include_finished: bool = True) -> dict[str, Any]:
    active = _active_session_ids(await list_shells())
    now = _utc()
    with _store_transaction() as store:
        jobs = [_refresh_job_status(job, active, now) for job in store.get("jobs", [])]
        store["jobs"] = jobs
        _prune_store(store)
        jobs = store["jobs"]
        rows = [
            _public_job(job)
            for job in jobs
            if include_finished or job.get("status") not in TERMINAL_STATUSES
        ]
        counts: dict[str, int] = {}
        for job in jobs:
            status = str(job.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
    rows.sort(key=lambda item: float(item.get("created_at") or 0), reverse=True)
    return {"jobs": rows, "counts": counts}


async def tail_job(job_id: str, lines: int = 200) -> dict[str, Any]:
    active = _active_session_ids(await list_shells())
    with _store_transaction() as store:
        job = _refresh_job_status(_find_job(store, job_id), active)
        public_job = _public_job(job)
        log_path = job.get("log_path")
        session_id = str(job.get("session_id") or "")
        status = str(job.get("status") or "")
    output = _read_log_tail(log_path, lines)
    if not output and status == "running" and public_job.get("backend") != "managed":
        try:
            tail = await read_shell(session_id, lines)
            output = str(tail.get("output", ""))
        except Exception as exc:
            with _store_transaction() as store:
                current = _find_job(store, job_id)
                if (
                    current.get("status") == "running"
                    and str(current.get("session_id") or "") == session_id
                ):
                    current["status"] = "lost"
                    current["updated_at"] = _utc()
                    current["completed_at"] = current["updated_at"]
                    current["error"] = str(exc)
                public_job = _public_job(current)
    result = {"job": public_job, "output": output}
    if public_job.get("status") in TERMINAL_STATUSES:
        result["message"] = (
            f"job completed with exit code {public_job.get('exit_code')}"
            if public_job.get("exit_code") is not None
            else f"job is {public_job.get('status')}"
        )
    return result


async def _stop_managed_job(job_id: str) -> dict[str, Any]:
    with _store_transaction() as store:
        job = _refresh_job_status(_find_job(store, job_id), set())
        if job.get("status") != "running":
            return {"job": _public_job(job), "killed": False, "stderr": ""}
        job["status"] = "stopping"
        job["updated_at"] = _utc()

    task = _MANAGED_JOB_TASKS.get(job_id)
    killed = task is not None and not task.done()
    if killed:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    else:
        await asyncio.to_thread(
            _finish_managed_job,
            job_id,
            status="stopped",
            exit_code=None,
            error=None,
        )

    with _store_transaction() as store:
        job = _find_job(store, job_id)
        if job.get("status") == "stopping":
            completed_at = _utc()
            job.update(
                {
                    "status": "stopped",
                    "updated_at": completed_at,
                    "completed_at": completed_at,
                    "exit_code": None,
                    "error": None,
                }
            )
        public_job = _public_job(job)
    audit("job_stop", job_id=job_id, backend="managed", killed=killed)
    return {"job": public_job, "killed": killed, "stderr": ""}


async def _retry_managed_job(job_id: str) -> dict[str, Any]:
    with _store_transaction() as store:
        job = _refresh_job_status(_find_job(store, job_id), set())
        if job.get("status") in {"starting", "running", "stopping", "retrying"}:
            raise RuntimeError(f"job is still active: {job_id}")
        kind = str(job.get("managed_kind") or "")
        if kind not in _MANAGED_JOB_HANDLERS:
            raise RuntimeError(f"managed job handler is unavailable: {kind}")
        payload = dict(job.get("managed_payload") or {})
        attempts = int(job.get("attempts") or 1) + 1
        paths = _attempt_paths(job_id, attempts)
        _private_write_text(paths["log"], "")
        started_at = _utc()
        job.update(
            {
                "status": "running",
                "updated_at": started_at,
                "last_started_at": started_at,
                "completed_at": None,
                "exit_code": None,
                "error": None,
                "log_path": str(paths["log"]),
                "log_truncated": False,
                "output_bytes": 0,
                "attempts": attempts,
                "progress": None,
                "result": None,
            }
        )
        public_job = _public_job(job)
    _remove_attempt_files(job_id, keep_attempt=attempts)
    try:
        _launch_managed_job(job_id, kind, payload, str(paths["log"]))
    except BaseException as exc:
        error = f"retry failed: {type(exc).__name__}: {exc}"
        await asyncio.to_thread(
            _finish_managed_job,
            job_id,
            status="failed",
            exit_code=1,
            error=error,
        )
        raise
    audit("job_retry", job_id=job_id, backend="managed", attempts=attempts)
    return public_job


async def stop_job(job_id: str) -> dict[str, Any]:
    with _store_transaction() as store:
        managed = _find_job(store, job_id).get("kind") == "managed"
    if managed:
        return await _stop_managed_job(job_id)
    active = _active_session_ids(await list_shells())
    session_id = ""
    operation_id = ""
    try:
        with _store_transaction() as store:
            job = _refresh_job_status(_find_job(store, job_id), active)
            if job.get("status") == "running":
                session_id = str(job.get("session_id") or "")
                job["status"] = "stopping"
                job["updated_at"] = _utc()
                operation_id = _begin_job_operation(job, "stop")
            else:
                return {
                    "job": _public_job(job),
                    "killed": False,
                    "stderr": "",
                }
    except BaseException:
        _ACTIVE_JOB_OPERATIONS.discard(operation_id)
        raise

    try:
        try:
            result = await kill_shell(session_id)
        except Exception as exc:
            still_active = True
            with contextlib.suppress(Exception):
                still_active = session_id in _active_session_ids(await list_shells())
            with _store_transaction() as store:
                job = _find_job(store, job_id)
                if (
                    job.get("status") == "stopping"
                    and str(job.get("session_id") or "") == session_id
                    and _job_operation_matches(job, operation_id)
                ):
                    job["status"] = "running" if still_active else "lost"
                    job["updated_at"] = _utc()
                    job["error"] = f"stop failed: {type(exc).__name__}: {exc}"
                    if not still_active:
                        job["completed_at"] = job["updated_at"]
                    _clear_job_operation(job)
            raise

        killed = bool(result.get("killed"))
        stderr = str(result.get("stderr") or "")
        with _store_transaction() as store:
            job = _find_job(store, job_id)
            if (
                job.get("status") == "stopping"
                and str(job.get("session_id") or "") == session_id
                and _job_operation_matches(job, operation_id)
            ):
                job["status"] = "stopped" if killed else "lost"
                job["updated_at"] = _utc()
                job["completed_at"] = job["updated_at"]
                job["exit_code"] = None
                _clear_job_operation(job)
            public_job = _public_job(job)
        audit("job_stop", job_id=job_id, session=session_id, killed=killed)
        return {"job": public_job, "killed": killed, "stderr": stderr}
    finally:
        _ACTIVE_JOB_OPERATIONS.discard(operation_id)


async def retry_job(job_id: str) -> dict[str, Any]:
    with _store_transaction() as store:
        managed = _find_job(store, job_id).get("kind") == "managed"
    if managed:
        return await _retry_managed_job(job_id)
    active = _active_session_ids(await list_shells())
    operation_id = ""
    try:
        with _store_transaction() as store:
            job = _refresh_job_status(_find_job(store, job_id), active)
            if job.get("status") in {"starting", "running", "stopping", "retrying"}:
                raise RuntimeError(f"job is still active: {job_id}")
            attempts = int(job.get("attempts") or 1) + 1
            command = str(job["command"])
            cwd = str(job.get("cwd") or ".")
            display_name = str(job.get("name") or job_id)
            shell_name = _shell_safe_name(f"{display_name}-{job_id}-{attempts}")
            job.update(
                {
                    "status": "retrying",
                    "updated_at": _utc(),
                    "pending_attempt": attempts,
                    "pending_session_name": shell_name,
                }
            )
            operation_id = _begin_job_operation(job, "retry")
    except BaseException:
        _ACTIVE_JOB_OPERATIONS.discard(operation_id)
        raise

    paths: dict[str, Path] | None = None
    try:
        try:
            paths, runner_command = _prepare_attempt(job_id, attempts, command, cwd)
            with _store_transaction() as store:
                job = _find_job(store, job_id)
                if (
                    job.get("status") != "retrying"
                    or not _job_operation_matches(job, operation_id)
                ):
                    raise RuntimeError(f"job changed while preparing retry: {job_id}")
                job.update(
                    {
                        "pending_command_path": str(paths["command"]),
                        "pending_log_path": str(paths["log"]),
                        "pending_status_path": str(paths["status"]),
                    }
                )
            shell = await start_shell(cwd, shell_name, runner_command)
        except Exception as exc:
            _remove_attempt_paths(paths)
            with _store_transaction() as store:
                job = _find_job(store, job_id)
                if (
                    job.get("status") == "retrying"
                    and _job_operation_matches(job, operation_id)
                ):
                    _clear_pending_retry(job)
                    _clear_job_operation(job)
                    job["status"] = "failed"
                    job["updated_at"] = _utc()
                    job["completed_at"] = job["updated_at"]
                    job["error"] = f"retry failed: {type(exc).__name__}: {exc}"
            raise

        now = _utc()
        changed_while_retrying = False
        try:
            with _store_transaction() as store:
                job = _find_job(store, job_id)
                if (
                    job.get("status") != "retrying"
                    or not _job_operation_matches(job, operation_id)
                ):
                    changed_while_retrying = True
                else:
                    _clear_pending_retry(job)
                    _clear_job_operation(job)
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
                public_job = _public_job(job)
        except Exception as exc:
            with contextlib.suppress(Exception):
                await kill_shell(str(shell["session_id"]))
            _remove_attempt_paths(paths)
            with contextlib.suppress(Exception), _store_transaction() as store:
                job = _find_job(store, job_id)
                if (
                    job.get("status") == "retrying"
                    and _job_operation_matches(job, operation_id)
                ):
                    _clear_pending_retry(job)
                    _clear_job_operation(job)
                    job["status"] = "failed"
                    job["updated_at"] = _utc()
                    job["completed_at"] = job["updated_at"]
                    job["error"] = f"retry commit failed: {type(exc).__name__}: {exc}"
            raise
        if changed_while_retrying:
            with contextlib.suppress(Exception):
                await kill_shell(str(shell["session_id"]))
            _remove_attempt_paths(paths)
            raise RuntimeError(f"job changed while retrying: {job_id}")
        _remove_attempt_files(job_id, keep_attempt=attempts)
        audit(
            "job_retry",
            job_id=job_id,
            session=shell["session_id"],
            attempts=attempts,
        )
        return public_job
    finally:
        _ACTIVE_JOB_OPERATIONS.discard(operation_id)


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


def _encode_runner_env_policy(values: list[str]) -> str:
    payload = json.dumps(values, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii")


def _parse_runner_env_policy(raw: str, label: str) -> list[str]:
    try:
        decoded = base64.b64decode(
            raw.encode("ascii"), altchars=b"-_", validate=True
        ).decode("utf-8")
        value = json.loads(decoded)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be a URL-safe Base64 JSON string list") from exc
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a URL-safe Base64 JSON string list")
    return value


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
    parser.add_argument(
        "--env-blocklist-b64",
        default=_encode_runner_env_policy(["CLOUDFLARE_TUNNEL_TOKEN"]),
    )
    parser.add_argument(
        "--env-blocked-prefixes-b64",
        default=_encode_runner_env_policy(["LOCAL_SHELL_MCP_", "DOCKER_"]),
    )
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
        blocked_names = _parse_runner_env_policy(
            args.env_blocklist_b64, "env blocklist"
        )
        blocked_prefixes = _parse_runner_env_policy(
            args.env_blocked_prefixes_b64, "env blocked prefixes"
        )
        process = subprocess.Popen(  # noqa: S603
            _runner_shell_args(args.shell, command),
            cwd=args.cwd,
            env=filtered_subprocess_env(blocked_names, blocked_prefixes),
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
