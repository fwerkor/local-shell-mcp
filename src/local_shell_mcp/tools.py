from __future__ import annotations

import asyncio
import base64
import inspect
import json
import subprocess
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlparse

from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, Icon, ImageContent, TextContent, ToolAnnotations
from pathspec.gitignore import GitIgnoreSpec
from pydantic import BaseModel, ConfigDict, Field, create_model

from . import __version__
from .audit import audit, audit_call_context, audit_result_ok
from .auth import current_principal, principal_scopes, require_current_scopes
from .browser_sessions import get_browser_session_manager
from .chat_dispatch_bridge import manage_chat_dispatch
from .deprecated_tools import DeprecatedToolFastMCP as FastMCP
from .downloads import create_share_link, list_share_links, revoke_share_link
from .dynamic_mcp import DynamicMCPManager
from .errors import (
    PathNotFoundError,
    ShellExecutableNotFoundError,
    workspace_path_not_found_error,
)
from .fs_ops import (
    delete_path,
    edit_text,
    glob_paths,
    list_dir,
    missing_path_context,
    prune_temp_dir,
    read_text,
    read_texts,
    relative_display,
    resolve_path,
    temp_dir,
    write_content,
    write_text,
)
from .image_ops import ImageFile, assert_view_image_size, read_image
from .jobs import (
    JOB_LIST_DEFAULT_LIMIT,
    ManagedJobContext,
    list_jobs,
    register_managed_job_handler,
    retry_job,
    start_job,
    start_managed_job,
    stop_job,
    tail_job,
)
from .live_channel import (
    LIVE_RESOURCE_COMPAT_URIS,
    LIVE_RESOURCE_MIME,
    LIVE_RESOURCE_TEMPLATE_URI,
    LIVE_RESOURCE_URI,
    LIVE_RESOURCE_VERSIONED_URI,
    get_live_channel_manager,
)
from .models import ToolResult
from .models import ok_result as _ok
from .oauth import ALL_OAUTH_SCOPES
from .patch_ops import git_apply_command, git_apply_prefix, normalize_patch_text
from .playwright_ops import playwright_run_script
from .process_utils import managed_process_kwargs
from .remote import REMOTE_WORKER_TRANSFER_LANE, remote_manager
from .remote_transfer import (
    create_download_ticket,
    create_upload_ticket,
    get_upload_ticket_status,
    revoke_transfer_ticket,
)
from .search_ops import grep, tree
from .session_runtime import (
    SESSION_IN_FLIGHT_LEASE_S,
    SessionToolLeaseStartPersistenceError,
    get_session_runtime_manager,
)
from .settings import get_settings, safe_settings_dump
from .shell_ops import (
    PUBLIC_RUN_SHELL_DEFAULT_TIMEOUT_S,
    PUBLIC_RUN_SHELL_TIMEOUT_CAP_S,
    PUBLIC_TOOL_WATCHDOG_TIMEOUT_S,
    kill_shell,
    list_shells,
    public_run_shell,
    public_run_shell_timeout,
    quote_shell_argument,
    quote_shell_executable,
    read_shell,
    run_shell,
    send_shell,
    start_shell,
)
from .skill_ops import (
    list_installed_skills,
    load_installed_skill,
    read_installed_skill_file,
)
from .state_store import get_state_store
from .tmux_helper import persistent_shell_backend_info
from .transfer_ops import (
    DEFAULT_TRANSFER_CHUNK_BYTES,
    normalize_chunk_size,
    transfer_alloc_temp_path,
    transfer_pack_dir_async,
    transfer_stat,
    transfer_unpack_archive_async,
)
from .version import version_info as get_version_info


class TextEdit(BaseModel):
    """One exact text replacement accepted by the unified edit tool."""

    model_config = ConfigDict(extra="forbid", strict=True)

    old: str = Field(min_length=1)
    new: str
    replace_all: bool = False


class ViewImageResult(BaseModel):
    """Structured metadata accompanying native MCP image content."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    path: str
    machine: str | None = None
    mime_type: str | None = None
    bytes: int | None = None
    message: str = ""
    error_type: str | None = None


class LiveChannelResult(BaseModel):
    """Model-visible state returned when the interactive workspace is opened."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    live_id: str
    session_id: str | None = None
    api_base: str
    ui_path: str
    machine: str
    cwd: str
    message: str = "Live workspace ready"


def _error_call_result(data: dict[str, Any], message: str) -> CallToolResult:
    structured = {"ok": False, "message": message, "data": data}
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=json.dumps(structured, ensure_ascii=False, indent=2),
            )
        ],
        structuredContent=structured,
        isError=True,
    )


def _handled_error(exc: Exception) -> CallToolResult:
    audit("tool_error", error=repr(exc))
    if isinstance(exc, ShellExecutableNotFoundError):
        message = f"Shell executable not found: {exc.executable}"
        return _error_call_result(
            {
                "status": "executable_not_found",
                "error_type": "FileNotFoundError",
                "message": str(exc),
                "executable": exc.executable,
                "command": exc.command,
                "cwd": exc.cwd,
                "original_error": exc.original_error,
            },
            message,
        )
    path_error = exc if isinstance(exc, PathNotFoundError) else None
    if isinstance(exc, FileNotFoundError) and path_error is None:
        path_error = workspace_path_not_found_error(exc, get_settings().workspace_root)
    if path_error is not None:
        with suppress(Exception):
            context = missing_path_context(path_error.path)
            return _error_call_result(
                {
                    "status": "not_found",
                    "error_type": "FileNotFoundError",
                    "message": str(exc),
                    **context,
                },
                f"Path not found: {context['path']}",
            )
    message = str(exc) or type(exc).__name__
    return _error_call_result(
        {
            "status": "error",
            "error_type": type(exc).__name__,
            "message": message,
        },
        message,
    )


def _sync(coro):  # noqa: ANN001
    return asyncio.get_event_loop().run_until_complete(coro)


async def _tool_call(operation, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
    try:
        result = operation(*args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        return _ok(result)
    except Exception as exc:
        return _handled_error(exc)


def _assert_text_input_size(label: str, text: str, limit: int | None = None) -> None:
    settings = get_settings()
    max_bytes = limit or settings.max_file_write_bytes
    size = len(text.encode("utf-8"))
    if size > max_bytes:
        raise ValueError(f"Refusing {label} of {size} bytes; max is {max_bytes}")


async def _apply_patch_text(patch: str, cwd: str = ".") -> dict:
    _assert_text_input_size("patch", patch)
    normalized_patch = await asyncio.to_thread(normalize_patch_text, patch, cwd)
    await asyncio.to_thread(prune_temp_dir)
    patch_path = temp_dir() / f"patch-{uuid.uuid4().hex}.diff"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(patch_path.write_bytes, normalized_patch.encode("utf-8"))
    quoted = quote_shell_argument(str(patch_path))
    git_bin = get_settings().git_bin
    git = quote_shell_executable(git_bin)
    prefix = await asyncio.to_thread(git_apply_prefix, git_bin, cwd)
    quoted_prefix = quote_shell_argument(prefix) if prefix else None
    check_result = await run_shell(
        git_apply_command(git, quoted, quoted_prefix, check=True),
        cwd=cwd,
        timeout_s=60,
        max_output_bytes=500_000,
    )
    if check_result.exit_code != 0 or check_result.timed_out:
        return {**check_result.model_dump(), "patch_path": relative_display(patch_path)}

    result = await run_shell(
        git_apply_command(git, quoted, quoted_prefix),
        cwd=cwd,
        timeout_s=60,
        max_output_bytes=500_000,
    )
    return {**result.model_dump(), "patch_path": relative_display(patch_path)}


async def _run_python(code: str, cwd: str = ".", timeout_s: int = 60) -> dict:
    _assert_text_input_size("Python script", code)
    await asyncio.to_thread(prune_temp_dir)
    path = temp_dir() / f"script-{uuid.uuid4().hex}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_text, code, encoding="utf-8")
    python = quote_shell_executable(get_settings().python_bin)
    result = await run_shell(
        f"{python} {quote_shell_argument(str(path))}",
        cwd=cwd,
        timeout_s=public_run_shell_timeout(timeout_s),
        max_output_bytes=1_000_000,
    )
    return {**result.model_dump(), "script_path": relative_display(path)}


SECRET_PATTERNS = {
    "github_token": r"gh[pousr]_[A-Za-z0-9_]{36,}",
    "aws_access_key": r"AKIA[0-9A-Z]{16}",
    "private_key": r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----",
    "generic_assignment": r"(?i)(token|secret|password|passwd|api_key|apikey)\s*[:=]\s*['\"][^'\"]{8,}['\"]",
}


def _oauth_security_scheme(scopes: list[str] | tuple[str, ...]) -> dict[str, Any]:
    return {"type": "oauth2", "scopes": list(ALL_OAUTH_SCOPES)}


NOAUTH_SECURITY_SCHEMES = [{"type": "noauth"}]
PUBLIC_TOOL_TIMEOUT_S = PUBLIC_TOOL_WATCHDOG_TIMEOUT_S
MCP_BASE_INSTRUCTIONS = (
    "When a task may benefit from an installed Agent Skill, call skill_list first "
    "to discover the exact Skill name and description. Before following a Skill's "
    "workflow, call skill_load with that exact name. Call skill_read only when "
    "a related file returned by skill_load is needed. Skills use this fixed tool "
    "surface; do not expect per-Skill MCP tools. When a registered external MCP may "
    "provide a capability, use mcp_tool_search, then mcp_tool_inspect, then mcp_tool_call; "
    "dynamic MCP tools never appear directly in tools/list."
)
LOGICAL_SESSION_MCP_INSTRUCTIONS = (
    " For substantive tool-driven work, use exactly one durable Logical Session. "
    "Start a new task with session_manage(action='start', ...). "
    "Only continue an existing Session when its session_id is already present in this conversation or the "
    "user explicitly provides that session_id; then call session_manage(action='resume', session_id=...). "
    "Never discover, infer, or auto-select a Session from other conversations. After start or resume, clearly "
    "tell the user the active session_id. Include it again at meaningful progress checkpoints and before ending "
    "the turn so the user can hand it to another conversation. Ordinary tools expose a required nullable "
    "logical_session_id; while working in a Session, pass the exact session_id returned by session_manage. "
    "Use null only when no Logical Session is active. Keep progress current with session_manage(action='report', "
    "session_id=...) at meaningful checkpoints. Logical Sessions are independent of MCP transports, machines, "
    "and working directories. plan_manage and workspace_open take the same session_id explicitly and never infer it "
    "from the transport. plan_manage is optional Goal mode owned by the Logical Session."
)
MCP_INSTRUCTIONS = MCP_BASE_INSTRUCTIONS + LOGICAL_SESSION_MCP_INSTRUCTIONS

LOGICAL_SESSION_ARGUMENT_DESCRIPTION = (
    "Logical Session for this tool call. Pass the session_id returned by session_manage while working in that "
    "task. Use null only when no Logical Session is active. This is the same durable session_id used by "
    "session_manage."
)


class PublicToolTimeoutError(TimeoutError):
    pass


NON_CANCELLABLE_TOOL_NAMES = frozenset(
    {
        "link_create",
        "link_revoke",
        "image_view",
        "file_write",
        "file_edit",
        "file_delete",
        "file_patch",
        "remote_transfer",
        "mcp_tool_call",
        "chat_dispatch",
    }
)

REMOTE_MACHINE_ARGUMENTS = frozenset({"machine", "source_machine", "destination_machine"})


def _security_meta(schemes: list[dict[str, Any]]) -> dict[str, Any]:
    return {"securitySchemes": schemes}


def _oauth_meta(scopes: list[str]) -> dict[str, Any]:
    if get_settings().auth_mode == "none":
        return _security_meta([*NOAUTH_SECURITY_SCHEMES])
    return _security_meta([_oauth_security_scheme(scopes)])


def _live_workspace_api_base() -> str:
    settings = get_settings()
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    host = settings.host
    if host in {"0.0.0.0", "::", "[::]"}:
        host = "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{settings.port}"


def _live_workspace_resource_meta() -> dict[str, Any]:
    parsed = urlparse(_live_workspace_api_base())
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    websocket_origin = ""
    if origin:
        websocket_scheme = "wss" if parsed.scheme == "https" else "ws"
        websocket_origin = f"{websocket_scheme}://{parsed.netloc}"
    connect_domains = [value for value in (origin, websocket_origin) if value]
    return {
        "ui": {
            "domain": origin,
            "csp": {"connectDomains": connect_domains},
            "permissions": {"clipboardWrite": {}},
            "prefersBorder": False,
        },
        "openai/widgetDescription": (
            "A live local-shell-mcp execution workspace with activity, terminal, files, "
            "diffs, jobs, remotes, audit, and shared human/agent interaction."
        ),
        "openai/widgetDomain": origin,
        "openai/widgetPrefersBorder": False,
    }


def _live_workspace_html() -> str:
    path = Path(__file__).resolve().parent / "ui_static" / "live-workspace.html"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return """<!doctype html><html><body style="font-family:system-ui;padding:16px">
<strong>local-shell-mcp Live Workspace assets are not built.</strong>
<p>Run <code>cd ui &amp;&amp; bun run build:web</code> and restart the server.</p>
</body></html>"""


def _transport_security_settings() -> TransportSecuritySettings:
    settings = get_settings()
    allowed_hosts = {
        "127.0.0.1",
        "127.0.0.1:*",
        "localhost",
        "localhost:*",
        "[::1]",
        "[::1]:*",
    }
    allowed_origins = {
        "http://127.0.0.1:*",
        "http://localhost:*",
        "http://[::1]:*",
        "https://chatgpt.com",
        "https://chat.openai.com",
    }

    if settings.public_base_url:
        parsed = urlparse(settings.public_base_url)
        if parsed.netloc:
            allowed_hosts.add(parsed.netloc)
            allowed_hosts.add(f"{parsed.hostname}:*")
            allowed_origins.add(f"{parsed.scheme}://{parsed.netloc}")

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=sorted(allowed_hosts),
        allowed_origins=sorted(allowed_origins),
    )


def _serialize_audit_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _serialize_audit_value(value.model_dump(mode="json"))
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_serialize_audit_value(item) for item in value]
    if isinstance(value, dict):
        return {str(name): _serialize_audit_value(item) for name, item in value.items()}
    return repr(value)


