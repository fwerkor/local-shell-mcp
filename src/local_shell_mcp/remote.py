from __future__ import annotations

import argparse
import asyncio
import importlib.metadata as importlib_metadata
import os
import re
import secrets
import shlex
import socket
import sys
import tarfile
import time
import uuid
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

from .audit import audit
from .fs_ops import (
    delete_path,
    edit_text,
    glob_paths,
    list_dir,
    multi_edit_text,
    prune_temp_dir,
    read_text,
    relative_display,
    temp_dir,
    write_text,
)
from .git_ops import (
    git_add,
    git_checkout,
    git_clone,
    git_commit,
    git_diff,
    git_fetch,
    git_log,
    git_pull,
    git_push,
    git_reset,
    git_show,
    git_status,
)
from .search_ops import grep, tree
from .settings import get_settings, safe_settings_dump
from .shell_ops import (
    kill_shell,
    list_shells,
    public_run_shell,
    public_run_shell_timeout,
    read_shell,
    run_shell,
    send_shell,
    start_shell,
)

REMOTE_JOIN_PATH = "/join"
REMOTE_API_PREFIX = "/remote"
REMOTE_WORKER_BUNDLE_PATH = "/remote/worker-bundle.tgz"
REMOTE_WORKER_DISTRIBUTIONS = (
    "mcp",
    "fastapi",
    "uvicorn",
    "pydantic",
    "pydantic-settings",
    "PyYAML",
    "Py" + "JWT",
    "httpx",
    "aiofiles",
    "python-multipart",
    "pathspec",
)


def _canonical_dist_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _dist_name_from_requirement(requirement: str) -> str | None:
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


def _ok(data: Any = None, message: str = "") -> dict[str, Any]:
    return {"ok": True, "message": message, "data": data}


