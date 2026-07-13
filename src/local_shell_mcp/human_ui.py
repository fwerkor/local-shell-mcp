from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import shlex
import shutil
import signal
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path, PurePosixPath
from typing import Any

from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from .audit import query_audit, suppress_audit
from .fs_ops import delete_path, list_dir, read_text, resolve_path, write_text
from .remote import remote_manager
from .settings import get_settings
from .shell_ops import kill_shell, list_shells, read_shell, send_shell, start_shell
from .todo_ops import todo_read, todo_write
from .version import version_info

UI_API_PREFIX = "/api/ui"
UI_SUBPROTOCOL = "lsm-ui"


def _json_ok(data: Any = None, message: str = "") -> JSONResponse:
    return JSONResponse({"ok": True, "message": message, "data": data})


def _json_error(exc: Exception, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        {
            "ok": False,
            "error": type(exc).__name__,
            "message": str(exc),
        },
        status_code=status_code,
    )


def _assets_dir() -> Path:
    return Path(__file__).resolve().parent / "ui_static"


def _ui_index_html() -> str:
    path = _assets_dir() / "index.html"
    if path.exists():
        return path.read_text(encoding="utf-8")
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
    path = _assets_dir().joinpath(*relative.parts)
    try:
        path.relative_to(_assets_dir())
    except ValueError:
        return Response("Not found", status_code=404)
    if not path.is_file():
        return Response("Not found", status_code=404)
    cache = "public, max-age=31536000, immutable" if "." in path.stem else "public, max-age=3600"
    return FileResponse(path, headers={"Cache-Control": cache})


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
    result = await remote_manager().call(machine, tool, {**args, "_human": True})
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
            result = local_call()
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


async def api_bootstrap(request: Request) -> Response:  # noqa: ARG001
    settings = get_settings()
    return _json_ok(
        {
            "version": version_info(),
            "machines": _machine_rows(),
            "todos": todo_read(),
            "features": {
                "remote": settings.remote_enabled,
                "wallpaper": settings.ui_wallpaper,
                "yazi_available": shutil.which("yazi") is not None,
            },
        }
    )


async def api_machines(request: Request) -> Response:  # noqa: ARG001
    return _json_ok(_machine_rows())


async def api_files(request: Request) -> Response:
    machine = request.query_params.get("machine", "local")
    path = request.query_params.get("path", ".")
    try:
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
        if machine == "local":
            resolved = resolve_path(path, must_exist=True)
            if resolved.is_dir():
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


def _remote_python_for_file_action(action: str, body: dict[str, Any]) -> str:
    payload = json.dumps(body, ensure_ascii=False)
    return f"""import json, pathlib, shutil
p=json.loads({payload!r})
action={action!r}
if action == 'mkdir':
    pathlib.Path(p['path']).mkdir(parents=True, exist_ok=bool(p.get('exist_ok', False)))
elif action == 'touch':
    path=pathlib.Path(p['path']); path.parent.mkdir(parents=True, exist_ok=True); path.open('x').close()
elif action == 'rename':
    pathlib.Path(p['path']).rename(pathlib.Path(p['destination']))
elif action == 'copy':
    src=pathlib.Path(p['path']); dst=pathlib.Path(p['destination'])
    shutil.copytree(src, dst) if src.is_dir() else shutil.copy2(src, dst)
elif action == 'move':
    shutil.move(p['path'], p['destination'])
else:
    raise ValueError(action)
print(json.dumps({{'action': action, 'ok': True}}))
"""