def _safe_audit_result(tool_name: str, value: Any) -> Any:
    serialized = _serialize_audit_value(value)
    if tool_name not in {
        "workspace_open",
        "open_live_workspace",
        "live_workspace_reconnect",
    } or not isinstance(serialized, dict):
        return serialized
    sanitized = dict(serialized)
    sanitized.pop("meta", None)
    return sanitized


def _audit_tool_arguments(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    return {
        "positional_count": len(args),
        "keyword_args": _serialize_audit_value(kwargs),
    }


def _safe_audit_call_arguments(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "mcp_tool_call":
        dynamic_arguments = arguments.get("arguments")
        return {
            "name": arguments.get("name"),
            "argument_keys": sorted(dynamic_arguments) if isinstance(dynamic_arguments, dict) else [],
            "timeout_s": arguments.get("timeout_s"),
        }
    if tool_name == "mcp_manage":
        safe = dict(arguments)
        for field_name in ("env", "headers"):
            value = safe.get(field_name)
            if isinstance(value, dict):
                safe[field_name] = {str(key): "<redacted>" for key in value}
        if str(safe.get("action") or "").lower() in {"env_set", "header_set"}:
            safe["value"] = "<redacted>"
        return safe
    if tool_name == "chat_dispatch":
        safe = dict(arguments)
        prompt = safe.get("prompt")
        if isinstance(prompt, str):
            safe["prompt"] = f"<redacted:{len(prompt.encode('utf-8'))} bytes>"
        return safe
    if tool_name == "browser_act":
        safe = dict(arguments)
        actions = safe.get("actions")
        if isinstance(actions, list):
            safe["actions"] = [
                {
                    str(key): "<redacted>" if key == "value" else value
                    for key, value in action.items()
                }
                if isinstance(action, dict)
                else action
                for action in actions
            ]
        return safe
    return arguments


_LIVE_ARGUMENT_KEYS = (
    "machine",
    "source_machine",
    "destination_machine",
    "session_id",
    "job_id",
    "path",
    "source_path",
    "destination_path",
    "cwd",
    "name",
    "action",
    "purpose",
)


def _live_event_arguments(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {"tool": tool_name}
    for key in _LIVE_ARGUMENT_KEYS:
        value = arguments.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, str):
            data[key] = value[:500]
        elif isinstance(value, (int, float, bool)):
            data[key] = value
        elif isinstance(value, list):
            data[key] = [str(item)[:160] for item in value[:8]]
    command = arguments.get("command")
    if isinstance(command, str) and command:
        data["command"] = command[:500]
    return data


def _live_result_summary(result: Any) -> dict[str, Any]:
    if isinstance(result, CallToolResult):
        value: Any = result.structuredContent or {}
    elif isinstance(result, BaseModel):
        value = result.model_dump(mode="json")
    else:
        value = result
    if isinstance(value, dict) and isinstance(value.get("data"), dict):
        value = value["data"]
    if not isinstance(value, dict):
        return {}
    summary: dict[str, Any] = {}
    for key in (
        "status",
        "exit_code",
        "timed_out",
        "session_id",
        "job_id",
        "path",
        "machine",
        "bytes",
    ):
        item = value.get(key)
        if isinstance(item, (str, int, float, bool)):
            summary[key] = item
    return summary


def _audit_tool_purpose(
    tool_name: str, purpose: str | None = None, explanation: str | None = None
) -> dict[str, str]:
    details: dict[str, str] = {}
    if purpose is not None:
        purpose = purpose.strip()
        if len(purpose) > 500:
            raise ValueError("purpose must be <= 500 characters")
        if purpose:
            details["purpose"] = purpose
    if explanation is not None:
        explanation = explanation.strip()
        if len(explanation) > 2000:
            raise ValueError("explanation must be <= 2000 characters")
        if explanation:
            details["explanation"] = explanation
    if details:
        audit("tool_call_purpose", tool=tool_name, **details)
    return details


def _timeout_payload_for_tool(_tool_name: str, exc: Exception) -> CallToolResult:
    return _handled_error(exc)


def _install_logical_session_arguments(mcp: FastMCP) -> None:
    """Expose the active Logical Session id on tools that do not own a session_id field."""

    explicit_session_tools = {
        "session_manage",
        "plan_manage",
        "workspace_open",
        "open_live_workspace",
        "live_workspace_reconnect",
    }
    for name, tool in mcp._tool_manager._tools.items():  # noqa: SLF001
        if name in explicit_session_tools:
            continue
        argument_model = tool.fn_metadata.arg_model
        extended_model = create_model(
            f"{argument_model.__name__}WithLogicalSession",
            __base__=argument_model,
            logical_session_id=(
                str | None,
                Field(default=None, description=LOGICAL_SESSION_ARGUMENT_DESCRIPTION),
            ),
        )
        tool.fn_metadata.arg_model = extended_model
        parameters = extended_model.model_json_schema()
        session_schema = (parameters.get("properties") or {}).get("logical_session_id")
        if isinstance(session_schema, dict):
            session_schema.pop("default", None)
        required = list(parameters.get("required") or [])
        if "logical_session_id" not in required:
            required.append("logical_session_id")
        parameters["required"] = required
        tool.parameters = parameters


_PENDING_SESSION_LEASE_CLEANUPS: set[asyncio.Task[None]] = set()
_SESSION_LEASE_CLEANUP_TASKS: dict[tuple[int, str], asyncio.Task[None]] = {}
_SESSION_LEASE_CLEANUP_QUEUES: dict[
    tuple[int, str], dict[str, tuple[dict[str, Any], str, float]]
] = {}
_SESSION_LEASE_CLEANUP_MAX_PENDING_PER_SESSION = 128


async def _retry_session_tool_cleanups(
    manager: Any,
    *,
    queue_key: tuple[int, str],
) -> None:
    delay_s = 0.25
    try:
        while True:
            queue = _SESSION_LEASE_CLEANUP_QUEUES.get(queue_key)
            if not queue:
                return
            now = time.monotonic()
            for call_id, (lease, tool_name, deadline) in list(queue.items()):
                if now >= deadline:
                    queue.pop(call_id, None)
                    continue
                try:
                    cleaned = await asyncio.to_thread(manager.retry_tool_call_cleanup, lease)
                except Exception as exc:  # noqa: BLE001 - retry while the durable in-flight marker remains active.
                    with suppress(Exception):
                        audit(
                            "session_lease_cleanup_retry_failed",
                            tool=tool_name,
                            call_id=call_id,
                            error=f"{type(exc).__name__}: {exc}",
                        )
                else:
                    if cleaned:
                        queue.pop(call_id, None)
            if not queue:
                return
            await asyncio.sleep(delay_s)
            delay_s = min(30.0, delay_s * 2)
    finally:
        _SESSION_LEASE_CLEANUP_QUEUES.pop(queue_key, None)
        _SESSION_LEASE_CLEANUP_TASKS.pop(queue_key, None)


def _schedule_session_tool_cleanup_retry(
    manager: Any,
    lease: dict[str, Any],
    *,
    tool_name: str,
    call_id: str,
) -> None:
    # Keep retry state alive for this controller, but do not infer completion
    # after a controller loss. If the shared state backend is completely
    # unavailable when the tool finishes, there is no durable fact a replacement
    # controller can use to distinguish "completed, then crashed" from "crashed
    # while the external operation was still running". In that failure mode the
    # persisted in-flight lease intentionally falls back to its bounded stale
    # timeout rather than leaving stale in-flight state indefinitely.
    session_id = str(lease.get("session_id") or "")
    if not session_id:
        return
    queue_key = (id(manager), session_id)
    queue = _SESSION_LEASE_CLEANUP_QUEUES.setdefault(queue_key, {})
    if call_id not in queue and len(queue) >= _SESSION_LEASE_CLEANUP_MAX_PENDING_PER_SESSION:
        # Cleanup is an optimization: durable leases already have a stale
        # timeout. Bound queued retries during a prolonged state-backend outage.
        return
    if call_id not in queue:
        queue[call_id] = (
            lease,
            tool_name,
            time.monotonic() + SESSION_IN_FLIGHT_LEASE_S,
        )
    existing = _SESSION_LEASE_CLEANUP_TASKS.get(queue_key)
    if existing is not None and not existing.done():
        return
    task = asyncio.create_task(_retry_session_tool_cleanups(manager, queue_key=queue_key))
    _SESSION_LEASE_CLEANUP_TASKS[queue_key] = task
    _PENDING_SESSION_LEASE_CLEANUPS.add(task)
    task.add_done_callback(_PENDING_SESSION_LEASE_CLEANUPS.discard)


async def _finish_session_tool_activity(
    manager: Any,
    lease: dict[str, Any] | None,
    event_type: str,
    data: dict[str, Any],
    *,
    tool_name: str,
    call_id: str,
    stage: str,
) -> None:
    try:
        persistence_error = await asyncio.to_thread(
            manager.finish_tool_call, lease, event_type, data=data
        )
    except Exception as exc:  # noqa: BLE001 - activity failures must not mask tool results.
        persistence_error = f"{type(exc).__name__}: {exc}"
    if persistence_error:
        # Completion persistence must never mask the original tool result, but
        # leaving the durable in-flight marker behind can block terminal Session actions for the
        # full stale window. Keep retrying only the lease removal in background.
        with suppress(Exception):
            audit(
                "session_activity_persistence_failed",
                tool=tool_name,
                call_id=call_id,
                stage=stage,
                error=persistence_error,
            )
        if lease is not None:
            _schedule_session_tool_cleanup_retry(
                manager,
                lease,
                tool_name=tool_name,
                call_id=call_id,
            )


async def _await_non_cancellable(awaitable):  # noqa: ANN001, ANN202
    """Keep an already-started side effect running until it actually settles.

    asyncio cancellation does not stop worker threads created by to_thread().
    Shielding the tool coroutine ensures its durable Session lease is held until
    the underlying side effect has really completed, even if the MCP request is
    cancelled or disconnected in the meantime.
    """

    task = asyncio.create_task(awaitable)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if task.done() and not task.cancelled():
            with suppress(Exception):
                task.result()
        raise


async def _renew_session_tool_lease(
    manager: Any,
    lease: dict[str, Any],
    *,
    tool_name: str,
    call_id: str,
) -> None:
    interval_s = max(60.0, SESSION_IN_FLIGHT_LEASE_S / 3)
    while True:
        await asyncio.sleep(interval_s)
        try:
            renewed = await asyncio.to_thread(manager.renew_tool_call, lease)
        except Exception as exc:  # noqa: BLE001 - a later heartbeat may recover.
            # Renewal telemetry must never terminate the heartbeat loop. The
            # audit sink can fail for the same transient storage outage that
            # caused the renewal attempt to fail.
            with suppress(Exception):
                audit(
                    "session_lease_renewal_failed",
                    tool=tool_name,
                    call_id=call_id,
                    error=f"{type(exc).__name__}: {exc}",
                )
            continue
        if not renewed:
            return


def _install_mcp_tool_watchdogs(mcp: FastMCP) -> None:
    for tool in mcp._tool_manager._tools.values():  # noqa: SLF001
        original = tool.fn
        tool_name = tool.name
        required_scopes: list[str] = []
        for scheme in (tool.meta or {}).get("securitySchemes", []):
            if scheme.get("type") == "oauth2":
                required_scopes.extend(str(scope) for scope in scheme.get("scopes", []))
                break
        tool_required_scopes = tuple(dict.fromkeys(required_scopes))
        signature = inspect.signature(original)

        async def wrapped(  # noqa: ANN202
            *args,
            __original=original,
            __signature=signature,
            __tool_name=tool_name,
            __required_scopes=tool_required_scopes,
            **kwargs,
        ):
            require_current_scopes(__required_scopes)
            invoke_kwargs = dict(kwargs)
            explicit_session_tools = {
                "session_manage",
                "plan_manage",
                "workspace_open",
                "open_live_workspace",
                "live_workspace_reconnect",
            }
            injected_session_id = kwargs.get("logical_session_id")
            if __tool_name not in explicit_session_tools:
                invoke_kwargs.pop("logical_session_id", None)
            try:
                bound = __signature.bind_partial(*args, **invoke_kwargs)
                call_arguments = dict(bound.arguments)
            except TypeError:
                call_arguments = dict(invoke_kwargs)
            if __tool_name not in explicit_session_tools and injected_session_id is not None:
                call_arguments["logical_session_id"] = injected_session_id

            if __tool_name in {"plan_manage", "workspace_open", "open_live_workspace"}:
                logical_session_id = call_arguments.get("session_id")
            elif __tool_name in {"live_workspace_reconnect", "session_manage"}:
                logical_session_id = None
            else:
                logical_session_id = injected_session_id
            logical_session_id = (
                str(logical_session_id).strip() if logical_session_id is not None else ""
            ) or None

            local_access_error = _disabled_local_access_error(__tool_name, call_arguments)
            if any(call_arguments.get(name) for name in REMOTE_MACHINE_ARGUMENTS):
                require_current_scopes(("remote:use",))
            safe_call_arguments = _safe_audit_call_arguments(__tool_name, call_arguments)
            arguments = {
                "positional_count": len(args),
                "keyword_args": _serialize_audit_value(safe_call_arguments),
            }
            audit_context = {
                name: call_arguments[name]
                for name in REMOTE_MACHINE_ARGUMENTS
                if call_arguments.get(name)
            }
            # Preserve tool-specific session identifiers (shell/browser/etc.) in the
            # established audit field. Logical Session identity is recorded separately.
            if call_arguments.get("session_id"):
                audit_context["session"] = call_arguments["session_id"]
            if logical_session_id:
                audit_context["logical_session"] = logical_session_id
            elif __tool_name == "session_manage" and call_arguments.get("session_id"):
                audit_context["logical_session"] = call_arguments["session_id"]
            call_id = uuid.uuid4().hex
            started_at = time.monotonic()
            live_manager = get_live_channel_manager()
            logical_manager = get_session_runtime_manager()
            principal_subject = _current_principal_subject()
            live_arguments = _live_event_arguments(__tool_name, safe_call_arguments)
            logical_lease = None
            normalized_tool_action = str(call_arguments.get("action") or "").strip().lower()
            tracks_session_activity = __tool_name not in {
                "session_manage",
                "workspace_open",
                "open_live_workspace",
                "live_workspace_reconnect",
            } and not (__tool_name == "plan_manage" and normalized_tool_action == "get")
            if tracks_session_activity:
                try:
                    logical_lease = await asyncio.to_thread(
                        logical_manager.begin_tool_call,
                        logical_session_id,
                        call_id,
                        subject=principal_subject,
                        data=live_arguments,
                    )
                except SessionToolLeaseStartPersistenceError as exc:
                    _schedule_session_tool_cleanup_retry(
                        logical_manager,
                        exc.lease,
                        tool_name=__tool_name,
                        call_id=call_id,
                    )
                    raise
            logical_activity_finished = False
            live_lifecycle_channel_id: str | None = None
            lease_heartbeat_task = (
                asyncio.create_task(
                    _renew_session_tool_lease(
                        logical_manager,
                        logical_lease,
                        tool_name=__tool_name,
                        call_id=call_id,
                    )
                )
                if logical_lease is not None
                else None
            )
            try:
                if logical_lease and logical_lease.get("persistence_error"):
                    audit(
                        "session_activity_persistence_failed",
                        tool=__tool_name,
                        call_id=call_id,
                        stage="started",
                        error=str(logical_lease["persistence_error"]),
                    )
                # Live Workspace follows the explicit Logical Session id. MCP transport
                # identity is irrelevant, so multiplexed ChatGPT conversations cannot rebind
                # one another's workspace or activity stream.
                if logical_lease and logical_lease.get("session_id"):
                    lifecycle_channel = live_manager.active_for_logical_session(
                        str(logical_lease["session_id"]), subject=principal_subject
                    )
                    if lifecycle_channel is not None:
                        live_lifecycle_channel_id = lifecycle_channel.live_id
                        live_manager.publish_channel(
                            live_lifecycle_channel_id,
                            "tool.started",
                            actor="agent",
                            data={"call_id": call_id, **live_arguments},
                        )
                audit(
                    "mcp_tool_call_start",
                    call_id=call_id,
                    tool=__tool_name,
                    arguments=arguments,
                    **audit_context,
                )
            except BaseException as setup_exc:
                if lease_heartbeat_task is not None:
                    lease_heartbeat_task.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await lease_heartbeat_task
                if live_lifecycle_channel_id is not None:
                    live_manager.publish_channel(
                        live_lifecycle_channel_id,
                        "tool.cancelled"
                        if isinstance(setup_exc, asyncio.CancelledError)
                        else "tool.failed",
                        actor="agent",
                        data={
                            "call_id": call_id,
                            "ok": False,
                            "duration_ms": round((time.monotonic() - started_at) * 1000),
                            "error": (str(setup_exc) or type(setup_exc).__name__)[:500],
                            "error_type": type(setup_exc).__name__,
                            **live_arguments,
                        },
                    )
                if logical_lease is not None:
                    setup_data = {
                        "call_id": call_id,
                        "ok": False,
                        "duration_ms": round((time.monotonic() - started_at) * 1000),
                        "error": (str(setup_exc) or type(setup_exc).__name__)[:500],
                        "error_type": type(setup_exc).__name__,
                        **live_arguments,
                    }
                    await _finish_session_tool_activity(
                        logical_manager,
                        logical_lease,
                        "tool.cancelled"
                        if isinstance(setup_exc, asyncio.CancelledError)
                        else "tool.failed",
                        setup_data,
                        tool_name=__tool_name,
                        call_id=call_id,
                        stage="setup",
                    )
                raise
            try:
                with audit_call_context(call_id) as call_state:
                    if local_access_error is not None:
                        result = _handled_error(RuntimeError(local_access_error))
                    elif __tool_name in NON_CANCELLABLE_TOOL_NAMES:
                        result = await _await_non_cancellable(
                            __original(*args, **invoke_kwargs)
                        )
                    else:
                        result = await asyncio.wait_for(
                            __original(*args, **invoke_kwargs), timeout=PUBLIC_TOOL_TIMEOUT_S
                        )
                serialized_result = _safe_audit_result(__tool_name, result)
                call_ok = audit_result_ok(result) and not bool(call_state["failed"])
                failure_context = {}
                if not call_ok and call_state.get("error"):
                    failure_context["error"] = call_state["error"]
                if not call_ok and call_state.get("error_type"):
                    failure_context["error_type"] = call_state["error_type"]
                audit(
                    "mcp_tool_call_end",
                    call_id=call_id,
                    tool=__tool_name,
                    ok=call_ok,
                    duration_ms=round((time.monotonic() - started_at) * 1000),
                    result=serialized_result,
                    **failure_context,
                    **audit_context,
                )
                completion_data = {
                    "call_id": call_id,
                    "ok": call_ok,
                    "duration_ms": round((time.monotonic() - started_at) * 1000),
                    **live_arguments,
                    **_live_result_summary(result),
                }
                if live_lifecycle_channel_id is not None:
                    live_manager.publish_channel(
                        live_lifecycle_channel_id,
                        "tool.completed" if call_ok else "tool.failed",
                        actor="agent",
                        data=completion_data,
                    )
                await _finish_session_tool_activity(
                    logical_manager,
                    logical_lease,
                    "tool.completed" if call_ok else "tool.failed",
                    completion_data,
                    tool_name=__tool_name,
                    call_id=call_id,
                    stage="completed",
                )
                logical_activity_finished = True
                return result
            except TimeoutError:
                exc = PublicToolTimeoutError(
                    f"{__tool_name} exceeded {PUBLIC_TOOL_TIMEOUT_S} second public tool timeout"
                )
                result = _timeout_payload_for_tool(__tool_name, exc)
                audit(
                    "tool_timeout",
                    call_id=call_id,
                    parent_call_id=call_id,
                    tool=__tool_name,
                    timeout_s=PUBLIC_TOOL_TIMEOUT_S,
                )
                audit(
                    "mcp_tool_call_end",
                    call_id=call_id,
                    tool=__tool_name,
                    ok=False,
                    duration_ms=round((time.monotonic() - started_at) * 1000),
                    error=str(exc),
                    error_type=type(exc).__name__,
                    result=_serialize_audit_value(result),
                    **audit_context,
                )
                failure_data = {
                    "call_id": call_id,
                    "ok": False,
                    "duration_ms": round((time.monotonic() - started_at) * 1000),
                    "error_type": type(exc).__name__,
                    **live_arguments,
                }
                if live_lifecycle_channel_id is not None:
                    live_manager.publish_channel(
                        live_lifecycle_channel_id,
                        "tool.failed",
                        actor="agent",
                        data=failure_data,
                    )
                await _finish_session_tool_activity(
                    logical_manager,
                    logical_lease,
                    "tool.failed",
                    failure_data,
                    tool_name=__tool_name,
                    call_id=call_id,
                    stage="timeout",
                )
                logical_activity_finished = True
                return result
            except Exception as exc:
                audit(
                    "mcp_tool_call_end",
                    call_id=call_id,
                    tool=__tool_name,
                    ok=False,
                    duration_ms=round((time.monotonic() - started_at) * 1000),
                    error=str(exc) or type(exc).__name__,
                    error_type=type(exc).__name__,
                    **audit_context,
                )
                failure_data = {
                    "call_id": call_id,
                    "ok": False,
                    "duration_ms": round((time.monotonic() - started_at) * 1000),
                    "error": (str(exc) or type(exc).__name__)[:500],
                    "error_type": type(exc).__name__,
                    **live_arguments,
                }
                if live_lifecycle_channel_id is not None:
                    live_manager.publish_channel(
                        live_lifecycle_channel_id,
                        "tool.failed",
                        actor="agent",
                        data=failure_data,
                    )
                await _finish_session_tool_activity(
                    logical_manager,
                    logical_lease,
                    "tool.failed",
                    failure_data,
                    tool_name=__tool_name,
                    call_id=call_id,
                    stage="failed",
                )
                logical_activity_finished = True
                raise
            finally:
                if lease_heartbeat_task is not None:
                    lease_heartbeat_task.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await lease_heartbeat_task
                if not logical_activity_finished and logical_lease is not None:
                    cancellation_data = {
                        "call_id": call_id,
                        "ok": False,
                        "duration_ms": round((time.monotonic() - started_at) * 1000),
                        "cancelled": True,
                        **live_arguments,
                    }
                    if live_lifecycle_channel_id is not None:
                        live_manager.publish_channel(
                            live_lifecycle_channel_id,
                            "tool.cancelled",
                            actor="agent",
                            data=cancellation_data,
                        )
                    await _finish_session_tool_activity(
                        logical_manager,
                        logical_lease,
                        "tool.cancelled",
                        cancellation_data,
                        tool_name=__tool_name,
                        call_id=call_id,
                        stage="cancelled",
                    )

        tool.fn = wrapped


LOGICAL_SESSION_TOOL_NAMES = {"session_manage", "plan_manage"}


def _remove_logical_session_tools_when_disabled(mcp: FastMCP) -> None:
    if get_settings().logical_sessions_enabled:
        return
    tools = mcp._tool_manager._tools  # noqa: SLF001
    for name in LOGICAL_SESSION_TOOL_NAMES:
        tools.pop(name, None)


def _remove_remote_tools_when_disabled(mcp: FastMCP) -> None:
    if get_settings().remote_enabled:
        return
    tools = mcp._tool_manager._tools  # noqa: SLF001
    for name in list(tools):
        if name.startswith("remote_"):
            tools.pop(name, None)


MACHINE_CAPABLE_TOOL_NAMES = {
    "environment_get",
    "run_shell",
    "run_python",
    "shell_start",
    "shell_send",
    "shell_read",
    "shell_stop",
    "shell_list",
    "job_start",
    "job_list",
    "job_tail",
    "job_stop",
    "job_retry",
    "file_list",
    "file_tree",
    "file_glob",
    "file_grep",
    "file_read",
    "image_view",
    "file_write",
    "file_edit",
    "file_delete",
    "file_patch",
    "browser_session",
    "browser_snapshot",
    "browser_act",
    "browser_run_script",
}

LOCAL_ONLY_TOOL_NAMES = {
    "skill_list",
    "skill_load",
    "skill_read",
    "link_create",
    "link_list",
    "link_revoke",
    "secret_scan",
    "chat_dispatch",
}


def _disabled_local_access_error(tool_name: str, arguments: dict[str, Any]) -> str | None:
    if not get_settings().disable_local:
        return None
    if tool_name in {"job_list", "job_tail", "job_stop", "job_retry"} and arguments.get(
        "machine"
    ) in {None, ""}:
        return None
    if tool_name in MACHINE_CAPABLE_TOOL_NAMES and arguments.get("machine") in {None, ""}:
        return "Local access is disabled; specify a remote machine"
    if tool_name == "remote_transfer" and (
        arguments.get("source_machine") in {None, ""}
        or arguments.get("destination_machine") in {None, ""}
    ):
        return "Local access is disabled; remote_transfer requires both remote endpoints"
    return None


def _remove_local_only_tools_when_disabled(mcp: FastMCP) -> None:
    if not get_settings().disable_local:
        return
    tools = mcp._tool_manager._tools  # noqa: SLF001
    for name in LOCAL_ONLY_TOOL_NAMES:
        tools.pop(name, None)


OPEN_WORLD_TOOL_NAMES = {
    *MACHINE_CAPABLE_TOOL_NAMES,
    "link_create",
    "link_revoke",
    "remote_transfer",
    "mcp_manage",
    "mcp_tool_call",
    "chat_dispatch",
}

READ_ONLY_OPEN_WORLD_TOOL_NAMES = {
    "browser_snapshot",
}

NON_DESTRUCTIVE_MUTATION_TOOL_NAMES = {
    "link_create",
    "workspace_open",
    "open_live_workspace",
}


def _install_tool_annotations(mcp: FastMCP) -> None:
    """Attach conservative, semantically accurate MCP safety annotations."""

    for name, tool in mcp._tool_manager._tools.items():  # noqa: SLF001
        existing_read_only = bool(tool.annotations and tool.annotations.readOnlyHint)
        read_only = existing_read_only or name in READ_ONLY_OPEN_WORLD_TOOL_NAMES
        open_world = name.startswith("remote_") or name in OPEN_WORLD_TOOL_NAMES
        tool.annotations = ToolAnnotations(
            readOnlyHint=read_only,
            destructiveHint=not (read_only or name in NON_DESTRUCTIVE_MUTATION_TOOL_NAMES),
            idempotentHint=read_only,
            openWorldHint=open_world,
        )


def _gitignore_spec(
    directory: Path, cache: dict[Path, GitIgnoreSpec | None]
) -> GitIgnoreSpec | None:
    if directory in cache:
        return cache[directory]
    path = directory / ".gitignore"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        spec = None
    else:
        spec = GitIgnoreSpec.from_lines(lines)
    cache[directory] = spec
    return spec


def _fallback_path_is_ignored(
    path: Path, base: Path, cache: dict[Path, GitIgnoreSpec | None]
) -> bool:
    ignored: bool | None = None
    directories = [base]
    current = base
    for part in path.parent.relative_to(base).parts:
        current = current / part
        directories.append(current)
    for directory in directories:
        spec = _gitignore_spec(directory, cache)
        if spec is None:
            continue
        include = spec.check_file(path.relative_to(directory).as_posix()).include
        if include is not None:
            ignored = bool(include)
    return bool(ignored)


def _secret_scan_candidates(base: Any, glob: str | None = None) -> list[Any]:
    settings = get_settings()
    args = [settings.rg_bin, "--files", "--hidden", "--glob", "!.git/**"]
    ignore_file = base / ".gitignore"
    if ignore_file.is_file():
        args.extend(["--ignore-file", str(ignore_file)])
    if glob:
        args.extend(["--glob", glob])
    try:
        result = subprocess.run(
            args, cwd=str(base), text=True, capture_output=True, timeout=30, check=False,
            **managed_process_kwargs(),
        )
    except Exception:
        result = None
    if result is not None and result.returncode in {0, 1}:
        return [base / line for line in result.stdout.splitlines() if line.strip()]

    candidates = []
    ignore_cache: dict[Path, GitIgnoreSpec | None] = {}
    for path in base.rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue
        if _fallback_path_is_ignored(path, base, ignore_cache):
            continue
        if glob and not path.match(glob):
            continue
        candidates.append(path)
    return candidates


def _is_placeholder_secret_match(kind: str, text: str) -> bool:
    if kind != "generic_assignment":
        return False
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "${",
            "dev-",
            "dummy",
            "example",
            "fixture",
            "ci-local-shell-mcp",
            "recent-token",
            "stale-token",
            "lsmcp_wk_",
        )
    )


