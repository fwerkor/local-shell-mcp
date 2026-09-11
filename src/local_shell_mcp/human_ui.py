from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import json
import logging
import os
import select
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Awaitable, Callable
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import urlsplit

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from . import __version__
from .audit import get_audit_entry, query_audit, suppress_audit
from .auth import Principal, require_scopes, verify_request
from .fs_ops import (
    FileConflictError,
    delete_path,
    list_dir,
    perform_file_action,
    read_text,
    resolve_path,
    write_content,
)
from .image_ops import ImageFile, assert_view_image_size, detect_image_type, make_image_preview
from .jobs import list_jobs
from .live_channel import get_live_channel_manager, live_id_from_claims
from .oauth import ALL_OAUTH_SCOPES
from .remote import remote_manager
from .session_runtime import get_session_runtime_manager
from .settings import get_settings
from .shell_environment import subprocess_env
from .shell_ops import (
    kill_shell,
    list_shells,
    read_shell,
    resize_shell,
    send_shell,
    start_shell,
    tmux,
)
from .tmux_helper import resolve_tmux, tmux_socket_name
from .tui_runtime import materialize_embedded_tui
from .ui_security import UI_LOCAL_TOKEN_ENV, get_or_create_ui_local_token
from .version import version_info

UI_API_PREFIX = "/api/ui"
UI_SUBPROTOCOL = "lsm-ui"
UI_FULL_SCOPES = ALL_OAUTH_SCOPES
UI_MIN_COLUMNS = 20
UI_MAX_COLUMNS = 1_600
UI_MIN_ROWS = 8
UI_MAX_ROWS = 500
UI_TUI_EXIT_CODE = 4410
UI_SHELL_EXIT_CODE = 4411
_ACTIVE_UI_TERMINALS: set[int] = set()
_LOGGER = logging.getLogger(__name__)

_PROCESS_STARTED_AT = time.time()
_SYSTEM_SAMPLE_LOCK = threading.Lock()
_CPU_SAMPLE: tuple[int, int] | None = None
_NETWORK_SAMPLE: tuple[float, int, int] | None = None


def _read_linux_cpu_times() -> tuple[int, int] | None:
    try:
        fields = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()
        values = [int(value) for value in fields[1:]]
    except (OSError, ValueError, IndexError):
        return None
    if len(values) < 4:
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle


def _read_linux_memory() -> tuple[int, int] | None:
    try:
        rows = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, value = line.split(":", 1)
            rows[key] = int(value.strip().split()[0]) * 1024
        total = rows["MemTotal"]
        available = rows.get("MemAvailable", rows.get("MemFree", 0))
    except (OSError, ValueError, KeyError):
        return None
    return total, max(0, total - available)


def _read_linux_network() -> tuple[int, int] | None:
    try:
        lines = Path("/proc/net/dev").read_text(encoding="utf-8").splitlines()[2:]
        received = transmitted = 0
        for line in lines:
            name, values = line.split(":", 1)
            if name.strip() == "lo":
                continue
            fields = values.split()
            received += int(fields[0])
            transmitted += int(fields[8])
    except (OSError, ValueError, IndexError):
        return None
    return received, transmitted


def _percent(used: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(max(0.0, min(100.0, used * 100.0 / total)), 1)


def _local_system_snapshot() -> dict[str, Any]:
    global _CPU_SAMPLE, _NETWORK_SAMPLE

    now = time.time()
    monotonic_now = time.monotonic()
    load_1m: float | None = None
    with contextlib.suppress(OSError, AttributeError):
        load_1m = round(float(os.getloadavg()[0]), 2)

    cpu_times = _read_linux_cpu_times()
    cpu_percent: float | None = None
    network = _read_linux_network()
    network_rx_bps = network_tx_bps = 0.0
    with _SYSTEM_SAMPLE_LOCK:
        if cpu_times is not None:
            if _CPU_SAMPLE is not None:
                total_delta = cpu_times[0] - _CPU_SAMPLE[0]
                idle_delta = cpu_times[1] - _CPU_SAMPLE[1]
                if total_delta > 0:
                    cpu_percent = round(
                        max(0.0, min(100.0, (total_delta - idle_delta) * 100.0 / total_delta)),
                        1,
                    )
            _CPU_SAMPLE = cpu_times
        if network is not None:
            if _NETWORK_SAMPLE is not None:
                elapsed = monotonic_now - _NETWORK_SAMPLE[0]
                if elapsed > 0:
                    network_rx_bps = max(0.0, (network[0] - _NETWORK_SAMPLE[1]) / elapsed)
                    network_tx_bps = max(0.0, (network[1] - _NETWORK_SAMPLE[2]) / elapsed)
            _NETWORK_SAMPLE = (monotonic_now, network[0], network[1])

    cpu_count = max(1, os.cpu_count() or 1)
    if cpu_percent is None and load_1m is not None:
        cpu_percent = round(max(0.0, min(100.0, load_1m * 100.0 / cpu_count)), 1)

    memory = _read_linux_memory()
    memory_total = memory[0] if memory else None
    memory_used = memory[1] if memory else None
    try:
        disk = shutil.disk_usage(get_settings().workspace_root)
    except OSError:
        disk = None
    uptime_s = max(0.0, now - _PROCESS_STARTED_AT)
    with contextlib.suppress(OSError, ValueError, IndexError):
        uptime_s = float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])

    return {
        "timestamp": now,
        "cpu_percent": cpu_percent,
        "cpu_count": cpu_count,
        "memory_percent": (
            _percent(memory_used, memory_total)
            if memory_used is not None and memory_total is not None
            else None
        ),
        "memory_used_bytes": memory_used,
        "memory_total_bytes": memory_total,
        "disk_percent": _percent(disk.used, disk.total) if disk else None,
        "disk_used_bytes": disk.used if disk else None,
        "disk_total_bytes": disk.total if disk else None,
        "load_1m": load_1m,
        "network_rx_bps": round(network_rx_bps, 1),
        "network_tx_bps": round(network_tx_bps, 1),
        "uptime_s": round(uptime_s),
    }


def _remote_version(machine: dict[str, Any]) -> str | None:
    info = machine.get("info") if isinstance(machine.get("info"), dict) else {}
    direct = info.get("version") or info.get("lsm_version")
    if direct:
        return str(direct)
    nested = info.get("local_shell_mcp")
    if isinstance(nested, dict) and nested.get("version"):
        return str(nested["version"])
    return None


