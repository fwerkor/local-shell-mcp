from __future__ import annotations

import asyncio
import base64
import inspect
import json
import subprocess
import time
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations
from pathspec.gitignore import GitIgnoreSpec
from pydantic import BaseModel, ConfigDict, Field

from .audit import audit, audit_call_context, audit_result_ok
from .auth import require_current_scopes
from .downloads import create_share_link, list_share_links, revoke_share_link
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
    write_text,
)
from .image_ops import ImageFile, assert_view_image_size, read_image
from .jobs import list_jobs, retry_job, start_job, stop_job, tail_job
from .models import ToolResult
from .models import ok_result as _ok
from .oauth import ALL_OAUTH_SCOPES
from .playwright_ops import browser_capture, browser_get_text, playwright_run_script
from .remote import remote_manager
from .remote_transfer import (
    create_download_ticket,
    create_upload_ticket,
    revoke_transfer_ticket,
)
from .search_ops import grep, tree
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
from .tmux_helper import persistent_shell_backend_info
from .todo_ops import todo_read, todo_write
from .transfer_ops import (
    normalize_chunk_size,
    transfer_alloc_temp_path,
    transfer_pack_dir,
    transfer_stat,
    transfer_unpack_archive,
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


def _handled_error(exc: Exception) -> dict:
    audit("tool_error", error=repr(exc))
    if isinstance(exc, FileNotFoundError) and str(exc):
        with suppress(Exception):
            context = missing_path_context(str(exc))
            return _ok(
                {
                    "status": "not_found",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    **context,
                },
                message=f"Path not found: {context['path']}",
            )
    return _ok(
        {
            "status": "error",
            "error_type": type(exc).__name__,
            "message": str(exc),
        },
        message=f"Tool handled {type(exc).__name__}",
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
    await asyncio.to_thread(prune_temp_dir)
    patch_path = temp_dir() / f"patch-{uuid.uuid4().hex}.diff"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(patch_path.write_text, patch, encoding="utf-8")
    quoted = quote_shell_argument(str(patch_path))
    git = quote_shell_argument(get_settings().git_bin)
    result = await run_shell(
        f"{git} apply --check {quoted} && {git} apply {quoted}",
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
    python = quote_shell_argument(get_settings().python_bin)
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


OAUTH_SECURITY_SCHEMES = [_oauth_security_scheme(ALL_OAUTH_SCOPES)]
NOAUTH_SECURITY_SCHEMES = [{"type": "noauth"}]
PUBLIC_TOOL_TIMEOUT_S = PUBLIC_TOOL_WATCHDOG_TIMEOUT_S
MCP_INSTRUCTIONS = (
    "When a task may benefit from an installed Agent Skill, call skills_list first "
    "to discover the exact Skill name and description. Before following a Skill's "
    "workflow, call skill_load with that exact name. Call skill_read_file only when "
    "a related file returned by skill_load is needed. Skills use this fixed tool "
    "surface; do not expect per-Skill MCP tools."
)


class PublicToolTimeoutError(TimeoutError):
    pass


NON_CANCELLABLE_TOOL_NAMES = frozenset(
    {
        "create_file_link",
        "revoke_file_link",
        "view_image",
        "write_file",
        "edit_file",
        "delete_file_or_dir",
        "apply_patch",
        "transfer_path",
        "todo_write_tool",
    }
)

REMOTE_MACHINE_ARGUMENTS = frozenset({"machine", "source_machine", "destination_machine"})


def _security_meta(schemes: list[dict[str, Any]]) -> dict[str, Any]:
    return {"securitySchemes": schemes}


def _oauth_meta(scopes: list[str]) -> dict[str, Any]:
    return _security_meta([_oauth_security_scheme(scopes)])


def _public_read_meta() -> dict[str, Any]:
    return _security_meta([*NOAUTH_SECURITY_SCHEMES, _oauth_security_scheme(ALL_OAUTH_SCOPES)])


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


def _audit_tool_arguments(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    return {
        "positional_count": len(args),
        "keyword_args": _serialize_audit_value(kwargs),
    }


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


def _timeout_payload_for_tool(tool_name: str, exc: Exception) -> dict | str:
    if tool_name == "search":
        return json.dumps({"results": []}, ensure_ascii=False)
    if tool_name == "fetch":
        return json.dumps(
            {
                "id": "",
                "title": "",
                "text": str(exc),
                "url": "file:///workspace/",
                "metadata": {"source": "workspace", "error": type(exc).__name__},
            },
            ensure_ascii=False,
        )
    return _handled_error(exc)


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
            try:
                bound = __signature.bind_partial(*args, **kwargs)
                call_arguments = dict(bound.arguments)
            except TypeError:
                call_arguments = dict(kwargs)
            if any(call_arguments.get(name) for name in REMOTE_MACHINE_ARGUMENTS):
                require_current_scopes(("remote:use",))
            arguments = {
                "positional_count": len(args),
                "keyword_args": _serialize_audit_value(call_arguments),
            }
            audit_context = {
                name: call_arguments[name]
                for name in REMOTE_MACHINE_ARGUMENTS
                if call_arguments.get(name)
            }
            if call_arguments.get("session_id"):
                audit_context["session"] = call_arguments["session_id"]
            call_id = uuid.uuid4().hex
            started_at = time.monotonic()
            audit(
                "mcp_tool_call_start",
                call_id=call_id,
                tool=__tool_name,
                arguments=arguments,
                **audit_context,
            )
            try:
                with audit_call_context(call_id) as call_state:
                    if __tool_name in NON_CANCELLABLE_TOOL_NAMES:
                        result = await __original(*args, **kwargs)
                    else:
                        result = await asyncio.wait_for(
                            __original(*args, **kwargs), timeout=PUBLIC_TOOL_TIMEOUT_S
                        )
                serialized_result = _serialize_audit_value(result)
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
                raise

        tool.fn = wrapped


def _remove_remote_tools_when_disabled(mcp: FastMCP) -> None:
    if get_settings().remote_enabled:
        return
    tools = mcp._tool_manager._tools  # noqa: SLF001
    for name in list(tools):
        if name.startswith("remote_") or name == "transfer_path":
            tools.pop(name, None)


MACHINE_CAPABLE_TOOL_NAMES = {
    "environment_info",
    "run_shell_tool",
    "run_python_tool",
    "shell_start",
    "shell_send",
    "shell_read",
    "shell_kill",
    "shell_list",
    "job_start",
    "job_list",
    "job_tail",
    "job_stop",
    "job_retry",
    "list_files",
    "tree_view",
    "glob_search",
    "grep_search",
    "read_file",
    "view_image",
    "write_file",
    "edit_file",
    "delete_file_or_dir",
    "apply_patch",
    "browser_capture_tool",
    "browser_get_text_tool",
    "playwright_run_script_tool",
}

OPEN_WORLD_TOOL_NAMES = {
    *MACHINE_CAPABLE_TOOL_NAMES,
    "create_file_link",
    "revoke_file_link",
    "transfer_path",
}

READ_ONLY_OPEN_WORLD_TOOL_NAMES = {
    "browser_get_text_tool",
}

NON_DESTRUCTIVE_MUTATION_TOOL_NAMES = {
    "create_file_link",
    "remote_invite",
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
            args, cwd=str(base), text=True, capture_output=True, timeout=30, check=False
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
    result = await remote_manager().call(machine, tool, args, timeout_s)
    return _unwrap_remote_transfer_result(result, machine=machine, tool=tool)


async def _copy_local_file_to_remote(
    source_path: str,
    dst_machine: str,
    dst_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
) -> dict:
    stat = await asyncio.to_thread(transfer_stat, source_path, True)
    if stat.get("type") != "file":
        raise ValueError(f"source is not a file: {source_path}")
    effective_chunk_size = (
        stat["size"] if chunk_size is None else normalize_chunk_size(chunk_size)
    )
    ticket = create_download_ticket(
        source_path,
        stat["size"],
        stat["sha256"],
    )
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
) -> dict:
    stat = await _remote_transfer_data(
        src_machine, "transfer_stat", {"path": src_path, "sha256": True}
    )
    if stat.get("type") != "file":
        raise ValueError(f"source is not a file: {src_path}")
    effective_chunk_size = (
        stat["size"] if chunk_size is None else normalize_chunk_size(chunk_size)
    )
    ticket = create_upload_ticket(
        destination_path,
        stat["size"],
        stat["sha256"],
        overwrite,
    )
    try:
        finish = await _remote_transfer_data(
            src_machine,
            "transfer_upload_url",
            {
                "path": src_path,
                "url": ticket["url"],
                "expected_bytes": stat["size"],
                "expected_sha256": stat["sha256"],
                "timeout_s": get_settings().remote_job_timeout_s,
            },
            get_settings().remote_job_timeout_s,
        )
    finally:
        revoke_transfer_ticket(ticket["token"])
    return {
        "source": {"machine": src_machine, "path": stat["path"]},
        "destination": {"machine": "controller", "path": finish["path"]},
        "bytes": stat["size"],
        "sha256": stat.get("sha256"),
        "chunks": 1,
        "chunk_size": effective_chunk_size,
        "transport": "http-stream",
    }


async def _copy_remote_file_to_remote(
    src_machine: str,
    src_path: str,
    dst_machine: str,
    dst_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
) -> dict:
    temporary = await asyncio.to_thread(transfer_alloc_temp_path, ".bin")
    try:
        pull = await _copy_remote_file_to_local(
            src_machine,
            src_path,
            temporary["path"],
            True,
            chunk_size,
        )
        push = await _copy_local_file_to_remote(
            temporary["path"],
            dst_machine,
            dst_path,
            overwrite,
            chunk_size,
        )
    finally:
        with suppress(Exception):
            delete_path(temporary["path"], False)
    return {
        "source": pull["source"],
        "destination": push["destination"],
        "bytes": pull["bytes"],
        "sha256": pull["sha256"],
        "chunks": pull["chunks"] + push["chunks"],
        "chunk_size": pull["chunk_size"],
        "transport": "http-stream-via-controller",
    }


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
            )
        else:
            copy_result = await _copy_local_file_to_remote(
                pack["archive_path"],
                dst_machine,
                dst_archive["path"],
                True,
                chunk_size,
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
    except Exception:
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
) -> dict:
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
    )


async def _copy_remote_dir_to_local(
    src_machine: str,
    src_path: str,
    destination_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
) -> dict:
    pack = await _remote_transfer_data(
        src_machine, "transfer_pack_dir", {"path": src_path, "compression": "gz"}
    )
    archive = await asyncio.to_thread(transfer_alloc_temp_path, ".tar.gz")
    try:
        copy_result = await _copy_remote_file_to_local(
            src_machine, pack["archive_path"], archive["path"], True, chunk_size
        )
        unpack = await asyncio.to_thread(
            transfer_unpack_archive, archive["path"], destination_path, overwrite, True
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
) -> dict:
    pack = await asyncio.to_thread(transfer_pack_dir, source_path, "gz")
    return await _copy_packed_dir_to_remote(
        pack,
        None,
        dst_machine,
        dst_path,
        overwrite,
        chunk_size,
    )


async def _transfer_path(
    source_path: str,
    destination_path: str,
    source_machine: str | None = None,
    destination_machine: str | None = None,
    overwrite: bool = False,
    chunk_size: int | None = None,
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
        result = await operation(
            source_machine,
            source_path,
            destination_machine,
            destination_path,
            overwrite,
            chunk_size,
        )
    elif source_machine:
        operation = (
            _copy_remote_dir_to_local if source_type == "dir" else _copy_remote_file_to_local
        )
        result = await operation(
            source_machine,
            source_path,
            destination_path,
            overwrite,
            chunk_size,
        )
    else:
        assert destination_machine is not None
        operation = (
            _copy_local_dir_to_remote if source_type == "dir" else _copy_local_file_to_remote
        )
        result = await operation(
            source_path,
            destination_machine,
            destination_path,
            overwrite,
            chunk_size,
        )
    return {"type": source_type, **result}


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
    path = settings.audit_log_path
    if not path.exists():
        return {"entries": []}

    line_limit = max(1, min(lines, 1000))
    max_bytes = max(1, settings.max_audit_tail_bytes)
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
        return await remote_manager().call(machine, tool, args, timeout_s)
    except Exception as exc:
        return _handled_error(exc)


def _register_connector_tools(mcp: FastMCP, read_only_tool: ToolAnnotations) -> None:
    read_only_meta = _public_read_meta()

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=read_only_meta)
    async def search(query: str) -> str:
        """Search workspace files and return ChatGPT connector-compatible results."""
        try:
            result = await grep(
                query,
                cwd=".",
                regex=False,
                case_sensitive=False,
                max_results=20,
            )
            seen: set[str] = set()
            rows = []
            for match in result.get("matches", []):
                path = match.get("path")
                if not path or path in seen:
                    continue
                seen.add(path)
                line = match.get("line")
                suffix = f":{line}" if line else ""
                resolved = resolve_path(path, must_exist=True)
                rows.append(
                    {
                        "id": path,
                        "title": f"{path}{suffix}",
                        "url": resolved.as_uri(),
                    }
                )
            return json.dumps({"results": rows}, ensure_ascii=False)
        except Exception as exc:
            audit("tool_error", error=repr(exc))
            return json.dumps({"results": []})

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=read_only_meta)
    async def fetch(id: str) -> str:
        """Fetch a workspace file by id returned from search."""
        try:
            data = await asyncio.to_thread(read_text, id)
            path = data.get("path") or id
            binary = bool(data.get("binary"))
            resolved = resolve_path(id, must_exist=True)
            return json.dumps(
                {
                    "id": path,
                    "title": path,
                    "text": data.get("content")
                    if not binary
                    else data.get("message", "Binary file omitted"),
                    "url": resolved.as_uri(),
                    "metadata": {
                        "source": "workspace",
                        "binary": binary,
                        "bytes": data.get("bytes"),
                        "bytes_read": data.get("bytes_read"),
                        "truncated": bool(data.get("truncated", False)),
                        "truncated_bytes": data.get("truncated_bytes", 0),
                    },
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            audit("tool_error", error=repr(exc))
            return json.dumps(
                {
                    "id": id,
                    "title": id,
                    "text": f"Unable to fetch file: {type(exc).__name__}: {exc}",
                    "url": f"file:///workspace/{id}",
                    "metadata": {
                        "source": "workspace",
                        "error": type(exc).__name__,
                    },
                },
                ensure_ascii=False,
            )


def _register_environment_tools(
    mcp: FastMCP, settings: Any, read_only_tool: ToolAnnotations
) -> None:
    shell_read_meta = _oauth_meta(["shell:read"])

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def environment_info(machine: str | None = None) -> ToolResult:
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
    async def skills_list() -> ToolResult:
        """List installed agent skills without loading their instructions. The MCP tool surface stays fixed; adding or removing skill directories is reflected on the next call."""
        return await _tool_call(asyncio.to_thread, list_installed_skills, settings)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def skill_load(name: str) -> ToolResult:
        """Load one installed agent skill by the exact name returned from skills_list. Returns SKILL.md instructions plus related file paths."""
        return await _tool_call(asyncio.to_thread, load_installed_skill, name, settings)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def skill_read_file(name: str, path: str) -> ToolResult:
        """Read one related text file from an installed Skill."""
        return await _tool_call(asyncio.to_thread, read_installed_skill_file, name, path, settings)


def _register_command_tools(mcp: FastMCP, settings: Any) -> None:
    shell_execute_meta = _oauth_meta(["shell:read", "shell:execute"])

    @mcp.tool(structured_output=True, meta=shell_execute_meta)
    async def run_shell_tool(
        command: str,
        cwd: str = ".",
        timeout_s: int | None = None,
        max_output_bytes: int | None = None,
        purpose: str | None = None,
        explanation: str | None = None,
        machine: str | None = None,
    ) -> ToolResult:
        """Run one non-interactive shell command locally or on a remote machine. Use for build, test, package-manager, Git, and inspection commands that should finish promptly. For long-running, interactive, or streaming processes, use shell_start or job_start. Optional purpose/explanation fields let agents state why the command is being run."""
        _audit_tool_purpose("run_shell_tool", purpose, explanation)
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
    async def run_python_tool(
        code: str,
        cwd: str = ".",
        timeout_s: int = 60,
        purpose: str | None = None,
        explanation: str | None = None,
        machine: str | None = None,
    ) -> ToolResult:
        """Write and run a short Python script locally or on a remote machine."""
        _audit_tool_purpose("run_python_tool", purpose, explanation)
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
    async def shell_kill(
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
        machine: str | None = None,
    ) -> ToolResult:
        """List tracked jobs locally or on a remote machine."""
        if machine:
            return await _remote_call(
                settings,
                machine,
                "job_list",
                {"include_finished": include_finished},
            )
        return await _tool_call(list_jobs, include_finished)

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
    async def list_files(
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
    async def tree_view(
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
    async def glob_search(
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
    async def grep_search(
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
    async def read_file(
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
    async def view_image(
        path: str,
        machine: str | None = None,
    ) -> ViewImageResult:
        """View a PNG, JPEG, GIF, or WebP file as native MCP image content locally or on a remote machine. Use this instead of read_file when visual inspection is needed. Remote images reuse the existing file-transfer protocol, so the worker does not need a new image-specific RPC."""
        return cast(ViewImageResult, await _view_image_result(path, machine))


def _register_download_tools(mcp: FastMCP, read_only_tool: ToolAnnotations) -> None:
    file_share_meta = _oauth_meta(["shell:read", "file:share"])

    @mcp.tool(structured_output=True, meta=file_share_meta)
    async def create_file_link(
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
    async def list_file_links(include_expired: bool = False) -> ToolResult:
        """List generated local file download URLs."""
        return await _tool_call(asyncio.to_thread, list_share_links, include_expired)

    @mcp.tool(structured_output=True, meta=file_share_meta)
    async def revoke_file_link(token: str) -> ToolResult:
        """Revoke a generated local file download URL."""
        return await _tool_call(asyncio.to_thread, revoke_share_link, token)


def _register_workspace_write_tools(mcp: FastMCP, settings: Any) -> None:
    shell_write_meta = _oauth_meta(["shell:read", "shell:write"])
    patch_meta = _oauth_meta(["shell:read", "shell:write"])
    transfer_meta = _oauth_meta(["remote:use", "shell:read", "shell:write"])

    @mcp.tool(structured_output=True, meta=shell_write_meta)
    async def write_file(
        path: str,
        content: str,
        overwrite: bool = True,
        purpose: str | None = None,
        explanation: str | None = None,
        machine: str | None = None,
    ) -> ToolResult:
        """Write a UTF-8 text file locally or on a remote machine."""
        _audit_tool_purpose("write_file", purpose, explanation)
        if machine:
            return await _remote_call(
                settings,
                machine,
                "write_file",
                {"path": path, "content": content, "overwrite": overwrite},
            )
        return await _tool_call(asyncio.to_thread, write_text, path, content, overwrite)

    @mcp.tool(structured_output=True, meta=shell_write_meta)
    async def edit_file(
        path: str,
        edits: list[TextEdit],
        purpose: str | None = None,
        explanation: str | None = None,
        machine: str | None = None,
    ) -> ToolResult:
        """Apply one or more exact-text edits to one local or remote file. Each edits entry contains old, new, and optional replace_all; old must match exactly, including whitespace and indentation."""
        _audit_tool_purpose("edit_file", purpose, explanation)
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
    async def delete_file_or_dir(
        path: str,
        recursive: bool = False,
        purpose: str | None = None,
        explanation: str | None = None,
        machine: str | None = None,
    ) -> ToolResult:
        """Delete a local or remote file or directory. recursive=false deletes files or empty directories; recursive=true is required for non-empty directories and should be used carefully."""
        _audit_tool_purpose("delete_file_or_dir", purpose, explanation)
        if machine:
            return await _remote_call(
                settings,
                machine,
                "delete_file_or_dir",
                {"path": path, "recursive": recursive},
            )
        return await _tool_call(asyncio.to_thread, delete_path, path, recursive)

    @mcp.tool(structured_output=True, meta=patch_meta)
    async def apply_patch(
        patch: str,
        cwd: str = ".",
        purpose: str | None = None,
        explanation: str | None = None,
        machine: str | None = None,
    ) -> ToolResult:
        """Check and apply a unified diff locally or on a remote machine."""
        _audit_tool_purpose("apply_patch", purpose, explanation)
        if machine:
            return await _remote_call(
                settings,
                machine,
                "apply_patch",
                {"patch": patch, "cwd": cwd},
            )
        return await _tool_call(_apply_patch_text, patch, cwd)

    @mcp.tool(structured_output=True, meta=transfer_meta)
    async def transfer_path(
        source_path: str,
        destination_path: str,
        source_machine: str | None = None,
        destination_machine: str | None = None,
        overwrite: bool = False,
        chunk_size: int | None = None,
        purpose: str | None = None,
        explanation: str | None = None,
    ) -> ToolResult:
        """Copy a file or directory between the controller and remote machines using raw HTTP streaming. A missing machine denotes the controller; at least one endpoint must be remote. chunk_size is retained for API compatibility and does not change the transport."""
        _audit_tool_purpose("transfer_path", purpose, explanation)
        return await _tool_call(
            _transfer_path,
            source_path,
            destination_path,
            source_machine,
            destination_machine,
            overwrite,
            chunk_size,
        )


def _register_maintenance_tools(mcp: FastMCP, read_only_tool: ToolAnnotations) -> None:
    shell_read_meta = _oauth_meta(["shell:read"])
    shell_write_meta = _oauth_meta(["shell:read", "shell:write"])

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def secret_scan(
        cwd: str = ".",
        glob: str | None = None,
        max_results: int = 200,
    ) -> ToolResult:
        """Scan local workspace text files for common secrets before commit or push."""
        return await _tool_call(_secret_scan, cwd, glob, max_results)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def todo_read_tool() -> ToolResult:
        """Read the local agent todo list."""
        return await _tool_call(asyncio.to_thread, todo_read)

    @mcp.tool(structured_output=True, meta=shell_write_meta)
    async def todo_write_tool(todos: list[dict]) -> ToolResult:
        """Write the local agent todo list."""
        return await _tool_call(asyncio.to_thread, todo_write, todos)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def audit_tail(lines: int = 100) -> ToolResult:
        """Read recent local audit log entries."""
        return await _tool_call(asyncio.to_thread, _read_audit_tail_entries, lines)


def _register_browser_tools(mcp: FastMCP, settings: Any, read_only_tool: ToolAnnotations) -> None:
    browser_meta = _oauth_meta(["browser:use"])
    browser_write_meta = _oauth_meta(["browser:use", "shell:write"])
    browser_execute_meta = _oauth_meta(["browser:use", "shell:execute"])

    @mcp.tool(structured_output=True, meta=browser_write_meta)
    async def browser_capture_tool(
        url: str,
        output_path: str | None = None,
        capture_format: str = "png",
        browser: str = "chromium",
        full_page: bool = True,
        width: int = 1440,
        height: int = 1000,
        wait_until: str = "networkidle",
        machine: str | None = None,
    ) -> ToolResult:
        """Open a URL and save a PNG screenshot or PDF locally or on a remote machine."""
        args = {
            "url": url,
            "output_path": output_path,
            "capture_format": capture_format,
            "browser": browser,
            "full_page": full_page,
            "width": width,
            "height": height,
            "wait_until": wait_until,
        }
        if machine:
            return await _remote_call(settings, machine, "browser_capture_tool", args)
        return await _tool_call(browser_capture, **args)

    @mcp.tool(structured_output=True, meta=browser_meta)
    async def browser_get_text_tool(
        url: str,
        browser: str = "chromium",
        wait_until: str = "networkidle",
        selector: str = "body",
        machine: str | None = None,
    ) -> ToolResult:
        """Open a URL and return visible text locally or on a remote machine."""
        args = {
            "url": url,
            "browser": browser,
            "wait_until": wait_until,
            "selector": selector,
        }
        if machine:
            return await _remote_call(settings, machine, "browser_get_text_tool", args)
        return await _tool_call(browser_get_text, **args)

    @mcp.tool(structured_output=True, meta=browser_execute_meta)
    async def playwright_run_script_tool(
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
                "playwright_run_script_tool",
                {"script": script, "cwd": cwd, "timeout_s": timeout_s},
                timeout_s,
            )
        return await _tool_call(playwright_run_script, script, cwd, timeout_s)


def _register_remote_admin_tools(mcp: FastMCP, read_only_tool: ToolAnnotations) -> None:
    remote_meta = _oauth_meta(["remote:use"])

    @mcp.tool(structured_output=True, meta=remote_meta)
    async def remote_invite(
        name: str | None = None,
        workdir: str | None = None,
        ttl_s: int | None = None,
    ) -> ToolResult:
        """Create a one-time command for a remote machine to join this server."""
        return await _tool_call(lambda: remote_manager().create_invite(name, workdir, ttl_s))

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=remote_meta)
    async def remote_list_machines() -> ToolResult:
        """List registered remote worker machines."""
        return await _tool_call(lambda: remote_manager().list_machines())

    @mcp.tool(structured_output=True, meta=remote_meta)
    async def remote_revoke_machine(machine: str) -> ToolResult:
        """Revoke and remove a remote worker machine."""
        return await _tool_call(lambda: remote_manager().revoke(machine))

    @mcp.tool(structured_output=True, meta=remote_meta)
    async def remote_rename_machine(machine: str, new_name: str) -> ToolResult:
        """Rename a remote worker machine."""
        return await _tool_call(lambda: remote_manager().rename(machine, new_name))


def build_mcp() -> FastMCP:
    settings = get_settings()
    mcp = FastMCP(
        "local-shell-mcp",
        instructions=MCP_INSTRUCTIONS,
        transport_security=_transport_security_settings(),
    )
    read_only_tool = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    _register_connector_tools(mcp, read_only_tool)
    _register_environment_tools(mcp, settings, read_only_tool)
    _register_command_tools(mcp, settings)
    _register_shell_tools(mcp, settings, read_only_tool)
    _register_job_tools(mcp, settings, read_only_tool)
    _register_workspace_read_tools(mcp, settings, read_only_tool)
    _register_download_tools(mcp, read_only_tool)
    _register_workspace_write_tools(mcp, settings)
    _register_maintenance_tools(mcp, read_only_tool)
    _register_browser_tools(mcp, settings, read_only_tool)
    _register_remote_admin_tools(mcp, read_only_tool)

    _remove_remote_tools_when_disabled(mcp)
    _install_tool_annotations(mcp)
    _install_mcp_tool_watchdogs(mcp)
    return mcp