async def api_file_action(request: Request) -> Response:
    action = str(request.path_params.get("action") or "")
    try:
        body = await request.json()
        machine = str(body.get("machine") or "local")
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
            result = await _machine_dispatch(
                machine,
                lambda: write_text(path, str(body.get("content") or ""), bool(body.get("overwrite", True))),
                "write_file",
                {"path": path, "content": str(body.get("content") or ""), "overwrite": bool(body.get("overwrite", True))},
            )
            return _json_ok(result)
        if action not in {"mkdir", "touch", "rename", "copy", "move"}:
            raise ValueError(f"Unsupported file action: {action}")

        if machine == "local":
            with suppress_audit():
                source = resolve_path(path, must_exist=action in {"rename", "copy", "move"})
                if action == "mkdir":
                    source.mkdir(parents=True, exist_ok=bool(body.get("exist_ok", False)))
                elif action == "touch":
                    source.parent.mkdir(parents=True, exist_ok=True)
                    source.touch(exist_ok=False)
                else:
                    destination = resolve_path(str(body.get("destination") or ""), must_exist=False)
                    if action == "rename":
                        source.rename(destination)
                    elif action == "copy":
                        if source.is_dir():
                            shutil.copytree(source, destination)
                        else:
                            shutil.copy2(source, destination)
                    elif action == "move":
                        shutil.move(str(source), str(destination))
            return _json_ok({"action": action, "path": path, "destination": body.get("destination")})

        code = _remote_python_for_file_action(action, body)
        result = await _remote_call(machine, "run_python_tool", {"code": code, "cwd": ".", "timeout_s": 60})
        return _json_ok(result)
    except Exception as exc:
        return _json_error(exc)


async def api_terminals(request: Request) -> Response:
    machine = request.query_params.get("machine", "local")
    try:
        result = await _machine_dispatch(machine, list_shells, "shell_list", {})
        return _json_ok({"machine": machine, **(result or {"sessions": []})})
    except Exception as exc:
        return _json_error(exc)


async def api_terminal_read(request: Request) -> Response:
    machine = request.query_params.get("machine", "local")
    session_id = request.query_params.get("session_id", "")
    lines = int(request.query_params.get("lines", "500"))
    try:
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
            return _json_ok(todo_read())
        body = await request.json()
        with suppress_audit():
            result = todo_write(list(body.get("todos") or []))
        return _json_ok(result)
    except Exception as exc:
        return _json_error(exc)


async def api_audit(request: Request) -> Response:
    params = request.query_params
    try:
        result = query_audit(
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
        if request.method == "GET":
            return _json_ok(remote_manager().list_machines())
        body = await request.json()
        result = await remote_manager().create_invite(body.get("name"), body.get("workdir"), body.get("ttl_s"))
        return _json_ok(result)
    except Exception as exc:
        return _json_error(exc)


async def api_remote_action(request: Request) -> Response:
    action = str(request.path_params.get("action") or "")
    try:
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


def _is_loopback_websocket(websocket: WebSocket) -> bool:
    client = websocket.client
    return bool(client and client.host in {"127.0.0.1", "::1", "localhost"})


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
    if settings.auth_bypass_localhost and _is_loopback_websocket(websocket):
        return True
    token = _websocket_token(websocket)
    if not token:
        return False
    try:
        from .oauth import validate_bearer_token

        validate_bearer_token(token, websocket)  # type: ignore[arg-type]
    except Exception:
        return False
    return True


def _tui_bundle_path() -> Path | None:
    candidates = [
        Path(__file__).resolve().parent / "ui_tui" / "tui.js",
        Path(__file__).resolve().parents[2] / "ui" / "dist" / "tui.js",
        Path.cwd() / "ui" / "dist" / "tui.js",
        Path("/app/ui/dist/tui.js"),
    ]
    return next((path for path in candidates if path.is_file()), None)


def resolve_tui_command() -> list[str]:
    settings = get_settings()
    if settings.ui_tui_command:
        return shlex.split(settings.ui_tui_command)

    executable_dir = Path(sys.executable).resolve().parent
    sidecar_name = "local-shell-mcp-tui.exe" if os.name == "nt" else "local-shell-mcp-tui"
    sidecar_candidates = [
        executable_dir / sidecar_name,
        Path(sys.argv[0]).resolve().parent / sidecar_name,
    ]
    for candidate in sidecar_candidates:
        if candidate.is_file():
            return [str(candidate)]

    bundle = _tui_bundle_path()
    bun = shutil.which("bun")
    if bundle and bun:
        return [bun, str(bundle)]
    if bundle:
        raise RuntimeError("The OpenTUI bundle is installed, but Bun is not available in PATH")
    raise RuntimeError("OpenTUI runtime not found; install a release bundle or run `cd ui && bun run build`")


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

    async def read(self) -> bytes:
        while True:
            try:
                return os.read(self.master_fd, 65_536)
            except BlockingIOError:
                await asyncio.sleep(0.01)
            except OSError:
                return b""

    async def write(self, data: bytes) -> None:
        if data:
            await asyncio.to_thread(os.write, self.master_fd, data)

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
        self.process = PtyProcess.spawn(command, dimensions=(max(1, rows), max(1, cols)), env=env)

    def resize(self, cols: int, rows: int) -> None:
        self.process.setwinsize(max(1, rows), max(1, cols))

    async def read(self) -> bytes:
        try:
            data = await asyncio.to_thread(self.process.read, 65_536, True)
        except Exception:
            return b""
        return data.encode("utf-8", errors="replace") if isinstance(data, str) else bytes(data)

    async def write(self, data: bytes) -> None:
        await asyncio.to_thread(self.process.write, data.decode("utf-8", errors="replace"))

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
        }
    )
    command = resolve_tui_command()
    if os.name == "nt":
        return _WindowsPtyProcess(command, env, cols, rows)
    return _UnixPtyProcess(command, env, cols, rows)