def _dashboard_alerts(
    machines: list[dict[str, Any]],
    system: dict[str, Any],
    jobs: list[dict[str, Any]],
    audit_entries: list[dict[str, Any]],
    current_version: str,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for machine in machines:
        if machine.get("name") == "local":
            continue
        if machine.get("status") != "online":
            alerts.append(
                {
                    "severity": "warning",
                    "title": f"{machine.get('name', 'remote')} is offline",
                    "detail": "Remote worker is not currently connected",
                    "node": machine.get("name"),
                    "age_s": machine.get("last_seen_age_s"),
                }
            )
            continue
        remote_version = _remote_version(machine)
        if remote_version and remote_version != current_version:
            alerts.append(
                {
                    "severity": "info",
                    "title": f"{machine.get('name')} uses LSM {remote_version}",
                    "detail": f"Controller is running LSM {current_version}",
                    "node": machine.get("name"),
                }
            )

    disk_percent = system.get("disk_percent")
    if isinstance(disk_percent, (int, float)) and disk_percent >= 85:
        alerts.append(
            {
                "severity": "critical" if disk_percent >= 95 else "warning",
                "title": f"Workspace disk is {disk_percent:.0f}% full",
                "detail": str(get_settings().workspace_root),
                "node": "local",
            }
        )

    now = time.time()
    recent_failed_jobs = [
        job
        for job in jobs
        if job.get("status") in {"failed", "lost"}
        and now - float(job.get("updated_at") or job.get("created_at") or 0) <= 86_400
    ]
    for job in recent_failed_jobs[:3]:
        alerts.append(
            {
                "severity": "warning",
                "title": f"Job {job.get('name') or job.get('job_id')} {job.get('status')}",
                "detail": str(job.get("error") or job.get("command") or "Tracked job needs attention"),
                "node": "local",
                "age_s": max(0.0, now - float(job.get("updated_at") or now)),
            }
        )

    failed_calls = [
        entry
        for entry in audit_entries
        if entry.get("ok") is False or entry.get("status") == "failed" or entry.get("error")
    ]
    if failed_calls:
        alerts.append(
            {
                "severity": "warning",
                "title": f"{len(failed_calls)} recent MCP call failure(s)",
                "detail": "Open Audit for call inputs and returned errors",
            }
        )
    return alerts


def _dashboard_activity(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for entry in entries[:12]:
        failed = entry.get("ok") is False or entry.get("status") == "failed" or entry.get("error")
        running = entry.get("paired") is False or entry.get("status") in {"running", "unpaired"}
        rows.append(
            {
                "timestamp": entry.get("ts"),
                "node": entry.get("node") or "local",
                "kind": "failed" if failed else "running" if running else "success",
                "title": entry.get("tool") or entry.get("event") or "MCP activity",
                "detail": entry.get("command") or entry.get("operation") or "",
            }
        )
    return rows


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


def _logical_session_subject(request: Request, *, create: bool = False) -> str | None:
    principal = _request_principal(request)
    if principal.claims.get("auth") not in {"native-tui", "localhost-bypass"}:
        return principal.subject or principal.email or "mcp-client"
    if not create:
        return None
    settings = get_settings()
    if settings.auth_mode == "none":
        return "anonymous"
    if settings.auth_mode == "oauth":
        return "local-user"
    return "local-mcp-client"


def _require_ui_scopes(
    request: Request, *scopes: str, machine: str | None = None
) -> None:
    required = list(scopes)
    if machine and machine != "local":
        required.append("remote:use")
    require_scopes(_request_principal(request), required)


def _live_channel_id(request: Request) -> str | None:
    principal = _request_principal(request)
    if principal.claims.get("auth") != "live-channel":
        return None
    return live_id_from_claims(principal.claims)


def _require_live_human_mutation(request: Request) -> str | None:
    return _live_channel_id(request)


def _record_live_human_action(
    live_id: str | None,
    action: str,
    **data: Any,
) -> None:
    if not live_id:
        return
    get_live_channel_manager().publish_channel(
        live_id,
        "human.action",
        actor="human",
        data={"action": action, **data},
    )


_AUDIT_FILE_WRITE_TOOLS = frozenset(
    {
        "file_write",
        "file_edit",
        "file_delete",
        "file_patch",
        "write_file",
        "edit_file",
        "delete_file_or_dir",
        "apply_patch",
    }
)
_AUDIT_EXECUTE_TOOLS = frozenset(
    {
        "run_shell",
        "run_python",
        "shell_start",
        "shell_send",
        "shell_stop",
        "run_shell_tool",
        "run_python_tool",
        "shell_kill",
        "job_start",
        "job_stop",
        "job_retry",
    }
)
_AUDIT_FILE_SHARE_TOOLS = frozenset(
    {"link_create", "link_list", "link_revoke", "create_file_link", "list_file_links", "revoke_file_link"}
)


def _audit_detail_scopes(entry: dict[str, Any]) -> tuple[str, ...]:
    required = {"shell:read"}
    tool = str(entry.get("tool") or "")
    operation = str(entry.get("operation") or "")
    if tool in _AUDIT_FILE_WRITE_TOOLS:
        required.add("shell:write")
    if tool in _AUDIT_EXECUTE_TOOLS or operation in {"shell", "jobs"}:
        required.add("shell:execute")
    if operation == "browser":
        required.add("browser:use")
    if tool in _AUDIT_FILE_SHARE_TOOLS:
        required.add("file:share")
    if operation == "remote" or str(entry.get("node") or "local") != "local":
        required.add("remote:use")
    if operation == "other":
        required.update(UI_FULL_SCOPES)
    return tuple(scope for scope in UI_FULL_SCOPES if scope in required)


def _audit_view_image_detail(
    entry: dict[str, Any],
    *,
    columns: int,
    rows: int,
    cell_aspect: float,
) -> dict[str, Any]:
    if str(entry.get("tool") or "") not in {"image_view", "view_image"}:
        return entry
    output = entry.get("output")
    if not isinstance(output, dict):
        return entry
    content = output.get("content")
    if not isinstance(content, list):
        return entry

    image_index = next(
        (
            index
            for index, item in enumerate(content)
            if isinstance(item, dict)
            and item.get("type") == "image"
            and isinstance(item.get("data"), str)
        ),
        None,
    )
    if image_index is None:
        return entry

    source_item = content[image_index]
    assert isinstance(source_item, dict)
    sanitized_item = {name: value for name, value in source_item.items() if name != "data"}
    sanitized_content = list(content)
    sanitized_content[image_index] = sanitized_item
    detail = {**entry, "output": {**output, "content": sanitized_content}}

    try:
        raw = base64.b64decode(str(source_item["data"]), validate=True)
        assert_view_image_size(len(raw))
        image_format, mime_type = detect_image_type(raw[:16])
        structured = output.get("structuredContent")
        if not isinstance(structured, dict):
            structured = output.get("structured_content")
        path = (
            str(structured.get("path") or "image result")
            if isinstance(structured, dict)
            else "image result"
        )
        image = ImageFile(
            path=path,
            data=raw,
            format=image_format,
            mime_type=mime_type,
            size=len(raw),
        )
        rendered = make_image_preview(image, columns, rows, cell_aspect)
        sanitized_item["bytes"] = image.size
        detail["image_preview"] = {
            "kind": "image",
            "path": path,
            "bytes": image.size,
            "mime_type": image.mime_type,
            "rgba": base64.b64encode(rendered.rgba).decode("ascii"),
            "width": rendered.width,
            "height": rendered.height,
            "cell_width": rendered.cell_width,
            "cell_height": rendered.cell_height,
            "original_width": rendered.original_width,
            "original_height": rendered.original_height,
        }
    except (ValueError, OSError, binascii.Error) as exc:
        detail["image_preview_error"] = str(exc)
    return detail


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


def _bounded_float(
    raw: str | float | None,
    *,
    default: float,
    minimum: float,
    maximum: float,
    label: str,
) -> float:
    if raw in {None, ""}:
        value = default
    else:
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be a number") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return value


def _assets_dir() -> Path:
    return Path(__file__).resolve().parent / "ui_static"


def _ui_index_html() -> str:
    settings = get_settings()
    ui_path = "/" + settings.ui_path.strip("/")
    path = _assets_dir() / "index.html"
    if path.exists():
        html = path.read_text(encoding="utf-8")
        config = json.dumps({"uiPath": ui_path, "apiPrefix": UI_API_PREFIX})
        return (
            html.replace("__LSM_UI_PATH__", ui_path)
            .replace("__LSM_UI_ASSET_VERSION__", __version__)
            .replace("__LSM_UI_CONFIG_JSON__", config)
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
        stamp_path.write_text(today, encoding="utf-8")

    return FileResponse(image_path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})


def _machine_rows() -> dict[str, Any]:
    remote = remote_manager().list_machines()
    settings = get_settings()
    rows = list(remote.get("machines", []))
    counts = dict(remote.get("counts") or {})
    if not settings.disable_local:
        rows.insert(
            0,
            {
                "name": "local",
                "status": "online",
                "workdir": str(settings.workspace_root),
                "last_seen": time.time(),
                "last_seen_age_s": 0,
                "capabilities": ["files", "terminals"],
                "info": {
                    "platform": sys.platform,
                    "local": True,
                    "version": version_info().get("version"),
                },
            },
        )
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
        if get_settings().disable_local:
            raise RuntimeError("Local access is disabled")
        with suppress_audit():
            result = await asyncio.to_thread(local_call)
            if asyncio.iscoroutine(result):
                return await result
            return result
    return await _remote_call(machine, remote_tool, remote_args)


def _machine_uses_windows_paths(machine: str) -> bool:
    if machine == "local":
        return os.name == "nt"
    with contextlib.suppress(Exception):
        for row in remote_manager().list_machines().get("machines", []):
            if str(row.get("name") or "") != machine:
                continue
            info = row.get("info") if isinstance(row.get("info"), dict) else {}
            platform = str(info.get("platform") or info.get("system") or "").lower()
            return platform.startswith("win") or "windows" in platform
    return False


def _path_parser(path: str, windows: bool | None = None):  # noqa: ANN201
    if windows is None:
        windows = "\\" in path or bool(PureWindowsPath(path).drive)
    return PureWindowsPath(path) if windows else PurePosixPath(path)


def _path_name(path: str, windows: bool | None = None) -> str:
    cleaned = path.rstrip("/\\")
    if not cleaned or cleaned == ".":
        return "."
    return _path_parser(cleaned, windows).name or cleaned


def _parent_path(path: str, windows: bool | None = None) -> str:
    parser = _path_parser(path, windows)
    if path in {"", "."}:
        return "."
    if parser.parent == parser:
        return str(parser)
    parent = str(parser.parent)
    return parent or "."


def _normalize_file_entries(
    entries: list[dict[str, Any]], windows: bool | None = None
) -> list[dict[str, Any]]:
    rows = []
    for item in entries:
        path = str(item.get("path") or "")
        name = _path_name(path, windows)
        rows.append(
            {
                **item,
                "path": path,
                "name": name,
                "hidden": name.startswith("."),
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
    machines = await asyncio.to_thread(_machine_rows)
    return _json_ok(
        {
            "version": version_info(),
            "machines": machines,
            "features": {
                "remote": settings.remote_enabled,
                "wallpaper": settings.ui_wallpaper,
            },
        }
    )


async def api_dashboard(request: Request) -> Response:
    settings = get_settings()
    machine = str(request.query_params.get("machine") or "local")
    required = ["shell:read"]
    if settings.remote_enabled or machine != "local":
        required.append("remote:use")
    _require_ui_scopes(request, *required)

    machines, system = await asyncio.gather(
        asyncio.to_thread(_machine_rows),
        asyncio.to_thread(_local_system_snapshot),
    )

    source_alerts: list[dict[str, Any]] = []
    with suppress_audit():
        try:
            terminals = await _machine_dispatch(machine, list_shells, "shell_list", {})
        except Exception as exc:
            _LOGGER.debug("Dashboard terminal snapshot failed", exc_info=True)
            terminals = {"sessions": []}
            source_alerts.append(
                {
                    "severity": "warning",
                    "title": "Persistent sessions unavailable",
                    "detail": f"{type(exc).__name__}: {exc}",
                    "node": machine,
                }
            )
        try:
            jobs_payload = await _machine_dispatch(
                machine,
                lambda: list_jobs(include_finished=True),
                "job_list",
                {"include_finished": True},
            )
        except Exception as exc:
            _LOGGER.debug("Dashboard job snapshot failed", exc_info=True)
            jobs_payload = {"jobs": [], "counts": {}}
            source_alerts.append(
                {
                    "severity": "warning",
                    "title": "Tracked jobs unavailable",
                    "detail": f"{type(exc).__name__}: {exc}",
                    "node": machine,
                }
            )
    try:
        audit_payload = await asyncio.to_thread(
            query_audit,
            limit=160,
            start_ts=time.time() - 86_400,
            sort="desc",
        )
    except Exception as exc:
        _LOGGER.debug("Dashboard audit snapshot failed", exc_info=True)
        audit_payload = {"entries": [], "count": 0, "total_matched": 0}
        source_alerts.append(
            {
                "severity": "warning",
                "title": "Audit activity unavailable",
                "detail": f"{type(exc).__name__}: {exc}",
                "node": "local",
            }
        )

    machine_rows = list(machines.get("machines") or [])
    jobs = [
        {**job, "machine": str(job.get("machine") or machine)}
        for job in list(jobs_payload.get("jobs") or [])
    ]
    sessions = [
        {**session, "machine": str(session.get("machine") or machine)}
        for session in list((terminals or {}).get("sessions") or [])
    ]
    audit_entries = list(audit_payload.get("entries") or [])
    version = version_info()
    current_version = str(version.get("version") or "unknown")
    alerts = [
        *_dashboard_alerts(machine_rows, system, jobs, audit_entries, current_version),
        *source_alerts,
    ]
    active_statuses = {"starting", "running", "stopping", "retrying"}
    active_jobs = [job for job in jobs if job.get("status") in active_statuses]
    job_session_ids = {str(job.get("session_id") or "") for job in active_jobs}
    standalone_sessions = [
        session for session in sessions if str(session.get("session_id") or "") not in job_session_ids
    ]
    severity_rank = {"info": 0, "warning": 1, "critical": 2}
    alerts.sort(
        key=lambda alert: severity_rank.get(str(alert.get("severity")), 0),
        reverse=True,
    )
    health = "healthy"
    if alerts:
        highest = severity_rank.get(str(alerts[0].get("severity")), 0)
        health = "critical" if highest >= 2 else "attention"

    return _json_ok(
        {
            "generated_at": time.time(),
            "selected_machine": machine,
            "health": health,
            "version": version,
            "system": system,
            "machines": machines,
            "jobs": active_jobs[:12],
            "job_counts": jobs_payload.get("counts") or {},
            "sessions": standalone_sessions[:12],
            "session_count": len(sessions),
            "alerts": alerts[:12],
            "activity": _dashboard_activity(audit_entries),
            "audit_total_24h": int(audit_payload.get("total_matched") or 0),
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
        windows_paths = _machine_uses_windows_paths(machine)
        parent = _parent_path(path, windows_paths)
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
                "entries": _normalize_file_entries(list(entries or []), windows_paths),
                "parent_entries": _normalize_file_entries(list(parent_entries or []), windows_paths),
            }
        )
    except Exception as exc:
        return _json_error(exc)


async def api_file_preview(request: Request) -> Response:
    machine = request.query_params.get("machine", "local")
    path = request.query_params.get("path", ".")
    try:
        _require_ui_scopes(request, "shell:read", machine=machine)
        if machine == "local" and get_settings().disable_local:
            raise RuntimeError("Local access is disabled; select a remote machine")
        windows_paths = _machine_uses_windows_paths(machine)
        if machine == "local":
            resolved = await asyncio.to_thread(resolve_path, path, must_exist=True)
            if await asyncio.to_thread(resolved.is_dir):
                return _json_ok(
                    {
                        "kind": "directory",
                        "entries": _normalize_file_entries(list_dir(path, False, 100), windows_paths),
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
                        {"kind": "directory", "entries": _normalize_file_entries(listed, windows_paths)}
                    )

        if path.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            columns = max(8, min(int(request.query_params.get("columns", "96")), 200))
            rows = max(4, min(int(request.query_params.get("rows", "32")), 100))
            cell_aspect = _bounded_float(
                request.query_params.get("cell_aspect"),
                default=2.0,
                minimum=0.5,
                maximum=5.0,
                label="cell_aspect",
            )
            from .tools import load_image_for_machine

            image, display_path = await load_image_for_machine(
                path,
                None if machine == "local" else machine,
            )
            rendered = await asyncio.to_thread(
                make_image_preview,
                image,
                columns,
                rows,
                cell_aspect,
            )
            return _json_ok(
                {
                    "kind": "image",
                    "path": display_path,
                    "bytes": image.size,
                    "mime_type": image.mime_type,
                    "rgba": base64.b64encode(rendered.rgba).decode("ascii"),
                    "width": rendered.width,
                    "height": rendered.height,
                    "cell_width": rendered.cell_width,
                    "cell_height": rendered.cell_height,
                    "original_width": rendered.original_width,
                    "original_height": rendered.original_height,
                }
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
            return _json_ok({"kind": "directory", "entries": _normalize_file_entries(list(entries or []), windows_paths)})
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
        live_id = _require_live_human_mutation(request)
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
            _record_live_human_action(live_id, "file.delete", machine=machine, path=path)
            return _json_ok(result)
        if action == "write":
            expected_sha256 = str(body.get("expected_sha256") or "") or None
            encoding = str(body.get("encoding") or "utf-8")
            result = await _machine_dispatch(
                machine,
                lambda: write_content(
                    path,
                    str(body.get("content") or ""),
                    bool(body.get("overwrite", True)),
                    expected_sha256,
                    encoding,
                ),
                "write_file",
                {
                    "path": path,
                    "content": str(body.get("content") or ""),
                    "overwrite": bool(body.get("overwrite", True)),
                    "expected_sha256": expected_sha256,
                    "encoding": encoding,
                },
            )
            _record_live_human_action(live_id, "file.write", machine=machine, path=path)
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
        _record_live_human_action(
            live_id,
            f"file.{action}",
            machine=machine,
            path=path,
            destination=args.get("destination"),
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
        live_id = None if action == "resize" else _require_live_human_mutation(request)
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
        elif action == "resize":
            session_id = str(body.get("session_id") or "")
            if not session_id:
                raise ValueError("session_id is required")
            if body.get("cols") is None or body.get("rows") is None:
                raise ValueError("cols and rows are required")
            args = {
                "session_id": session_id,
                "cols": _bounded_int(
                    body.get("cols"),
                    default=80,
                    minimum=UI_MIN_COLUMNS,
                    maximum=UI_MAX_COLUMNS,
                    label="cols",
                ),
                "rows": _bounded_int(
                    body.get("rows"),
                    default=24,
                    minimum=3,
                    maximum=UI_MAX_ROWS,
                    label="rows",
                ),
            }
            result = await _machine_dispatch(
                machine,
                lambda: resize_shell(args["session_id"], args["cols"], args["rows"]),
                "shell_resize",
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
        if action != "resize":
            result_session_id = result.get("session_id") if isinstance(result, dict) else None
            _record_live_human_action(
                live_id,
                f"terminal.{action}",
                machine=machine,
                session_id=str(body.get("session_id") or result_session_id or ""),
            )
        return _json_ok(result)
    except Exception as exc:
        return _json_error(exc)



async def api_logical_sessions(request: Request) -> Response:
    try:
        _require_ui_scopes(request, "shell:read")
        subject = _logical_session_subject(request)
        sessions = await asyncio.to_thread(
            get_session_runtime_manager().list_sessions,
            subject=subject,
        )
        counts = {"active": 0, "completed": 0, "cancelled": 0, "total": len(sessions)}
        for session in sessions:
            status = str(session.get("status") or "")
            if status in counts:
                counts[status] += 1
        return _json_ok({"sessions": sessions, "counts": counts})
    except Exception as exc:
        return _json_error(exc)


async def api_logical_session_detail(request: Request) -> Response:
    try:
        _require_ui_scopes(request, "shell:read")
        session_id = str(request.query_params.get("session_id") or "")
        if not session_id:
            raise ValueError("session_id is required")
        session = await asyncio.to_thread(
            get_session_runtime_manager().get,
            session_id,
            subject=_logical_session_subject(request),
        )
        return _json_ok(session)
    except (ValueError, PermissionError) as exc:
        return _json_error(exc, status_code=404)
    except Exception as exc:
        return _json_error(exc)


async def api_logical_session_action(request: Request) -> Response:
    action = str(request.path_params.get("action") or "").strip().lower()
    try:
        _require_ui_scopes(request, "shell:write")
        if action not in {"start", "finish", "cancel", "delete"}:
            raise ValueError("Unsupported logical session action")
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("JSON object required")
        manager = get_session_runtime_manager()
        if action == "start":
            subject = _logical_session_subject(request, create=True)
            if not subject:
                raise PermissionError("Unable to determine logical session principal")
            result = await asyncio.to_thread(
                manager.manage,
                subject,
                action="start",
                label=str(body.get("label") or "").strip() or None,
                objective=str(body.get("prompt") or body.get("objective") or "").strip() or None,
                actor="human",
            )
        else:
            session_id = str(body.get("session_id") or "").strip()
            if not session_id:
                raise ValueError("session_id is required")
            subject = _logical_session_subject(request)
            result = await asyncio.to_thread(
                manager.manage,
                subject,
                action=action,
                session_id=session_id,
                actor="human",
            )
            if action == "delete":
                get_live_channel_manager().detach_logical_session(session_id)
            elif action in {"finish", "cancel"}:
                channel = get_live_channel_manager().active_for_logical_session(
                    session_id,
                    subject=subject,
                )
                if channel is not None:
                    get_live_channel_manager().publish_channel(
                        channel.live_id,
                        "session.updated",
                        actor="human",
                        data={"session_id": session_id, "action": action},
                    )
        return _json_ok(result)
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
            summary_only=True,
        )
        return _json_ok(result)
    except Exception as exc:
        return _json_error(exc)


async def api_audit_detail(request: Request) -> Response:
    try:
        entry_id = str(request.query_params.get("id") or "")
        preview = await asyncio.to_thread(get_audit_entry, entry_id, full=False)
        _require_ui_scopes(request, *_audit_detail_scopes(preview))
        detail = await asyncio.to_thread(get_audit_entry, entry_id)
        columns = _bounded_int(
            request.query_params.get("columns"),
            default=96,
            minimum=8,
            maximum=200,
            label="columns",
        )
        rows = _bounded_int(
            request.query_params.get("rows"),
            default=32,
            minimum=4,
            maximum=100,
            label="rows",
        )
        cell_aspect = _bounded_float(
            request.query_params.get("cell_aspect"),
            default=2.0,
            minimum=0.5,
            maximum=5.0,
            label="cell_aspect",
        )
        return _json_ok(
            await asyncio.to_thread(
                _audit_view_image_detail,
                detail,
                columns=columns,
                rows=rows,
                cell_aspect=cell_aspect,
            )
        )
    except ValueError as exc:
        return _json_error(exc, status_code=404)
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
        live_id = _require_live_human_mutation(request)
        body = await request.json()
        from .oauth import public_base_url

        result = await remote_manager().create_invite(
            body.get("name"),
            body.get("workdir"),
            body.get("ttl_s"),
            base_url=public_base_url(request),
        )
        _record_live_human_action(live_id, "remote.invite", name=body.get("name"))
        return _json_ok(result)
    except Exception as exc:
        return _json_error(exc)


async def api_remote_action(request: Request) -> Response:
    action = str(request.path_params.get("action") or "")
    try:
        _require_ui_scopes(request, "remote:use")
        if not get_settings().remote_enabled:
            raise RuntimeError("Remote worker support is disabled")
        live_id = _require_live_human_mutation(request)
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
        _record_live_human_action(live_id, f"remote.{action}", machine=machine)
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


def _websocket_principal(websocket: WebSocket) -> Principal | None:
    settings = get_settings()
    token = _websocket_token(websocket)
    if token:
        auth_context = get_live_channel_manager().authenticate_context(token)
        if auth_context is not None:
            channel, subject, scopes = auth_context
            principal = Principal(
                email=None,
                subject=subject,
                claims={
                    "auth": "live-channel",
                    "scope": " ".join(scopes),
                    "live_id": channel.live_id,
                },
            )
            try:
                require_scopes(principal, UI_FULL_SCOPES)
            except Exception:
                return None
            return principal
        if settings.auth_mode == "none":
            return None
    elif settings.auth_mode == "none":
        return Principal(email=None, subject="anonymous", claims={"auth": "none"})
    else:
        return None
    try:
        from .oauth import validate_bearer_token

        claims = validate_bearer_token(token, websocket)  # type: ignore[arg-type]
        principal = Principal(email=None, subject=claims.get("sub"), claims=claims)
        require_scopes(principal, UI_FULL_SCOPES)
    except Exception:
        return None
    return principal


def _authorize_websocket(websocket: WebSocket) -> bool:
    return _websocket_principal(websocket) is not None


def _live_websocket_credentials(websocket: WebSocket) -> tuple[str, str] | None:
    token = _websocket_token(websocket)
    if not token:
        return None
    channel = get_live_channel_manager().authenticate(token)
    if channel is None:
        return None
    return channel.live_id, token


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

    try:
        embedded = materialize_embedded_tui(settings.state_dir)
    except (OSError, EOFError) as exc:
        raise RuntimeError(f"Unable to prepare embedded OpenTUI runtime: {exc}") from exc
    if embedded is not None:
        return [str(embedded)]

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
        self.process = subprocess.Popen(
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

    async def exit_code(self) -> int | None:
        code = self.process.poll()
        if code is not None:
            return int(code)
        try:
            return int(
                await asyncio.wait_for(
                    asyncio.to_thread(self.process.wait), timeout=0.25
                )
            )
        except TimeoutError:
            return None

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

    def _write_once(self, text: str) -> None:
        result = self.process.write(text)
        if result is not None and not isinstance(result, int):
            raise OSError(f"Unexpected ConPTY write result: {type(result).__name__}")

    async def write(self, data: bytes) -> None:
        if data:
            text = data.decode("utf-8", errors="replace")
            await asyncio.to_thread(self._write_once, text)

    async def exit_code(self) -> int | None:
        for _ in range(25):
            try:
                if not self.process.isalive():
                    status = getattr(self.process, "exitstatus", None)
                    return int(status) if status is not None else None
            except Exception:
                return None
            await asyncio.sleep(0.01)
        return None

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await asyncio.to_thread(self.process.terminate, True)


def _spawn_tui_process(
    cols: int,
    rows: int,
    cell_aspect: float = 2.0,
):  # noqa: ANN201
    settings = get_settings()
    env = os.environ.copy()
    env.update(
        {
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            # The browser wrapper is xterm.js with the image addon. Advertising
            # VS Code terminal compatibility enables the image protocol path supported
            # by that terminal implementation.
            "TERM_PROGRAM": "vscode",
            "TERM_PROGRAM_VERSION": "local-shell-mcp",
            "LOCAL_SHELL_MCP_UI_API_BASE": f"http://127.0.0.1:{settings.port}{UI_API_PREFIX}",
            "LOCAL_SHELL_MCP_UI_MODE": "web",
            UI_LOCAL_TOKEN_ENV: get_or_create_ui_local_token(),
            "LOCAL_SHELL_MCP_UI_CELL_ASPECT": f"{cell_aspect:.4f}",
        }
    )
    command = resolve_tui_command()
    if os.name == "nt":
        return _WindowsPtyProcess(command, env, cols, rows)
    return _UnixPtyProcess(command, env, cols, rows)


class _PollingShellProcess:
    """Adapt the shell read/send API to the byte-stream interface used by WebSockets.

    Remote workers and native/ConPTY persistent shells cannot be attached as a local
    PTY client. For those backends, send screen snapshots only when the captured pane
    changes and forward input through the persistent-shell API. The browser receives an
    ANSI screen and scrollback clear before each replacement snapshot, so polling does
    not duplicate captured history in xterm.js.
    """

    def __init__(self, machine: str, session_id: str, cols: int, rows: int):
        self.machine = machine
        self.session_id = session_id
        self.cols = cols
        self.rows = rows
        self._closed = False
        self._exit_code: int | None = None
        self._last_output: str | None = None
        self._consecutive_errors = 0

    async def _dispatch(self, local_call: Callable[[], Any | Awaitable[Any]], tool: str, args: dict[str, Any]) -> Any:
        return await _machine_dispatch(self.machine, local_call, tool, args)

    async def read(self) -> bytes:
        while not self._closed:
            try:
                result = await self._dispatch(
                    lambda: read_shell(self.session_id, max(300, self.rows * 8)),
                    "shell_read",
                    {"session_id": self.session_id, "lines": max(300, self.rows * 8)},
                )
                self._consecutive_errors = 0
            except Exception as exc:
                self._consecutive_errors += 1
                if self._consecutive_errors >= 3:
                    self._exit_code = 1
                    self._closed = True
                    return f"\r\nPersistent terminal stream stopped: {type(exc).__name__}: {exc}\r\n".encode()
                await asyncio.sleep(0.25)
                continue

            output = str((result or {}).get("output") or "") if isinstance(result, dict) else str(result or "")
            if output != self._last_output:
                self._last_output = output
                return ("\x1b[?25l\x1b[3J\x1b[H\x1b[2J" + output + "\x1b[?25h").encode(
                    "utf-8", errors="replace"
                )
            await asyncio.sleep(0.12)
        return b""

    async def write(self, data: bytes) -> None:
        if self._closed or not data:
            return
        text = data.decode("utf-8", errors="replace")
        await self._dispatch(
            lambda: send_shell(self.session_id, text, False),
            "shell_send",
            {"session_id": self.session_id, "input_text": text, "enter": False},
        )

    async def resize(self, cols: int, rows: int) -> None:
        self.cols = cols
        self.rows = rows
        await self._dispatch(
            lambda: resize_shell(self.session_id, cols, rows),
            "shell_resize",
            {"session_id": self.session_id, "cols": cols, "rows": rows},
        )

    async def exit_code(self) -> int | None:
        return self._exit_code if self._closed else None

    async def close(self) -> None:
        self._closed = True


async def _spawn_shell_process(machine: str, session_id: str, cols: int, rows: int):  # noqa: ANN201
    sessions = await _machine_dispatch(machine, list_shells, "shell_list", {})
    rows_payload = list((sessions or {}).get("sessions") or []) if isinstance(sessions, dict) else []
    session = next(
        (row for row in rows_payload if str(row.get("session_id") or "") == session_id),
        None,
    )
    if session is None:
        raise ValueError(f"Persistent terminal session not found: {session_id}")

    backend = str(session.get("backend") or "")
    if machine == "local" and os.name != "nt" and backend.startswith("tmux-"):
        selection = resolve_tmux()
        if selection.path:
            env = subprocess_env()
            env.update(
                {
                    "TERM": "xterm-256color",
                    "COLORTERM": "truecolor",
                    "TERM_PROGRAM": "local-shell-mcp-webui",
                }
            )
            process = _UnixPtyProcess(
                [
                    selection.path,
                    "-L",
                    tmux_socket_name(),
                    "attach-session",
                    "-t",
                    f"={session_id}",
                ],
                env,
                cols,
                rows,
            )
            process._tmux_session_id = session_id
            return process
    return _PollingShellProcess(machine, session_id, cols, rows)


async def _tmux_scrollback_command(args: list[str]):  # noqa: ANN201
    with suppress_audit():
        return await tmux(args, bypass_limit=True)


def _parse_tmux_scrollback_state(parts: list[str]) -> dict[str, Any]:
    if len(parts) != 3:
        raise RuntimeError("Unexpected tmux scrollback state")
    copy_mode = parts[1] == "copy-mode"
    try:
        history = max(0, int(parts[0] or 0))
        position = max(0, int(parts[2] or 0)) if copy_mode else 0
    except ValueError as exc:
        raise RuntimeError("Invalid tmux scrollback state") from exc
    return {
        "type": "scrollback",
        "supported": True,
        "history": history,
        "position": min(position, history),
        "copy_mode": copy_mode,
    }


async def _tmux_scrollback_state(
    process: Any, pane_id: str | None = None
) -> dict[str, Any]:
    session_id = getattr(process, "_tmux_session_id", None)
    if not session_id:
        return {
            "type": "scrollback",
            "supported": False,
            "history": 0,
            "position": 0,
            "copy_mode": False,
        }

    target = pane_id or f"={session_id}:"
    result = await _tmux_scrollback_command(
        [
            "display-message",
            "-p",
            "-t",
            target,
            "#{history_size}\t#{pane_mode}\t#{scroll_position}",
        ]
    )
    if not result.ok:
        raise RuntimeError(result.stderr or result.stdout or "Unable to read tmux scrollback state")
    return _parse_tmux_scrollback_state(result.stdout.rstrip("\r\n").split("\t"))


async def _tmux_scrollback_baseline(process: Any) -> tuple[dict[str, Any], str]:
    session_id = getattr(process, "_tmux_session_id", None)
    if not session_id:
        raise RuntimeError("tmux session unavailable")
    result = await _tmux_scrollback_command(
        [
            "display-message",
            "-p",
            "-t",
            f"={session_id}:",
            "#{pane_id}\t#{history_size}\t#{pane_mode}\t#{scroll_position}",
        ]
    )
    if not result.ok:
        raise RuntimeError(result.stderr or result.stdout or "Unable to read tmux scrollback baseline")
    parts = result.stdout.rstrip("\r\n").split("\t")
    if len(parts) != 4 or not parts[0].startswith("%"):
        raise RuntimeError("Unexpected tmux scrollback baseline")
    return _parse_tmux_scrollback_state(parts[1:]), parts[0]


async def _tmux_scroll_to(
    process: Any, position: int, pane_id: str | None = None
) -> dict[str, Any]:
    session_id = getattr(process, "_tmux_session_id", None)
    if not session_id:
        return await _tmux_scrollback_state(process, pane_id)

    tmux_target = pane_id or f"={session_id}:"
    state = await _tmux_scrollback_state(process, pane_id)
    history = int(state["history"])
    target = max(0, min(int(position), history))
    current = int(state["position"])
    copy_mode = bool(state.get("copy_mode"))

    if target == 0:
        if copy_mode:
            result = await _tmux_scrollback_command(
                ["send-keys", "-X", "-t", tmux_target, "cancel"]
            )
            if not result.ok:
                raise RuntimeError(result.stderr or result.stdout or "Unable to leave tmux copy mode")
        return await _tmux_scrollback_state(process, pane_id)

    if target == current and copy_mode:
        return state
    if not copy_mode:
        result = await _tmux_scrollback_command(["copy-mode", "-t", tmux_target])
        if not result.ok:
            raise RuntimeError(result.stderr or result.stdout or "Unable to enter tmux copy mode")
    result = await _tmux_scrollback_command(
        ["send-keys", "-X", "-t", tmux_target, "history-bottom"]
    )
    if not result.ok:
        raise RuntimeError(result.stderr or result.stdout or "Unable to scroll tmux history")
    result = await _tmux_scrollback_command(
        ["send-keys", "-N", str(target), "-X", "-t", tmux_target, "scroll-up"]
    )
    if not result.ok:
        raise RuntimeError(result.stderr or result.stdout or "Unable to scroll tmux history")
    return await _tmux_scrollback_state(process, pane_id)


async def _tmux_restore_copy_mode_position(
    process: Any, position: int, pane_id: str | None = None
) -> None:
    session_id = getattr(process, "_tmux_session_id", None)
    if not session_id:
        return
    target = pane_id or f"={session_id}:"
    state = await _tmux_scrollback_state(process, pane_id)
    history = int(state["history"])
    requested = max(0, min(int(position), history))
    if state.get("copy_mode") and int(state.get("position") or 0) == requested:
        return
    if not state.get("copy_mode"):
        result = await _tmux_scrollback_command(["copy-mode", "-t", target])
        if not result.ok:
            raise RuntimeError(result.stderr or result.stdout or "Unable to restore tmux copy mode")
    result = await _tmux_scrollback_command(
        ["send-keys", "-X", "-t", target, "history-bottom"]
    )
    if not result.ok:
        raise RuntimeError(result.stderr or result.stdout or "Unable to restore tmux scrollback position")
    if requested:
        result = await _tmux_scrollback_command(
            ["send-keys", "-N", str(requested), "-X", "-t", target, "scroll-up"]
        )
        if not result.ok:
            raise RuntimeError(
                result.stderr or result.stdout or "Unable to restore tmux scrollback position"
            )


class _TmuxScrollbackAttachmentGroup:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.members: set[int] = set()
        self.initial_copy_mode: bool | None = None
        self.initial_position = 0
        self.owned_copy_mode = False
        self.pane_id: str | None = None
        self.prefix_pending = False
        self.binding_sync_pending = False


_TMUX_SCROLLBACK_ATTACHMENTS: dict[str, _TmuxScrollbackAttachmentGroup] = {}


async def _tmux_restore_attachment_baseline(
    process: Any, group: _TmuxScrollbackAttachmentGroup
) -> None:
    if group.pane_id is None or group.initial_copy_mode is None:
        group.owned_copy_mode = False
        return
    state = await _tmux_scrollback_state(process, group.pane_id)
    copy_mode = bool(state.get("copy_mode"))
    position = int(state.get("position") or 0)
    if group.initial_copy_mode is False:
        if group.owned_copy_mode and copy_mode:
            await _tmux_scroll_to(process, 0, group.pane_id)
    elif not copy_mode or position != group.initial_position:
        await _tmux_restore_copy_mode_position(
            process, group.initial_position, group.pane_id
        )
    group.owned_copy_mode = False


async def _tmux_sync_attachment_pane(
    process: Any,
    group: _TmuxScrollbackAttachmentGroup,
    *,
    claim_copy_mode: bool = False,
) -> dict[str, Any]:
    state, pane_id = await _tmux_scrollback_baseline(process)
    if group.pane_id != pane_id:
        try:
            await _tmux_restore_attachment_baseline(process, group)
        except Exception:
            _LOGGER.debug(
                "Unable to restore previous Native WebUI tmux pane during retarget",
                exc_info=True,
            )
        group.pane_id = pane_id
        group.initial_copy_mode = bool(state.get("copy_mode"))
        group.initial_position = int(state.get("position") or 0)
        group.owned_copy_mode = False
    elif claim_copy_mode and group.initial_copy_mode is False and state.get("copy_mode"):
        group.owned_copy_mode = True
    return state


async def _register_tmux_scrollback_attachment(
    process: Any, marker: int
) -> tuple[str, _TmuxScrollbackAttachmentGroup] | None:
    session_id = getattr(process, "_tmux_session_id", None)
    if not session_id:
        return None
    key = str(session_id)
    while True:
        group = _TMUX_SCROLLBACK_ATTACHMENTS.setdefault(key, _TmuxScrollbackAttachmentGroup())
        async with group.lock:
            if _TMUX_SCROLLBACK_ATTACHMENTS.get(key) is not group:
                continue
            if not group.members:
                try:
                    state, pane_id = await _tmux_scrollback_baseline(process)
                except Exception:
                    _LOGGER.debug(
                        "Unable to read initial Native WebUI scrollback state", exc_info=True
                    )
                    if _TMUX_SCROLLBACK_ATTACHMENTS.get(key) is group:
                        _TMUX_SCROLLBACK_ATTACHMENTS.pop(key, None)
                    return None
                if not state.get("supported"):
                    if _TMUX_SCROLLBACK_ATTACHMENTS.get(key) is group:
                        _TMUX_SCROLLBACK_ATTACHMENTS.pop(key, None)
                    return None
                group.initial_copy_mode = bool(state.get("copy_mode"))
                group.initial_position = int(state.get("position") or 0)
                group.pane_id = pane_id
            group.members.add(marker)
            return key, group


async def _release_tmux_scrollback_attachment(
    process: Any,
    marker: int,
    registration: tuple[str, _TmuxScrollbackAttachmentGroup] | None,
) -> None:
    if registration is None:
        return
    key, group = registration
    async with group.lock:
        if _TMUX_SCROLLBACK_ATTACHMENTS.get(key) is not group:
            return
        group.members.discard(marker)
        if group.members:
            return
        try:
            try:
                await _tmux_sync_attachment_pane(
                    process,
                    group,
                    claim_copy_mode=group.binding_sync_pending,
                )
                group.binding_sync_pending = False
            except Exception:
                _LOGGER.debug(
                    "Unable to refresh Native WebUI tmux pane before detach",
                    exc_info=True,
                )
            await _tmux_restore_attachment_baseline(process, group)
        except Exception:
            _LOGGER.debug("Unable to leave Native WebUI tmux copy mode", exc_info=True)
        finally:
            if _TMUX_SCROLLBACK_ATTACHMENTS.get(key) is group:
                _TMUX_SCROLLBACK_ATTACHMENTS.pop(key, None)


async def _tmux_apply_scrollback_request(
    process: Any,
    registration: tuple[str, _TmuxScrollbackAttachmentGroup],
    control: dict[str, Any],
) -> dict[str, Any]:
    _, group = registration
    async with group.lock:
        state = await _tmux_sync_attachment_pane(process, group)
        current = int(state["position"])
        history = int(state["history"])
        if "position" in control:
            requested = int(control.get("position") or 0)
        else:
            requested = current + int(control.get("offset") or 0)
        requested = max(0, min(requested, history))
        if group.initial_copy_mode is False and requested > 0:
            group.owned_copy_mode = True
        try:
            state = await _tmux_scroll_to(process, requested, group.pane_id)
        except Exception:
            try:
                await _tmux_restore_attachment_baseline(process, group)
            except Exception:
                _LOGGER.debug(
                    "Unable to roll back failed Native WebUI scrollback mutation",
                    exc_info=True,
                )
            raise
        if group.initial_copy_mode is False:
            group.owned_copy_mode = requested > 0 and bool(state.get("copy_mode"))
        return state


async def _tmux_claim_scrollback_state(
    process: Any,
    registration: tuple[str, _TmuxScrollbackAttachmentGroup],
) -> dict[str, Any]:
    _, group = registration
    async with group.lock:
        return await _tmux_sync_attachment_pane(
            process, group, claim_copy_mode=True
        )


async def _tmux_write_terminal_input(
    process: Any,
    registration: tuple[str, _TmuxScrollbackAttachmentGroup] | None,
    data: bytes,
) -> None:
    if registration is None:
        await process.write(data)
        return
    _, group = registration
    async with group.lock:
        if group.binding_sync_pending:
            await _tmux_sync_attachment_pane(process, group, claim_copy_mode=True)
            group.binding_sync_pending = False
        elif group.owned_copy_mode:
            await _tmux_sync_attachment_pane(process, group)
        if group.owned_copy_mode:
            await _tmux_scroll_to(process, 0, group.pane_id)
            group.owned_copy_mode = False
        binding_command = group.prefix_pending
        await process.write(data)
        if binding_command:
            group.prefix_pending = False
            group.binding_sync_pending = True
        if _tmux_input_may_be_prefix(data):
            if binding_command:
                group.binding_sync_pending = True
            group.prefix_pending = True


def _tmux_input_may_be_prefix(data: bytes) -> bool:
    if len(data) != 1:
        return False
    value = data[0]
    return value < 0x20 and value not in {0x09, 0x0A, 0x0D, 0x1B}


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
    initial_live_credentials = _live_websocket_credentials(websocket)
    if not _authorize_websocket(websocket):
        await websocket.close(code=4401, reason="OAuth authentication required")
        return
    if initial_live_credentials is not None:
        await websocket.close(
            code=4403,
            reason="The embedded live workspace uses persistent shell sessions, not the TUI bridge",
        )
        return

    settings = get_settings()
    if settings.disable_local:
        await websocket.close(
            code=4403,
            reason="The local TUI bridge is unavailable when local access is disabled",
        )
        return
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
        cell_aspect = _bounded_float(
            websocket.query_params.get("cell_aspect"),
            default=2.0,
            minimum=0.5,
            maximum=5.0,
            label="cell_aspect",
        )
        process = _spawn_tui_process(cols, rows, cell_aspect)
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
                if await process.exit_code() == 0:
                    await websocket.close(
                        code=UI_TUI_EXIT_CODE, reason="TUI process exited"
                    )
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


async def ui_shell_websocket(websocket: WebSocket) -> None:
    initial_live_credentials = _live_websocket_credentials(websocket)
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

    machine = str(websocket.query_params.get("machine") or "local")
    session_id = str(websocket.query_params.get("session_id") or "")
    scrollback_enabled = str(websocket.query_params.get("scrollback") or "").lower() in {
        "1",
        "true",
        "yes",
    }
    live_id = (
        initial_live_credentials[0] if initial_live_credentials is not None else None
    )
    live_token = initial_live_credentials[1] if initial_live_credentials is not None else None
    try:
        if not session_id:
            raise ValueError("session_id is required")
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
        process = await _spawn_shell_process(machine, session_id, cols, rows)
    except Exception as exc:
        _ACTIVE_UI_TERMINALS.discard(marker)
        _LOGGER.exception("Unable to attach the Native WebUI terminal")
        detail = f"{type(exc).__name__}: {exc}"
        await websocket.send_bytes(f"\r\nUnable to attach terminal: {detail}\r\n".encode())
        await websocket.close(code=1011, reason=detail[:120])
        return

    loop = asyncio.get_running_loop()
    last_activity = loop.time()
    send_lock = asyncio.Lock()
    scrollback_updated_at = 0.0
    scrollback_refresh_task: asyncio.Task[None] | None = None
    scrollback_registration: tuple[str, _TmuxScrollbackAttachmentGroup] | None = None
    if scrollback_enabled:
        try:
            scrollback_registration = await _register_tmux_scrollback_attachment(process, marker)
        except Exception:
            _LOGGER.debug("Unable to register Native WebUI scrollback attachment", exc_info=True)
    scrollback_available = scrollback_enabled and scrollback_registration is not None

    def live_credential_valid() -> bool:
        if not live_id or not live_token:
            return True
        channel = get_live_channel_manager().authenticate(live_token)
        return channel is not None and channel.live_id == live_id

    async def reject_invalid_live_credential() -> bool:
        if live_credential_valid():
            return False
        await websocket.close(code=4401, reason="Live workspace credential expired or rotated")
        return True

    async def send_scrollback_state(*, force: bool = False) -> None:
        nonlocal scrollback_refresh_task, scrollback_updated_at
        if not scrollback_available or scrollback_registration is None:
            return
        now = loop.time()
        remaining = 0.75 - (now - scrollback_updated_at)
        if not force and remaining > 0:
            if scrollback_refresh_task is None or scrollback_refresh_task.done():
                async def delayed_refresh() -> None:
                    nonlocal scrollback_refresh_task
                    try:
                        await asyncio.sleep(remaining)
                        await send_scrollback_state(force=True)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        _LOGGER.debug(
                            "Unable to send trailing Native WebUI scrollback state",
                            exc_info=True,
                        )
                    finally:
                        if scrollback_refresh_task is asyncio.current_task():
                            scrollback_refresh_task = None

                scrollback_refresh_task = asyncio.create_task(delayed_refresh())
            return
        try:
            _, group = scrollback_registration
            async with group.lock:
                state = await _tmux_sync_attachment_pane(
                    process,
                    group,
                    claim_copy_mode=group.binding_sync_pending,
                )
                group.binding_sync_pending = False
        except Exception:
            _LOGGER.debug("Unable to read Native WebUI scrollback state", exc_info=True)
            return
        scrollback_updated_at = now
        async with send_lock:
            await websocket.send_text(json.dumps(state, separators=(",", ":")))

    async def sender() -> None:
        nonlocal last_activity
        await send_scrollback_state(force=True)
        while True:
            data = await process.read()
            if not data:
                if await process.exit_code() is not None:
                    await websocket.close(
                        code=UI_SHELL_EXIT_CODE,
                        reason="Persistent terminal attachment exited",
                    )
                return
            if await reject_invalid_live_credential():
                return
            last_activity = loop.time()
            async with send_lock:
                await websocket.send_bytes(data)
            await send_scrollback_state()

    async def receiver() -> None:
        nonlocal cols, rows, last_activity
        idle_timeout = max(0, settings.ui_terminal_idle_timeout_s)

        while True:
            if idle_timeout:
                remaining = _idle_timeout_remaining(last_activity, idle_timeout, loop.time())
                if remaining <= 0:
                    await websocket.close(code=4408, reason="WebUI terminal session idle timeout")
                    return
                try:
                    message = await asyncio.wait_for(websocket.receive(), timeout=remaining)
                except TimeoutError:
                    if _idle_timeout_remaining(last_activity, idle_timeout, loop.time()) > 0:
                        continue
                    await websocket.close(code=4408, reason="WebUI terminal session idle timeout")
                    return
            else:
                message = await websocket.receive()
            last_activity = loop.time()
            if message["type"] == "websocket.disconnect":
                return
            if await reject_invalid_live_credential():
                return
            if message.get("bytes") is not None:
                data = message["bytes"]
                await _tmux_write_terminal_input(process, scrollback_registration, data)
                continue
            text = message.get("text")
            if not text:
                continue
            try:
                control = json.loads(text)
            except json.JSONDecodeError:
                await _tmux_write_terminal_input(process, scrollback_registration, text.encode())
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
                resized = process.resize(cols, rows)
                if asyncio.iscoroutine(resized):
                    await resized
                await send_scrollback_state()
            elif scrollback_available and scrollback_registration is not None and control.get("type") == "scrollback":
                try:
                    state = await _tmux_apply_scrollback_request(
                        process, scrollback_registration, control
                    )
                except (TypeError, ValueError, OverflowError):
                    await websocket.close(code=4400, reason="Invalid scrollback request")
                    return
                except Exception:
                    _LOGGER.debug("Unable to scroll Native WebUI terminal", exc_info=True)
                    request_id = control.get("request_id")
                    if isinstance(request_id, int) and not isinstance(request_id, bool):
                        async with send_lock:
                            await websocket.send_text(
                                json.dumps(
                                    {"type": "scrollback-ack", "request_id": request_id},
                                    separators=(",", ":"),
                                )
                            )
                    continue
                request_id = control.get("request_id")
                if isinstance(request_id, int) and not isinstance(request_id, bool):
                    state = {**state, "request_id": request_id}
                async with send_lock:
                    await websocket.send_text(json.dumps(state, separators=(",", ":")))
            elif (
                scrollback_available
                and scrollback_registration is not None
                and control.get("type") == "scrollback-sync"
            ):
                try:
                    state = await _tmux_claim_scrollback_state(
                        process, scrollback_registration
                    )
                except Exception:
                    _LOGGER.debug(
                        "Unable to synchronize Native WebUI terminal scrollback",
                        exc_info=True,
                    )
                    continue
                async with send_lock:
                    await websocket.send_text(json.dumps(state, separators=(",", ":")))

    async def credential_watcher() -> None:
        while live_id and live_token:
            await asyncio.sleep(5)
            if await reject_invalid_live_credential():
                return

    tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
    if live_id and live_token:
        tasks.append(asyncio.create_task(credential_watcher()))
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
        if scrollback_refresh_task is not None and not scrollback_refresh_task.done():
            scrollback_refresh_task.cancel()
            await asyncio.gather(scrollback_refresh_task, return_exceptions=True)
        await _release_tmux_scrollback_attachment(process, marker, scrollback_registration)
        await process.close()
        with contextlib.suppress(Exception):
            await websocket.close()


async def ui_root_redirect(request: Request) -> RedirectResponse:  # noqa: ARG001
    ui_path = get_settings().ui_path.strip("/")
    return RedirectResponse(f"./{ui_path}/", status_code=307)


def ui_routes() -> list[Any]:
    settings = get_settings()
    if not settings.ui_enabled:
        return []
    ui_path = "/" + settings.ui_path.strip("/")
    return [
        Route("/", ui_root_redirect, methods=["GET"]),
        Route(ui_path, ui_index, methods=["GET"]),
        Route(ui_path + "/", ui_index, methods=["GET"]),
        Route(ui_path + "/callback", ui_index, methods=["GET"]),
        Route(ui_path + "/wallpaper", ui_wallpaper, methods=["GET"]),
        Route(ui_path + "/assets/{path:path}", ui_asset, methods=["GET"]),
        WebSocketRoute(ui_path + "/ws", ui_terminal_websocket),
        WebSocketRoute(ui_path + "/ws/shell", ui_shell_websocket),
        Route(UI_API_PREFIX + "/bootstrap", api_bootstrap, methods=["GET"]),
        Route(UI_API_PREFIX + "/dashboard", api_dashboard, methods=["GET"]),
        Route(UI_API_PREFIX + "/machines", api_machines, methods=["GET"]),
        Route(UI_API_PREFIX + "/files", api_files, methods=["GET"]),
        Route(UI_API_PREFIX + "/files/preview", api_file_preview, methods=["GET"]),
        Route(UI_API_PREFIX + "/files/content", api_file_content, methods=["GET"]),
        Route(UI_API_PREFIX + "/files/{action}", api_file_action, methods=["POST"]),
        Route(UI_API_PREFIX + "/terminals", api_terminals, methods=["GET"]),
        Route(UI_API_PREFIX + "/terminals/read", api_terminal_read, methods=["GET"]),
        Route(UI_API_PREFIX + "/terminals/{action}", api_terminal_action, methods=["POST"]),
        Route(UI_API_PREFIX + "/logical-sessions", api_logical_sessions, methods=["GET"]),
        Route(UI_API_PREFIX + "/logical-sessions/detail", api_logical_session_detail, methods=["GET"]),
        Route(UI_API_PREFIX + "/logical-sessions/{action}", api_logical_session_action, methods=["POST"]),
        Route(UI_API_PREFIX + "/audit", api_audit, methods=["GET"]),
        Route(UI_API_PREFIX + "/audit/detail", api_audit_detail, methods=["GET"]),
        Route(UI_API_PREFIX + "/remotes", api_remotes, methods=["GET", "POST"]),
        Route(UI_API_PREFIX + "/remotes/{action}", api_remote_action, methods=["POST"]),
    ]