def _secret_scan_sync(cwd: str = ".", glob: str | None = None, max_results: int = 200) -> dict:
    import re

    settings = get_settings()
    max_results = max(1, min(max_results, settings.max_grep_results))
    base = resolve_path(cwd, must_exist=True)
    findings = []
    truncated_files = 0
    for path in _secret_scan_candidates(base, glob):
        if not path.is_file():
            continue
        try:
            data = read_text(str(path))
        except Exception:
            continue
        if data.get("binary"):
            continue
        if data.get("truncated"):
            truncated_files += 1
        text = data.get("content") or ""
        for name, pattern in SECRET_PATTERNS.items():
            for match in re.finditer(pattern, text):
                if _is_placeholder_secret_match(name, match.group(0)):
                    continue
                line = text.count("\n", 0, match.start()) + 1
                findings.append({"type": name, "path": relative_display(path), "line": line})
                if len(findings) >= max_results:
                    return {
                        "findings": findings,
                        "truncated": True,
                        "truncated_files": truncated_files,
                    }
    return {"findings": findings, "truncated": False, "truncated_files": truncated_files}


async def _secret_scan(cwd: str = ".", glob: str | None = None, max_results: int = 200) -> dict:
    return await asyncio.to_thread(_secret_scan_sync, cwd, glob, max_results)