async def ui_terminal_websocket(websocket: WebSocket) -> None:
    if not _authorize_websocket(websocket):
        await websocket.close(code=4401, reason="OAuth authentication required")
        return

    offered = [item.strip() for item in websocket.headers.get("sec-websocket-protocol", "").split(",")]
    subprotocol = UI_SUBPROTOCOL if UI_SUBPROTOCOL in offered else None
    await websocket.accept(subprotocol=subprotocol)
    try:
        cols = int(websocket.query_params.get("cols", "120"))
        rows = int(websocket.query_params.get("rows", "36"))
        process = _spawn_tui_process(cols, rows)
    except Exception as exc:
        await websocket.send_bytes(f"\r\nUnable to start the TUI: {exc}\r\n".encode())
        await websocket.close(code=1011)
        return

    async def sender() -> None:
        while True:
            data = await process.read()
            if not data:
                return
            await websocket.send_bytes(data)

    async def receiver() -> None:
        while True:
            message = await websocket.receive()
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
            if control.get("type") == "resize":
                process.resize(int(control.get("cols") or cols), int(control.get("rows") or rows))

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
        Route(ui_path + "/assets/{path:path}", ui_asset, methods=["GET"]),
        WebSocketRoute(ui_path + "/ws", ui_terminal_websocket),
        Route(UI_API_PREFIX + "/bootstrap", api_bootstrap, methods=["GET"]),
        Route(UI_API_PREFIX + "/machines", api_machines, methods=["GET"]),
        Route(UI_API_PREFIX + "/files", api_files, methods=["GET"]),
        Route(UI_API_PREFIX + "/files/preview", api_file_preview, methods=["GET"]),
        Route(UI_API_PREFIX + "/files/{action}", api_file_action, methods=["POST"]),
        Route(UI_API_PREFIX + "/terminals", api_terminals, methods=["GET"]),
        Route(UI_API_PREFIX + "/terminals/read", api_terminal_read, methods=["GET"]),
        Route(UI_API_PREFIX + "/terminals/{action}", api_terminal_action, methods=["POST"]),
        Route(UI_API_PREFIX + "/todos", api_todos, methods=["GET", "PUT"]),
        Route(UI_API_PREFIX + "/audit", api_audit, methods=["GET"]),
        Route(UI_API_PREFIX + "/remotes", api_remotes, methods=["GET", "POST"]),
        Route(UI_API_PREFIX + "/remotes/{action}", api_remote_action, methods=["POST"]),
    ]
