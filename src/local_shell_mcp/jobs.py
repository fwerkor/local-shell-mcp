from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from .audit import audit
from .settings import get_settings
from .shell_ops import kill_shell, list_shells, read_shell, start_shell

JOB_STORE_FILE_NAME = "jobs.json"
JOB_STORE_VERSION = 1
TERMINAL_STATUSES = {"exited", "stopped", "lost"}


def _utc() -> float:
    return time.time()


def _job_store_path() -> Path:
    return get_settings().state_dir / JOB_STORE_FILE_NAME


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
    return {"version": JOB_STORE_VERSION, "jobs": [job for job in jobs if isinstance(job, dict)]}


def _save_store(store: dict[str, Any]) -> None:
    path = _job_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(store, indent=2, sort_keys=True), encoding="utf-8")
    try:
        tmp_path.chmod(0o600)
    except OSError:
        pass
    tmp_path.replace(path)


def _new_job_id() -> str:
    return "job_" + uuid.uuid4().hex[:12]


def _shell_safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "-", value.strip())
    return cleaned[:48] or "job"


def _active_session_ids(shells: dict[str, Any]) -> set[str]:
    return {str(item.get("session_id")) for item in shells.get("sessions", []) if item.get("session_id")}


def _refresh_job_status(job: dict[str, Any], active_sessions: set[str], now: float | None = None) -> dict[str, Any]:
    status = str(job.get("status") or "unknown")
    session_id = str(job.get("session_id") or "")
    if status == "running" and session_id not in active_sessions:
        job["status"] = "exited"
        job["updated_at"] = now or _utc()
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
        "attempts": job.get("attempts", 1),
    }


def _find_job(store: dict[str, Any], job_id: str) -> dict[str, Any]:
    for job in store.get("jobs", []):
        if job.get("job_id") == job_id:
            return job
    raise KeyError(f"job not found: {job_id}")


async def start_job(command: str, cwd: str = ".", name: str | None = None) -> dict[str, Any]:
    job_id = _new_job_id()
    display_name = name or job_id
    shell_name = _shell_safe_name(f"{display_name}-{job_id}")
    shell = await start_shell(cwd, shell_name, command)
    now = _utc()
    job = {
        "job_id": job_id,
        "name": display_name,
        "status": "running",
        "command": command,
        "cwd": cwd,
        "session_id": shell["session_id"],
        "backend": shell.get("backend"),
        "created_at": now,
        "updated_at": now,
        "last_started_at": now,
        "attempts": 1,
    }
    store = _load_store()
    store["jobs"].append(job)
    _save_store(store)
    audit("job_start", job_id=job_id, session=shell["session_id"], cwd=cwd, command=command)
    return _public_job(job)


async def list_jobs(include_finished: bool = True) -> dict[str, Any]:
    store = _load_store()
    active = _active_session_ids(await list_shells())
    now = _utc()
    jobs = [_refresh_job_status(job, active, now) for job in store.get("jobs", [])]
    _save_store(store)
    rows = [_public_job(job) for job in jobs if include_finished or job.get("status") not in TERMINAL_STATUSES]
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
    result = {"job": _public_job(job), "output": ""}
    if job.get("status") != "running":
        result["message"] = "job is not running; shell output is no longer available"
        return result
    try:
        tail = await read_shell(str(job["session_id"]), lines)
    except Exception as exc:
        job["status"] = "lost"
        job["updated_at"] = _utc()
        _save_store(store)
        return {"job": _public_job(job), "output": "", "message": str(exc)}
    result["output"] = tail.get("output", "")
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
    shell_name = _shell_safe_name(f"{job.get('name') or job_id}-{job_id}-{attempts}")
    shell = await start_shell(str(job.get("cwd") or "."), shell_name, str(job["command"]))
    now = _utc()
    job.update(
        {
            "status": "running",
            "session_id": shell["session_id"],
            "backend": shell.get("backend"),
            "updated_at": now,
            "last_started_at": now,
            "attempts": attempts,
        }
    )
    _save_store(store)
    audit("job_retry", job_id=job_id, session=shell["session_id"], attempts=attempts)
    return _public_job(job)