class RemoteTransferError(RuntimeError):
    pass


TransferProgress = Callable[[dict[str, Any]], Awaitable[None]]


async def _report_transfer_progress(progress: TransferProgress | None, **fields: Any) -> None:
    if progress is not None:
        await progress(fields)


def _unwrap_remote_transfer_result(result: dict, *, machine: str, tool: str) -> Any:
    if not result.get("ok", False):
        raise RemoteTransferError(f"{tool} on {machine} failed: {result.get('message') or result}")
    data = result.get("data")
    if isinstance(data, dict) and data.get("status") == "error":
        raise RemoteTransferError(
            f"{tool} on {machine} failed: {data.get('error_type', 'remote_error')}: {data.get('message', '')}"
        )
    return data


async def _remote_transfer_data(
    machine: str, tool: str, args: dict, timeout_s: int | None = None
) -> Any:
    result = await remote_manager().call(
        machine, tool, args, timeout_s, lane=REMOTE_WORKER_TRANSFER_LANE
    )
    return _unwrap_remote_transfer_result(result, machine=machine, tool=tool)


def _revoke_cancelled_snapshot_ticket(task: asyncio.Task[dict[str, Any]]) -> None:
    if task.cancelled():
        return
    try:
        ticket = task.result()
    except Exception:
        return
    with suppress(Exception):
        revoke_transfer_ticket(ticket["token"])


async def _copy_local_file_to_remote(
    source_path: str,
    dst_machine: str,
    dst_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
    progress: TransferProgress | None = None,
) -> dict:
    stat = await asyncio.to_thread(transfer_stat, source_path, True)
    if stat.get("type") != "file":
        raise ValueError(f"source is not a file: {source_path}")
    effective_chunk_size = stat["size"] if chunk_size is None else normalize_chunk_size(chunk_size)
    ticket_task = asyncio.create_task(
        asyncio.to_thread(
            create_download_ticket,
            source_path,
            stat["size"],
            stat["sha256"],
        )
    )
    try:
        ticket = await asyncio.shield(ticket_task)
    except asyncio.CancelledError:
        ticket_task.add_done_callback(_revoke_cancelled_snapshot_ticket)
        raise
    try:
        finish = await _remote_transfer_data(
            dst_machine,
            "transfer_download_url",
            {
                "url": ticket["url"],
                "path": dst_path,
                "overwrite": overwrite,
                "expected_bytes": stat["size"],
                "expected_sha256": stat["sha256"],
                "timeout_s": get_settings().remote_job_timeout_s,
            },
            get_settings().remote_job_timeout_s,
        )
    finally:
        revoke_transfer_ticket(ticket["token"])
    await _report_transfer_progress(
        progress,
        phase="transferring",
        bytes_transferred=stat["size"],
        total_bytes=stat["size"],
        chunks=1,
        chunk_size=effective_chunk_size,
    )
    return {
        "source": {"machine": "controller", "path": stat["path"]},
        "destination": {"machine": dst_machine, "path": finish["path"]},
        "bytes": stat["size"],
        "sha256": stat.get("sha256"),
        "chunks": 1,
        "chunk_size": effective_chunk_size,
        "transport": "http-stream",
    }


async def _copy_remote_file_to_local(
    src_machine: str,
    src_path: str,
    destination_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
    progress: TransferProgress | None = None,
) -> dict:
    stat = await _remote_transfer_data(
        src_machine, "transfer_stat", {"path": src_path, "sha256": True}
    )
    if stat.get("type") != "file":
        raise ValueError(f"source is not a file: {src_path}")
    total_bytes = int(stat["size"])
    effective_chunk_size = normalize_chunk_size(
        DEFAULT_TRANSFER_CHUNK_BYTES if chunk_size is None else chunk_size
    )
    chunk_timeout_s = min(int(get_settings().remote_job_timeout_s), 300)
    ticket = create_upload_ticket(
        destination_path,
        total_bytes,
        stat["sha256"],
        overwrite,
    )
    chunks = 0
    finish: dict[str, Any] | None = None
    try:
        status = get_upload_ticket_status(ticket["token"])
        offset = int(status["received_bytes"])
        await _report_transfer_progress(
            progress,
            phase="transferring",
            bytes_transferred=offset,
            total_bytes=total_bytes,
            chunks=chunks,
            chunk_size=effective_chunk_size,
        )
        while offset < total_bytes or (total_bytes == 0 and chunks == 0):
            expected_end = min(total_bytes, offset + effective_chunk_size)
            last_error: Exception | None = None
            for attempt in range(3):
                try:
                    response = await _remote_transfer_data(
                        src_machine,
                        "transfer_upload_url",
                        {
                            "path": src_path,
                            "url": ticket["url"],
                            "expected_bytes": total_bytes,
                            "expected_sha256": stat["sha256"],
                            "timeout_s": chunk_timeout_s,
                            "offset": offset,
                            "chunk_size": effective_chunk_size,
                        },
                        chunk_timeout_s,
                    )
                except Exception as exc:
                    last_error = exc
                    status = get_upload_ticket_status(ticket["token"])
                    acknowledged = int(status["received_bytes"])
                    if acknowledged == expected_end or (
                        total_bytes == 0 and status.get("completed")
                    ):
                        response = status
                    elif acknowledged != offset or attempt == 2:
                        raise
                    else:
                        await asyncio.sleep(1)
                        continue

                acknowledged = int(response.get("received_bytes", -1))
                if total_bytes == 0:
                    if not response.get("completed"):
                        raise RemoteTransferError("empty upload was not completed")
                elif acknowledged != expected_end:
                    raise RemoteTransferError(
                        f"upload acknowledged offset {acknowledged}, expected {expected_end}"
                    )
                offset = acknowledged
                chunks += 1
                finish = response
                await _report_transfer_progress(
                    progress,
                    phase="transferring",
                    bytes_transferred=offset,
                    total_bytes=total_bytes,
                    chunks=chunks,
                    chunk_size=effective_chunk_size,
                )
                break
            else:
                assert last_error is not None
                raise last_error
            if finish.get("completed"):
                break

        if finish is None or not finish.get("completed"):
            finish = get_upload_ticket_status(ticket["token"])
        if not finish.get("completed"):
            raise RemoteTransferError(f"upload did not complete: {finish}")
    finally:
        revoke_transfer_ticket(ticket["token"])
    return {
        "source": {"machine": src_machine, "path": stat["path"]},
        "destination": {"machine": "controller", "path": finish["path"]},
        "bytes": total_bytes,
        "sha256": stat.get("sha256"),
        "chunks": chunks,
        "chunk_size": effective_chunk_size,
        "transport": "http-chunks",
    }


async def _copy_remote_file_via_controller_relay(
    src_machine: str,
    src_path: str,
    dst_machine: str,
    dst_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
    progress: TransferProgress | None = None,
) -> dict:
    stat = await _remote_transfer_data(
        src_machine, "transfer_stat", {"path": src_path, "sha256": True}
    )
    if stat.get("type") != "file":
        raise ValueError(f"source is not a file: {src_path}")
    total_bytes = int(stat["size"])
    effective_chunk_size = normalize_chunk_size(
        DEFAULT_TRANSFER_CHUNK_BYTES if chunk_size is None else chunk_size
    )
    begin = await _remote_transfer_data(
        dst_machine,
        "transfer_begin_write",
        {
            "path": dst_path,
            "overwrite": overwrite,
            "expected_bytes": total_bytes,
        },
    )
    transfer_id = str(begin["transfer_id"])
    offset = 0
    chunks = 0
    try:
        await _report_transfer_progress(
            progress,
            phase="transferring",
            bytes_transferred=0,
            total_bytes=total_bytes,
            chunks=0,
            chunk_size=effective_chunk_size,
        )
        while offset < total_bytes:
            chunk = await _remote_transfer_data(
                src_machine,
                "transfer_read_chunk",
                {
                    "path": src_path,
                    "offset": offset,
                    "chunk_size": effective_chunk_size,
                },
            )
            chunk_bytes = int(chunk.get("bytes", 0))
            if chunk_bytes <= 0:
                raise RemoteTransferError(
                    f"source returned an empty chunk at offset {offset} before EOF"
                )
            if int(chunk.get("offset", -1)) != offset:
                raise RemoteTransferError(
                    f"source returned offset {chunk.get('offset')}, expected {offset}"
                )
            written = await _remote_transfer_data(
                dst_machine,
                "transfer_write_chunk",
                {
                    "path": dst_path,
                    "transfer_id": transfer_id,
                    "offset": offset,
                    "data_b64": chunk["data_b64"],
                    "expected_sha256": chunk["sha256"],
                },
            )
            if int(written.get("bytes", -1)) != chunk_bytes:
                raise RemoteTransferError(
                    f"destination wrote {written.get('bytes')} bytes, expected {chunk_bytes}"
                )
            offset += chunk_bytes
            chunks += 1
            await _report_transfer_progress(
                progress,
                phase="transferring",
                bytes_transferred=offset,
                total_bytes=total_bytes,
                chunks=chunks,
                chunk_size=effective_chunk_size,
            )

        finish = await _remote_transfer_data(
            dst_machine,
            "transfer_finish_write",
            {
                "path": dst_path,
                "transfer_id": transfer_id,
                "expected_bytes": total_bytes,
                "expected_sha256": stat["sha256"],
            },
        )
    except Exception:
        with suppress(Exception):
            await _remote_transfer_data(
                dst_machine,
                "transfer_abort_write",
                {"path": dst_path, "transfer_id": transfer_id},
            )
        raise
    return {
        "source": {"machine": src_machine, "path": stat["path"]},
        "destination": {"machine": dst_machine, "path": finish["path"]},
        "bytes": total_bytes,
        "sha256": stat.get("sha256"),
        "chunks": chunks,
        "chunk_size": effective_chunk_size,
        "transport": "controller-memory-relay",
    }


async def _copy_remote_file_direct(
    src_machine: str,
    src_path: str,
    dst_machine: str,
    dst_path: str,
    overwrite: bool,
    progress: TransferProgress | None,
) -> dict:
    settings = get_settings()
    if not settings.remote_peer_transfer_enabled:
        raise RuntimeError("direct remote transfer is not enabled")
    stat = await _remote_transfer_data(
        src_machine, "transfer_stat", {"path": src_path, "sha256": True}
    )
    if stat.get("type") != "file":
        raise ValueError(f"source is not a file: {src_path}")
    total_bytes = int(stat["size"])
    receiver = await _remote_transfer_data(
        dst_machine,
        "transfer_open_receiver",
        {
            "path": dst_path,
            "overwrite": overwrite,
            "expected_bytes": total_bytes,
            "expected_sha256": stat["sha256"],
            "bind_host": settings.remote_peer_transfer_bind_host,
            "advertise_host": settings.remote_peer_transfer_advertise_host,
            "port": settings.remote_peer_transfer_port,
            "timeout_s": settings.remote_peer_transfer_timeout_s,
        },
    )
    try:
        await _remote_transfer_data(
            src_machine,
            "transfer_put_url",
            {
                "path": src_path,
                "url": receiver["url"],
                "expected_bytes": total_bytes,
                "expected_sha256": stat["sha256"],
                "timeout_s": settings.remote_peer_transfer_timeout_s,
            },
            settings.remote_peer_transfer_timeout_s,
        )
        finish = await _remote_transfer_data(
            dst_machine, "transfer_stat", {"path": dst_path, "sha256": True}
        )
    except Exception:
        with suppress(Exception):
            await _remote_transfer_data(
                dst_machine,
                "transfer_close_receiver",
                {"receiver_id": receiver["receiver_id"]},
            )
        raise
    if int(finish.get("size", -1)) != total_bytes or finish.get("sha256") != stat["sha256"]:
        raise RemoteTransferError("direct peer transfer verification failed")
    await _report_transfer_progress(
        progress,
        phase="transferring",
        bytes_transferred=total_bytes,
        total_bytes=total_bytes,
        chunks=1,
        chunk_size=total_bytes,
    )
    return {
        "source": {"machine": src_machine, "path": stat["path"]},
        "destination": {"machine": dst_machine, "path": finish["path"]},
        "bytes": total_bytes,
        "sha256": stat.get("sha256"),
        "chunks": 1,
        "chunk_size": total_bytes,
        "transport": "peer-direct",
    }


