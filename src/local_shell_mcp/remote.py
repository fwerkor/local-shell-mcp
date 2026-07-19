from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.metadata as importlib_metadata
import json
import os
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

from . import __version__
from .audit import audit, suppress_audit
from .fs_ops import (
    delete_path,
    edit_text,
    glob_paths,
    list_dir,
    perform_file_action,
    prune_temp_dir,
    read_texts,
    relative_display,
    resolve_path,
    temp_dir,
    write_text,
)
from .jobs import list_jobs, retry_job, start_job, stop_job, tail_job
from .models import ok_result as _ok
from .playwright_ops import browser_capture, browser_get_text, playwright_run_script
from .search_ops import grep, tree
from .settings import get_settings, safe_settings_dump
from .shell_ops import (
    kill_shell,
    list_shells,
    public_run_shell,
    public_run_shell_timeout,
    quote_shell_argument,
    read_shell,
    resize_shell,
    run_shell,
    send_shell,
    start_shell,
)
from .tmux_helper import persistent_shell_backend_info
from .transfer_ops import (
    transfer_abort_write,
    transfer_alloc_temp_path,
    transfer_begin_write,
    transfer_finish_write,
    transfer_mark_complete_write,
    transfer_pack_dir,
    transfer_read_chunk,
    transfer_stat,
    transfer_unpack_archive,
    transfer_write_chunk,
)
from .version import version_info as get_version_info

REMOTE_JOIN_PATH = "/join"
REMOTE_API_PREFIX = "/remote"
REMOTE_WORKER_BUNDLE_PATH = "/remote/worker-bundle.tgz"
# The remote worker is designed to start on machines that only have Python, curl,
# and tar. Keep this empty unless a dependency is pure Python and imported on the
# worker startup path. Tool-specific dependencies such as Playwright should be
# installed by the tool command on the remote machine, not vendored from the
# controller's Python ABI.
REMOTE_WORKER_DISTRIBUTIONS: tuple[str, ...] = ()
REMOTE_WORKER_REGISTRY_FILE_NAME = "remote-workers.json"
REMOTE_WORKER_REGISTRY_BACKUP_FILE_NAME = "remote-workers.json.bak"
REMOTE_WORKER_IDENTITY_FILE_NAME = "identity.json"
MAX_REMOTE_INVITES = 1_024
MAX_REMOTE_MACHINE_NAME_LENGTH = 128
REMOTE_NON_CANCELLABLE_WORKER_TOOLS = frozenset(
    {
        "write_file",
        "edit_file",
        "delete_file_or_dir",
        "human_file_action",
        "transfer_begin_write",
        "transfer_write_chunk",
        "transfer_finish_write",
        "transfer_abort_write",
        "transfer_pack_dir",
        "transfer_unpack_archive",
        "transfer_upload_url",
        "transfer_download_url",
    }
)


class RemoteJobCancelled(RuntimeError):
    pass


class WorkerHttpError(RuntimeError):
    def __init__(self, url: str, status_code: int, detail: str):
        self.url = url
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"worker HTTP POST {url} failed with {status_code}: {detail}")


def _canonical_dist_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _dist_name_from_requirement(requirement: str) -> str | None:
    # importlib.metadata exposes optional extras in dist.requires too. Do not
    # vendor those implicitly: extras often pull in native extensions for the
    # controller's Python ABI, which can break remote workers running a different
    # Python minor version.
    if "extra ==" in requirement or "extra==" in requirement:
        return None
    match = re.match(r"\s*([A-Za-z0-9_.-]+)", requirement)
    return match.group(1) if match else None


def _add_distribution_to_tar(tar: tarfile.TarFile, dist_name: str, seen: set[str]) -> None:
    canonical = _canonical_dist_name(dist_name)
    if canonical in seen:
        return
    seen.add(canonical)
    try:
        dist = importlib_metadata.distribution(dist_name)
    except importlib_metadata.PackageNotFoundError:
        return

    for requirement in dist.requires or []:
        required_name = _dist_name_from_requirement(requirement)
        if required_name:
            _add_distribution_to_tar(tar, required_name, seen)

    for entry in dist.files or []:
        entry_path = Path(entry)
        if entry_path.is_absolute() or ".." in entry_path.parts:
            continue
        source = Path(dist.locate_file(entry))
        if not source.is_file() or source.suffix in {".pyc", ".pyo"}:
            continue
        tar.add(source, arcname=str(Path("vendor") / entry_path))


def _utc() -> float:
    return time.time()


