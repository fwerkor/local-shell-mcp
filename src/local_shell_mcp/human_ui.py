from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import select
import shlex
import shutil
import signal
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from .audit import query_audit, suppress_audit
from .auth import Principal, require_scopes, verify_request
from .fs_ops import (
    FileConflictError,
    delete_path,
    list_dir,
    perform_file_action,
    read_text,
    resolve_path,
    write_text,
)
from .remote import remote_manager
from .settings import get_settings
from .shell_ops import kill_shell, list_shells, read_shell, send_shell, start_shell
from .todo_ops import TodoConflictError, todo_read, todo_write
from .ui_security import UI_LOCAL_TOKEN_ENV, get_or_create_ui_local_token
from .version import version_info

UI_API_PREFIX = "/api/ui"
UI_SUBPROTOCOL = "lsm-ui"
UI_FULL_SCOPES = (
    "shell:read",
    "shell:write",
    "shell:execute",
    "git:write",
    "browser:use",
    "file:share",
    "remote:use",
)
UI_MIN_COLUMNS = 20
UI_MAX_COLUMNS = 500
UI_MIN_ROWS = 8
UI_MAX_ROWS = 200
_ACTIVE_UI_TERMINALS: set[int] = set()
_LOGGER = logging.getLogger(__name__)


def _json_ok(data: Any = None, message: str = "") -> JSONResponse:
    return JSONResponse({"ok": True, "message": message, "data": data})


def _json_error(exc: Exception, status_code: int = 400) -> JSONResponse:
    headers = None
    message = str(exc)
    if isinstance(exc, HTTPException):
        status_code = exc.status_code
        message = str(exc.detail)
        headers = exc.headers
    return JSONResponse(
        {
            "ok": False,
            "error": type(exc).__name__,
            "message": message,
        },
        status_code=status_code,
        headers=headers,
    )


def _request_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    return principal if isinstance(principal, Principal) else verify_request(request)


def _require_ui_scopes(
    request: Request, *scopes: str, machine: str | None = None
) -> None:
    required = list(scopes)
    if machine and machine != "local":
        required.append("remote:use")
    require_scopes(_request_principal(request), required)


def _bounded_int(
    raw: str | int | None,
    *,
    default: int,
    minimum: int,
    maximum: int,
    label: str,
) -> int:
    if raw in {None, ""}:
        value = default
    else:
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be an integer") from exc
    return max(minimum, min(value, maximum))


def _assets_dir() -> Path:
    return Path(__file__).resolve().parent / "ui_static"


def _ui_index_html() -> str:
    settings = get_settings()
    ui_path = "/" + settings.ui_path.strip("/")
    path = _assets_dir() / "index.html"
    if path.exists():
        html = path.read_text(encoding="utf-8")
        config = json.dumps({"uiPath": ui_path, "apiPrefix": UI_API_PREFIX})
        return html.replace("__LSM_UI_PATH__", ui_path).replace(
            "__LSM_UI_CONFIG_JSON__", config
        )
    return """<!doctype html><html><head><meta charset=\"utf-8\"><title>local-shell-mcp UI</title></head>
<body style=\"background:#050812;color:#dbeafe;font:16px system-ui;padding:48px\">
<h1>local-shell-mcp UI assets are not built</h1><p>Build them with <code>cd ui &amp;&amp; bun run build</code>.</p></body></html>"""


async def ui_index(request: Request) -> Response:  # noqa: ARG001
    return HTMLResponse(_ui_index_html(), headers={"Cache-Control": "no-store"})


async def ui_asset(request: Request) -> Response:
    raw = request.path_params.get("path", "")
    relative = PurePosixPath(str(raw))
    if relative.is_absolute() or ".." in relative.parts:
        return Response("Not found", status_code=404)
    assets_dir = _assets_dir().resolve()
    try:
        path = assets_dir.joinpath(*relative.parts).resolve(strict=True)
        path.relative_to(assets_dir)
    except (OSError, ValueError):
        return Response("Not found", status_code=404)
    if not path.is_file():
        return Response("Not found", status_code=404)
    cache = "public, max-age=31536000, immutable" if "." in path.stem else "public, max-age=3600"
    return FileResponse(path, headers={"Cache-Control": cache})