def _s3_transfer_client():  # noqa: ANN202
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - optional dependency.
        raise RuntimeError(
            "object-store transfer requires the 'boto3' package; install local-shell-mcp[s3]"
        ) from exc
    settings = get_settings()
    return boto3.client(
        "s3",
        region_name=settings.remote_transfer_s3_region,
        endpoint_url=settings.remote_transfer_s3_endpoint_url,
    )


async def _delete_s3_transfer_object(client: Any, bucket: str, key: str) -> str | None:
    last_error: str | None = None
    for attempt in range(3):
        try:
            await asyncio.to_thread(client.delete_object, Bucket=bucket, Key=key)
            return None
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < 2:
                await asyncio.sleep(0.05 * (2**attempt))
    with suppress(Exception):
        audit(
            "remote_transfer_object_cleanup_failed",
            bucket=bucket,
            key=key,
            error=last_error,
            attempts=3,
        )
    return last_error


async def _copy_remote_file_via_object_store(
    src_machine: str,
    src_path: str,
    dst_machine: str,
    dst_path: str,
    overwrite: bool,
    progress: TransferProgress | None,
) -> dict:
    settings = get_settings()
    bucket = str(settings.remote_transfer_s3_bucket or "").strip()
    if not bucket:
        raise RuntimeError("remote_transfer_s3_bucket is required for object-store transfer")
    stat = await _remote_transfer_data(
        src_machine, "transfer_stat", {"path": src_path, "sha256": True}
    )
    if stat.get("type") != "file":
        raise ValueError(f"source is not a file: {src_path}")
    total_bytes = int(stat["size"])
    prefix = settings.remote_transfer_s3_prefix.strip("/")
    key = "/".join(part for part in (prefix, "transfers", uuid.uuid4().hex) if part)
    client = await asyncio.to_thread(_s3_transfer_client)
    ttl = int(settings.remote_transfer_s3_presign_ttl_s)
    put_url = await asyncio.to_thread(
        client.generate_presigned_url,
        "put_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=ttl,
        HttpMethod="PUT",
    )
    cleanup_error: str | None = None
    try:
        await _remote_transfer_data(
            src_machine,
            "transfer_put_url",
            {
                "path": src_path,
                "url": put_url,
                "expected_bytes": total_bytes,
                "expected_sha256": stat["sha256"],
                "timeout_s": settings.remote_job_timeout_s,
            },
            settings.remote_job_timeout_s,
        )
        get_url = await asyncio.to_thread(
            client.generate_presigned_url,
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=ttl,
            HttpMethod="GET",
        )
        finish = await _remote_transfer_data(
            dst_machine,
            "transfer_get_url",
            {
                "url": get_url,
                "path": dst_path,
                "overwrite": overwrite,
                "expected_bytes": total_bytes,
                "expected_sha256": stat["sha256"],
                "timeout_s": settings.remote_job_timeout_s,
            },
            settings.remote_job_timeout_s,
        )
    finally:
        cleanup_error = await _delete_s3_transfer_object(client, bucket, key)
    await _report_transfer_progress(
        progress,
        phase="transferring",
        bytes_transferred=total_bytes,
        total_bytes=total_bytes,
        chunks=1,
        chunk_size=total_bytes,
    )
    result = {
        "source": {"machine": src_machine, "path": stat["path"]},
        "destination": {"machine": dst_machine, "path": finish["path"]},
        "bytes": total_bytes,
        "sha256": stat.get("sha256"),
        "chunks": 1,
        "chunk_size": total_bytes,
        "transport": "s3-presigned",
    }
    if cleanup_error:
        result["cleanup_error"] = cleanup_error
    return result


async def _copy_remote_file_to_remote(
    src_machine: str,
    src_path: str,
    dst_machine: str,
    dst_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
    progress: TransferProgress | None = None,
) -> dict:
    settings = get_settings()
    strategy = settings.remote_transfer_strategy
    if strategy == "relay":
        return await _copy_remote_file_via_controller_relay(
            src_machine, src_path, dst_machine, dst_path, overwrite, chunk_size, progress
        )
    if strategy == "direct":
        return await _copy_remote_file_direct(
            src_machine, src_path, dst_machine, dst_path, overwrite, progress
        )
    if strategy == "object_store":
        return await _copy_remote_file_via_object_store(
            src_machine, src_path, dst_machine, dst_path, overwrite, progress
        )

    failures: list[str] = []
    if settings.remote_peer_transfer_enabled:
        try:
            return await _copy_remote_file_direct(
                src_machine, src_path, dst_machine, dst_path, overwrite, progress
            )
        except Exception as exc:
            failures.append(f"peer-direct: {type(exc).__name__}: {exc}")
            audit(
                "remote_transfer_fallback",
                transport="peer-direct",
                source_machine=src_machine,
                destination_machine=dst_machine,
                error=type(exc).__name__,
                message=str(exc),
            )
    if settings.remote_transfer_s3_bucket:
        try:
            return await _copy_remote_file_via_object_store(
                src_machine, src_path, dst_machine, dst_path, overwrite, progress
            )
        except Exception as exc:
            failures.append(f"s3-presigned: {type(exc).__name__}: {exc}")
            audit(
                "remote_transfer_fallback",
                transport="s3-presigned",
                source_machine=src_machine,
                destination_machine=dst_machine,
                error=type(exc).__name__,
                message=str(exc),
            )
    result = await _copy_remote_file_via_controller_relay(
        src_machine, src_path, dst_machine, dst_path, overwrite, chunk_size, progress
    )
    if failures:
        result["fallbacks"] = failures
    return result


async def _remote_cleanup_file(machine: str, path: str) -> None:
    with suppress(Exception):
        await _remote_transfer_data(
            machine, "delete_file_or_dir", {"path": path, "recursive": False}
        )


async def _copy_packed_dir_to_remote(
    pack: dict,
    src_machine: str | None,
    dst_machine: str,
    dst_path: str,
    overwrite: bool,
    chunk_size: int | None,
    progress: TransferProgress | None = None,
) -> dict:
    dst_archive = await _remote_transfer_data(
        dst_machine, "transfer_alloc_temp_path", {"suffix": ".tar.gz"}
    )
    try:
        if src_machine:
            copy_result = await _copy_remote_file_to_remote(
                src_machine,
                pack["archive_path"],
                dst_machine,
                dst_archive["path"],
                True,
                chunk_size,
                progress,
            )
        else:
            copy_result = await _copy_local_file_to_remote(
                pack["archive_path"],
                dst_machine,
                dst_archive["path"],
                True,
                chunk_size,
                progress,
            )
        unpack = await _remote_transfer_data(
            dst_machine,
            "transfer_unpack_archive",
            {
                "archive_path": dst_archive["path"],
                "dst_path": dst_path,
                "overwrite": overwrite,
                "cleanup_archive": True,
            },
        )
    except (asyncio.CancelledError, Exception):
        await _remote_cleanup_file(dst_machine, dst_archive.get("path", ""))
        raise
    finally:
        if src_machine:
            await _remote_cleanup_file(src_machine, pack.get("archive_path", ""))
        else:
            with suppress(Exception):
                delete_path(pack.get("archive_path", ""), False)
    return {
        "source": {"machine": src_machine or "controller", "path": pack["path"]},
        "destination": {"machine": dst_machine, "path": unpack["path"]},
        "archive_bytes": pack["bytes"],
        "archive_sha256": pack["sha256"],
        "chunks": copy_result["chunks"],
        "entries": unpack["entries"],
    }


async def _copy_remote_dir_to_remote(
    src_machine: str,
    src_path: str,
    dst_machine: str,
    dst_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
    progress: TransferProgress | None = None,
) -> dict:
    await _report_transfer_progress(progress, phase="packing", bytes_transferred=0)
    pack = await _remote_transfer_data(
        src_machine, "transfer_pack_dir", {"path": src_path, "compression": "gz"}
    )
    return await _copy_packed_dir_to_remote(
        pack,
        src_machine,
        dst_machine,
        dst_path,
        overwrite,
        chunk_size,
        progress,
    )


async def _copy_remote_dir_to_local(
    src_machine: str,
    src_path: str,
    destination_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
    progress: TransferProgress | None = None,
) -> dict:
    await _report_transfer_progress(progress, phase="packing", bytes_transferred=0)
    pack = await _remote_transfer_data(
        src_machine, "transfer_pack_dir", {"path": src_path, "compression": "gz"}
    )
    archive = await asyncio.to_thread(transfer_alloc_temp_path, ".tar.gz")
    try:
        copy_result = await _copy_remote_file_to_local(
            src_machine,
            pack["archive_path"],
            archive["path"],
            True,
            chunk_size,
            progress,
        )
        await _report_transfer_progress(
            progress,
            phase="unpacking",
            bytes_transferred=pack["bytes"],
            total_bytes=pack["bytes"],
            chunks=copy_result["chunks"],
        )
        unpack = await transfer_unpack_archive_async(
            archive["path"], destination_path, overwrite, True
        )
    finally:
        with suppress(Exception):
            delete_path(archive.get("path", ""), False)
        await _remote_cleanup_file(src_machine, pack.get("archive_path", ""))
    return {
        "source": {"machine": src_machine, "path": pack["path"]},
        "destination": {"machine": "controller", "path": unpack["path"]},
        "archive_bytes": pack["bytes"],
        "archive_sha256": pack["sha256"],
        "chunks": copy_result["chunks"],
        "entries": unpack["entries"],
    }


async def _copy_local_dir_to_remote(
    source_path: str,
    dst_machine: str,
    dst_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
    progress: TransferProgress | None = None,
) -> dict:
    await _report_transfer_progress(progress, phase="packing", bytes_transferred=0)
    pack = await transfer_pack_dir_async(source_path, "gz")
    return await _copy_packed_dir_to_remote(
        pack,
        None,
        dst_machine,
        dst_path,
        overwrite,
        chunk_size,
        progress,
    )


async def _execute_transfer_path(
    source_path: str,
    destination_path: str,
    source_machine: str | None = None,
    destination_machine: str | None = None,
    overwrite: bool = False,
    chunk_size: int | None = None,
    progress: TransferProgress | None = None,
) -> dict:
    if not source_machine and not destination_machine:
        raise ValueError("At least one transfer endpoint must be a remote machine")
    if source_machine:
        source_stat = await _remote_transfer_data(
            source_machine,
            "transfer_stat",
            {"path": source_path, "sha256": False},
        )
    else:
        source_stat = await asyncio.to_thread(transfer_stat, source_path, False)

    source_type = source_stat.get("type")
    if source_type not in {"file", "dir"}:
        raise ValueError(f"Unsupported transfer source type: {source_type}")

    if source_machine and destination_machine:
        operation = (
            _copy_remote_dir_to_remote if source_type == "dir" else _copy_remote_file_to_remote
        )
        arguments = (
            source_machine,
            source_path,
            destination_machine,
            destination_path,
        )
    elif source_machine:
        operation = (
            _copy_remote_dir_to_local if source_type == "dir" else _copy_remote_file_to_local
        )
        arguments = (source_machine, source_path, destination_path)
    else:
        assert destination_machine is not None
        operation = (
            _copy_local_dir_to_remote if source_type == "dir" else _copy_local_file_to_remote
        )
        arguments = (source_path, destination_machine, destination_path)

    result = await operation(
        *arguments,
        overwrite,
        chunk_size,
        progress,
    )
    return {"type": source_type, **result}


_transfer_path = _execute_transfer_path


def _transfer_endpoint(machine: str | None, path: str) -> str:
    return f"{machine or 'controller'}:{path}"


async def _run_transfer_job(context: ManagedJobContext, payload: dict[str, Any]) -> dict[str, Any]:
    source_path = str(payload["source_path"])
    destination_path = str(payload["destination_path"])
    source_machine = payload.get("source_machine")
    destination_machine = payload.get("destination_machine")
    source = _transfer_endpoint(source_machine, source_path)
    destination = _transfer_endpoint(destination_machine, destination_path)
    await context.log(f"transfer started: {source} -> {destination}")
    await context.update_progress(phase="preparing", bytes_transferred=0)

    async def report(fields: dict[str, Any]) -> None:
        await context.update_progress(**fields)
        phase = str(fields.get("phase") or "transferring")
        done = fields.get("bytes_transferred")
        total = fields.get("total_bytes")
        chunks = fields.get("chunks")
        if isinstance(done, int) and isinstance(total, int):
            await context.log(
                f"{phase}: {done}/{total} bytes"
                + (f" in {chunks} chunks" if isinstance(chunks, int) else "")
            )
        else:
            await context.log(phase)

    result = await _execute_transfer_path(
        source_path,
        destination_path,
        source_machine,
        destination_machine,
        bool(payload.get("overwrite", False)),
        payload.get("chunk_size"),
        report,
    )
    completed_bytes = result.get("bytes", result.get("archive_bytes"))
    await context.update_progress(
        phase="completed",
        bytes_transferred=completed_bytes,
        total_bytes=completed_bytes,
        chunks=result.get("chunks"),
    )
    await context.log(f"transfer completed: {source} -> {destination}")
    return result


async def _start_transfer_job(
    source_path: str,
    destination_path: str,
    source_machine: str | None = None,
    destination_machine: str | None = None,
    overwrite: bool = False,
    chunk_size: int | None = None,
) -> dict[str, Any]:
    if not source_machine and not destination_machine:
        raise ValueError("At least one transfer endpoint must be a remote machine")
    if chunk_size is not None:
        normalize_chunk_size(chunk_size)
    payload = {
        "source_path": source_path,
        "destination_path": destination_path,
        "source_machine": source_machine,
        "destination_machine": destination_machine,
        "overwrite": overwrite,
        "chunk_size": chunk_size,
    }
    source = _transfer_endpoint(source_machine, source_path)
    destination = _transfer_endpoint(destination_machine, destination_path)
    name = f"transfer-{Path(destination_path).name or 'path'}"
    return await start_managed_job(
        "transfer",
        payload,
        name=name,
        command=f"transfer {source} -> {destination}",
    )


register_managed_job_handler("transfer", _run_transfer_job)