def _error(message: str, error: str = "remote_error", status_code: int = 400) -> JSONResponse:
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
        self._lock = asyncio.Lock()

    def _join_url(self) -> str:
        settings = get_settings()
        base = settings.public_base_url or f"http://{settings.host}:{settings.port}"
        return base.rstrip("/") + REMOTE_JOIN_PATH

    async def create_invite(
        self, name: str | None = None, workdir: str | None = None, ttl_s: int | None = None
    ) -> dict[str, Any]:
        settings = get_settings()
        ttl = max(60, min(ttl_s or settings.remote_invite_ttl_s, 24 * 3600))
        code = "lsmcp_inv_" + secrets.token_urlsafe(24)
        invite = RemoteInvite(code=code, name=name, workdir=workdir, expires_at=_utc() + ttl)
        async with self._lock:
            self.invites[code] = invite
        command = (
            f"curl -fsSL {shlex.quote(self._join_url())} | bash -s -- --invite {shlex.quote(code)}"
        )
        if name:
            command += f" --name {shlex.quote(name)}"
        if workdir:
            command += f" --workdir {shlex.quote(workdir)}"
        return {
            "code": code,
            "name": name,
            "workdir": workdir,
            "expires_at": invite.expires_at,
            "ttl_s": ttl,
            "join_url": self._join_url(),
            "command": command,
        }

    async def register_worker(self, payload: dict[str, Any]) -> dict[str, Any]:
        code = str(payload.get("invite") or "")
        requested_name = str(payload.get("name") or "").strip() or None
        async with self._lock:
            invite = self.invites.get(code)
            if not invite:
                raise ValueError("invalid invite code")
            if invite.used:
                raise ValueError("invite code has already been used")
            if invite.expires_at < _utc():
                raise ValueError("invite code has expired")
            name = requested_name or invite.name or self._default_machine_name(payload)
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
        audit("remote_worker_registered", machine=name)
        return {"token": token, "name": name, "poll_interval_s": 0}

    def _default_machine_name(self, payload: dict[str, Any]) -> str:
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

    async def poll(self, token: str) -> dict[str, Any]:
        worker = self._worker_by_token(token)
        worker.status = "online"
        worker.last_seen = _utc()
        try:
            job = await asyncio.wait_for(
                worker.queue.get(), timeout=get_settings().remote_poll_timeout_s
            )
            return {"job": job}
        except TimeoutError:
            return {"job": None, "heartbeat": True}

    async def submit_result(self, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        worker = self._worker_by_token(token)
        worker.status = "online"
        worker.last_seen = _utc()
        job_id = str(payload.get("job_id") or "")
        future = self.pending.pop(job_id, None)
        if future and not future.done():
            future.set_result(payload)
        return {"accepted": bool(future)}

    async def call(
        self, machine: str, tool: str, args: dict[str, Any], timeout_s: int | None = None
    ) -> dict[str, Any]:
        worker = self.workers.get(machine)
        if not worker:
            raise ValueError(f"unknown remote machine: {machine}")
        if _utc() - worker.last_seen > max(2 * get_settings().remote_poll_timeout_s, 60):
            worker.status = "offline"
            raise RuntimeError(f"remote machine is offline: {machine}")
        job_id = "job_" + uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self.pending[job_id] = future
        await worker.queue.put({"id": job_id, "tool": tool, "args": args})
        try:
            result = await asyncio.wait_for(
                future, timeout=timeout_s or get_settings().remote_job_timeout_s
            )
        except TimeoutError as exc:
            self.pending.pop(job_id, None)
            raise TimeoutError(f"remote job timed out: {tool} on {machine}") from exc
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
        now = _utc()
        rows = []
        for worker in self.workers.values():
            status = (
                "online"
                if now - worker.last_seen <= max(2 * get_settings().remote_poll_timeout_s, 60)
                else "offline"
            )
            worker.status = status
            rows.append(
                {
                    "name": worker.name,
                    "status": status,
                    "workdir": worker.workdir,
                    "last_seen": worker.last_seen,
                    "capabilities": worker.capabilities,
                    "info": worker.info,
                }
            )
        return {"machines": sorted(rows, key=lambda item: item["name"])}

    def revoke(self, machine: str) -> dict[str, Any]:
        worker = self.workers.pop(machine, None)
        if not worker:
            raise ValueError(f"unknown remote machine: {machine}")
        self.tokens.pop(worker.token, None)
        return {"machine": machine, "revoked": True}

    def rename(self, machine: str, new_name: str) -> dict[str, Any]:
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("new_name is required")
        if new_name in self.workers:
            raise ValueError(f"machine name already exists: {new_name}")
        worker = self.workers.pop(machine, None)
        if not worker:
            raise ValueError(f"unknown remote machine: {machine}")
        worker.name = new_name
        self.workers[new_name] = worker
        self.tokens[worker.token] = new_name
        return {"old_name": machine, "new_name": new_name}

    def _worker_by_token(self, token: str) -> RemoteWorker:
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


def _bearer_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return ""


async def worker_bundle(request: Request) -> Response:  # noqa: ARG001
    package_root = Path(__file__).resolve().parent
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path in package_root.rglob("*.py"):
            tar.add(path, arcname=str(path.relative_to(package_root.parent)))
        seen: set[str] = set()
        for dist_name in REMOTE_WORKER_DISTRIBUTIONS:
            _add_distribution_to_tar(tar, dist_name, seen)
    return Response(buffer.getvalue(), media_type="application/gzip")


async def join_script(request: Request) -> PlainTextResponse:  # noqa: ARG001
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
curl -fsSL "$BUNDLE_URL" -o "$TMPDIR/worker.tgz"
tar -xzf "$TMPDIR/worker.tgz" -C "$TMPDIR"
export PYTHONPATH="$TMPDIR:${{PYTHONPATH:-}}"
ARGS=(--server "$SERVER" --invite "$INVITE" --workdir "$WORKDIR")
if [ -n "$NAME" ]; then ARGS+=(--name "$NAME"); fi
if [ "$PERSIST" = "1" ]; then ARGS+=(--persist); fi
if [ "$BACKGROUND" = "1" ]; then
  mkdir -p "$HOME/.local/state/local-shell-mcp-worker"
  nohup python3 -m local_shell_mcp.main worker "${{ARGS[@]}}" > "$HOME/.local/state/local-shell-mcp-worker/worker.log" 2>&1 &
  echo "local-shell-mcp worker started in background. Log: $HOME/.local/state/local-shell-mcp-worker/worker.log"
else
  exec python3 -m local_shell_mcp.main worker "${{ARGS[@]}}"
fi
"""
    return PlainTextResponse(script, media_type="text/x-shellscript")


async def register_endpoint(request: Request) -> JSONResponse:
    try:
        return JSONResponse(_ok(await remote_manager().register_worker(await request.json())))
    except Exception as exc:
        return _error(str(exc), type(exc).__name__, 400)


async def poll_endpoint(request: Request) -> JSONResponse:
    try:
        return JSONResponse(_ok(await remote_manager().poll(_bearer_token(request))))
    except Exception as exc:
        return _error(str(exc), type(exc).__name__, 401)


async def result_endpoint(request: Request) -> JSONResponse:
    try:
        return JSONResponse(
            _ok(await remote_manager().submit_result(_bearer_token(request), await request.json()))
        )
    except Exception as exc:
        return _error(str(exc), type(exc).__name__, 401)


def remote_routes() -> list[Route]:
    return [
        Route(REMOTE_JOIN_PATH, join_script, methods=["GET"]),
        Route(REMOTE_WORKER_BUNDLE_PATH, worker_bundle, methods=["GET"]),
        Route(f"{REMOTE_API_PREFIX}/register", register_endpoint, methods=["POST"]),
        Route(f"{REMOTE_API_PREFIX}/poll", poll_endpoint, methods=["POST"]),
        Route(f"{REMOTE_API_PREFIX}/result", result_endpoint, methods=["POST"]),
    ]


async def _to_thread(func, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
    return await asyncio.to_thread(func, *args, **kwargs)


def _handled_remote_exception(exc: Exception) -> dict[str, Any]:
    return {"ok": False, "error": type(exc).__name__, "message": str(exc)}


def _read_many_files_sync(
    paths: list[str],
    start_line: int | None = None,
    end_line: int | None = None,
    binary_preview: str | None = None,
    binary_preview_bytes: int = 256,
) -> dict[str, Any]:
    files = [
        read_text(path, start_line, end_line, binary_preview, binary_preview_bytes)
        for path in paths
    ]
    return {
        "files": files,
        "total_content_bytes": sum(
            len(str(item.get("content") or item.get("preview") or "").encode()) for item in files
        ),
    }


async def _apply_patch_text(patch: str, cwd: str = ".") -> dict[str, Any]:
    await _to_thread(prune_temp_dir)
    patch_path = temp_dir() / f"remote-patch-{uuid.uuid4().hex}.diff"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    await _to_thread(patch_path.write_text, patch, encoding="utf-8")
    result = await run_shell(
        f"git apply --check {shlex.quote(str(patch_path))} && git apply {shlex.quote(str(patch_path))}",
        cwd=cwd,
        timeout_s=60,
        max_output_bytes=500_000,
    )
    return {**result.model_dump(), "patch_path": relative_display(patch_path)}


async def _run_python(code: str, cwd: str = ".", timeout_s: int = 60) -> dict[str, Any]:
    await _to_thread(prune_temp_dir)
    script = temp_dir() / f"remote-script-{uuid.uuid4().hex}.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    await _to_thread(script.write_text, code, encoding="utf-8")
    result = await run_shell(
        f"python3 {shlex.quote(str(script))}",
        cwd=cwd,
        timeout_s=public_run_shell_timeout(timeout_s),
        max_output_bytes=1_000_000,
    )
    return {**result.model_dump(), "script_path": relative_display(script)}


async def execute_worker_tool(tool: str, args: dict[str, Any]) -> Any:
    if tool == "environment_info":
        result = await run_shell(
            "uname -a; echo '---'; id; echo '---'; pwd; echo '---'; python3 --version; git --version",
            cwd=".",
            timeout_s=10,
        )
        return {"settings": safe_settings_dump(), "probe": result.model_dump()}
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
    if tool == "shell_start":
        return await start_shell(args.get("cwd", "."), args.get("name"), args.get("command"))
    if tool == "shell_send":
        return await send_shell(args["session_id"], args["input_text"], args.get("enter", True))
    if tool == "shell_read":
        return await read_shell(args["session_id"], args.get("lines", 200))
    if tool == "shell_kill":
        return await kill_shell(args["session_id"])
    if tool == "shell_list":
        return await list_shells()
    if tool == "list_files":
        return await _to_thread(
            list_dir,
            args.get("path", "."),
            args.get("recursive", False),
            args.get("max_entries", 500),
        )
    if tool == "tree_view":
        return await tree(args.get("cwd", "."), args.get("depth", 3), args.get("max_entries", 500))
    if tool == "glob_search":
        return {
            "paths": await _to_thread(
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
        return await _to_thread(
            read_text,
            args["path"],
            args.get("start_line"),
            args.get("end_line"),
            args.get("binary_preview"),
            args.get("binary_preview_bytes", 256),
        )
    if tool == "read_many_files":
        return await _to_thread(
            _read_many_files_sync,
            args["paths"],
            args.get("start_line"),
            args.get("end_line"),
            args.get("binary_preview"),
            args.get("binary_preview_bytes", 256),
        )
    if tool == "write_file":
        return await _to_thread(
            write_text, args["path"], args["content"], args.get("overwrite", True)
        )
    if tool == "edit_file":
        return await _to_thread(
            edit_text, args["path"], args["old"], args["new"], args.get("replace_all", False)
        )
    if tool == "multi_edit_file":
        return await _to_thread(multi_edit_text, args["path"], args["edits"])
    if tool == "delete_file_or_dir":
        return await _to_thread(delete_path, args["path"], args.get("recursive", False))
    if tool == "apply_patch":
        return await _apply_patch_text(args["patch"], args.get("cwd", "."))
    if tool == "git_clone_tool":
        return await git_clone(
            args["repo_url"], args.get("dest"), args.get("branch"), args.get("cwd", ".")
        )
    if tool == "git_status_tool":
        return await git_status(args.get("cwd", "."))
    if tool == "git_diff_tool":
        return await git_diff(
            args.get("cwd", "."),
            args.get("staged", False),
            args.get("path"),
            args.get("stat", False),
        )
    if tool == "git_log_tool":
        return await git_log(args.get("cwd", "."), args.get("max_count", 20))
    if tool == "git_checkout_tool":
        return await git_checkout(args["cwd"], args["ref"], args.get("create", False))
    if tool == "git_fetch_tool":
        return await git_fetch(
            args.get("cwd", "."), args.get("remote", "origin"), args.get("prune", True)
        )
    if tool == "git_pull_tool":
        return await git_pull(args.get("cwd", "."), args.get("ff_only", True))
    if tool == "git_add_tool":
        return await git_add(args.get("cwd", "."), args.get("paths"))
    if tool == "git_commit_tool":
        return await git_commit(args["cwd"], args["message"], args.get("all_changes", False))
    if tool == "git_push_tool":
        return await git_push(
            args["cwd"],
            args.get("remote", "origin"),
            args.get("branch"),
            args.get("set_upstream", True),
        )
    if tool == "git_show_tool":
        return await git_show(args.get("cwd", "."), args.get("ref", "HEAD"), args.get("path"))
    if tool == "git_reset_tool":
        return await git_reset(
            args.get("cwd", "."), args.get("mode", "soft"), args.get("ref", "HEAD")
        )
    raise ValueError(f"unsupported remote worker tool: {tool}")


def worker_capabilities() -> list[str]:
    return ["shell", "persistent_shell", "files", "search", "git", "python"]


def worker_info(workdir: str) -> dict[str, Any]:
    return {
        "hostname": socket.gethostname(),
        "user": os.getenv("USER") or os.getenv("USERNAME") or "unknown",
        "cwd": os.getcwd(),
        "workdir": workdir,
        "python": sys.version.split()[0],
        "platform": sys.platform,
    }


async def run_worker(
    server: str,
    invite: str,
    name: str | None = None,
    workdir: str | None = None,
    persist: bool = False,
) -> None:  # noqa: ARG001
    workdir = str(Path(workdir or os.getcwd()).expanduser().resolve())
    os.environ.setdefault("LOCAL_SHELL_MCP_WORKSPACE_ROOT", workdir)
    os.environ.setdefault("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER", "true")
    from .settings import get_settings as _get_settings

    _get_settings.cache_clear()
    server = server.rstrip("/")
    async with httpx.AsyncClient(timeout=None) as client:
        register_payload = {
            "invite": invite,
            "name": name,
            "workdir": workdir,
            "capabilities": worker_capabilities(),
            "info": worker_info(workdir),
        }
        response = await client.post(
            f"{server}{REMOTE_API_PREFIX}/register", json=register_payload, timeout=30
        )
        response.raise_for_status()
        body = response.json()
        if not body.get("ok"):
            raise RuntimeError(body.get("message") or body)
        data = body["data"]
        token = data["token"]
        machine_name = data["name"]
        print("local-shell-mcp worker")
        print(f"Server:  {server}")
        print(f"Name:    {machine_name}")
        print(f"Workdir: {workdir}")
        print("Status: connected")
        print(
            "Keep this process running while ChatGPT should access this machine. Press Ctrl-C to disconnect.",
            flush=True,
        )
        headers = {"Authorization": f"Bearer {token}"}
        while True:
            poll = await client.post(
                f"{server}{REMOTE_API_PREFIX}/poll", headers=headers, json={}, timeout=None
            )
            poll.raise_for_status()
            payload = poll.json().get("data", {})
            job = payload.get("job")
            if not job:
                continue
            try:
                result = await execute_worker_tool(job["tool"], dict(job.get("args") or {}))
                out = {"job_id": job["id"], "ok": True, "data": result}
            except Exception as exc:  # noqa: BLE001
                out = {"job_id": job.get("id"), **_handled_remote_exception(exc)}
            await client.post(
                f"{server}{REMOTE_API_PREFIX}/result", headers=headers, json=out, timeout=30
            )


def add_worker_cli_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--server", required=True)
    parser.add_argument("--invite", required=True)
    parser.add_argument("--name", default=None)
    parser.add_argument("--workdir", default=None)
    parser.add_argument(
        "--persist", action="store_true", help="Reserved for future user-service installation"
    )


def run_worker_from_args(args: argparse.Namespace) -> None:
    asyncio.run(run_worker(args.server, args.invite, args.name, args.workdir, args.persist))


def run_worker_cli(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Connect this machine to a local-shell-mcp control server"
    )
    add_worker_cli_args(parser)
    args = parser.parse_args(argv)
    run_worker_from_args(args)