async def ui_wallpaper(request: Request) -> Response:  # noqa: ARG001
    settings = get_settings()
    if settings.ui_wallpaper != "bing":
        return Response(status_code=204)

    cache_dir = settings.state_dir / "ui"
    cache_dir.mkdir(parents=True, exist_ok=True)
    image_path = cache_dir / "wallpaper.jpg"
    stamp_path = cache_dir / "wallpaper-date.txt"
    today = time.strftime("%Y-%m-%d", time.gmtime())
    attempted_today = False
    if stamp_path.is_file():
        with contextlib.suppress(OSError):
            attempted_today = stamp_path.read_text(encoding="utf-8").strip() == today
    if attempted_today:
        if image_path.is_file():
            return FileResponse(
                image_path,
                media_type="image/jpeg",
                headers={"Cache-Control": "public, max-age=3600"},
            )
        return Response(status_code=204)

    stamp_path.write_text(today, encoding="utf-8")
    try:
        import httpx

        async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
            archive = await client.get(
                "https://www.bing.com/HPImageArchive.aspx",
                params={"format": "js", "idx": 0, "n": 1, "mkt": "en-US"},
            )
            archive.raise_for_status()
            images = archive.json().get("images") or []
            if not images:
                raise RuntimeError("Bing returned no wallpaper")
            image_url = str(images[0].get("url") or "")
            if not image_url.startswith("/"):
                raise RuntimeError("Bing returned an invalid wallpaper URL")
            image = await client.get("https://www.bing.com" + image_url)
            image.raise_for_status()
            if len(image.content) > 20_000_000:
                raise RuntimeError("Bing wallpaper exceeds 20 MB")
            image_path.write_bytes(image.content)
            stamp_path.write_text(today, encoding="utf-8")
    except Exception:
        if not image_path.is_file():
            return Response(status_code=204)

    return FileResponse(image_path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})


def _machine_rows() -> dict[str, Any]:
    remote = remote_manager().list_machines()
    rows = [
        {
            "name": "local",
            "status": "online",
            "workdir": str(get_settings().workspace_root),
            "last_seen": time.time(),
            "last_seen_age_s": 0,
            "capabilities": ["files", "terminals"],
            "info": {"platform": sys.platform, "local": True},
        },
        *remote.get("machines", []),
    ]
    counts = dict(remote.get("counts") or {})
    counts["online"] = int(counts.get("online", 0)) + 1
    counts["total"] = int(counts.get("total", 0)) + 1
    return {"machines": rows, "counts": counts}


async def _remote_call(machine: str, tool: str, args: dict[str, Any]) -> Any:
    result = await remote_manager().call(
        machine,
        tool,
        {**args, "_human": True},
        timeout_s=max(1, get_settings().ui_remote_request_timeout_s),
    )
    if not result.get("ok", False):
        raise RuntimeError(result.get("message") or f"Remote operation failed: {tool}")
    data = result.get("data")
    if isinstance(data, dict) and data.get("status") == "error":
        raise RuntimeError(str(data.get("message") or data.get("error_type") or "Remote operation failed"))
    return data


async def _machine_dispatch(
    machine: str,
    local_call: Callable[[], Any | Awaitable[Any]],
    remote_tool: str,
    remote_args: dict[str, Any],
) -> Any:
    if machine == "local":
        with suppress_audit():
            result = await asyncio.to_thread(local_call)
            if asyncio.iscoroutine(result):
                return await result
            return result
    return await _remote_call(machine, remote_tool, remote_args)


def _path_name(path: str) -> str:
    cleaned = path.rstrip("/\\")
    if not cleaned or cleaned == ".":
        return "."
    return Path(cleaned).name or cleaned


def _parent_path(path: str) -> str:
    if path in {"", ".", "/"}:
        return "." if path != "/" else "/"
    parent = str(Path(path).parent)
    return parent or "."


def _normalize_file_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in entries:
        path = str(item.get("path") or "")
        rows.append(
            {
                **item,
                "path": path,
                "name": _path_name(path),
                "hidden": _path_name(path).startswith("."),
            }
        )
    rows.sort(key=lambda item: (item.get("type") != "dir", str(item.get("name") or "").casefold()))
    return rows