def _view_image_success_result(
    image: ImageFile,
    path: str,
    machine: str | None,
) -> CallToolResult:
    metadata = ViewImageResult(
        ok=True,
        path=path,
        machine=machine,
        mime_type=image.mime_type,
        bytes=image.size,
    )
    return CallToolResult(
        content=[
            ImageContent(
                type="image",
                data=base64.b64encode(image.data).decode("ascii"),
                mimeType=image.mime_type,
            ),
            TextContent(
                type="text",
                text=f"{path} ({image.mime_type}, {image.size} bytes)",
            ),
        ],
        structuredContent=metadata.model_dump(mode="json"),
    )


def _view_image_error_result(
    path: str,
    machine: str | None,
    exc: Exception,
) -> CallToolResult:
    audit("tool_error", error=repr(exc))
    message = f"{type(exc).__name__}: {exc}"
    metadata = ViewImageResult(
        ok=False,
        path=path,
        machine=machine,
        message=message,
        error_type=type(exc).__name__,
    )
    return CallToolResult(
        content=[TextContent(type="text", text=f"Unable to view image: {message}")],
        structuredContent=metadata.model_dump(mode="json"),
        isError=True,
    )


async def load_image_for_machine(
    path: str,
    machine: str | None = None,
) -> tuple[ImageFile, str]:
    display_path = path
    if machine:
        if not get_settings().remote_enabled:
            raise RuntimeError("Remote workers are disabled")
        stat = await _remote_transfer_data(
            machine,
            "transfer_stat",
            {"path": path, "sha256": False},
        )
        if not isinstance(stat, dict) or stat.get("type") != "file":
            raise ValueError(f"source is not a file: {path}")
        assert_view_image_size(int(stat.get("size") or 0))
        temporary = await asyncio.to_thread(transfer_alloc_temp_path, ".bin")
        temporary_path = temporary["path"]
        try:
            await _copy_remote_file_to_local(
                machine,
                path,
                temporary_path,
                True,
            )
            image = await asyncio.to_thread(read_image, temporary_path)
        finally:
            with suppress(Exception):
                await asyncio.to_thread(delete_path, temporary_path, False)
        display_path = str(stat.get("path") or path)
    else:
        image = await asyncio.to_thread(read_image, path)
        display_path = image.path
    return image, display_path


async def _view_image_result(path: str, machine: str | None = None) -> CallToolResult:
    try:
        image, display_path = await load_image_for_machine(path, machine)
        return _view_image_success_result(image, display_path, machine)
    except Exception as exc:
        return _view_image_error_result(path, machine, exc)


def _read_audit_tail_entries(lines: int = 100) -> dict:
    settings = get_settings()
    line_limit = max(1, min(lines, 1000))
    max_bytes = max(1, settings.max_audit_tail_bytes)
    if settings.state_backend != "file":
        stored = get_state_store().read_bytes("audit.jsonl") or b""
        bytes_read = min(len(stored), max_bytes)
        content_bytes = stored[-bytes_read:]
        if bytes_read < len(stored):
            newline = content_bytes.find(b"\n")
            if newline >= 0:
                content_bytes = content_bytes[newline + 1 :]
        content = content_bytes.decode("utf-8", errors="replace").splitlines()[-line_limit:]
        entries = []
        for line in content:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                entries.append({"raw": line})
        return {
            "entries": entries,
            "bytes_read": bytes_read,
            "truncated_bytes": max(0, len(stored) - bytes_read),
        }

    path = settings.audit_log_path
    if not path.exists():
        return {"entries": []}

    chunks: list[bytes] = []
    bytes_read = 0
    newline_count = 0
    with path.open("rb") as fh:
        fh.seek(0, 2)
        position = fh.tell()
        while position > 0 and bytes_read < max_bytes and newline_count <= line_limit:
            read_size = min(8192, position, max_bytes - bytes_read)
            position -= read_size
            fh.seek(position)
            chunk = fh.read(read_size)
            chunks.append(chunk)
            bytes_read += len(chunk)
            newline_count += chunk.count(b"\n")

    content = (
        b"".join(reversed(chunks)).decode("utf-8", errors="replace").splitlines()[-line_limit:]
    )
    entries = []
    for line in content:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            entries.append({"raw": line})
    return {
        "entries": entries,
        "bytes_read": bytes_read,
        "truncated_bytes": max(0, path.stat().st_size - bytes_read),
    }


async def _remote_call(
    settings: Any,
    machine: str,
    tool: str,
    args: dict,
    timeout_s: int | None = None,
) -> ToolResult:
    try:
        if not settings.remote_enabled:
            raise RuntimeError("Remote workers are disabled")
        result = await remote_manager().call(machine, tool, args, timeout_s)
        data = result.get("data") if isinstance(result, dict) else None
        failed_status = (
            isinstance(data, dict)
            and data.get("status") in {"error", "not_found", "executable_not_found"}
        )
        if not result.get("ok", False) or failed_status:
            if not isinstance(data, dict):
                data = {
                    "status": "error",
                    "error_type": "remote_error",
                    "message": result.get("message", "remote job failed"),
                }
            return _error_call_result(
                data,
                result.get("message") or data.get("message") or "Remote tool failed",
            )
        return result
    except Exception as exc:
        return _handled_error(exc)


def _register_environment_tools(
    mcp: FastMCP, settings: Any, read_only_tool: ToolAnnotations
) -> None:
    shell_read_meta = _oauth_meta(["shell:read"])

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def environment_get(machine: str | None = None) -> ToolResult:
        """Return version, workspace, auth, policy, and environment information locally or on a remote machine."""
        if machine:
            return await _remote_call(settings, machine, "environment_info", {})
        try:
            public_settings = safe_settings_dump(settings)
            public_settings["default_timeout_s"] = PUBLIC_RUN_SHELL_DEFAULT_TIMEOUT_S
            public_settings["max_timeout_s"] = PUBLIC_RUN_SHELL_TIMEOUT_CAP_S
            python = quote_shell_argument(settings.python_bin)
            git = quote_shell_argument(settings.git_bin)
            result = await run_shell(
                f"uname -a; echo '---'; id; echo '---'; pwd; echo '---'; "
                f"{python} --version; {git} --version",
                cwd=".",
                timeout_s=10,
            )
            return _ok(
                {
                    "version": get_version_info(),
                    "settings": public_settings,
                    "persistent_shell": persistent_shell_backend_info(),
                    "probe": result.model_dump(),
                }
            )
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def skill_list() -> ToolResult:
        """List installed agent skills without loading their instructions. The MCP tool surface stays fixed; adding or removing skill directories is reflected on the next call."""
        return await _tool_call(asyncio.to_thread, list_installed_skills, settings)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def skill_load(name: str) -> ToolResult:
        """Load one installed agent skill by the exact name returned from skill_list. Returns SKILL.md instructions plus related file paths."""
        return await _tool_call(asyncio.to_thread, load_installed_skill, name, settings)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def skill_read(name: str, path: str) -> ToolResult:
        """Read one related text file from an installed Skill."""
        return await _tool_call(asyncio.to_thread, read_installed_skill_file, name, path, settings)


def _register_command_tools(mcp: FastMCP, settings: Any) -> None:
    shell_execute_meta = _oauth_meta(["shell:read", "shell:execute"])

    @mcp.tool(structured_output=True, meta=shell_execute_meta)
    async def run_shell(
        command: str,
        cwd: str = ".",
        timeout_s: int | None = None,
        max_output_bytes: int | None = None,
        purpose: str | None = None,
        explanation: str | None = None,
        machine: str | None = None,
    ) -> ToolResult:
        """Run one non-interactive shell command locally or on a remote machine. Use for build, test, package-manager, Git, and inspection commands that should finish promptly. For long-running, interactive, or streaming processes, use shell_start or job_start. Optional purpose/explanation fields let agents state why the command is being run."""
        _audit_tool_purpose("run_shell", purpose, explanation)
        if machine:
            return await _remote_call(
                settings,
                machine,
                "run_shell_tool",
                {
                    "command": command,
                    "cwd": cwd,
                    "timeout_s": timeout_s,
                    "max_output_bytes": max_output_bytes,
                },
                timeout_s,
            )
        try:
            return _ok(
                (await public_run_shell(command, cwd, timeout_s, max_output_bytes)).model_dump()
            )
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=shell_execute_meta)
    async def run_python(
        code: str,
        cwd: str = ".",
        timeout_s: int = 60,
        purpose: str | None = None,
        explanation: str | None = None,
        machine: str | None = None,
    ) -> ToolResult:
        """Write and run a short Python script locally or on a remote machine."""
        _audit_tool_purpose("run_python", purpose, explanation)
        if machine:
            return await _remote_call(
                settings,
                machine,
                "run_python_tool",
                {"code": code, "cwd": cwd, "timeout_s": timeout_s},
                timeout_s,
            )
        return await _tool_call(_run_python, code, cwd, timeout_s)


def _register_shell_tools(mcp: FastMCP, settings: Any, read_only_tool: ToolAnnotations) -> None:
    shell_read_meta = _oauth_meta(["shell:read"])
    shell_execute_meta = _oauth_meta(["shell:read", "shell:execute"])

    @mcp.tool(structured_output=True, meta=shell_execute_meta)
    async def shell_start(
        cwd: str = ".",
        name: str | None = None,
        command: str | None = None,
        purpose: str | None = None,
        explanation: str | None = None,
        machine: str | None = None,
    ) -> ToolResult:
        """Start a persistent interactive shell locally or on a remote machine."""
        _audit_tool_purpose("shell_start", purpose, explanation)
        if machine:
            return await _remote_call(
                settings,
                machine,
                "shell_start",
                {"cwd": cwd, "name": name, "command": command},
            )
        return await _tool_call(start_shell, cwd, name, command)

    @mcp.tool(structured_output=True, meta=shell_execute_meta)
    async def shell_send(
        session_id: str,
        input_text: str,
        enter: bool = True,
        machine: str | None = None,
    ) -> ToolResult:
        """Send input to a persistent local or remote shell session."""
        if machine:
            return await _remote_call(
                settings,
                machine,
                "shell_send",
                {"session_id": session_id, "input_text": input_text, "enter": enter},
            )
        return await _tool_call(send_shell, session_id, input_text, enter)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def shell_read(
        session_id: str,
        lines: int = 200,
        machine: str | None = None,
    ) -> ToolResult:
        """Read recent output from a persistent local or remote shell session."""
        if machine:
            return await _remote_call(
                settings,
                machine,
                "shell_read",
                {"session_id": session_id, "lines": lines},
            )
        return await _tool_call(read_shell, session_id, lines)

    @mcp.tool(structured_output=True, meta=shell_execute_meta)
    async def shell_stop(
        session_id: str,
        machine: str | None = None,
    ) -> ToolResult:
        """Terminate a persistent local or remote shell session."""
        if machine:
            return await _remote_call(settings, machine, "shell_kill", {"session_id": session_id})
        return await _tool_call(kill_shell, session_id)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def shell_list(machine: str | None = None) -> ToolResult:
        """List persistent shell sessions locally or on a remote machine."""
        if machine:
            return await _remote_call(settings, machine, "shell_list", {})
        return await _tool_call(list_shells)


def _register_job_tools(mcp: FastMCP, settings: Any, read_only_tool: ToolAnnotations) -> None:
    shell_read_meta = _oauth_meta(["shell:read"])
    shell_execute_meta = _oauth_meta(["shell:read", "shell:execute"])

    @mcp.tool(structured_output=True, meta=shell_execute_meta)
    async def job_start(
        command: str,
        cwd: str = ".",
        name: str | None = None,
        purpose: str | None = None,
        explanation: str | None = None,
        machine: str | None = None,
    ) -> ToolResult:
        """Start a tracked long-running job locally or on a remote machine."""
        _audit_tool_purpose("job_start", purpose, explanation)
        if machine:
            return await _remote_call(
                settings,
                machine,
                "job_start",
                {"command": command, "cwd": cwd, "name": name},
            )
        return await _tool_call(start_job, command, cwd, name)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def job_list(
        include_finished: bool = True,
        limit: int = JOB_LIST_DEFAULT_LIMIT,
        machine: str | None = None,
    ) -> ToolResult:
        """List tracked jobs locally or on a remote machine. Active jobs are returned first; limit is clamped to 1-1000."""
        if machine:
            return await _remote_call(
                settings,
                machine,
                "job_list",
                {"include_finished": include_finished, "limit": limit},
            )
        return await _tool_call(list_jobs, include_finished, limit)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def job_tail(
        job_id: str,
        lines: int = 200,
        machine: str | None = None,
    ) -> ToolResult:
        """Read recent output for a tracked local or remote job."""
        if machine:
            return await _remote_call(
                settings,
                machine,
                "job_tail",
                {"job_id": job_id, "lines": lines},
            )
        return await _tool_call(tail_job, job_id, lines)

    @mcp.tool(structured_output=True, meta=shell_execute_meta)
    async def job_stop(
        job_id: str,
        machine: str | None = None,
    ) -> ToolResult:
        """Stop a tracked local or remote job."""
        if machine:
            return await _remote_call(settings, machine, "job_stop", {"job_id": job_id})
        return await _tool_call(stop_job, job_id)

    @mcp.tool(structured_output=True, meta=shell_execute_meta)
    async def job_retry(
        job_id: str,
        purpose: str | None = None,
        explanation: str | None = None,
        machine: str | None = None,
    ) -> ToolResult:
        """Restart a stopped or exited tracked local or remote job."""
        _audit_tool_purpose("job_retry", purpose, explanation)
        if machine:
            return await _remote_call(settings, machine, "job_retry", {"job_id": job_id})
        return await _tool_call(retry_job, job_id)