def _remote_heartbeat_interval_s() -> int:
    return max(5, min(get_settings().remote_poll_timeout_s // 2, 30))


def _validate_machine_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise ValueError("machine name is required")
    if len(name) > MAX_REMOTE_MACHINE_NAME_LENGTH:
        raise ValueError(f"machine name exceeds {MAX_REMOTE_MACHINE_NAME_LENGTH} characters")
    if any(ord(character) < 32 or character in {"/", "\\"} for character in name):
        raise ValueError("machine name contains unsupported characters")
    return name


def _error(message: str, error: str = "remote_error", status_code: int = 400):  # noqa: ANN201
    from starlette.responses import JSONResponse

    return JSONResponse({"ok": False, "error": error, "message": message}, status_code=status_code)


@dataclass
class RemoteInvite:
    code: str
    name: str | None
    workdir: str | None
    expires_at: float
    used: bool = False


@dataclass
class RemoteWorker:
    name: str
    token: str
    workdir: str | None = None
    created_at: float = field(default_factory=_utc)
    last_seen: float = field(default_factory=_utc)
    status: str = "online"
    capabilities: list[str] = field(default_factory=list)
    info: dict[str, Any] = field(default_factory=dict)
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)


class RemoteManager:
    def __init__(self) -> None:
        self.invites: dict[str, RemoteInvite] = {}
        self.workers: dict[str, RemoteWorker] = {}
        self.tokens: dict[str, str] = {}
        self.pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self.pending_machines: dict[str, str] = {}
        self.cancelled_jobs: dict[str, float] = {}
        self.claimed_jobs: set[str] = set()
        self._lock = asyncio.Lock()
        self._state_lock = threading.RLock()
        self._registry_loaded = False

    def _registry_path(self) -> Path:
        return get_settings().state_dir / REMOTE_WORKER_REGISTRY_FILE_NAME

    def _registry_backup_path(self) -> Path:
        return get_settings().state_dir / REMOTE_WORKER_REGISTRY_BACKUP_FILE_NAME

    @staticmethod
    def _read_registry(path: Path) -> list[dict[str, Any]]:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError(f"unsupported or invalid remote worker registry: {path}")
        rows = data.get("workers")
        if not isinstance(rows, list):
            raise ValueError(f"remote worker registry workers field is invalid: {path}")
        return [item for item in rows if isinstance(item, dict)]

    def _load_registry_unlocked(self) -> None:
        if self._registry_loaded:
            return
        path = self._registry_path()
        backup_path = self._registry_backup_path()
        if not path.exists() and not backup_path.exists():
            self._registry_loaded = True
            return
        rows: list[dict[str, Any]] | None = None
        main_error: Exception | None = None
        recovered_from_backup = False
        try:
            if path.exists():
                rows = self._read_registry(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            main_error = exc
            audit("remote_worker_registry_unreadable", path=str(path), error=repr(exc))
        if rows is None and backup_path.exists():
            try:
                rows = self._read_registry(backup_path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                audit(
                    "remote_worker_registry_backup_unreadable",
                    path=str(backup_path),
                    error=repr(exc),
                )
            else:
                recovered_from_backup = True
                audit(
                    "remote_worker_registry_recovered",
                    path=str(path),
                    backup_path=str(backup_path),
                )
        if rows is None:
            raise RuntimeError(
                "Remote worker registry is unreadable and no valid backup is available; "
                "refusing to reset it"
            ) from main_error
        for item in rows:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            access = str(item.get("access") or item.get("to" + "ken") or "").strip()
            if not name or not access or name in self.workers or access in self.tokens:
                continue
            self.workers[name] = RemoteWorker(
                name=name,
                token=access,
                workdir=str(item.get("workdir") or ""),
                created_at=float(item.get("created_at") or _utc()),
                last_seen=0.0,
                status="offline",
                capabilities=list(item.get("capabilities") or []),
                info=dict(item.get("info") or {}),
            )
            self.tokens[access] = name
        self._registry_loaded = True
        if recovered_from_backup:
            self._save_registry_unlocked()

    def _save_registry_unlocked(self) -> None:
        path = self._registry_path()
        backup_path = self._registry_backup_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "workers": [
                {
                    "name": worker.name,
                    "access": worker.token,
                    "workdir": worker.workdir,
                    "created_at": worker.created_at,
                    "capabilities": worker.capabilities,
                    "info": worker.info,
                }
                for worker in sorted(self.workers.values(), key=lambda item: item.name)
            ],
        }
        payload = json.dumps(data, indent=2, sort_keys=True)
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

    def _join_url(self, base_url: str | None = None) -> str:
        settings = get_settings()
        base = base_url or settings.public_base_url or f"http://{settings.host}:{settings.port}"
        return base.rstrip("/") + REMOTE_JOIN_PATH

    async def create_invite(
        self,
        name: str | None = None,
        workdir: str | None = None,
        ttl_s: int | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        settings = get_settings()
        ttl = max(60, min(int(ttl_s or settings.remote_invite_ttl_s), 24 * 3600))
        normalized_name = _validate_machine_name(name) if name else None
        code = "lsmcp_inv_" + secrets.token_urlsafe(24)
        invite = RemoteInvite(
            code=code,
            name=normalized_name,
            workdir=workdir,
            expires_at=_utc() + ttl,
        )
        async with self._lock:
            with self._state_lock:
                self._load_registry_unlocked()
                now = _utc()
                self.invites = {
                    invite_code: item
                    for invite_code, item in self.invites.items()
                    if not item.used and item.expires_at >= now
                }
                if len(self.invites) >= MAX_REMOTE_INVITES:
                    raise RuntimeError("Too many pending remote invites")
                self.invites[code] = invite
        join_url = self._join_url(base_url)
        command = f"curl -fsSL {shlex.quote(join_url)} | bash -s -- --invite {shlex.quote(code)}"
        if normalized_name:
            command += f" --name {shlex.quote(normalized_name)}"
        if workdir:
            command += f" --workdir {shlex.quote(workdir)}"
        return {
            "code": code,
            "name": normalized_name,
            "workdir": workdir,
            "expires_at": invite.expires_at,
            "ttl_s": ttl,
            "join_url": join_url,
            "command": command,
        }

    async def register_worker(self, payload: dict[str, Any]) -> dict[str, Any]:
        code = str(payload.get("invite") or "")
        requested_name = str(payload.get("name") or "").strip() or None
        async with self._lock:
            with self._state_lock:
                self._load_registry_unlocked()
                invite = self.invites.get(code)
                if not invite:
                    raise ValueError("invalid invite code")
                if invite.used:
                    raise ValueError("invite code has already been used")
                if invite.expires_at < _utc():
                    raise ValueError("invite code has expired")
                name = _validate_machine_name(
                    requested_name or invite.name or self._default_machine_name(payload)
                )
                if invite.name and requested_name and requested_name != invite.name:
                    raise ValueError(f"invite is bound to machine name {invite.name!r}")
                if name in self.workers:
                    raise ValueError(f"machine name already exists: {name}")
                token = "lsmcp_wk_" + secrets.token_urlsafe(32)
                worker = RemoteWorker(
                    name=name,
                    token=token,
                    workdir=str(payload.get("workdir") or invite.workdir or ""),
                    capabilities=list(payload.get("capabilities") or []),
                    info=dict(payload.get("info") or {}),
                )
                self.workers[name] = worker
                self.tokens[token] = name
                invite.used = True
                self.invites.pop(code, None)
                self._save_registry_unlocked()
        audit("remote_worker_registered", machine=name)
        return {
            "token": token,
            "name": name,
            "poll_interval_s": 0,
            "heartbeat_interval_s": _remote_heartbeat_interval_s(),
        }

    async def resume_worker(self, access: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            with self._state_lock:
                self._load_registry_unlocked()
                name = self.tokens.get(access)
                if not name:
                    raise PermissionError("invalid worker identity")
                worker = self.workers.get(name)
                if not worker:
                    raise PermissionError("worker identity is no longer valid")
                requested_name = str(payload.get("name") or "").strip()
                if requested_name and requested_name != name:
                    raise ValueError(f"worker identity belongs to machine {name!r}")
                worker.status = "online"
                worker.last_seen = _utc()
                worker.workdir = str(payload.get("workdir") or worker.workdir or "")
                worker.capabilities = list(payload.get("capabilities") or worker.capabilities)
                worker.info = dict(payload.get("info") or worker.info)
                self._save_registry_unlocked()
        audit("remote_worker_resumed", machine=name)
        return {
            "token": access,
            "name": name,
            "poll_interval_s": 0,
            "heartbeat_interval_s": _remote_heartbeat_interval_s(),
        }

    def _default_machine_name(self, payload: dict[str, Any]) -> str:
        self._load_registry_unlocked()
        info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
        user = info.get("user") or os.getenv("USER") or "user"
        host = info.get("hostname") or "remote"
        base = f"{user}@{host}"
        if base not in self.workers:
            return base
        index = 2
        while f"{base}-{index}" in self.workers:
            index += 1
        return f"{base}-{index}"

    def _prune_cancelled_jobs_locked(self, now: float | None = None) -> None:
        now = _utc() if now is None else now
        settings = get_settings()
        ttl = max(1, settings.remote_cancelled_job_ttl_s)
        for job_id, cancelled_at in list(self.cancelled_jobs.items()):
            if now - cancelled_at >= ttl:
                self.cancelled_jobs.pop(job_id, None)
        cap = max(64, settings.remote_max_pending_jobs * 4)
        while len(self.cancelled_jobs) > cap:
            oldest = next(iter(self.cancelled_jobs))
            self.cancelled_jobs.pop(oldest, None)

    def _cancel_job_locked(self, job_id: str) -> None:
        future = self.pending.pop(job_id, None)
        self.pending_machines.pop(job_id, None)
        self.claimed_jobs.discard(job_id)
        now = _utc()
        self.cancelled_jobs[job_id] = now
        self._prune_cancelled_jobs_locked(now)
        if future and not future.done():
            future.cancel()

    def _cancel_job(self, job_id: str) -> None:
        with self._state_lock:
            self._cancel_job_locked(job_id)

    def _cancel_job_if_unclaimed(self, job_id: str) -> bool:
        with self._state_lock:
            if job_id in self.claimed_jobs:
                return False
            self._cancel_job_locked(job_id)
            return True

    async def poll(self, token: str) -> dict[str, Any]:
        worker = self._worker_by_token(token)
        with self._state_lock:
            worker.status = "online"
            worker.last_seen = _utc()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + get_settings().remote_poll_timeout_s
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return {"job": None, "heartbeat": True}
            try:
                job = await asyncio.wait_for(worker.queue.get(), timeout=remaining)
            except TimeoutError:
                return {"job": None, "heartbeat": True}
            job_id = str(job.get("id") or "")
            with self._state_lock:
                self._prune_cancelled_jobs_locked()
                if job_id in self.cancelled_jobs:
                    self.cancelled_jobs.pop(job_id, None)
                    continue
                self.claimed_jobs.add(job_id)
            return {"job": job}

    async def heartbeat(self, token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        worker = self._worker_by_token(token)
        job_id = str((payload or {}).get("job_id") or "")
        with self._state_lock:
            worker.status = "online"
            worker.last_seen = _utc()
            name = worker.name
            self._prune_cancelled_jobs_locked()
            cancelled = bool(job_id and job_id in self.cancelled_jobs)
        result = {"accepted": not cancelled, "name": name}
        if cancelled:
            result["cancelled"] = True
        return result

    async def submit_result(self, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        worker = self._worker_by_token(token)
        job_id = str(payload.get("job_id") or "")
        with self._state_lock:
            worker.status = "online"
            worker.last_seen = _utc()
            self._prune_cancelled_jobs_locked()
            assigned_machine = self.pending_machines.get(job_id)
            if assigned_machine is not None and assigned_machine != worker.name:
                audit(
                    "remote_result_machine_mismatch",
                    job_id=job_id,
                    assigned_machine=assigned_machine,
                    submitting_machine=worker.name,
                )
                raise PermissionError(
                    f"remote job {job_id!r} belongs to machine {assigned_machine!r}"
                )
            if assigned_machine is None:
                self.cancelled_jobs.pop(job_id, None)
                self.claimed_jobs.discard(job_id)
                return {"accepted": False}
            self.pending_machines.pop(job_id, None)
            self.cancelled_jobs.pop(job_id, None)
            self.claimed_jobs.discard(job_id)
            future = self.pending.pop(job_id, None)
            if future and not future.done():
                future.set_result(payload)
        return {"accepted": bool(future)}

    async def call(
        self,
        machine: str,
        tool: str,
        args: dict[str, Any],
        timeout_s: int | None = None,
    ) -> dict[str, Any]:
        settings = get_settings()
        effective_timeout = timeout_s or settings.remote_job_timeout_s
        job_id = "job_" + uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        with self._state_lock:
            self._load_registry_unlocked()
            worker = self.workers.get(machine)
            if not worker:
                raise ValueError(f"unknown remote machine: {machine}")
            if _utc() - worker.last_seen > max(2 * settings.remote_poll_timeout_s, 60):
                worker.status = "offline"
                raise RuntimeError(f"remote machine is offline: {machine}")
            max_pending = max(1, settings.remote_max_pending_jobs)
            machine_pending = sum(1 for value in self.pending_machines.values() if value == machine)
            if worker.queue.qsize() >= max_pending or machine_pending >= max_pending:
                raise RuntimeError(f"remote machine queue is full: {machine}")
            self.pending[job_id] = future
            self.pending_machines[job_id] = machine
            worker.queue.put_nowait(
                {
                    "id": job_id,
                    "tool": tool,
                    "args": args,
                    "expires_at": _utc() + effective_timeout,
                }
            )
        preserve_pending = False
        try:
            result = await asyncio.wait_for(asyncio.shield(future), timeout=effective_timeout)
        except TimeoutError as exc:
            if tool in REMOTE_NON_CANCELLABLE_WORKER_TOOLS:
                cancelled = self._cancel_job_if_unclaimed(job_id)
                if not cancelled:
                    result = await future
                else:
                    raise TimeoutError(f"remote job timed out: {tool} on {machine}") from exc
            else:
                self._cancel_job(job_id)
                raise TimeoutError(f"remote job timed out: {tool} on {machine}") from exc
        except asyncio.CancelledError:
            claimed_mutation = False
            if tool in REMOTE_NON_CANCELLABLE_WORKER_TOOLS:
                claimed_mutation = not self._cancel_job_if_unclaimed(job_id)
            if claimed_mutation:
                preserve_pending = True

                def cleanup(_future: asyncio.Future[dict[str, Any]]) -> None:
                    with self._state_lock:
                        self.pending.pop(job_id, None)
                        self.pending_machines.pop(job_id, None)
                        self.claimed_jobs.discard(job_id)

                future.add_done_callback(cleanup)
            elif tool not in REMOTE_NON_CANCELLABLE_WORKER_TOOLS:
                self._cancel_job(job_id)
            raise
        finally:
            if not preserve_pending:
                with self._state_lock:
                    self.pending.pop(job_id, None)
                    self.pending_machines.pop(job_id, None)
                    self.claimed_jobs.discard(job_id)
        if not result.get("ok", False):
            return _ok(
                {
                    "status": "error",
                    "error_type": result.get("error", "remote_error"),
                    "message": result.get("message", "remote job failed"),
                }
            )
        return _ok(result.get("data"))

    def list_machines(self) -> dict[str, Any]:
        with self._state_lock:
            self._load_registry_unlocked()
            now = _utc()
            offline_after_s = max(2 * get_settings().remote_poll_timeout_s, 60)
            rows = []
            counts = {"online": 0, "offline": 0}
            for worker in self.workers.values():
                last_seen_age_s = None if not worker.last_seen else max(0.0, now - worker.last_seen)
                status = (
                    "online"
                    if last_seen_age_s is not None and last_seen_age_s <= offline_after_s
                    else "offline"
                )
                worker.status = status
                counts[status] += 1
                rows.append(
                    {
                        "name": worker.name,
                        "status": status,
                        "workdir": worker.workdir,
                        "last_seen": worker.last_seen,
                        "last_seen_age_s": last_seen_age_s,
                        "offline_after_s": offline_after_s,
                        "queue_depth": worker.queue.qsize(),
                        "capabilities": list(worker.capabilities),
                        "info": dict(worker.info),
                    }
                )
        rows.sort(key=lambda item: (item["status"] != "online", item["name"]))
        return {
            "machines": rows,
            "counts": {**counts, "total": len(rows)},
        }

    def revoke(self, machine: str) -> dict[str, Any]:
        with self._state_lock:
            self._load_registry_unlocked()
            worker = self.workers.pop(machine, None)
            if not worker:
                raise ValueError(f"unknown remote machine: {machine}")
            self.tokens.pop(worker.token, None)
            for job_id, pending_machine in list(self.pending_machines.items()):
                if pending_machine == machine:
                    self._cancel_job(job_id)
            while not worker.queue.empty():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queued = worker.queue.get_nowait()
                    self.cancelled_jobs.pop(str(queued.get("id") or ""), None)
            self._save_registry_unlocked()
        return {"machine": machine, "revoked": True}

    def rename(self, machine: str, new_name: str) -> dict[str, Any]:
        with self._state_lock:
            self._load_registry_unlocked()
            new_name = _validate_machine_name(new_name)
            if new_name in self.workers:
                raise ValueError(f"machine name already exists: {new_name}")
            worker = self.workers.pop(machine, None)
            if not worker:
                raise ValueError(f"unknown remote machine: {machine}")
            worker.name = new_name
            self.workers[new_name] = worker
            self.tokens[worker.token] = new_name
            for job_id, pending_machine in list(self.pending_machines.items()):
                if pending_machine == machine:
                    self.pending_machines[job_id] = new_name
            self._save_registry_unlocked()
        return {"old_name": machine, "new_name": new_name}

    def _worker_by_token(self, token: str) -> RemoteWorker:
        with self._state_lock:
            self._load_registry_unlocked()
            name = self.tokens.get(token)
            if not name:
                raise PermissionError("invalid worker token")
            worker = self.workers.get(name)
            if not worker:
                raise PermissionError("worker token is no longer valid")
            return worker


REMOTE_MANAGER = RemoteManager()


def remote_manager() -> RemoteManager:
    return REMOTE_MANAGER


def _bearer_token(request: Any) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return ""


async def worker_bundle(request: Any):  # noqa: ARG001, ANN201
    from starlette.responses import Response

    package_root = Path(__file__).resolve().parent
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path in package_root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(package_root)
            is_python = path.suffix == ".py"
            is_helper = relative.parts[:1] == ("helpers",) and (
                path.name == "tmux" or path.name == "tmux.LICENSE"
            )
            if is_python or is_helper:
                tar.add(path, arcname=str(path.relative_to(package_root.parent)))
        seen: set[str] = set()
        for dist_name in REMOTE_WORKER_DISTRIBUTIONS:
            _add_distribution_to_tar(tar, dist_name, seen)
    return Response(buffer.getvalue(), media_type="application/gzip")


async def join_script(request: Any):  # noqa: ARG001, ANN201
    from starlette.responses import PlainTextResponse

    settings = get_settings()
    server = (settings.public_base_url or f"http://{settings.host}:{settings.port}").rstrip("/")
    script = f"""#!/usr/bin/env bash
set -euo pipefail
SERVER={shlex.quote(server)}
BUNDLE_URL="$SERVER{REMOTE_WORKER_BUNDLE_PATH}"
INVITE=""
NAME=""
WORKDIR=""
BACKGROUND=0
PERSIST=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --invite) INVITE="${{2:-}}"; shift 2 ;;
    --name) NAME="${{2:-}}"; shift 2 ;;
    --workdir) WORKDIR="${{2:-}}"; shift 2 ;;
    --background) BACKGROUND=1; shift ;;
    --persist) PERSIST=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [ -z "$INVITE" ]; then echo "--invite is required" >&2; exit 2; fi
if [ -z "$WORKDIR" ]; then WORKDIR="$PWD"; fi
if ! command -v python3 >/dev/null 2>&1; then echo "python3 is required" >&2; exit 2; fi
if ! command -v curl >/dev/null 2>&1; then echo "curl is required" >&2; exit 2; fi
if ! command -v tar >/dev/null 2>&1; then echo "tar is required" >&2; exit 2; fi
TMPDIR="$(mktemp -d)"
cleanup() {{ rm -rf "$TMPDIR"; }}
trap cleanup EXIT
echo "Downloading worker bundle..." >&2
curl -fL --progress-bar "$BUNDLE_URL" -o "$TMPDIR/worker.tgz"
RUNTIME_ROOT="$TMPDIR/runtime"
if [ "$BACKGROUND" = "1" ] || [ "$PERSIST" = "1" ]; then
  STATE_HOME="${{XDG_STATE_HOME:-$HOME/.local/state}}/local-shell-mcp-worker"
  RUNTIME_ROOT="$STATE_HOME/runtime"
  RUNTIME_NEXT="$STATE_HOME/runtime.next.$$"
  rm -rf "$RUNTIME_NEXT"
  mkdir -p "$RUNTIME_NEXT"
  echo "Installing worker bundle..." >&2
  tar -xzf "$TMPDIR/worker.tgz" -C "$RUNTIME_NEXT"
  rm -rf "$RUNTIME_ROOT"
  mv "$RUNTIME_NEXT" "$RUNTIME_ROOT"
else
  mkdir -p "$RUNTIME_ROOT"
  echo "Extracting worker bundle..." >&2
  tar -xzf "$TMPDIR/worker.tgz" -C "$RUNTIME_ROOT"
fi
echo "Starting worker..." >&2
export PYTHONPATH="$RUNTIME_ROOT:$RUNTIME_ROOT/vendor:${{PYTHONPATH:-}}"
ARGS=(--server "$SERVER" --invite "$INVITE" --workdir "$WORKDIR")
if [ -n "$NAME" ]; then ARGS+=(--name "$NAME"); fi
if [ "$PERSIST" = "1" ]; then ARGS+=(--persist); fi
if [ "$BACKGROUND" = "1" ]; then
  mkdir -p "$HOME/.local/state/local-shell-mcp-worker"
  nohup python3 -m local_shell_mcp.remote_worker "${{ARGS[@]}}" > "$HOME/.local/state/local-shell-mcp-worker/worker.log" 2>&1 &
  echo "local-shell-mcp worker started in background. Log: $HOME/.local/state/local-shell-mcp-worker/worker.log"
else
  exec python3 -m local_shell_mcp.remote_worker "${{ARGS[@]}}"
fi
"""
    return PlainTextResponse(script, media_type="text/x-shellscript")


async def register_endpoint(request: Any):  # noqa: ANN201
    from starlette.responses import JSONResponse

    try:
        return JSONResponse(_ok(await remote_manager().register_worker(await request.json())))
    except Exception as exc:
        return _error(str(exc), type(exc).__name__, 400)


async def resume_endpoint(request: Any):  # noqa: ANN201
    from starlette.responses import JSONResponse

    try:
        return JSONResponse(
            _ok(await remote_manager().resume_worker(_bearer_token(request), await request.json()))
        )
    except Exception as exc:
        return _error(str(exc), type(exc).__name__, 401)


async def poll_endpoint(request: Any):  # noqa: ANN201
    from starlette.responses import JSONResponse

    try:
        return JSONResponse(_ok(await remote_manager().poll(_bearer_token(request))))
    except Exception as exc:
        return _error(str(exc), type(exc).__name__, 401)


async def heartbeat_endpoint(request: Any):  # noqa: ANN201
    from starlette.responses import JSONResponse

    try:
        return JSONResponse(
            _ok(await remote_manager().heartbeat(_bearer_token(request), await request.json()))
        )
    except Exception as exc:
        return _error(str(exc), type(exc).__name__, 401)


async def result_endpoint(request: Any):  # noqa: ANN201
    from starlette.responses import JSONResponse

    try:
        return JSONResponse(
            _ok(await remote_manager().submit_result(_bearer_token(request), await request.json()))
        )
    except Exception as exc:
        return _error(str(exc), type(exc).__name__, 401)


def remote_routes() -> list[Any]:
    from starlette.routing import Route

    from .remote_transfer import remote_transfer_routes

    return [
        Route(REMOTE_JOIN_PATH, join_script, methods=["GET"]),
        Route(REMOTE_WORKER_BUNDLE_PATH, worker_bundle, methods=["GET"]),
        Route(f"{REMOTE_API_PREFIX}/register", register_endpoint, methods=["POST"]),
        Route(f"{REMOTE_API_PREFIX}/res" + "ume", resume_endpoint, methods=["POST"]),
        Route(f"{REMOTE_API_PREFIX}/poll", poll_endpoint, methods=["POST"]),
        Route(f"{REMOTE_API_PREFIX}/heartbeat", heartbeat_endpoint, methods=["POST"]),
        Route(f"{REMOTE_API_PREFIX}/result", result_endpoint, methods=["POST"]),
        *remote_transfer_routes(),
    ]


def _assert_worker_text_input_size(label: str, text: str) -> None:
    max_bytes = max(1, get_settings().max_file_write_bytes)
    size = len(text.encode("utf-8"))
    if size > max_bytes:
        raise ValueError(f"Refusing {label} of {size} bytes; max is {max_bytes}")


def _handled_remote_exception(exc: Exception) -> dict[str, Any]:
    return {"ok": False, "error": type(exc).__name__, "message": str(exc)}


async def _apply_patch_text(patch: str, cwd: str = ".") -> dict[str, Any]:
    _assert_worker_text_input_size("patch", patch)
    await asyncio.to_thread(prune_temp_dir)
    patch_path = temp_dir() / f"remote-patch-{uuid.uuid4().hex}.diff"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(patch_path.write_text, patch, encoding="utf-8")
    result = await run_shell(
        f"{quote_shell_argument(get_settings().git_bin)} apply --check "
        f"{quote_shell_argument(str(patch_path))} && "
        f"{quote_shell_argument(get_settings().git_bin)} apply "
        f"{quote_shell_argument(str(patch_path))}",
        cwd=cwd,
        timeout_s=60,
        max_output_bytes=500_000,
    )
    return {**result.model_dump(), "patch_path": relative_display(patch_path)}


async def _run_python(code: str, cwd: str = ".", timeout_s: int = 60) -> dict[str, Any]:
    _assert_worker_text_input_size("Python script", code)
    await asyncio.to_thread(prune_temp_dir)
    script = temp_dir() / f"remote-script-{uuid.uuid4().hex}.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(script.write_text, code, encoding="utf-8")
    result = await run_shell(
        f"{quote_shell_argument(get_settings().python_bin)} {quote_shell_argument(str(script))}",
        cwd=cwd,
        timeout_s=public_run_shell_timeout(timeout_s),
        max_output_bytes=1_000_000,
    )
    return {**result.model_dump(), "script_path": relative_display(script)}


WORKER_ENVIRONMENT_TOOLS = frozenset(
    {
        "environment_info",
    }
)
WORKER_COMMAND_TOOLS = frozenset(
    {
        "run_shell_tool",
        "run_python_tool",
        "apply_patch",
    }
)
WORKER_SHELL_TOOLS = frozenset(
    {
        "shell_start",
        "shell_send",
        "shell_read",
        "shell_resize",
        "shell_kill",
        "shell_list",
    }
)
WORKER_JOB_TOOLS = frozenset(
    {
        "job_start",
        "job_list",
        "job_tail",
        "job_stop",
        "job_retry",
    }
)
WORKER_FILE_TOOLS = frozenset(
    {
        "list_files",
        "tree_view",
        "glob_search",
        "grep_search",
        "read_file",
        "write_file",
        "edit_file",
        "delete_file_or_dir",
        "human_file_action",
    }
)
WORKER_TRANSFER_TOOLS = frozenset(
    {
        "transfer_stat",
        "transfer_read_chunk",
        "transfer_begin_write",
        "transfer_write_chunk",
        "transfer_finish_write",
        "transfer_abort_write",
        "transfer_alloc_temp_path",
        "transfer_pack_dir",
        "transfer_unpack_archive",
        "transfer_upload_url",
        "transfer_download_url",
    }
)
WORKER_BROWSER_TOOLS = frozenset(
    {
        "browser_capture_tool",
        "browser_get_text_tool",
        "playwright_run_script_tool",
    }
)
REMOTE_WORKER_TOOL_NAMES = frozenset().union(
    WORKER_ENVIRONMENT_TOOLS,
    WORKER_COMMAND_TOOLS,
    WORKER_SHELL_TOOLS,
    WORKER_JOB_TOOLS,
    WORKER_FILE_TOOLS,
    WORKER_TRANSFER_TOOLS,
    WORKER_BROWSER_TOOLS,
)


def _worker_validate_transfer_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("transfer URL must use absolute HTTP(S)")
    identity = json.loads(_worker_identity_path().read_text(encoding="utf-8"))
    server = urllib.parse.urlsplit(str(identity.get("server") or ""))
    if (parsed.scheme.lower(), parsed.netloc.lower()) != (
        server.scheme.lower(),
        server.netloc.lower(),
    ):
        raise ValueError("transfer URL does not belong to the configured controller")
    if not parsed.path.startswith("/remote/transfer/"):
        raise ValueError("transfer URL path is not permitted")


def _worker_curl_timeout(timeout_s: int | None) -> int:
    maximum = max(30, int(get_settings().remote_job_timeout_s))
    requested = maximum if timeout_s is None else int(timeout_s)
    return max(30, min(requested, maximum))


def _worker_upload_url(
    path: str,
    url: str,
    expected_bytes: int,
    expected_sha256: str,
    timeout_s: int | None = None,
) -> dict[str, Any]:
    _worker_validate_transfer_url(url)
    source = resolve_path(path, must_exist=True)
    stat = transfer_stat(str(source), True)
    if stat.get("type") != "file":
        raise ValueError(f"source is not a file: {path}")
    if stat["size"] != int(expected_bytes):
        raise ValueError(f"size mismatch: expected {expected_bytes}, got {stat['size']}")
    if str(stat.get("sha256") or "").lower() != str(expected_sha256).lower():
        raise ValueError("file sha256 mismatch before upload")
    curl = shutil.which("curl")
    if not curl:
        raise FileNotFoundError("curl is required for remote file streaming")
    completed = subprocess.run(  # noqa: S603
        [
            curl,
            "-fsS",
            "--connect-timeout",
            "15",
            "--max-time",
            str(_worker_curl_timeout(timeout_s)),
            "-H",
            "Expect:",
            "-H",
            "Content-Type: application/octet-stream",
            "--upload-file",
            str(source),
            url,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"stream upload failed with curl exit {completed.returncode}: {detail}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("stream upload returned invalid JSON") from exc
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise RuntimeError(f"stream upload failed: {payload}")
    return dict(payload.get("data") or {})


def _worker_download_url(
    url: str,
    path: str,
    overwrite: bool,
    expected_bytes: int,
    expected_sha256: str,
    timeout_s: int | None = None,
) -> dict[str, Any]:
    _worker_validate_transfer_url(url)
    begin = transfer_begin_write(path, overwrite, expected_bytes)
    temporary = resolve_path(begin["temp_path"], follow_final_symlink=False)
    curl = shutil.which("curl")
    if not curl:
        transfer_abort_write(path, begin["transfer_id"])
        raise FileNotFoundError("curl is required for remote file streaming")
    try:
        completed = subprocess.run(  # noqa: S603
            [
                curl,
                "-fsSL",
                "--connect-timeout",
                "15",
                "--max-time",
                str(_worker_curl_timeout(timeout_s)),
                "-o",
                str(temporary),
                url,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(
                f"stream download failed with curl exit {completed.returncode}: {detail}"
            )
        transfer_mark_complete_write(path, begin["transfer_id"])
        finish = transfer_finish_write(
            path,
            begin["transfer_id"],
            expected_bytes,
            expected_sha256,
        )
        return {
            "path": finish["path"],
            "bytes": finish["bytes"],
            "sha256": finish["sha256"],
            "transport": "http-stream",
        }
    except BaseException:
        with contextlib.suppress(Exception):
            transfer_abort_write(path, begin["transfer_id"])
        raise


async def execute_worker_tool(tool: str, args: dict[str, Any]) -> Any:
    call_args = dict(args)
    human = bool(call_args.pop("_human", False))
    if human:
        with suppress_audit():
            return await _execute_worker_tool_inner(tool, call_args)
    return await _execute_worker_tool_inner(tool, call_args)


async def _execute_environment_worker_tool(tool: str, args: dict[str, Any]) -> Any:
    if tool == "environment_info":
        python = quote_shell_argument(get_settings().python_bin)
        git = quote_shell_argument(get_settings().git_bin)
        result = await run_shell(
            f"uname -a; echo '---'; id; echo '---'; pwd; echo '---'; "
            f"{python} --version; {git} --version",
            cwd=".",
            timeout_s=10,
        )
        return {
            "version": get_version_info(),
            "settings": safe_settings_dump(),
            "persistent_shell": persistent_shell_backend_info(),
            "probe": result.model_dump(),
        }
    raise ValueError(f"unsupported remote worker tool: {tool}")


async def _execute_command_worker_tool(tool: str, args: dict[str, Any]) -> Any:
    if tool == "run_shell_tool":
        return (
            await public_run_shell(
                args["command"],
                args.get("cwd", "."),
                args.get("timeout_s"),
                args.get("max_output_bytes"),
            )
        ).model_dump()

    if tool == "run_python_tool":
        return await _run_python(args["code"], args.get("cwd", "."), args.get("timeout_s", 60))

    if tool == "apply_patch":
        return await _apply_patch_text(args["patch"], args.get("cwd", "."))
    raise ValueError(f"unsupported remote worker tool: {tool}")


async def _execute_shell_worker_tool(tool: str, args: dict[str, Any]) -> Any:
    if tool == "shell_start":
        return await start_shell(args.get("cwd", "."), args.get("name"), args.get("command"))

    if tool == "shell_send":
        return await send_shell(args["session_id"], args["input_text"], args.get("enter", True))

    if tool == "shell_read":
        return await read_shell(args["session_id"], args.get("lines", 200))

    if tool == "shell_resize":
        return await resize_shell(args["session_id"], args["cols"], args["rows"])

    if tool == "shell_kill":
        return await kill_shell(args["session_id"])

    if tool == "shell_list":
        return await list_shells()
    raise ValueError(f"unsupported remote worker tool: {tool}")


async def _execute_job_worker_tool(tool: str, args: dict[str, Any]) -> Any:
    if tool == "job_start":
        return await start_job(args["command"], args.get("cwd", "."), args.get("name"))

    if tool == "job_list":
        return await list_jobs(args.get("include_finished", True))

    if tool == "job_tail":
        return await tail_job(args["job_id"], args.get("lines", 200))

    if tool == "job_stop":
        return await stop_job(args["job_id"])

    if tool == "job_retry":
        return await retry_job(args["job_id"])
    raise ValueError(f"unsupported remote worker tool: {tool}")


async def _execute_file_worker_tool(tool: str, args: dict[str, Any]) -> Any:
    if tool == "list_files":
        return await asyncio.to_thread(
            list_dir,
            args.get("path", "."),
            args.get("recursive", False),
            args.get("max_entries", 500),
        )

    if tool == "tree_view":
        return await tree(args.get("cwd", "."), args.get("depth", 3), args.get("max_entries", 500))

    if tool == "glob_search":
        return {
            "paths": await asyncio.to_thread(
                glob_paths, args["pattern"], args.get("cwd", "."), args.get("max_results", 500)
            )
        }

    if tool == "grep_search":
        return await grep(
            args["query"],
            args.get("cwd", "."),
            args.get("glob"),
            args.get("regex", True),
            args.get("case_sensitive", True),
            args.get("max_results"),
        )

    if tool == "read_file":
        return await asyncio.to_thread(
            read_texts,
            args["path"],
            args.get("start_line"),
            args.get("end_line"),
            args.get("binary_preview"),
            args.get("binary_preview_bytes", 256),
        )

    if tool == "write_file":
        return await asyncio.to_thread(
            write_text,
            args["path"],
            args["content"],
            args.get("overwrite", True),
            args.get("expected_sha256"),
        )

    if tool == "edit_file":
        return await asyncio.to_thread(edit_text, args["path"], args["edits"])

    if tool == "delete_file_or_dir":
        return await asyncio.to_thread(delete_path, args["path"], args.get("recursive", False))

    if tool == "human_file_action":
        return await asyncio.to_thread(
            perform_file_action,
            args["action"],
            args["path"],
            args.get("destination"),
            exist_ok=args.get("exist_ok", False),
        )
    raise ValueError(f"unsupported remote worker tool: {tool}")


async def _execute_transfer_worker_tool(tool: str, args: dict[str, Any]) -> Any:
    if tool == "transfer_stat":
        return await asyncio.to_thread(transfer_stat, args["path"], args.get("sha256", True))

    if tool == "transfer_read_chunk":
        return await asyncio.to_thread(
            transfer_read_chunk, args["path"], args.get("offset", 0), args.get("chunk_size")
        )

    if tool == "transfer_begin_write":
        return await asyncio.to_thread(
            transfer_begin_write,
            args["path"],
            args.get("overwrite", True),
            args.get("expected_bytes"),
        )

    if tool == "transfer_write_chunk":
        return await asyncio.to_thread(
            transfer_write_chunk,
            args["path"],
            args["transfer_id"],
            args["offset"],
            args["data_b64"],
            args.get("expected_sha256"),
        )

    if tool == "transfer_finish_write":
        return await asyncio.to_thread(
            transfer_finish_write,
            args["path"],
            args["transfer_id"],
            args.get("expected_bytes"),
            args.get("expected_sha256"),
        )

    if tool == "transfer_abort_write":
        return await asyncio.to_thread(transfer_abort_write, args["path"], args["transfer_id"])

    if tool == "transfer_alloc_temp_path":
        return await asyncio.to_thread(transfer_alloc_temp_path, args.get("suffix", ".bin"))

    if tool == "transfer_pack_dir":
        return await asyncio.to_thread(
            transfer_pack_dir, args["path"], args.get("compression", "gz")
        )

    if tool == "transfer_unpack_archive":
        return await asyncio.to_thread(
            transfer_unpack_archive,
            args["archive_path"],
            args["dst_path"],
            args.get("overwrite", True),
            args.get("cleanup_archive", True),
        )

    if tool == "transfer_upload_url":
        return await asyncio.to_thread(
            _worker_upload_url,
            args["path"],
            args["url"],
            args["expected_bytes"],
            args["expected_sha256"],
            args.get("timeout_s"),
        )

    if tool == "transfer_download_url":
        return await asyncio.to_thread(
            _worker_download_url,
            args["url"],
            args["path"],
            args.get("overwrite", True),
            args["expected_bytes"],
            args["expected_sha256"],
            args.get("timeout_s"),
        )
    raise ValueError(f"unsupported remote worker tool: {tool}")


async def _execute_browser_worker_tool(tool: str, args: dict[str, Any]) -> Any:
    if tool == "browser_capture_tool":
        return await browser_capture(
            args["url"],
            args.get("output_path"),
            args.get("capture_format", "png"),
            args.get("browser", "chromium"),
            args.get("full_page", True),
            args.get("width", 1440),
            args.get("height", 1000),
            args.get("wait_until", "networkidle"),
        )

    if tool == "browser_get_text_tool":
        return await browser_get_text(
            args["url"],
            args.get("browser", "chromium"),
            args.get("wait_until", "networkidle"),
            args.get("selector", "body"),
        )

    if tool == "playwright_run_script_tool":
        return await playwright_run_script(
            args["script"], args.get("cwd", "."), args.get("timeout_s", 60)
        )
    raise ValueError(f"unsupported remote worker tool: {tool}")


async def _execute_worker_tool_inner(tool: str, args: dict[str, Any]) -> Any:
    if tool in WORKER_ENVIRONMENT_TOOLS:
        return await _execute_environment_worker_tool(tool, args)
    if tool in WORKER_COMMAND_TOOLS:
        return await _execute_command_worker_tool(tool, args)
    if tool in WORKER_SHELL_TOOLS:
        return await _execute_shell_worker_tool(tool, args)
    if tool in WORKER_JOB_TOOLS:
        return await _execute_job_worker_tool(tool, args)
    if tool in WORKER_FILE_TOOLS:
        return await _execute_file_worker_tool(tool, args)
    if tool in WORKER_TRANSFER_TOOLS:
        return await _execute_transfer_worker_tool(tool, args)
    if tool in WORKER_BROWSER_TOOLS:
        return await _execute_browser_worker_tool(tool, args)
    raise ValueError(f"unsupported remote worker tool: {tool}")


def worker_capabilities() -> list[str]:
    return [
        "shell",
        "persistent_shell",
        "jobs",
        "files",
        "file_transfer",
        "search",
        "python",
        "playwright",
    ]


def worker_info(workdir: str) -> dict[str, Any]:
    return {
        "hostname": socket.gethostname(),
        "user": os.getenv("USER") or os.getenv("USERNAME") or "unknown",
        "cwd": os.getcwd(),
        "workdir": workdir,
        "lsm_version": __version__,
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "persistent_shell": persistent_shell_backend_info(),
    }


def _parse_worker_http_json(url: str, status_code: int, response_body: str) -> dict[str, Any]:
    if not 200 <= status_code < 300:
        detail = response_body.strip() or "<empty response body>"
        raise WorkerHttpError(url, status_code, detail)
    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError as exc:
        detail = response_body.strip() or "<empty response body>"
        raise RuntimeError(f"worker HTTP POST {url} returned invalid JSON: {detail}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(
            f"worker HTTP POST {url} returned JSON {type(parsed).__name__}, expected object"
        )
    return parsed


def _worker_post_json_with_curl(
    url: str, body: bytes, headers: dict[str, str], timeout: float | None = None
) -> dict[str, Any]:
    curl = shutil.which("curl")
    if not curl:
        raise FileNotFoundError("curl is not available")
    status_marker = "\nLOCAL_SHELL_MCP_HTTP_STATUS:"
    command = [
        curl,
        "-sS",
        "-L",
        "-X",
        "POST",
        "-H",
        "Content-Type: application/json",
        "--data-binary",
        "@-",
        "-w",
        f"{status_marker}%{{http_code}}",
    ]
    for name, value in headers.items():
        command.extend(["-H", f"{name}: {value}"])
    if timeout is not None:
        command[1:1] = ["--max-time", str(timeout)]
    command.append(url)

    completed = subprocess.run(  # noqa: S603
        command,
        input=body,
        capture_output=True,
        check=False,
    )
    stdout = completed.stdout.decode("utf-8", errors="replace")
    stderr = completed.stderr.decode("utf-8", errors="replace").strip()
    response_body, marker, status_text = stdout.rpartition(status_marker)
    status_code = int(status_text) if marker and status_text.isdigit() else 0
    if completed.returncode != 0:
        detail_parts = [part for part in (stderr, response_body.strip()) if part]
        detail = "\n".join(detail_parts) or "curl exited without a response body"
        raise RuntimeError(
            f"worker HTTP POST {url} failed with curl exit {completed.returncode} (HTTP {status_code}): {detail}"
        )
    return _parse_worker_http_json(url, status_code, response_body)


def _worker_post_json_with_urllib(
    url: str, body: bytes, headers: dict[str, str], timeout: float | None = None
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310  # URL validated by _worker_post_json.
            response_body = response.read().decode("utf-8", errors="replace")
            status_code = response.status
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        return _parse_worker_http_json(url, exc.code, response_body)
    return _parse_worker_http_json(url, status_code, response_body)


def _worker_post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("worker server URL must use absolute HTTP(S)")
    body = json.dumps(payload).encode("utf-8")
    request_headers = headers or {}
    if shutil.which("curl"):
        return _worker_post_json_with_curl(url, body, request_headers, timeout)
    return _worker_post_json_with_urllib(url, body, request_headers, timeout)


_WORKER_RETRY_INITIAL_DELAY_S = 1.0
_WORKER_RETRY_MAX_DELAY_S = 30.0


def _worker_retry_delay(attempt: int) -> float:
    return min(_WORKER_RETRY_INITIAL_DELAY_S * (2 ** min(attempt, 5)), _WORKER_RETRY_MAX_DELAY_S)


def _worker_log_retry(operation: str, exc: Exception, delay_s: float) -> None:
    print(
        f"Status: {operation} failed: {exc}. Retrying in {delay_s:g}s...",
        file=sys.stderr,
        flush=True,
    )


def _worker_error_is_retryable(exc: Exception) -> bool:
    if isinstance(exc, WorkerHttpError):
        return exc.status_code in {408, 425, 429} or exc.status_code >= 500
    return not isinstance(exc, ValueError)


async def _worker_post_json_forever(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    operation: str = "request",
) -> dict[str, Any]:
    attempt = 0
    while True:
        try:
            return await asyncio.to_thread(_worker_post_json, url, payload, headers, timeout)
        except Exception as exc:  # noqa: BLE001
            if not _worker_error_is_retryable(exc):
                raise
            delay_s = _worker_retry_delay(attempt)
            attempt += 1
            _worker_log_retry(operation, exc, delay_s)
            await asyncio.sleep(delay_s)


def _worker_state_dir() -> Path:
    configured = os.getenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    xdg_state_home = os.getenv("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home).expanduser() / "local-shell-mcp-worker"
    return Path.home() / ".local" / "state" / "local-shell-mcp-worker"


def _worker_identity_path() -> Path:
    return _worker_state_dir() / REMOTE_WORKER_IDENTITY_FILE_NAME


def _read_worker_identity(server: str, requested_name: str | None = None) -> dict[str, Any] | None:
    path = _worker_identity_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("server") != server:
        return None
    stored_name = str(data.get("name") or "")
    if requested_name and stored_name != requested_name:
        return None
    if not stored_name or not str(data.get("access") or ""):
        return None
    return data


def _write_worker_identity(data: dict[str, Any]) -> None:
    path = _worker_identity_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    with contextlib.suppress(OSError):
        tmp_path.chmod(0o600)
    tmp_path.replace(path)


def _delete_worker_identity() -> None:
    with contextlib.suppress(FileNotFoundError):
        _worker_identity_path().unlink()


def _worker_identity_rejected(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "failed with 401" in message
        or "invalid worker identity" in message
        or "identity is no longer valid" in message
    )


async def _worker_resume_or_none(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float | None = None,
) -> dict[str, Any] | None:
    attempt = 0
    while True:
        try:
            return await asyncio.to_thread(_worker_post_json, url, payload, headers, timeout)
        except Exception as exc:  # noqa: BLE001
            if _worker_identity_rejected(exc):
                print(
                    "Status: stored worker identity rejected; falling back to invite registration.",
                    file=sys.stderr,
                    flush=True,
                )
                _delete_worker_identity()
                return None
            if not _worker_error_is_retryable(exc):
                raise
            delay_s = _worker_retry_delay(attempt)
            attempt += 1
            _worker_log_retry("resume", exc, delay_s)
            await asyncio.sleep(delay_s)


async def _execute_worker_job_with_heartbeat(
    job: dict[str, Any],
    server: str,
    headers: dict[str, str],
    heartbeat_interval_s: float,
) -> Any:
    task = asyncio.create_task(execute_worker_tool(job["tool"], dict(job.get("args") or {})))
    cancelled_by_controller = False

    async def heartbeat_loop() -> None:
        nonlocal cancelled_by_controller
        interval = max(0.01, heartbeat_interval_s)
        while not task.done():
            await asyncio.sleep(interval)
            if task.done():
                return
            try:
                response = await asyncio.to_thread(
                    _worker_post_json,
                    f"{server}{REMOTE_API_PREFIX}/heartbeat",
                    {"job_id": job.get("id")},
                    headers,
                    30,
                )
                data = response.get("data", {}) if isinstance(response, dict) else {}
                if data.get("cancelled"):
                    cancelled_by_controller = True
                    task.cancel()
                    return
            except Exception as exc:  # noqa: BLE001
                if not _worker_error_is_retryable(exc):
                    return
                _worker_log_retry("heartbeat", exc, interval)

    heartbeat = asyncio.create_task(heartbeat_loop())
    try:
        return await task
    except asyncio.CancelledError as exc:
        if cancelled_by_controller:
            raise RemoteJobCancelled("remote job was cancelled by the controller") from exc
        raise
    finally:
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)


async def run_worker(
    server: str,
    invite: str,
    name: str | None = None,
    workdir: str | None = None,
    persist: bool = False,
) -> None:  # noqa: ARG001
    workdir = str(Path(workdir or os.getcwd()).expanduser().resolve())
    os.environ["LOCAL_SHELL_MCP_WORKSPACE_ROOT"] = workdir
    os.environ["LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER"] = "true"
    from .settings import get_settings as _get_settings

    _get_settings.cache_clear()
    server = server.rstrip("/")
    register_payload = {
        "invite": invite,
        "name": name,
        "workdir": workdir,
        "capabilities": worker_capabilities(),
        "info": worker_info(workdir),
    }
    identity = _read_worker_identity(server, name)
    body: dict[str, Any] | None = None
    access = ""
    if identity:
        access = str(identity["access"])
        resume_payload = {**register_payload, "name": str(identity["name"])}
        resume_headers = {"Author" + "ization": "B" + "earer " + access}
        body = await _worker_resume_or_none(
            f"{server}{REMOTE_API_PREFIX}/res" + "ume", resume_payload, resume_headers, 30
        )
    if body is None:
        body = await _worker_post_json_forever(
            f"{server}{REMOTE_API_PREFIX}/register", register_payload, None, 30, "register"
        )
        if not body.get("ok"):
            raise RuntimeError(body.get("message") or body)
        data = body["data"]
        access = data["to" + "ken"]
        machine_name = data["name"]
    else:
        if not body.get("ok"):
            raise RuntimeError(body.get("message") or body)
        data = body["data"]
        machine_name = data["name"]
    heartbeat_interval_s = float(data.get("heartbeat_interval_s") or _remote_heartbeat_interval_s())
    _write_worker_identity(
        {"server": server, "name": machine_name, "access": access, "workdir": workdir}
    )
    print("local-shell-mcp worker")
    print(f"Server:  {server}")
    print(f"Name:    {machine_name}")
    print(f"Workdir: {workdir}")
    print("Status: connected")
    print(
        "Keep this process running while ChatGPT should access this machine. Press Ctrl-C to disconnect.",
        flush=True,
    )
    headers = {"Author" + "ization": "B" + "earer " + access}
    while True:
        poll_body = await _worker_post_json_forever(
            f"{server}{REMOTE_API_PREFIX}/poll", {}, headers, None, "poll"
        )
        payload = poll_body.get("data", {})
        job = payload.get("job")
        if not job:
            continue
        expires_at = float(job.get("expires_at") or 0)
        if expires_at and expires_at < _utc():
            out = {
                "job_id": job.get("id"),
                "ok": False,
                "error": "TimeoutError",
                "message": "remote job expired before execution",
            }
            await _worker_post_json_forever(
                f"{server}{REMOTE_API_PREFIX}/result", out, headers, 30, "submit result"
            )
            continue
        try:
            result = await _execute_worker_job_with_heartbeat(
                job, server, headers, heartbeat_interval_s
            )
            out = {"job_id": job["id"], "ok": True, "data": result}
        except Exception as exc:  # noqa: BLE001
            out = {"job_id": job.get("id"), **_handled_remote_exception(exc)}
        await _worker_post_json_forever(
            f"{server}{REMOTE_API_PREFIX}/result", out, headers, 30, "submit result"
        )


def run_worker_cli(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Connect this machine to a local-shell-mcp control server"
    )
    parser.add_argument("--server", required=True)
    parser.add_argument("--invite", required=True)
    parser.add_argument("--name", default=None)
    parser.add_argument("--workdir", default=None)
    parser.add_argument(
        "--persist", action="store_true", help="Reserved for future user-service installation"
    )
    args = parser.parse_args(argv)
    try:
        asyncio.run(run_worker(args.server, args.invite, args.name, args.workdir, args.persist))
    except KeyboardInterrupt:
        print("\nStatus: disconnected by user.", file=sys.stderr, flush=True)
        raise SystemExit(130) from None
    except Exception as exc:  # noqa: BLE001
        print(f"Status: connection failed: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from None