async def api_bootstrap(request: Request) -> Response:
    settings = get_settings()
    required = ["shell:read"]
    if settings.remote_enabled:
        required.append("remote:use")
    _require_ui_scopes(request, *required)
    machines, todos = await asyncio.gather(
        asyncio.to_thread(_machine_rows),
        asyncio.to_thread(todo_read),
    )
    return _json_ok(
        {
            "version": version_info(),
            "machines": machines,
            "todos": todos,
            "features": {
                "remote": settings.remote_enabled,
                "wallpaper": settings.ui_wallpaper,
                "yazi_available": shutil.which("yazi") is not None,
            },
        }
    )


async def api_machines(request: Request) -> Response:
    required = ["shell:read"]
    if get_settings().remote_enabled:
        required.append("remote:use")
    _require_ui_scopes(request, *required)
    return _json_ok(await asyncio.to_thread(_machine_rows))


async def api_files(request: Request) -> Response:
    machine = request.query_params.get("machine", "local")
    path = request.query_params.get("path", ".")
    try:
        _require_ui_scopes(request, "shell:read", machine=machine)
        entries = await _machine_dispatch(
            machine,
            lambda: list_dir(path, False, 1_000),
            "list_files",
            {"path": path, "recursive": False, "max_entries": 1_000},
        )
        parent = _parent_path(path)
        parent_entries: list[dict[str, Any]] = []
        if parent != path:
            with contextlib.suppress(Exception):
                parent_entries = await _machine_dispatch(
                    machine,
                    lambda: list_dir(parent, False, 1_000),
                    "list_files",
                    {"path": parent, "recursive": False, "max_entries": 1_000},
                )
        return _json_ok(
            {
                "machine": machine,
                "path": path,
                "parent": parent,
                "entries": _normalize_file_entries(list(entries or [])),
                "parent_entries": _normalize_file_entries(list(parent_entries or [])),
            }
        )
    except Exception as exc:
        return _json_error(exc)


async def api_file_preview(request: Request) -> Response:
    machine = request.query_params.get("machine", "local")
    path = request.query_params.get("path", ".")
    try:
        _require_ui_scopes(request, "shell:read", machine=machine)
        if machine == "local":
            resolved = await asyncio.to_thread(resolve_path, path, must_exist=True)
            if await asyncio.to_thread(resolved.is_dir):
                return _json_ok(
                    {
                        "kind": "directory",
                        "entries": _normalize_file_entries(list_dir(path, False, 100)),
                    }
                )
        else:
            with contextlib.suppress(Exception):
                listed = await _remote_call(
                    machine,
                    "list_files",
                    {"path": path, "recursive": False, "max_entries": 100},
                )
                if isinstance(listed, list):
                    return _json_ok(
                        {"kind": "directory", "entries": _normalize_file_entries(listed)}
                    )

        content = await _machine_dispatch(
            machine,
            lambda: read_text(path, 1, 240, "hex", 256),
            "read_file",
            {"path": path, "start_line": 1, "end_line": 240, "binary_preview": "hex", "binary_preview_bytes": 256},
        )
        if not isinstance(content, dict):
            content = {"content": str(content)}
        kind = "binary" if "preview" in content and not content.get("content") else "text"
        return _json_ok({"kind": kind, **content})
    except (NotADirectoryError, IsADirectoryError):
        try:
            entries = await _machine_dispatch(
                machine,
                lambda: list_dir(path, False, 100),
                "list_files",
                {"path": path, "recursive": False, "max_entries": 100},
            )
            return _json_ok({"kind": "directory", "entries": _normalize_file_entries(list(entries or []))})
        except Exception as exc:
            return _json_error(exc)
    except Exception as exc:
        return _json_error(exc)


async def api_file_content(request: Request) -> Response:
    machine = request.query_params.get("machine", "local")
    path = request.query_params.get("path", "")
    try:
        _require_ui_scopes(request, "shell:read", machine=machine)
        if not path:
            raise ValueError("path is required")
        content = await _machine_dispatch(
            machine,
            lambda: read_text(path),
            "read_file",
            {"path": path},
        )
        if not isinstance(content, dict):
            raise TypeError("File read returned an invalid payload")
        if content.get("binary"):
            raise ValueError("Binary files cannot be edited in the built-in editor")
        if content.get("truncated"):
            raise ValueError(
                "File exceeds the configured editor read limit; use a terminal or external editor"
            )
        return _json_ok({"kind": "text", **content})
    except Exception as exc:
        return _json_error(exc)