def _register_workspace_read_tools(
    mcp: FastMCP, settings: Any, read_only_tool: ToolAnnotations
) -> None:
    shell_read_meta = _oauth_meta(["shell:read"])

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def file_list(
        path: str = ".",
        recursive: bool = False,
        max_entries: int = 500,
        machine: str | None = None,
    ) -> ToolResult:
        """List files and directories locally or on a remote machine."""
        if machine:
            return await _remote_call(
                settings,
                machine,
                "list_files",
                {
                    "path": path,
                    "recursive": recursive,
                    "max_entries": max_entries,
                },
            )
        return await _tool_call(asyncio.to_thread, list_dir, path, recursive, max_entries)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def file_tree(
        cwd: str = ".",
        depth: int = 3,
        max_entries: int = 500,
        machine: str | None = None,
    ) -> ToolResult:
        """Return a compact directory tree locally or on a remote machine."""
        if machine:
            return await _remote_call(
                settings,
                machine,
                "tree_view",
                {"cwd": cwd, "depth": depth, "max_entries": max_entries},
            )
        return await _tool_call(tree, cwd, depth, max_entries)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def file_glob(
        pattern: str,
        cwd: str = ".",
        max_results: int = 500,
        machine: str | None = None,
    ) -> ToolResult:
        """Find paths by glob locally or on a remote machine."""
        if machine:
            return await _remote_call(
                settings,
                machine,
                "glob_search",
                {"pattern": pattern, "cwd": cwd, "max_results": max_results},
            )
        try:
            return _ok({"paths": await asyncio.to_thread(glob_paths, pattern, cwd, max_results)})
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def file_grep(
        query: str,
        cwd: str = ".",
        glob: str | None = None,
        regex: bool = True,
        case_sensitive: bool = True,
        max_results: int | None = None,
        machine: str | None = None,
    ) -> ToolResult:
        """Search file contents locally or on a remote machine."""
        if machine:
            return await _remote_call(
                settings,
                machine,
                "grep_search",
                {
                    "query": query,
                    "cwd": cwd,
                    "glob": glob,
                    "regex": regex,
                    "case_sensitive": case_sensitive,
                    "max_results": max_results,
                },
            )
        return await _tool_call(grep, query, cwd, glob, regex, case_sensitive, max_results)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def file_read(
        path: str | list[str],
        start_line: int | None = None,
        end_line: int | None = None,
        binary_preview: str | None = None,
        binary_preview_bytes: int = 256,
        machine: str | None = None,
    ) -> ToolResult:
        """Read one file or a list of files locally or on a remote machine."""
        args = {
            "path": path,
            "start_line": start_line,
            "end_line": end_line,
            "binary_preview": binary_preview,
            "binary_preview_bytes": binary_preview_bytes,
        }
        if machine:
            return await _remote_call(settings, machine, "read_file", args)
        return await _tool_call(
            asyncio.to_thread,
            read_texts,
            path,
            start_line,
            end_line,
            binary_preview,
            binary_preview_bytes,
        )

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def image_view(
        path: str,
        machine: str | None = None,
    ) -> ViewImageResult:
        """View a PNG, JPEG, GIF, or WebP file as native MCP image content locally or on a remote machine. Use this instead of file_read when visual inspection is needed. Remote images reuse the existing file-transfer protocol, so the worker does not need a new image-specific RPC."""
        return cast(ViewImageResult, await _view_image_result(path, machine))


def _register_download_tools(mcp: FastMCP, read_only_tool: ToolAnnotations) -> None:
    file_share_meta = _oauth_meta(["shell:read", "file:share"])

    @mcp.tool(structured_output=True, meta=file_share_meta)
    async def link_create(
        path: str,
        ttl_s: int | None = None,
        filename: str | None = None,
        max_downloads: int | None = None,
        inline: bool = False,
    ) -> ToolResult:
        """Create a temporary browser-accessible URL for a local file. By default the response is an attachment download; set inline=true when the file should render directly in a browser or Markdown image. Links are public bearer URLs protected by a high-entropy token, TTL, optional download-count limit, and explicit revocation."""
        return await _tool_call(
            asyncio.to_thread,
            create_share_link,
            path,
            ttl_s,
            filename,
            max_downloads,
            inline,
        )

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=file_share_meta)
    async def link_list(include_expired: bool = False) -> ToolResult:
        """List generated local file download URLs."""
        return await _tool_call(asyncio.to_thread, list_share_links, include_expired)

    @mcp.tool(structured_output=True, meta=file_share_meta)
    async def link_revoke(token: str) -> ToolResult:
        """Revoke a generated local file download URL."""
        return await _tool_call(asyncio.to_thread, revoke_share_link, token)


def _register_workspace_write_tools(mcp: FastMCP, settings: Any) -> None:
    shell_write_meta = _oauth_meta(["shell:read", "shell:write"])
    patch_meta = _oauth_meta(["shell:read", "shell:write"])
    transfer_meta = _oauth_meta(["remote:use", "shell:read", "shell:write"])

    @mcp.tool(structured_output=True, meta=shell_write_meta)
    async def file_write(
        path: str,
        content: str,
        overwrite: bool = True,
        encoding: Literal["utf-8", "base64"] = "utf-8",
        purpose: str | None = None,
        explanation: str | None = None,
        machine: str | None = None,
    ) -> ToolResult:
        """Write a UTF-8 text file or base64-encoded binary file locally or remotely."""
        _audit_tool_purpose("file_write", purpose, explanation)
        if machine:
            return await _remote_call(
                settings,
                machine,
                "write_file",
                {
                    "path": path,
                    "content": content,
                    "overwrite": overwrite,
                    "encoding": encoding,
                },
            )
        if encoding == "utf-8":
            return await _tool_call(asyncio.to_thread, write_text, path, content, overwrite)
        return await _tool_call(
            asyncio.to_thread, write_content, path, content, overwrite, None, encoding
        )

    @mcp.tool(structured_output=True, meta=shell_write_meta)
    async def file_edit(
        path: str,
        edits: list[TextEdit],
        purpose: str | None = None,
        explanation: str | None = None,
        machine: str | None = None,
    ) -> ToolResult:
        """Apply one or more exact-text edits to one local or remote file. Each edits entry contains old, new, and optional replace_all; old must match exactly, including whitespace and indentation."""
        _audit_tool_purpose("file_edit", purpose, explanation)
        edit_payloads = [edit.model_dump() for edit in edits]
        if machine:
            return await _remote_call(
                settings,
                machine,
                "edit_file",
                {"path": path, "edits": edit_payloads},
            )
        return await _tool_call(asyncio.to_thread, edit_text, path, edit_payloads)

    @mcp.tool(structured_output=True, meta=shell_write_meta)
    async def file_delete(
        path: str,
        recursive: bool = False,
        purpose: str | None = None,
        explanation: str | None = None,
        machine: str | None = None,
    ) -> ToolResult:
        """Delete a local or remote file or directory. recursive=false deletes files or empty directories; recursive=true is required for non-empty directories and should be used carefully."""
        _audit_tool_purpose("file_delete", purpose, explanation)
        if machine:
            return await _remote_call(
                settings,
                machine,
                "delete_file_or_dir",
                {"path": path, "recursive": recursive},
            )
        return await _tool_call(asyncio.to_thread, delete_path, path, recursive)

    @mcp.tool(structured_output=True, meta=patch_meta)
    async def file_patch(
        patch: str,
        cwd: str = ".",
        purpose: str | None = None,
        explanation: str | None = None,
        machine: str | None = None,
    ) -> ToolResult:
        """Check and apply a unified diff or an apply_patch envelope locally or remotely."""
        _audit_tool_purpose("file_patch", purpose, explanation)
        if machine:
            return await _remote_call(
                settings,
                machine,
                "apply_patch",
                {"patch": patch, "cwd": cwd},
            )
        return await _tool_call(_apply_patch_text, patch, cwd)

    @mcp.tool(structured_output=True, meta=transfer_meta)
    async def remote_transfer(
        source_path: str,
        destination_path: str,
        source_machine: str | None = None,
        destination_machine: str | None = None,
        overwrite: bool = False,
        chunk_size: int | None = None,
        purpose: str | None = None,
        explanation: str | None = None,
    ) -> ToolResult:
        """Start a tracked job that copies a file or directory between the controller and remote machines. Remote uploads use resumable raw-binary chunks; use job_list, job_tail, job_stop, and job_retry to manage the transfer."""
        _audit_tool_purpose("remote_transfer", purpose, explanation)
        return await _tool_call(
            _start_transfer_job,
            source_path,
            destination_path,
            source_machine,
            destination_machine,
            overwrite,
            chunk_size,
        )


def _current_principal_subject() -> str:
    principal = current_principal()
    if principal is None:
        return "local-mcp-client"
    return principal.subject or principal.email or "mcp-client"


def _register_maintenance_tools(mcp: FastMCP, read_only_tool: ToolAnnotations) -> None:
    shell_read_meta = _oauth_meta(["shell:read"])
    shell_write_meta = _oauth_meta(["shell:read", "shell:write"])

    @mcp.tool(structured_output=True, meta=shell_write_meta)
    async def session_manage(
        action: str,
        session_id: str | None = None,
        label: str | None = None,
        objective: str | None = None,
        summary: str | None = None,
        findings: list[str] | None = None,
        next: str | None = None,
        blockers: list[str] | None = None,
    ) -> ToolResult:
        """Manage one durable Logical Session. Start creates a new task and returns its session_id. Resume continues only the explicit session_id supplied by the user or already present in this conversation. All non-start actions require session_id. Actions: start, resume, get, report, finish, cancel, delete. report accepts summary/findings/next/blockers/objective/label. delete requires a terminal Session."""
        subject = _current_principal_subject()
        result = await _tool_call(
            asyncio.to_thread,
            get_session_runtime_manager().manage,
            subject,
            action=action,
            session_id=session_id,
            label=label,
            objective=objective,
            summary=summary,
            findings=findings,
            next=next,
            blockers=blockers,
        )
        if isinstance(result, dict) and result.get("ok"):
            data = result.get("data")
            normalized_action = action.strip().lower()
            if isinstance(data, dict):
                changed_session_id = str(data.get("session_id") or session_id or "")
                if changed_session_id and normalized_action == "delete":
                    get_live_channel_manager().detach_logical_session(changed_session_id)
                elif changed_session_id and normalized_action in {
                    "resume",
                    "report",
                    "finish",
                    "cancel",
                }:
                    channel = get_live_channel_manager().active_for_logical_session(
                        changed_session_id, subject=subject
                    )
                    if channel is not None:
                        get_live_channel_manager().publish_channel(
                            channel.live_id,
                            "session.updated",
                            actor="agent",
                            data={"session_id": changed_session_id, "action": normalized_action},
                        )
        return result

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def secret_scan(
        cwd: str = ".",
        glob: str | None = None,
        max_results: int = 200,
    ) -> ToolResult:
        """Scan local workspace text files for common secrets before commit or push."""
        return await _tool_call(_secret_scan, cwd, glob, max_results)

    @mcp.tool(structured_output=True, meta=shell_write_meta)
    async def plan_manage(
        action: str,
        session_id: str,
        objective: str | None = None,
        steps: list[dict[str, Any]] | None = None,
        step_id: str | None = None,
        status: str | None = None,
        text: str | None = None,
        note: str | None = None,
    ) -> ToolResult:
        """Manage optional Goal mode for the explicit Logical Session. An active plan enables automatic continuation after 15 minutes without agent activity, capped at 10 continuation attempts. session_id must be the same durable id returned by session_manage. Actions: start, get, update, block, resume, finish, cancel. start requires objective and steps; finish requires every step to be completed or skipped."""
        return await _tool_call(
            asyncio.to_thread,
            get_session_runtime_manager().manage_plan,
            session_id,
            action=action,
            subject=_current_principal_subject(),
            objective=objective,
            steps=steps,
            step_id=step_id,
            status=status,
            text=text,
            note=note,
        )

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def audit_tail(lines: int = 100) -> ToolResult:
        """Read recent local audit log entries."""
        return await _tool_call(asyncio.to_thread, _read_audit_tail_entries, lines)


def _register_dynamic_mcp_tools(
    mcp: FastMCP, settings: Any, read_only_tool: ToolAnnotations
) -> None:
    manager = DynamicMCPManager(settings.state_dir, max_timeout_s=settings.max_timeout_s)
    shell_read_meta = _oauth_meta(["shell:read"])
    shell_execute_meta = _oauth_meta(["shell:read", "shell:execute"])

    @mcp.tool(structured_output=True, meta=shell_execute_meta)
    async def mcp_manage(
        action: str,
        name: str | None = None,
        transport: str | None = None,
        command: str | None = None,
        args: list[str] | None = None,
        cwd: str | None = None,
        url: str | None = None,
        env: dict[str, Any] | None = None,
        headers: dict[str, Any] | None = None,
        enabled: bool = True,
        overwrite: bool = False,
        refresh: bool = True,
        key: str | None = None,
        value: str | None = None,
    ) -> ToolResult:
        """Register, list, get, enable, disable, refresh, remove, or update the isolated environment/headers of dynamic MCP servers. Use transport=stdio with command/args/cwd, or transport=streamable_http with url. Secret env/header values are persisted privately and are never returned."""
        return await _tool_call(
            manager.manage,
            action=action,
            name=name,
            transport=transport,
            command=command,
            args=args,
            cwd=cwd,
            url=url,
            env=env,
            headers=headers,
            enabled=enabled,
            overwrite=overwrite,
            refresh=refresh,
            key=key,
            value=value,
        )

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def mcp_tool_search(
        query: str = "", server: str | None = None, limit: int = 20
    ) -> ToolResult:
        """Search cached lightweight tool summaries from enabled dynamic MCP servers. Dynamic tools stay out of this server's tools/list; use the returned <server>:<tool> name with mcp_tool_inspect before calling it."""
        return await _tool_call(manager.search, query, server=server, limit=limit)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def mcp_tool_inspect(name: str) -> ToolResult:
        """Return the full cached schema for one dynamic MCP tool named <server>:<tool>. Refresh the server with mcp_manage if its cached schema is stale."""
        return await _tool_call(manager.inspect, name)

    @mcp.tool(structured_output=True, meta=shell_execute_meta)
    async def mcp_tool_call(
        name: str,
        arguments: dict[str, Any] | None = None,
        timeout_s: int | None = None,
    ) -> ToolResult:
        """Call one cached dynamic MCP tool named <server>:<tool>. Discover it with mcp_tool_search and inspect its schema with mcp_tool_inspect first. External MCP connections are opened only for the duration of this call."""
        try:
            result = await manager.call(name, arguments, timeout_s=timeout_s)
        except Exception as exc:
            return _handled_error(exc)
        downstream = result.get("result") if isinstance(result, dict) else None
        if isinstance(downstream, dict) and downstream.get("isError") is True:
            return _error_call_result(result, f"Dynamic MCP tool returned an error: {name}")
        return _ok(result)