async def api_file_action(request: Request) -> Response:
    action = str(request.path_params.get("action") or "")
    try:
        body = await request.json()
        machine = str(body.get("machine") or "local")
        _require_ui_scopes(request, "shell:read", "shell:write", machine=machine)
        path = str(body.get("path") or "")
        if not path:
            raise ValueError("path is required")

        if action == "delete":
            result = await _machine_dispatch(
                machine,
                lambda: delete_path(path, bool(body.get("recursive", False))),
                "delete_file_or_dir",
                {"path": path, "recursive": bool(body.get("recursive", False))},
            )
            return _json_ok(result)
        if action == "write":
            expected_sha256 = str(body.get("expected_sha256") or "") or None
            result = await _machine_dispatch(
                machine,
                lambda: write_text(
                    path,
                    str(body.get("content") or ""),
                    bool(body.get("overwrite", True)),
                    expected_sha256,
                ),
                "write_file",
                {
                    "path": path,
                    "content": str(body.get("content") or ""),
                    "overwrite": bool(body.get("overwrite", True)),
                    "expected_sha256": expected_sha256,
                },
            )
            return _json_ok(result)
        if action not in {"mkdir", "touch", "rename", "copy", "move"}:
            raise ValueError(f"Unsupported file action: {action}")

        args = {
            "action": action,
            "path": path,
            "destination": str(body.get("destination") or "") or None,
            "exist_ok": bool(body.get("exist_ok", False)),
        }
        result = await _machine_dispatch(
            machine,
            lambda: perform_file_action(**args),
            "human_file_action",
            args,
        )
        return _json_ok(result)
    except FileConflictError as exc:
        return _json_error(exc, status_code=409)
    except Exception as exc:
        return _json_error(exc)


async def api_terminals(request: Request) -> Response:
    machine = request.query_params.get("machine", "local")
    try:
        _require_ui_scopes(request, "shell:read", machine=machine)
        result = await _machine_dispatch(machine, list_shells, "shell_list", {})
        return _json_ok({"machine": machine, **(result or {"sessions": []})})
    except Exception as exc:
        return _json_error(exc)


async def api_terminal_read(request: Request) -> Response:
    machine = request.query_params.get("machine", "local")
    session_id = request.query_params.get("session_id", "")
    try:
        _require_ui_scopes(request, "shell:read", machine=machine)
        lines = _bounded_int(
            request.query_params.get("lines"),
            default=500,
            minimum=1,
            maximum=5_000,
            label="lines",
        )
        if not session_id:
            raise ValueError("session_id is required")
        result = await _machine_dispatch(
            machine,
            lambda: read_shell(session_id, lines),
            "shell_read",
            {"session_id": session_id, "lines": lines},
        )
        return _json_ok(result)
    except Exception as exc:
        return _json_error(exc)


async def api_terminal_action(request: Request) -> Response:
    action = str(request.path_params.get("action") or "")
    try:
        body = await request.json()
        machine = str(body.get("machine") or "local")
        _require_ui_scopes(request, "shell:read", "shell:execute", machine=machine)
        if action == "start":
            args = {
                "cwd": str(body.get("cwd") or "."),
                "name": body.get("name"),
                "command": body.get("command"),
            }
            result = await _machine_dispatch(
                machine,
                lambda: start_shell(args["cwd"], args["name"], args["command"]),
                "shell_start",
                args,
            )
        elif action == "send":
            args = {
                "session_id": str(body.get("session_id") or ""),
                "input_text": str(body.get("input_text") or ""),
                "enter": bool(body.get("enter", True)),
            }
            if not args["session_id"]:
                raise ValueError("session_id is required")
            result = await _machine_dispatch(
                machine,
                lambda: send_shell(args["session_id"], args["input_text"], args["enter"]),
                "shell_send",
                args,
            )
        elif action == "kill":
            session_id = str(body.get("session_id") or "")
            if not session_id:
                raise ValueError("session_id is required")
            result = await _machine_dispatch(
                machine,
                lambda: kill_shell(session_id),
                "shell_kill",
                {"session_id": session_id},
            )
        else:
            raise ValueError(f"Unsupported terminal action: {action}")
        return _json_ok(result)
    except Exception as exc:
        return _json_error(exc)


async def api_todos(request: Request) -> Response:
    try:
        if request.method == "GET":
            _require_ui_scopes(request, "shell:read")
            return _json_ok(await asyncio.to_thread(todo_read))
        _require_ui_scopes(request, "shell:read", "shell:write")
        body = await request.json()
        expected_revision = body.get("expected_revision")
        with suppress_audit():
            result = await asyncio.to_thread(
                todo_write,
                list(body.get("todos") or []),
                int(expected_revision) if expected_revision is not None else None,
            )
        return _json_ok(result)
    except TodoConflictError as exc:
        return _json_error(exc, status_code=409)
    except Exception as exc:
        return _json_error(exc)


async def api_audit(request: Request) -> Response:
    params = request.query_params
    try:
        _require_ui_scopes(request, "shell:read")
        result = await asyncio.to_thread(
            query_audit,
            limit=int(params.get("limit", "300")),
            node=params.get("node"),
            event=params.get("event"),
            operation=params.get("operation"),
            session=params.get("session"),
            search=params.get("search"),
            start_ts=float(params["start_ts"]) if "start_ts" in params else None,
            end_ts=float(params["end_ts"]) if "end_ts" in params else None,
            sort=params.get("sort", "desc"),
        )
        return _json_ok(result)
    except Exception as exc:
        return _json_error(exc)


async def api_remotes(request: Request) -> Response:
    try:
        _require_ui_scopes(request, "remote:use")
        if not get_settings().remote_enabled:
            if request.method == "GET":
                return _json_ok(
                    {
                        "machines": [],
                        "counts": {"online": 0, "offline": 0, "total": 0},
                        "enabled": False,
                    }
                )
            raise RuntimeError("Remote worker support is disabled")
        if request.method == "GET":
            return _json_ok(remote_manager().list_machines())
        body = await request.json()
        from .oauth import public_base_url

        result = await remote_manager().create_invite(
            body.get("name"),
            body.get("workdir"),
            body.get("ttl_s"),
            base_url=public_base_url(request),
        )
        return _json_ok(result)
    except Exception as exc:
        return _json_error(exc)


async def api_remote_action(request: Request) -> Response:
    action = str(request.path_params.get("action") or "")
    try:
        _require_ui_scopes(request, "remote:use")
        if not get_settings().remote_enabled:
            raise RuntimeError("Remote worker support is disabled")
        body = await request.json()
        machine = str(body.get("machine") or "")
        if not machine:
            raise ValueError("machine is required")
        if action == "rename":
            result = remote_manager().rename(machine, str(body.get("new_name") or ""))
        elif action == "revoke":
            result = remote_manager().revoke(machine)
        else:
            raise ValueError(f"Unsupported remote action: {action}")
        return _json_ok(result)
    except Exception as exc:
        return _json_error(exc)


def _websocket_token(websocket: WebSocket) -> str | None:
    protocols = [item.strip() for item in websocket.headers.get("sec-websocket-protocol", "").split(",")]
    for protocol in protocols:
        if not protocol.startswith("bearer."):
            continue
        encoded = protocol.removeprefix("bearer.")
        padding = "=" * (-len(encoded) % 4)
        try:
            return base64.urlsafe_b64decode(encoded + padding).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None
    return None


def _authorize_websocket(websocket: WebSocket) -> bool:
    settings = get_settings()
    if settings.auth_mode == "none":
        return True
    token = _websocket_token(websocket)
    if not token:
        return False
    try:
        from .oauth import validate_bearer_token

        claims = validate_bearer_token(token, websocket)  # type: ignore[arg-type]
        require_scopes(
            Principal(email=None, subject=claims.get("sub"), claims=claims),
            UI_FULL_SCOPES,
        )
    except Exception:
        return False
    return True


def _tui_source_path() -> Path | None:
    candidates = [
        Path(__file__).resolve().parents[2] / "ui" / "src" / "tui.tsx",
        Path.cwd() / "ui" / "src" / "tui.tsx",
        Path("/app/ui/src/tui.tsx"),
    ]
    return next((path for path in candidates if path.is_file()), None)


def _split_tui_command(value: str, *, windows: bool | None = None) -> list[str]:
    windows = os.name == "nt" if windows is None else windows
    parts = shlex.split(value, posix=not windows)
    if windows:
        parts = [
            part[1:-1] if len(part) >= 2 and part[0] == part[-1] and part[0] in {'"', "'"} else part
            for part in parts
        ]
    if not parts:
        raise ValueError("ui_tui_command is empty")
    return parts