def _register_chat_dispatch_tools(mcp: FastMCP, settings: Any) -> None:
    chat_dispatch_meta = _oauth_meta(["browser:use", "shell:execute"])

    @mcp.tool(structured_output=True, meta=chat_dispatch_meta)
    async def chat_dispatch(
        action: str = "enqueue",
        prompt: str | None = None,
        conversation_key: str | None = None,
        conversation_url: str | None = None,
        project_url: str | None = None,
        dispatch_id: str | None = None,
        idempotency_key: str | None = None,
        max_windows: int | None = None,
        idle_close_s: int | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Queue and supervise prompts to new or existing ChatGPT child conversations.

        Use action="enqueue" (default) to durably queue a prompt. For an existing child,
        provide conversation_url or a previously resolved conversation_key. For a new child,
        provide project_url plus a stable conversation_key; once the first prompt creates a
        /c/ conversation, later enqueue calls may use only that key. Every enqueue must include
        an idempotency_key so a repeated call returns the original dispatch instead of sending
        twice after an interrupted tool call.

        The dispatcher borrows already-open user Chrome windows without closing them. If it
        must open its own page, it keeps that exact HWND/PID until the queue for the child is
        drained, waits idle_close_s, then closes only that owned page. Ambiguous Send outcomes
        are fenced as RECONCILE_REQUIRED and are never replayed automatically.

        Use action="status" with optional dispatch_id to inspect durable jobs/pages and the
        resident watchdog; use action="cancel" only for a pre-send dispatch; use action="ensure"
        to restart a short-lived dispatcher for pending durable work. watchdog_start,
        watchdog_status, and watchdog_stop manage the hidden detached recovery loop.
        """

        return await asyncio.to_thread(
            manage_chat_dispatch,
            settings,
            action=action,
            prompt=prompt,
            conversation_key=conversation_key,
            conversation_url=conversation_url,
            project_url=project_url,
            dispatch_id=dispatch_id,
            idempotency_key=idempotency_key,
            max_windows=max_windows,
            idle_close_s=idle_close_s,
            limit=limit,
        )


def _register_browser_tools(mcp: FastMCP, settings: Any, read_only_tool: ToolAnnotations) -> None:
    browser_meta = _oauth_meta(["browser:use"])
    browser_execute_meta = _oauth_meta(["browser:use", "shell:execute"])
    session_manager = get_browser_session_manager(settings.state_dir)

    @mcp.tool(structured_output=True, meta=browser_meta)
    async def browser_session(
        action: str,
        session_id: str | None = None,
        browser: str = "chromium",
        headless: bool = True,
        width: int = 1440,
        height: int = 1000,
        url: str | None = None,
        wait_until: str = "domcontentloaded",
        profile_id: str | None = None,
        storage_state_path: str | None = None,
        save_storage_state_path: str | None = None,
        machine: str | None = None,
    ) -> ToolResult:
        """Start, list, close, or clean up persistent high-level browser sessions locally or remotely. start can open a URL, reuse a persistent profile_id, or load storage_state_path; close can save storage state."""
        args = {
            "action": action,
            "session_id": session_id,
            "browser": browser,
            "headless": headless,
            "width": width,
            "height": height,
            "url": url,
            "wait_until": wait_until,
            "profile_id": profile_id,
            "storage_state_path": storage_state_path,
            "save_storage_state_path": save_storage_state_path,
        }
        if machine:
            return await _remote_call(settings, machine, "browser_session", args)
        return await _tool_call(session_manager.manage, **args)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=browser_meta)
    async def browser_snapshot(
        session_id: str,
        page_id: str | None = None,
        include_text: bool = True,
        screenshot: bool = True,
        full_page: bool = False,
        max_text_chars: int = 100_000,
        max_elements: int = 100,
        machine: str | None = None,
    ) -> ToolResult:
        """Capture a persistent browser page: title, URL, bounded visible text, interactive elements with stable short refs such as e1, recent page/network errors, and an optional screenshot path. Use refs directly as browser_act targets until the page navigates or a new snapshot is taken."""
        args = {
            "session_id": session_id,
            "page_id": page_id,
            "include_text": include_text,
            "screenshot": screenshot,
            "full_page": full_page,
            "max_text_chars": max_text_chars,
            "max_elements": max_elements,
        }
        if machine:
            return await _remote_call(settings, machine, "browser_snapshot", args)
        return await _tool_call(session_manager.snapshot, **args)

    @mcp.tool(structured_output=True, meta=browser_meta)
    async def browser_act(
        session_id: str,
        actions: list[dict[str, Any]],
        page_id: str | None = None,
        timeout_ms: int = 30_000,
        machine: str | None = None,
    ) -> ToolResult:
        """Run structured actions in a persistent browser session. Supports navigate, new_page, close_page, click, fill, type, select, press, check, uncheck, hover, wait, wait_for_text, and wait_for_url. target may be a browser_snapshot ref such as e1 or a CSS selector. Use browser_run_script only when these high-level actions are insufficient."""
        args = {
            "session_id": session_id,
            "actions": actions,
            "page_id": page_id,
            "timeout_ms": timeout_ms,
        }
        if machine:
            return await _remote_call(settings, machine, "browser_act", args)
        return await _tool_call(session_manager.act, **args)

    @mcp.tool(structured_output=True, meta=browser_execute_meta)
    async def browser_run_script(
        script: str,
        cwd: str = ".",
        timeout_s: int = 60,
        machine: str | None = None,
    ) -> ToolResult:
        """Run a full Python Playwright script locally or on a remote machine."""
        if machine:
            return await _remote_call(
                settings,
                machine,
                "browser_run_script",
                {"script": script, "cwd": cwd, "timeout_s": timeout_s},
                timeout_s,
            )
        return await _tool_call(playwright_run_script, script, cwd, timeout_s)


def _register_remote_admin_tools(mcp: FastMCP) -> None:
    remote_meta = _oauth_meta(["remote:use"])

    @mcp.tool(structured_output=True, meta=remote_meta)
    async def remote_manage(
        action: str,
        name: str | None = None,
        workdir: str | None = None,
        ttl_s: int | None = None,
        machine: str | None = None,
        new_name: str | None = None,
    ) -> ToolResult:
        """Manage remote workers with action=invite, list, revoke, or rename. invite accepts name/workdir/ttl_s; revoke requires machine; rename requires machine and new_name."""

        async def run() -> Any:
            manager = remote_manager()
            normalized = action.strip().lower()
            if normalized == "invite":
                return await manager.create_invite(name, workdir, ttl_s)
            if normalized == "list":
                return manager.list_machines()
            if normalized == "revoke":
                if not machine:
                    raise ValueError("machine is required for action=revoke")
                return manager.revoke(machine)
            if normalized == "rename":
                if not machine:
                    raise ValueError("machine is required for action=rename")
                if not new_name:
                    raise ValueError("new_name is required for action=rename")
                return manager.rename(machine, new_name)
            raise ValueError("action must be one of: invite, list, revoke, rename")

        return await _tool_call(run)


def _register_live_workspace_tools(
    mcp: FastMCP,
    settings: Any,
) -> None:
    resource_options = {
        "name": "local-shell-mcp-live-workspace",
        "title": "LSM Live Workspace",
        "description": "Interactive human/agent workspace for local-shell-mcp execution.",
        "mime_type": LIVE_RESOURCE_MIME,
        "meta": _live_workspace_resource_meta(),
    }

    @mcp.resource(
        LIVE_RESOURCE_URI,
        **resource_options,
    )
    def live_workspace_resource() -> str:
        return _live_workspace_html()

    @mcp.resource(
        LIVE_RESOURCE_VERSIONED_URI,
        **resource_options,
    )
    def versioned_live_workspace_resource() -> str:
        return _live_workspace_html()

    for compatibility_uri in LIVE_RESOURCE_COMPAT_URIS:
        mcp.resource(
            compatibility_uri,
            **resource_options,
        )(live_workspace_resource)

    @mcp.resource(
        LIVE_RESOURCE_TEMPLATE_URI,
        **resource_options,
    )
    def cached_live_workspace_resource(version: str) -> str:
        del version
        return _live_workspace_html()

    tool_meta = {
        **_oauth_meta(list(ALL_OAUTH_SCOPES)),
        "ui": {"resourceUri": LIVE_RESOURCE_VERSIONED_URI},
        # Use the content-versioned URI as the render cache key. Keep the stable
        # resource registered as a compatibility alias for direct readers.
        "ui/resourceUri": LIVE_RESOURCE_VERSIONED_URI,
        "openai/outputTemplate": LIVE_RESOURCE_VERSIONED_URI,
        "openai/widgetAccessible": True,
        "openai/toolInvocation/invoking": "Opening live workspace",
        "openai/toolInvocation/invoked": "Live workspace ready",
    }

    async def build_live_channel_result(
        *,
        machine: str | None,
        cwd: str,
        live_id: str | None,
        session_id: str | None = None,
        app_reattach: bool = False,
    ) -> LiveChannelResult:
        principal = current_principal()
        subject = _current_principal_subject()
        scopes = (
            tuple(ALL_OAUTH_SCOPES)
            if principal is None
            else tuple(sorted(principal_scopes(principal))) or tuple(ALL_OAUTH_SCOPES)
        )
        session_manager = get_session_runtime_manager()
        logical_session_id = None
        if session_id:
            try:
                await asyncio.to_thread(session_manager.get, session_id, subject=subject)
            except ValueError as exc:
                if not app_reattach or not str(exc).startswith("Unknown logical session:"):
                    raise
                # A suspended app can reconnect after the Session was deleted.
                get_live_channel_manager().detach_logical_session(session_id)
            else:
                logical_session_id = session_id
        channel, live_token = get_live_channel_manager().open(
            subject=subject,
            scopes=scopes,
            live_id=live_id,
            logical_session_id=logical_session_id,
            app_reattach=app_reattach,
            machine=machine,
            cwd=cwd,
            parent_expires_at=(
                float(principal.claims["exp"])
                if principal is not None and principal.claims.get("exp") is not None
                else None
            ),
        )
        result = LiveChannelResult(
            live_id=channel.live_id,
            session_id=channel.logical_session_id,
            api_base=_live_workspace_api_base(),
            ui_path=settings.ui_path,
            machine=channel.machine,
            cwd=channel.cwd,
        )
        return cast(
            LiveChannelResult,
            CallToolResult(
                _meta={
                    "local-shell-mcp/live": {
                        "token": live_token,
                        "apiBase": result.api_base,
                        "uiPath": result.ui_path,
                        "liveId": result.live_id,
                    }
                },
                content=[TextContent(type="text", text="Live Workspace channel ready.")],
                structuredContent=result.model_dump(mode="json"),
            ),
        )

    @mcp.tool(
        structured_output=True,
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        meta=tool_meta,
    )
    async def workspace_open(
        session_id: str | None,
        machine: str | None = None,
        cwd: str = ".",
    ) -> LiveChannelResult:
        """Open or reuse a Live Workspace that displays the explicitly supplied Logical Session. Pass the active session_id returned by session_manage. The Workspace never infers task identity from the MCP transport; pass null explicitly when no Logical Session is active."""
        return await build_live_channel_result(
            machine=machine,
            cwd=cwd,
            live_id=None,
            session_id=session_id,
            app_reattach=False,
        )

    @mcp.tool(
        structured_output=True,
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        meta=tool_meta,
    )
    async def open_live_workspace(
        session_id: str | None = None,
        machine: str | None = None,
        cwd: str = ".",
    ) -> LiveChannelResult:
        """Compatibility alias for workspace_open used by cached ChatGPT tool recipients."""
        return await workspace_open(session_id=session_id, machine=machine, cwd=cwd)

    @mcp.tool(
        structured_output=True,
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        meta={
            **_oauth_meta(list(ALL_OAUTH_SCOPES)),
            "ui": {"visibility": ["app"]},
        },
    )
    async def live_workspace_reconnect(
        machine: str | None = None,
        cwd: str = ".",
        live_id: str | None = None,
        session_id: str | None = None,
    ) -> LiveChannelResult:
        """Internal app-only Live Workspace credential attachment endpoint."""
        return await build_live_channel_result(
            machine=machine,
            cwd=cwd,
            live_id=live_id,
            session_id=session_id,
            app_reattach=True,
        )


def build_mcp() -> FastMCP:
    settings = get_settings()
    mcp = FastMCP(
        "local-shell-mcp",
        instructions=(
            MCP_INSTRUCTIONS if settings.logical_sessions_enabled else MCP_BASE_INSTRUCTIONS
        ),
        website_url="https://fwerkor.github.io/local-shell-mcp/",
        icons=[
            Icon(
                src="https://fwerkor.github.io/local-shell-mcp/assets/logo.svg",
                mimeType="image/svg+xml",
                sizes=["any"],
            )
        ],
        transport_security=_transport_security_settings(),
    )
    # FastMCP currently leaves the low-level server version unset, which makes
    # the MCP SDK advertise its own package version during initialize. Report
    # the local-shell-mcp version instead.
    mcp._mcp_server.version = __version__
    read_only_tool = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    if settings.ui_enabled and settings.live_workspace_enabled and settings.mode != "stdio":
        _register_live_workspace_tools(mcp, settings)
    _register_environment_tools(mcp, settings, read_only_tool)
    _register_command_tools(mcp, settings)
    _register_shell_tools(mcp, settings, read_only_tool)
    _register_job_tools(mcp, settings, read_only_tool)
    _register_workspace_read_tools(mcp, settings, read_only_tool)
    _register_download_tools(mcp, read_only_tool)
    _register_workspace_write_tools(mcp, settings)
    _register_maintenance_tools(mcp, read_only_tool)
    _register_dynamic_mcp_tools(mcp, settings, read_only_tool)
    _register_chat_dispatch_tools(mcp, settings)
    _register_browser_tools(mcp, settings, read_only_tool)
    _register_remote_admin_tools(mcp)

    _remove_remote_tools_when_disabled(mcp)
    _remove_local_only_tools_when_disabled(mcp)
    _remove_logical_session_tools_when_disabled(mcp)
    _install_tool_annotations(mcp)
    if settings.logical_sessions_enabled:
        _install_logical_session_arguments(mcp)
    _install_mcp_tool_watchdogs(mcp)
    return mcp