def resolve_tui_command() -> list[str]:
    settings = get_settings()
    if settings.ui_tui_command:
        return _split_tui_command(settings.ui_tui_command)

    executable_dir = Path(sys.executable).resolve().parent
    repository_root = Path(__file__).resolve().parents[2]
    sidecar_name = "local-shell-mcp-tui.exe" if os.name == "nt" else "local-shell-mcp-tui"
    sidecar_candidates = [
        executable_dir / sidecar_name,
        Path(sys.argv[0]).resolve().parent / sidecar_name,
        repository_root / "ui" / "dist" / sidecar_name,
        Path.cwd() / "ui" / "dist" / sidecar_name,
        Path("/app/ui/dist") / sidecar_name,
    ]
    for candidate in sidecar_candidates:
        if candidate.is_file():
            return [str(candidate)]

    source = _tui_source_path()
    bun = shutil.which("bun")
    if source and bun:
        return [bun, str(source)]
    if source:
        raise RuntimeError("The OpenTUI source is installed, but Bun is not available in PATH")
    raise RuntimeError(
        "OpenTUI runtime not found; install a release bundle or run `cd ui && bun run compile:tui`"
    )


class _UnixPtyProcess:
    def __init__(self, command: list[str], env: dict[str, str], cols: int, rows: int):
        import fcntl
        import pty
        import struct
        import termios

        self._fcntl = fcntl
        self._struct = struct
        self._termios = termios
        self.master_fd, slave_fd = pty.openpty()
        self.resize(cols, rows)
        self.process = __import__("subprocess").Popen(
            command,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            close_fds=True,
            start_new_session=True,
        )
        os.close(slave_fd)
        os.set_blocking(self.master_fd, False)

    def resize(self, cols: int, rows: int) -> None:
        winsize = self._struct.pack("HHHH", max(1, rows), max(1, cols), 0, 0)
        self._fcntl.ioctl(self.master_fd, self._termios.TIOCSWINSZ, winsize)
        process = getattr(self, "process", None)
        if process is not None and process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGWINCH)

    async def read(self) -> bytes:
        while True:
            try:
                return os.read(self.master_fd, 65_536)
            except BlockingIOError:
                await asyncio.sleep(0.01)
            except OSError:
                return b""

    def _write_all(self, data: bytes) -> None:
        remaining = memoryview(data)
        while remaining:
            try:
                written = os.write(self.master_fd, remaining)
            except BlockingIOError:
                select.select([], [self.master_fd], [], 0.1)
                continue
            if written <= 0:
                raise OSError("PTY write made no progress")
            remaining = remaining[written:]

    async def write(self, data: bytes) -> None:
        if data:
            await asyncio.to_thread(self._write_all, data)

    async def close(self) -> None:
        with contextlib.suppress(OSError):
            os.close(self.master_fd)
        if self.process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGTERM)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(asyncio.to_thread(self.process.wait), timeout=2)
        if self.process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGKILL)


class _WindowsPtyProcess:
    def __init__(self, command: list[str], env: dict[str, str], cols: int, rows: int):
        try:
            from winpty import PtyProcess
        except ImportError as exc:  # pragma: no cover - Windows-only dependency.
            raise RuntimeError("pywinpty is required for the WebUI on Windows") from exc
        try:
            self.process = PtyProcess.spawn(
                command,
                dimensions=(max(1, rows), max(1, cols)),
                env=env,
            )
        except TypeError:
            import subprocess

            self.process = PtyProcess.spawn(
                subprocess.list2cmdline(command),
                dimensions=(max(1, rows), max(1, cols)),
                env=env,
            )

    def resize(self, cols: int, rows: int) -> None:
        self.process.setwinsize(max(1, rows), max(1, cols))

    async def read(self) -> bytes:
        def read_chunk():  # noqa: ANN202
            try:
                return self.process.read(65_536)
            except TypeError:
                return self.process.read()

        try:
            data = await asyncio.to_thread(read_chunk)
        except Exception:
            return b""
        return data.encode("utf-8", errors="replace") if isinstance(data, str) else bytes(data)

    def _write_all(self, text: str) -> None:
        remaining = text
        while remaining:
            written = self.process.write(remaining)
            if written is None:
                return
            if not isinstance(written, int) or written <= 0:
                raise OSError("ConPTY write made no progress")
            remaining = remaining[written:]

    async def write(self, data: bytes) -> None:
        if data:
            text = data.decode("utf-8", errors="replace")
            await asyncio.to_thread(self._write_all, text)

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await asyncio.to_thread(self.process.terminate, True)


def _spawn_tui_process(cols: int, rows: int):  # noqa: ANN201
    settings = get_settings()
    env = os.environ.copy()
    env.update(
        {
            "TERM": env.get("TERM", "xterm-256color"),
            "COLORTERM": "truecolor",
            "LOCAL_SHELL_MCP_UI_API_BASE": f"http://127.0.0.1:{settings.port}{UI_API_PREFIX}",
            "LOCAL_SHELL_MCP_UI_MODE": "web",
            UI_LOCAL_TOKEN_ENV: get_or_create_ui_local_token(),
        }
    )
    command = resolve_tui_command()
    if os.name == "nt":
        return _WindowsPtyProcess(command, env, cols, rows)
    return _UnixPtyProcess(command, env, cols, rows)


def _validate_tui_api_base(value: str) -> str:
    normalized = str(value).rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "127.0.0.1",
        "::1",
        "localhost",
    }:
        raise ValueError("Native TUI --api-base must use a loopback HTTP(S) URL")
    return normalized


def run_tui_cli(argv: list[str] | None = None) -> None:
    import argparse
    import subprocess

    settings = get_settings()
    parser = argparse.ArgumentParser(
        prog="local-shell-mcp tui",
        description="Launch the local-shell-mcp OpenTUI against a running service.",
    )
    parser.add_argument(
        "--api-base",
        default=f"http://127.0.0.1:{settings.port}{UI_API_PREFIX}",
        help="Human UI API base URL (local loopback requires no authentication)",
    )
    args = parser.parse_args(argv)
    env = os.environ.copy()
    try:
        api_base = _validate_tui_api_base(args.api_base)
    except ValueError as exc:
        parser.error(str(exc))
    env["LOCAL_SHELL_MCP_UI_API_BASE"] = api_base
    env["LOCAL_SHELL_MCP_UI_MODE"] = "tui"
    env[UI_LOCAL_TOKEN_ENV] = get_or_create_ui_local_token()
    try:
        completed = subprocess.run(resolve_tui_command(), env=env, check=False)
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    raise SystemExit(completed.returncode)


def _idle_timeout_remaining(
    last_activity: float, idle_timeout: float, now: float
) -> float:
    return max(0.0, idle_timeout - max(0.0, now - last_activity))


async def ui_terminal_websocket(websocket: WebSocket) -> None:
    if not _authorize_websocket(websocket):
        await websocket.close(code=4401, reason="OAuth authentication required")
        return

    settings = get_settings()
    marker = id(websocket)
    if len(_ACTIVE_UI_TERMINALS) >= max(1, settings.ui_terminal_max_sessions):
        await websocket.close(code=4429, reason="Too many active WebUI terminal sessions")
        return
    _ACTIVE_UI_TERMINALS.add(marker)

    offered = [item.strip() for item in websocket.headers.get("sec-websocket-protocol", "").split(",")]
    subprotocol = UI_SUBPROTOCOL if UI_SUBPROTOCOL in offered else None
    try:
        await websocket.accept(subprotocol=subprotocol)
    except Exception:
        _ACTIVE_UI_TERMINALS.discard(marker)
        raise
    try:
        cols = _bounded_int(
            websocket.query_params.get("cols"),
            default=120,
            minimum=UI_MIN_COLUMNS,
            maximum=UI_MAX_COLUMNS,
            label="cols",
        )
        rows = _bounded_int(
            websocket.query_params.get("rows"),
            default=36,
            minimum=UI_MIN_ROWS,
            maximum=UI_MAX_ROWS,
            label="rows",
        )
        process = _spawn_tui_process(cols, rows)
    except Exception as exc:
        _ACTIVE_UI_TERMINALS.discard(marker)
        _LOGGER.exception("Unable to start the human-interface TUI process")
        detail = f"{type(exc).__name__}: {exc}"
        await websocket.send_bytes(f"\r\nUnable to start the TUI: {detail}\r\n".encode())
        await websocket.close(code=1011, reason=detail[:120])
        return

    loop = asyncio.get_running_loop()
    last_activity = loop.time()

    async def sender() -> None:
        nonlocal last_activity
        while True:
            data = await process.read()
            if not data:
                return
            last_activity = loop.time()
            await websocket.send_bytes(data)

    async def receiver() -> None:
        nonlocal cols, rows, last_activity
        idle_timeout = max(0, settings.ui_terminal_idle_timeout_s)
        while True:
            if idle_timeout:
                remaining = _idle_timeout_remaining(
                    last_activity, idle_timeout, loop.time()
                )
                if remaining <= 0:
                    await websocket.close(
                        code=4408, reason="WebUI terminal session idle timeout"
                    )
                    return
                try:
                    message = await asyncio.wait_for(
                        websocket.receive(), timeout=remaining
                    )
                except TimeoutError:
                    if _idle_timeout_remaining(
                        last_activity, idle_timeout, loop.time()
                    ) > 0:
                        continue
                    await websocket.close(
                        code=4408, reason="WebUI terminal session idle timeout"
                    )
                    return
            else:
                message = await websocket.receive()
            last_activity = loop.time()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                await process.write(message["bytes"])
                continue
            text = message.get("text")
            if not text:
                continue
            try:
                control = json.loads(text)
            except json.JSONDecodeError:
                await process.write(text.encode())
                continue
            if not isinstance(control, dict):
                continue
            if control.get("type") == "resize":
                try:
                    cols = _bounded_int(
                        control.get("cols"),
                        default=cols,
                        minimum=UI_MIN_COLUMNS,
                        maximum=UI_MAX_COLUMNS,
                        label="cols",
                    )
                    rows = _bounded_int(
                        control.get("rows"),
                        default=rows,
                        minimum=UI_MIN_ROWS,
                        maximum=UI_MAX_ROWS,
                        label="rows",
                    )
                except ValueError as exc:
                    await websocket.close(code=4400, reason=str(exc)[:120])
                    return
                process.resize(cols, rows)

    tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            with contextlib.suppress(WebSocketDisconnect, RuntimeError):
                task.result()
    except WebSocketDisconnect:
        pass
    finally:
        _ACTIVE_UI_TERMINALS.discard(marker)
        await process.close()
        with contextlib.suppress(Exception):
            await websocket.close()


def ui_routes() -> list[Any]:
    settings = get_settings()
    if not settings.ui_enabled:
        return []
    ui_path = "/" + settings.ui_path.strip("/")
    return [
        Route(ui_path, ui_index, methods=["GET"]),
        Route(ui_path + "/", ui_index, methods=["GET"]),
        Route(ui_path + "/callback", ui_index, methods=["GET"]),
        Route(ui_path + "/wallpaper", ui_wallpaper, methods=["GET"]),
        Route(ui_path + "/assets/{path:path}", ui_asset, methods=["GET"]),
        WebSocketRoute(ui_path + "/ws", ui_terminal_websocket),
        Route(UI_API_PREFIX + "/bootstrap", api_bootstrap, methods=["GET"]),
        Route(UI_API_PREFIX + "/machines", api_machines, methods=["GET"]),
        Route(UI_API_PREFIX + "/files", api_files, methods=["GET"]),
        Route(UI_API_PREFIX + "/files/preview", api_file_preview, methods=["GET"]),
        Route(UI_API_PREFIX + "/files/content", api_file_content, methods=["GET"]),
        Route(UI_API_PREFIX + "/files/{action}", api_file_action, methods=["POST"]),
        Route(UI_API_PREFIX + "/terminals", api_terminals, methods=["GET"]),
        Route(UI_API_PREFIX + "/terminals/read", api_terminal_read, methods=["GET"]),
        Route(UI_API_PREFIX + "/terminals/{action}", api_terminal_action, methods=["POST"]),
        Route(UI_API_PREFIX + "/todos", api_todos, methods=["GET", "PUT"]),
        Route(UI_API_PREFIX + "/audit", api_audit, methods=["GET"]),
        Route(UI_API_PREFIX + "/remotes", api_remotes, methods=["GET", "POST"]),
        Route(UI_API_PREFIX + "/remotes/{action}", api_remote_action, methods=["POST"]),
    ]
