from __future__ import annotations

import asyncio
import json
import shlex
import subprocess
import uuid
from contextlib import suppress
from typing import Any
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from .audit import audit
from .auth import require_current_scopes
from .fs_ops import (
    delete_path,
    edit_text,
    glob_paths,
    list_dir,
    missing_path_context,
    multi_edit_text,
    prune_temp_dir,
    read_text,
    relative_display,
    resolve_path,
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
from .jobs import list_jobs, retry_job, start_job, stop_job, tail_job
from .models import ToolResult
from .playwright_ops import (
    browser_eval,
    browser_get_text,
    browser_pdf,
    browser_screenshot,
    playwright_install,
    playwright_run_script,
)
from .remote import remote_manager
from .remote_transfer import (
    create_download_ticket,
    create_upload_ticket,
    revoke_transfer_ticket,
)
from .search_ops import grep, tree
from .settings import get_settings, safe_settings_dump
from .shell_ops import (
    PUBLIC_TOOL_WATCHDOG_TIMEOUT_S,
    kill_shell,
    list_shells,
    public_run_shell,
    public_run_shell_timeout,
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
    transfer_alloc_temp_path,
    transfer_pack_dir,
    transfer_stat,
    transfer_unpack_archive,
)
from .version import version_info as get_version_info


def _ok(data: Any = None, message: str = "") -> dict:
    return {"ok": True, "message": message, "data": data}


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


async def _to_thread(func, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
    return await asyncio.to_thread(func, *args, **kwargs)


def _assert_text_input_size(label: str, text: str, limit: int | None = None) -> None:
    settings = get_settings()
    max_bytes = limit or settings.max_file_write_bytes
    size = len(text.encode("utf-8"))
    if size > max_bytes:
        raise ValueError(f"Refusing {label} of {size} bytes; max is {max_bytes}")


async def _apply_patch_text(patch: str, cwd: str = ".") -> dict:
    _assert_text_input_size("patch", patch)
    await _to_thread(prune_temp_dir)
    patch_path = temp_dir() / f"patch-{uuid.uuid4().hex}.diff"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    await _to_thread(patch_path.write_text, patch, encoding="utf-8")
    quoted = shlex.quote(str(patch_path))
    result = await run_shell(f"git apply --check {quoted} && git apply {quoted}", cwd=cwd, timeout_s=60, max_output_bytes=500_000)
    return {**result.model_dump(), "patch_path": relative_display(patch_path)}


async def _run_python(code: str, cwd: str = ".", timeout_s: int = 60) -> dict:
    _assert_text_input_size("Python script", code)
    await _to_thread(prune_temp_dir)
    path = temp_dir() / f"script-{uuid.uuid4().hex}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    await _to_thread(path.write_text, code, encoding="utf-8")
    result = await run_shell(f"python3 {shlex.quote(str(path))}", cwd=cwd, timeout_s=public_run_shell_timeout(timeout_s), max_output_bytes=1_000_000)
    return {**result.model_dump(), "script_path": relative_display(path)}


SECRET_PATTERNS = {
    "github_token": r"gh[pousr]_[A-Za-z0-9_]{36,}",
    "aws_access_key": r"AKIA[0-9A-Z]{16}",
    "private_key": r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----",
    "generic_assignment": r"(?i)(token|secret|password|passwd|api_key|apikey)\s*[:=]\s*['\"][^'\"]{8,}['\"]",
}

ALL_OAUTH_SCOPES = ["shell:read", "shell:write", "shell:execute", "git:write", "browser:use", "file:share", "remote:use"]


def _oauth_security_scheme(scopes: list[str]) -> dict[str, Any]:
    return {"type": "oauth2", "scopes": list(dict.fromkeys(scopes))}


OAUTH_SECURITY_SCHEMES = [_oauth_security_scheme(ALL_OAUTH_SCOPES)]
NOAUTH_SECURITY_SCHEMES = [{"type": "noauth"}]
PUBLIC_TOOL_TIMEOUT_S = PUBLIC_TOOL_WATCHDOG_TIMEOUT_S
SENSITIVE_TOOL_ARG_FRAGMENTS = ("token", "secret", "password", "passwd", "pin", "jwt", "key")
OPAQUE_AUDIT_TOOL_ARGS = {
    "code",
    "command",
    "content",
    "data_b64",
    "explanation",
    "input_text",
    "javascript",
    "patch",
    "purpose",
    "repo_url",
    "script",
}
MAX_AUDIT_TOOL_ARG_STRING = 500
MCP_INSTRUCTIONS = (
    "When a task may benefit from an installed Agent Skill, call skills_list first "
    "to discover the exact Skill name and description. Before following a Skill's "
    "workflow, call skill_load with that exact name. Call skill_read_file only when "
    "a related file returned by skill_load is needed. Skills use this fixed tool "
    "surface; do not expect per-Skill MCP tools."
)


class PublicToolTimeoutError(TimeoutError):
    pass


def _security_meta(schemes: list[dict[str, Any]]) -> dict[str, Any]:
    return {"securitySchemes": schemes}


def _oauth_meta(scopes: list[str]) -> dict[str, Any]:
    return _security_meta([_oauth_security_scheme(scopes)])


def _public_read_meta() -> dict[str, Any]:
    return _security_meta([*NOAUTH_SECURITY_SCHEMES, _oauth_security_scheme(["shell:read"])])


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


def _redact_audit_value(value: Any) -> Any:
    if isinstance(value, str):
        if len(value) > MAX_AUDIT_TOOL_ARG_STRING:
            return value[:MAX_AUDIT_TOOL_ARG_STRING] + "…<truncated>"
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_redact_audit_value(item) for item in value[:20]]
    if isinstance(value, tuple):
        return [_redact_audit_value(item) for item in value[:20]]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for name, item in list(value.items())[:50]:
            name_s = str(name)
            name_lower = name_s.lower()
            if (
                name_lower in OPAQUE_AUDIT_TOOL_ARGS
                or any(fragment in name_lower for fragment in SENSITIVE_TOOL_ARG_FRAGMENTS)
            ):
                out[name_s] = "<redacted>"
            else:
                out[name_s] = _redact_audit_value(item)
        return out
    return repr(value)


def _audit_tool_arguments(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    return {
        "positional_count": len(args),
        "keyword_args": _redact_audit_value(kwargs),
    }


def _audit_tool_purpose(tool_name: str, purpose: str | None = None, explanation: str | None = None) -> dict[str, str]:
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

        async def wrapped(  # noqa: ANN202
            *args,
            __original=original,
            __tool_name=tool_name,
            __required_scopes=tool_required_scopes,
            **kwargs,
        ):
            require_current_scopes(__required_scopes)
            arguments = _audit_tool_arguments(args, kwargs)
            audit_context = {}
            keyword_args = (
                arguments.get("keyword_args", {})
                if isinstance(arguments, dict)
                else {}
            )
            if isinstance(keyword_args, dict):
                if keyword_args.get("machine"):
                    audit_context["machine"] = keyword_args["machine"]
                if keyword_args.get("session_id"):
                    audit_context["session"] = keyword_args["session_id"]
            audit(
                "mcp_tool_call_start",
                tool=__tool_name,
                arguments=arguments,
                **audit_context,
            )
            try:
                result = await asyncio.wait_for(
                    __original(*args, **kwargs), timeout=PUBLIC_TOOL_TIMEOUT_S
                )
                audit("mcp_tool_call_end", tool=__tool_name, ok=True, **audit_context)
                return result
            except TimeoutError:
                exc = PublicToolTimeoutError(
                    f"{__tool_name} exceeded {PUBLIC_TOOL_TIMEOUT_S} second public tool timeout"
                )
                audit("tool_timeout", tool=__tool_name, timeout_s=PUBLIC_TOOL_TIMEOUT_S)
                audit(
                    "mcp_tool_call_end",
                    tool=__tool_name,
                    ok=False,
                    error=type(exc).__name__,
                    **audit_context,
                )
                return _timeout_payload_for_tool(__tool_name, exc)
            except Exception as exc:
                audit(
                    "mcp_tool_call_end",
                    tool=__tool_name,
                    ok=False,
                    error=type(exc).__name__,
                    **audit_context,
                )
                raise

        tool.fn = wrapped



def _remove_remote_tools_when_disabled(mcp: FastMCP) -> None:
    if get_settings().remote_enabled:
        return
    tools = mcp._tool_manager._tools  # noqa: SLF001
    for name in list(tools):
        if name.startswith("remote_"):
            tools.pop(name, None)


OPEN_WORLD_TOOL_NAMES = {
    "browser_eval_tool",
    "browser_get_text_tool",
    "browser_pdf_tool",
    "browser_screenshot_tool",
    "create_file_link",
    "git_clone_tool",
    "git_fetch_tool",
    "git_pull_tool",
    "git_push_tool",
    "playwright_install_tool",
    "playwright_run_script_tool",
    "revoke_file_link",
    "run_python_tool",
    "run_shell_tool",
    "shell_send",
    "shell_start",
    "job_start",
    "job_retry",
}

READ_ONLY_OPEN_WORLD_TOOL_NAMES = {
    "browser_get_text_tool",
    "remote_browser_get_text_tool",
}

NON_DESTRUCTIVE_MUTATION_TOOL_NAMES = {
    "create_file_link",
    "git_clone_tool",
    "git_commit_tool",
    "remote_invite",
}


def _install_tool_annotations(mcp: FastMCP) -> None:
    """Attach conservative, semantically accurate MCP safety annotations."""

    for name, tool in mcp._tool_manager._tools.items():  # noqa: SLF001
        existing_read_only = bool(
            tool.annotations and tool.annotations.readOnlyHint
        )
        read_only = existing_read_only or name in READ_ONLY_OPEN_WORLD_TOOL_NAMES
        open_world = name.startswith("remote_") or name in OPEN_WORLD_TOOL_NAMES
        tool.annotations = ToolAnnotations(
            readOnlyHint=read_only,
            destructiveHint=not (
                read_only or name in NON_DESTRUCTIVE_MUTATION_TOOL_NAMES
            ),
            idempotentHint=read_only,
            openWorldHint=open_world,
        )


def _read_many_files_sync(
    paths: list[str],
    start_line: int | None = None,
    end_line: int | None = None,
    binary_preview: str | None = None,
    binary_preview_bytes: int = 256,
) -> dict:
    settings = get_settings()
    if len(paths) > settings.max_read_many_files:
        raise ValueError(f"Refusing to read {len(paths)} files; max is {settings.max_read_many_files}")

    files = []
    total_content_bytes = 0
    for path in paths:
        item = read_text(path, start_line, end_line, binary_preview, binary_preview_bytes)
        content = item.get("content")
        if isinstance(content, str):
            total_content_bytes += len(content.encode("utf-8"))
        preview = item.get("preview")
        if isinstance(preview, str):
            total_content_bytes += len(preview.encode("utf-8"))
        if total_content_bytes > settings.max_read_many_total_bytes:
            raise ValueError(
                f"Refusing to return {total_content_bytes} bytes from read_many_files; "
                f"max is {settings.max_read_many_total_bytes}"
            )
        files.append(item)
    return {"files": files, "total_content_bytes": total_content_bytes}


def _secret_scan_candidates(base: Any, glob: str | None = None) -> list[Any]:
    settings = get_settings()
    args = [settings.rg_bin, "--files", "--hidden", "--glob", "!.git/**"]
    ignore_file = base / ".gitignore"
    if ignore_file.is_file():
        args.extend(["--ignore-file", str(ignore_file)])
    if glob:
        args.extend(["--glob", glob])
    try:
        result = subprocess.run(args, cwd=str(base), text=True, capture_output=True, timeout=30, check=False)
    except Exception:
        result = None
    if result is not None and result.returncode in {0, 1}:
        return [base / line for line in result.stdout.splitlines() if line.strip()]

    candidates = []
    for path in base.rglob("*"):
        if ".git" in path.parts or not path.is_file():
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
                    return {"findings": findings, "truncated": True, "truncated_files": truncated_files}
    return {"findings": findings, "truncated": False, "truncated_files": truncated_files}


async def _secret_scan(cwd: str = ".", glob: str | None = None, max_results: int = 200) -> dict:
    return await _to_thread(_secret_scan_sync, cwd, glob, max_results)


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


async def _remote_transfer_data(machine: str, tool: str, args: dict, timeout_s: int | None = None) -> Any:
    result = await remote_manager().call(machine, tool, args, timeout_s)
    return _unwrap_remote_transfer_result(result, machine=machine, tool=tool)


async def _copy_local_file_to_remote(
    source_path: str,
    dst_machine: str,
    dst_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
) -> dict:
    del chunk_size
    stat = await _to_thread(transfer_stat, source_path, True)
    if stat.get("type") != "file":
        raise ValueError(f"source is not a file: {source_path}")
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
        "chunk_size": stat["size"],
        "transport": "http-stream",
    }


async def _copy_remote_file_to_local(
    src_machine: str,
    src_path: str,
    destination_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
) -> dict:
    del chunk_size
    stat = await _remote_transfer_data(
        src_machine, "transfer_stat", {"path": src_path, "sha256": True}
    )
    if stat.get("type") != "file":
        raise ValueError(f"source is not a file: {src_path}")
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
        "chunk_size": stat["size"],
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
    temporary = await _to_thread(transfer_alloc_temp_path, ".bin")
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
        await _remote_transfer_data(machine, "delete_file_or_dir", {"path": path, "recursive": False})


async def _copy_remote_dir_to_remote(
    src_machine: str,
    src_path: str,
    dst_machine: str,
    dst_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
) -> dict:
    pack = await _remote_transfer_data(src_machine, "transfer_pack_dir", {"path": src_path, "compression": "gz"})
    dst_archive = await _remote_transfer_data(dst_machine, "transfer_alloc_temp_path", {"suffix": ".tar.gz"})
    try:
        copy_result = await _copy_remote_file_to_remote(
            src_machine, pack["archive_path"], dst_machine, dst_archive["path"], True, chunk_size
        )
        unpack = await _remote_transfer_data(
            dst_machine,
            "transfer_unpack_archive",
            {"archive_path": dst_archive["path"], "dst_path": dst_path, "overwrite": overwrite, "cleanup_archive": True},
        )
    except Exception:
        await _remote_cleanup_file(dst_machine, dst_archive.get("path", ""))
        raise
    finally:
        await _remote_cleanup_file(src_machine, pack.get("archive_path", ""))
    return {
        "source": {"machine": src_machine, "path": pack["path"]},
        "destination": {"machine": dst_machine, "path": unpack["path"]},
        "archive_bytes": pack["bytes"],
        "archive_sha256": pack["sha256"],
        "chunks": copy_result["chunks"],
        "entries": unpack["entries"],
    }


async def _copy_remote_dir_to_local(
    src_machine: str,
    src_path: str,
    destination_path: str,
    overwrite: bool = True,
    chunk_size: int | None = None,
) -> dict:
    pack = await _remote_transfer_data(src_machine, "transfer_pack_dir", {"path": src_path, "compression": "gz"})
    archive = await _to_thread(transfer_alloc_temp_path, ".tar.gz")
    try:
        copy_result = await _copy_remote_file_to_local(
            src_machine, pack["archive_path"], archive["path"], True, chunk_size
        )
        unpack = await _to_thread(transfer_unpack_archive, archive["path"], destination_path, overwrite, True)
    finally:
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
    pack = await _to_thread(transfer_pack_dir, source_path, "gz")
    dst_archive = await _remote_transfer_data(dst_machine, "transfer_alloc_temp_path", {"suffix": ".tar.gz"})
    try:
        copy_result = await _copy_local_file_to_remote(pack["archive_path"], dst_machine, dst_archive["path"], True, chunk_size)
        unpack = await _remote_transfer_data(
            dst_machine,
            "transfer_unpack_archive",
            {"archive_path": dst_archive["path"], "dst_path": dst_path, "overwrite": overwrite, "cleanup_archive": True},
        )
    except Exception:
        await _remote_cleanup_file(dst_machine, dst_archive.get("path", ""))
        raise
    finally:
        with suppress(Exception):
            delete_path(pack.get("archive_path", ""), False)
    return {
        "source": {"machine": "controller", "path": pack["path"]},
        "destination": {"machine": dst_machine, "path": unpack["path"]},
        "archive_bytes": pack["bytes"],
        "archive_sha256": pack["sha256"],
        "chunks": copy_result["chunks"],
        "entries": unpack["entries"],
    }


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

    content = b"".join(reversed(chunks)).decode("utf-8", errors="replace").splitlines()[-line_limit:]
    entries = []
    for line in content:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            entries.append({"raw": line})
    return {"entries": entries, "bytes_read": bytes_read, "truncated_bytes": max(0, path.stat().st_size - bytes_read)}


def build_mcp() -> FastMCP:
    settings = get_settings()
    mcp = FastMCP(
        "local-shell-mcp",
        instructions=MCP_INSTRUCTIONS,
        transport_security=_transport_security_settings(),
    )
    read_only_tool = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    read_only_meta = _public_read_meta()
    shell_read_meta = _oauth_meta(["shell:read"])
    shell_write_meta = _oauth_meta(["shell:read", "shell:write"])
    shell_execute_meta = _oauth_meta(["shell:read", "shell:execute"])
    git_read_meta = shell_read_meta
    git_write_meta = _oauth_meta(["shell:read", "git:write"])
    patch_meta = _oauth_meta(["shell:read", "shell:write", "git:write"])
    browser_meta = _oauth_meta(["browser:use"])
    browser_write_meta = _oauth_meta(["browser:use", "shell:write"])
    browser_execute_meta = _oauth_meta(["browser:use", "shell:execute"])
    file_share_meta = _oauth_meta(["shell:read", "file:share"])
    remote_meta = _oauth_meta(["remote:use"])
    remote_read_meta = _oauth_meta(["remote:use", "shell:read"])
    remote_write_meta = _oauth_meta(["remote:use", "shell:read", "shell:write"])
    remote_execute_meta = _oauth_meta(["remote:use", "shell:read", "shell:execute"])
    remote_git_read_meta = remote_read_meta
    remote_git_write_meta = _oauth_meta(["remote:use", "shell:read", "git:write"])
    remote_patch_meta = _oauth_meta(["remote:use", "shell:read", "shell:write", "git:write"])
    remote_browser_meta = _oauth_meta(["remote:use", "browser:use"])
    remote_browser_write_meta = _oauth_meta(["remote:use", "browser:use", "shell:write"])
    remote_browser_execute_meta = _oauth_meta(["remote:use", "browser:use", "shell:execute"])

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=read_only_meta)
    async def search(query: str) -> str:
        """Search workspace files and return ChatGPT connector-compatible results."""
        try:
            result = await grep(query, cwd=".", regex=False, case_sensitive=False, max_results=20)
            seen: set[str] = set()
            rows = []
            for match in result.get("matches", []):
                path = match.get("path")
                if not path or path in seen:
                    continue
                seen.add(path)
                line = match.get("line")
                suffix = f":{line}" if line else ""
                rows.append(
                    {
                        "id": path,
                        "title": f"{path}{suffix}",
                        "url": f"file:///workspace/{path}",
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
            data = await _to_thread(read_text, id)
            path = data.get("path") or id
            binary = bool(data.get("binary"))
            return json.dumps(
                {
                    "id": path,
                    "title": path,
                    "text": data.get("content") if not binary else data.get("message", "Binary file omitted"),
                    "url": f"file:///workspace/{path}",
                    "metadata": {
                        "source": "workspace",
                        "binary": binary,
                        "bytes": data.get("bytes"),
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
                    "metadata": {"source": "workspace", "error": type(exc).__name__},
                },
                ensure_ascii=False,
            )

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def environment_info() -> ToolResult:
        """Return workspace, auth, policy, and basic environment information."""
        try:
            result = await run_shell("uname -a; echo '---'; id; echo '---'; pwd; echo '---'; python3 --version; git --version", cwd=".", timeout_s=10)
            return _ok({"settings": safe_settings_dump(settings), "persistent_shell": persistent_shell_backend_info(), "probe": result.model_dump()})
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def version_info() -> ToolResult:
        """Return the local-shell-mcp version, installed package version, Python version, platform, and executable path."""
        try:
            return _ok(get_version_info())
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def skills_list() -> ToolResult:
        """List installed agent skills from the server-side skills directory without loading their instructions. The MCP tool surface stays fixed; adding or removing skill directories is reflected on the next call."""
        try:
            return _ok(await _to_thread(list_installed_skills, settings))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def skill_load(name: str) -> ToolResult:
        """Load one installed agent skill by the exact name returned from skills_list. Returns SKILL.md instructions plus related file paths; read related files separately only when needed."""
        try:
            return _ok(await _to_thread(load_installed_skill, name, settings))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def skill_read_file(name: str, path: str) -> ToolResult:
        """Read one related text file from an installed Skill. Use the exact Skill name and relative path returned by skill_load; paths are constrained to that Skill directory."""
        try:
            return _ok(
                await _to_thread(read_installed_skill_file, name, path, settings)
            )
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=shell_execute_meta)
    async def run_shell_tool(command: str, cwd: str = ".", timeout_s: int | None = None, max_output_bytes: int | None = None, purpose: str | None = None, explanation: str | None = None) -> ToolResult:
        """Run one non-interactive shell command in the controlled workspace/container. Use for build, test, package-manager, git, and inspection commands that should finish promptly. Parameters: command is the shell command string; cwd defaults to '.' and is resolved relative to the workspace unless full-container mode allows absolute paths. timeout_s defaults to 10 seconds and may be set to at most 120 seconds. For long-running, interactive, or streaming processes, use shell_start with shell_send and shell_read. Optional purpose/explanation fields let agents state why the command is being run."""
        try:
            _audit_tool_purpose("run_shell_tool", purpose, explanation)
            return _ok((await public_run_shell(command, cwd, timeout_s, max_output_bytes)).model_dump())
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=shell_execute_meta)
    async def run_python_tool(code: str, cwd: str = ".", timeout_s: int = 60, purpose: str | None = None, explanation: str | None = None) -> ToolResult:
        """Write Python code to a temporary file and execute it in the controlled workspace/container. Use for short scripts, structured file analysis, JSON manipulation, or calculations that are easier and safer in Python than shell. Keep code non-interactive and write durable outputs explicitly if needed. Optional purpose/explanation fields let agents state why the script is being run."""
        try:
            _audit_tool_purpose("run_python_tool", purpose, explanation)
            return _ok(await _run_python(code, cwd, timeout_s))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=shell_execute_meta)
    async def shell_start(cwd: str = ".", name: str | None = None, command: str | None = None, purpose: str | None = None, explanation: str | None = None) -> ToolResult:
        """Start a persistent shell session using system or bundled tmux on Unix-like platforms, with native process fallback when tmux is unavailable; Windows uses ConPTY when available and otherwise the native fallback. Use for interactive programs, development servers, REPLs, long-running watches, or commands whose output must be read incrementally. For one-shot commands, use run_shell_tool. Optional purpose/explanation fields let agents state why the session is being started."""
        try:
            _audit_tool_purpose("shell_start", purpose, explanation)
            return _ok(await start_shell(cwd, name, command))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=shell_execute_meta)
    async def shell_send(session_id: str, input_text: str, enter: bool = True) -> ToolResult:
        """Send input to an existing persistent shell session. Use after shell_start when a process is waiting for commands or interactive input. Set enter=false only when intentionally sending partial input without a newline."""
        try:
            return _ok(await send_shell(session_id, input_text, enter))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def shell_read(session_id: str, lines: int = 200) -> ToolResult:
        """Read recent output from a persistent shell session. Use after shell_start or shell_send to inspect incremental output without blocking. Increase lines only when needed for context."""
        try:
            return _ok(await read_shell(session_id, lines))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=shell_execute_meta)
    async def shell_kill(session_id: str) -> ToolResult:
        """Terminate a persistent shell session by session_id. Use when a server, watch process, REPL, or stuck command is no longer needed. This is destructive for that session but does not delete files."""
        try:
            return _ok(await kill_shell(session_id))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def shell_list() -> ToolResult:
        """List active persistent shell sessions. Use before reading, sending to, or killing sessions when you do not know the session_id or need to check what long-running processes are active."""
        try:
            return _ok(await list_shells())
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=shell_execute_meta)
    async def job_start(command: str, cwd: str = ".", name: str | None = None, purpose: str | None = None, explanation: str | None = None) -> ToolResult:
        """Start a named long-running job backed by a persistent shell session. Use for builds, servers, watches, experiments, or other commands that should be listed, tailed, stopped, or retried later. Optional purpose/explanation fields let agents state why the job is being started."""
        try:
            _audit_tool_purpose("job_start", purpose, explanation)
            return _ok(await start_job(command, cwd, name))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def job_list(include_finished: bool = True) -> ToolResult:
        """List tracked long-running jobs with running/exited/stopped status counts."""
        try:
            return _ok(await list_jobs(include_finished))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def job_tail(job_id: str, lines: int = 200) -> ToolResult:
        """Read recent output for a tracked long-running job."""
        try:
            return _ok(await tail_job(job_id, lines))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=shell_execute_meta)
    async def job_stop(job_id: str) -> ToolResult:
        """Stop a tracked long-running job and its backing persistent shell session."""
        try:
            return _ok(await stop_job(job_id))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=shell_execute_meta)
    async def job_retry(job_id: str, purpose: str | None = None, explanation: str | None = None) -> ToolResult:
        """Restart a stopped or exited tracked job using the original command and working directory. Optional purpose/explanation fields let agents state why the retry is needed."""
        try:
            _audit_tool_purpose("job_retry", purpose, explanation)
            return _ok(await retry_job(job_id))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def list_files(path: str = ".", recursive: bool = False, max_entries: int = 500) -> ToolResult:
        """List files and directories under a path. Use for quick directory inspection when a compact listing is enough. path defaults to '.' and is workspace-relative unless full-container mode allows absolute paths; recursive walks descendants and max_entries is capped by server settings."""
        try:
            return _ok(await _to_thread(list_dir, path, recursive, max_entries))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def tree_view(cwd: str = ".", depth: int = 3, max_entries: int = 500) -> ToolResult:
        """Return a compact directory tree."""
        try:
            return _ok(await tree(cwd, depth, max_entries))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def glob_search(pattern: str, cwd: str = ".", max_results: int = 500) -> ToolResult:
        """Find files by glob pattern."""
        try:
            return _ok({"paths": await _to_thread(glob_paths, pattern, cwd, max_results)})
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def grep_search(query: str, cwd: str = ".", glob: str | None = None, regex: bool = True, case_sensitive: bool = True, max_results: int | None = None) -> ToolResult:
        """Search file contents using ripgrep."""
        try:
            return _ok(await grep(query, cwd, glob, regex, case_sensitive, max_results))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def read_file(
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        binary_preview: str | None = None,
        binary_preview_bytes: int = 256,
    ) -> ToolResult:
        """Read a UTF-8 text file, optionally by line range. Use after locating a file to inspect exact content before editing. start_line and end_line are 1-based inclusive line numbers for paging large files; binary_preview can request a bounded hex or base64 preview."""
        try:
            return _ok(await _to_thread(read_text, path, start_line, end_line, binary_preview, binary_preview_bytes))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def read_many_files(
        paths: list[str],
        start_line: int | None = None,
        end_line: int | None = None,
        binary_preview: str | None = None,
        binary_preview_bytes: int = 256,
    ) -> ToolResult:
        """Read multiple UTF-8 text files with the same optional line range. Use when comparing related small files or collecting context across a targeted path list; server settings cap file count and total bytes."""
        try:
            return _ok(
                await _to_thread(
                    _read_many_files_sync,
                    paths,
                    start_line,
                    end_line,
                    binary_preview,
                    binary_preview_bytes,
                )
            )
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=file_share_meta)
    async def create_file_link(path: str, ttl_s: int | None = None, filename: str | None = None, max_downloads: int | None = None) -> ToolResult:
        """Create a temporary browser-accessible download URL for a regular workspace file. Generated links are public bearer URLs protected by a high-entropy token, TTL, optional download-count limit, optional size limit, and explicit revocation."""
        try:
            mod = __import__("local_shell_mcp.downloads", fromlist=["create_share_link"])
            return _ok(await _to_thread(mod.create_share_link, path, ttl_s, filename, max_downloads))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=file_share_meta)
    async def list_file_links(include_expired: bool = False) -> ToolResult:
        """List generated file download URLs."""
        try:
            mod = __import__("local_shell_mcp.downloads", fromlist=["list_share_links"])
            return _ok(await _to_thread(mod.list_share_links, include_expired))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=file_share_meta)
    async def revoke_file_link(token: str) -> ToolResult:
        """Revoke a generated file download URL."""
        try:
            mod = __import__("local_shell_mcp.downloads", fromlist=["revoke_share_link"])
            return _ok(await _to_thread(mod.revoke_share_link, token))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=shell_write_meta)
    async def write_file(path: str, content: str, overwrite: bool = True, purpose: str | None = None, explanation: str | None = None) -> ToolResult:
        """Write a UTF-8 text file. Use to create a new file or intentionally replace a whole file. overwrite defaults to true; set overwrite=false when creating only if absent. For precise modifications to existing files, use edit_file or apply_patch. Optional purpose/explanation fields let agents state why the file write is needed."""
        try:
            _audit_tool_purpose("write_file", purpose, explanation)
            return _ok(await _to_thread(write_text, path, content, overwrite))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=shell_write_meta)
    async def edit_file(path: str, old: str, new: str, replace_all: bool = False, purpose: str | None = None, explanation: str | None = None) -> ToolResult:
        """Replace exact text in a file. Use for small precise edits after reading the target file. old must match exactly, including whitespace and indentation; replace_all should be true only when every exact occurrence should change. Optional purpose/explanation fields let agents state why the edit is needed."""
        try:
            _audit_tool_purpose("edit_file", purpose, explanation)
            return _ok(await _to_thread(edit_text, path, old, new, replace_all))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=shell_write_meta)
    async def multi_edit_file(path: str, edits: list[dict], purpose: str | None = None, explanation: str | None = None) -> ToolResult:
        """Apply multiple exact-text edits to one file. Use when several small replacements in the same file should be made together. Each old string must match exactly; read the file first to avoid stale or ambiguous edits. Optional purpose/explanation fields let agents state why the edits are needed."""
        try:
            _audit_tool_purpose("multi_edit_file", purpose, explanation)
            return _ok(await _to_thread(multi_edit_text, path, edits))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=shell_write_meta)
    async def delete_file_or_dir(path: str, recursive: bool = False, purpose: str | None = None, explanation: str | None = None) -> ToolResult:
        """Delete a file or directory inside the controlled workspace/container. Use only when removal is intentional. recursive=false deletes files or empty directories; recursive=true is required for non-empty directories and should be used carefully. Optional purpose/explanation fields let agents state why deletion is needed."""
        try:
            _audit_tool_purpose("delete_file_or_dir", purpose, explanation)
            return _ok(await _to_thread(delete_path, path, recursive))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=patch_meta)
    async def apply_patch(patch: str, cwd: str = ".", purpose: str | None = None, explanation: str | None = None) -> ToolResult:
        """Apply a unified diff using git apply. Use for larger or multi-file edits where an exact patch is clearer than multiple edit_file calls. The patch is checked before application and cwd is workspace-relative unless full-container mode allows absolute paths. Optional purpose/explanation fields let agents state why the patch is needed."""
        try:
            _audit_tool_purpose("apply_patch", purpose, explanation)
            return _ok(await _apply_patch_text(patch, cwd))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=git_write_meta)
    async def git_clone_tool(repo_url: str, dest: str | None = None, branch: str | None = None, cwd: str = ".") -> ToolResult:
        """Clone a Git repository."""
        try:
            return _ok(await git_clone(repo_url, dest, branch, cwd))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=git_read_meta)
    async def git_status_tool(cwd: str = ".") -> ToolResult:
        """Run git status and list remotes."""
        try:
            return _ok(await git_status(cwd))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=git_read_meta)
    async def git_diff_tool(cwd: str = ".", staged: bool = False, path: str | None = None, stat: bool = False) -> ToolResult:
        """Run git diff."""
        try:
            return _ok(await git_diff(cwd, staged, path, stat))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=git_read_meta)
    async def git_log_tool(cwd: str = ".", max_count: int = 20) -> ToolResult:
        """Show recent git commits."""
        try:
            return _ok(await git_log(cwd, max_count))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=git_write_meta)
    async def git_checkout_tool(cwd: str, ref: str, create: bool = False) -> ToolResult:
        """Checkout an existing ref or create a branch."""
        try:
            return _ok(await git_checkout(cwd, ref, create))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=git_write_meta)
    async def git_fetch_tool(cwd: str = ".", remote: str = "origin", prune: bool = True) -> ToolResult:
        """Fetch a git remote."""
        try:
            return _ok(await git_fetch(cwd, remote, prune))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=git_write_meta)
    async def git_pull_tool(cwd: str = ".", ff_only: bool = True) -> ToolResult:
        """Pull current branch."""
        try:
            return _ok(await git_pull(cwd, ff_only))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=git_write_meta)
    async def git_add_tool(cwd: str = ".", paths: list[str] | None = None) -> ToolResult:
        """Stage paths for commit."""
        try:
            return _ok(await git_add(cwd, paths))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=git_write_meta)
    async def git_commit_tool(cwd: str, message: str, all_changes: bool = False, purpose: str | None = None, explanation: str | None = None) -> ToolResult:
        """Create a git commit. Optional purpose/explanation fields let agents state why the commit is being created."""
        try:
            _audit_tool_purpose("git_commit_tool", purpose, explanation)
            return _ok(await git_commit(cwd, message, all_changes))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=git_write_meta)
    async def git_push_tool(cwd: str, remote: str = "origin", branch: str | None = None, set_upstream: bool = True, purpose: str | None = None, explanation: str | None = None) -> ToolResult:
        """Push current HEAD to a remote branch. Optional purpose/explanation fields let agents state why the push is being performed."""
        try:
            _audit_tool_purpose("git_push_tool", purpose, explanation)
            return _ok(await git_push(cwd, remote, branch, set_upstream))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=git_read_meta)
    async def git_show_tool(cwd: str = ".", ref: str = "HEAD", path: str | None = None) -> ToolResult:
        """Show a commit, object, or file at ref:path."""
        try:
            return _ok(await git_show(cwd, ref, path))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=git_write_meta)
    async def git_reset_tool(cwd: str = ".", mode: str = "soft", ref: str = "HEAD") -> ToolResult:
        """Run git reset. Modes: soft, mixed, hard."""
        try:
            return _ok(await git_reset(cwd, mode, ref))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def secret_scan(cwd: str = ".", glob: str | None = None, max_results: int = 200) -> ToolResult:
        """Scan workspace text files for common secrets before commit/push."""
        try:
            return _ok(await _secret_scan(cwd, glob, max_results))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def todo_read_tool() -> ToolResult:
        """Read the agent todo list. Similar to Claude Code TodoRead."""
        try:
            return _ok(await _to_thread(todo_read))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=shell_write_meta)
    async def todo_write_tool(todos: list[dict]) -> ToolResult:
        """Write the agent todo list. Each todo: id, content, status, priority."""
        try:
            return _ok(await _to_thread(todo_write, todos))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=browser_write_meta)
    async def playwright_install_tool(browser: str = "chromium", with_deps: bool = False) -> ToolResult:
        """Install Playwright browser binaries in the container."""
        try:
            return _ok(await playwright_install(browser, with_deps))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=browser_write_meta)
    async def browser_screenshot_tool(url: str, output_path: str = "screenshots/page.png", browser: str = "chromium", full_page: bool = True, width: int = 1440, height: int = 1000, wait_until: str = "networkidle") -> ToolResult:
        """Open a URL with Playwright and save a screenshot."""
        try:
            return _ok(await browser_screenshot(url, output_path, browser, full_page, width, height, wait_until))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=browser_meta)
    async def browser_get_text_tool(url: str, browser: str = "chromium", wait_until: str = "networkidle", selector: str = "body") -> ToolResult:
        """Open a URL with Playwright and return visible text for a selector."""
        try:
            return _ok(await browser_get_text(url, browser, wait_until, selector))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=browser_meta)
    async def browser_eval_tool(url: str, javascript: str, browser: str = "chromium", wait_until: str = "networkidle") -> ToolResult:
        """Open a URL with Playwright and evaluate JavaScript."""
        try:
            return _ok(await browser_eval(url, javascript, browser, wait_until))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=browser_write_meta)
    async def browser_pdf_tool(url: str, output_path: str = "screenshots/page.pdf", width: int = 1440, height: int = 1000, wait_until: str = "networkidle") -> ToolResult:
        """Open a URL with Chromium and save a PDF."""
        try:
            return _ok(await browser_pdf(url, output_path, width, height, wait_until))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=browser_execute_meta)
    async def playwright_run_script_tool(script: str, cwd: str = ".", timeout_s: int = 60) -> ToolResult:
        """Run a full Python Playwright script. Powerful; use in disposable containers."""
        try:
            return _ok(await playwright_run_script(script, cwd, timeout_s))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=shell_read_meta)
    async def audit_tail(lines: int = 100) -> ToolResult:
        """Read recent audit log entries."""
        try:
            return _ok(await _to_thread(_read_audit_tail_entries, lines))
        except Exception as exc:
            return _handled_error(exc)



    async def _remote_call(machine: str, tool: str, args: dict, timeout_s: int | None = None) -> ToolResult:
        try:
            return await remote_manager().call(machine, tool, args, timeout_s)
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=remote_meta)
    async def remote_invite(name: str | None = None, workdir: str | None = None, ttl_s: int | None = None) -> ToolResult:
        """Create a one-time command for a remote machine to join this control server."""
        try:
            return _ok(await remote_manager().create_invite(name, workdir, ttl_s))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=remote_meta)
    async def remote_list_machines() -> ToolResult:
        """List remote worker machines connected to this control server."""
        try:
            return _ok(remote_manager().list_machines())
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=remote_meta)
    async def remote_revoke_machine(machine: str) -> ToolResult:
        """Revoke and remove a remote worker machine."""
        try:
            return _ok(remote_manager().revoke(machine))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=remote_meta)
    async def remote_rename_machine(machine: str, new_name: str) -> ToolResult:
        """Rename a remote worker machine."""
        try:
            return _ok(remote_manager().rename(machine, new_name))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=remote_read_meta)
    async def remote_environment_info(machine: str) -> ToolResult:
        """Return remote workspace, auth, policy, and basic environment information."""
        return await _remote_call(machine, "environment_info", {})

    @mcp.tool(structured_output=True, meta=remote_execute_meta)
    async def remote_run_shell_tool(machine: str, command: str, cwd: str = ".", timeout_s: int | None = None, max_output_bytes: int | None = None, purpose: str | None = None, explanation: str | None = None) -> ToolResult:
        """Run a shell command on a remote worker machine. timeout_s defaults to 10 seconds and may be set to at most 120 seconds. Optional purpose/explanation fields let agents state why the command is being run."""
        return await _remote_call(machine, "run_shell_tool", {"command": command, "cwd": cwd, "timeout_s": timeout_s, "max_output_bytes": max_output_bytes, "purpose": purpose, "explanation": explanation}, timeout_s)

    @mcp.tool(structured_output=True, meta=remote_execute_meta)
    async def remote_run_python_tool(machine: str, code: str, cwd: str = ".", timeout_s: int = 60, purpose: str | None = None, explanation: str | None = None) -> ToolResult:
        """Write Python code to a temporary file and execute it on a remote worker. Optional purpose/explanation fields let agents state why the script is being run."""
        return await _remote_call(machine, "run_python_tool", {"code": code, "cwd": cwd, "timeout_s": timeout_s, "purpose": purpose, "explanation": explanation}, timeout_s)

    @mcp.tool(structured_output=True, meta=remote_execute_meta)
    async def remote_shell_start(machine: str, cwd: str = ".", name: str | None = None, command: str | None = None, purpose: str | None = None, explanation: str | None = None) -> ToolResult:
        """Start a persistent shell session on a remote worker. Optional purpose/explanation fields let agents state why the session is being started."""
        return await _remote_call(machine, "shell_start", {"cwd": cwd, "name": name, "command": command, "purpose": purpose, "explanation": explanation})

    @mcp.tool(structured_output=True, meta=remote_execute_meta)
    async def remote_shell_send(machine: str, session_id: str, input_text: str, enter: bool = True) -> ToolResult:
        """Send input to a persistent remote shell session."""
        return await _remote_call(machine, "shell_send", {"session_id": session_id, "input_text": input_text, "enter": enter})

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=remote_read_meta)
    async def remote_shell_read(machine: str, session_id: str, lines: int = 200) -> ToolResult:
        """Read recent output from a persistent remote shell session."""
        return await _remote_call(machine, "shell_read", {"session_id": session_id, "lines": lines})

    @mcp.tool(structured_output=True, meta=remote_execute_meta)
    async def remote_shell_kill(machine: str, session_id: str) -> ToolResult:
        """Kill a persistent remote shell session."""
        return await _remote_call(machine, "shell_kill", {"session_id": session_id})

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=remote_read_meta)
    async def remote_shell_list(machine: str) -> ToolResult:
        """List persistent shell sessions on a remote worker."""
        return await _remote_call(machine, "shell_list", {})

    @mcp.tool(structured_output=True, meta=remote_execute_meta)
    async def remote_job_start(machine: str, command: str, cwd: str = ".", name: str | None = None, purpose: str | None = None, explanation: str | None = None) -> ToolResult:
        """Start a tracked long-running job on a remote worker. Optional purpose/explanation fields let agents state why the job is being started."""
        return await _remote_call(machine, "job_start", {"command": command, "cwd": cwd, "name": name, "purpose": purpose, "explanation": explanation})

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=remote_read_meta)
    async def remote_job_list(machine: str, include_finished: bool = True) -> ToolResult:
        """List tracked long-running jobs on a remote worker."""
        return await _remote_call(machine, "job_list", {"include_finished": include_finished})

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=remote_read_meta)
    async def remote_job_tail(machine: str, job_id: str, lines: int = 200) -> ToolResult:
        """Read recent output for a tracked remote job."""
        return await _remote_call(machine, "job_tail", {"job_id": job_id, "lines": lines})

    @mcp.tool(structured_output=True, meta=remote_execute_meta)
    async def remote_job_stop(machine: str, job_id: str) -> ToolResult:
        """Stop a tracked long-running job on a remote worker."""
        return await _remote_call(machine, "job_stop", {"job_id": job_id})

    @mcp.tool(structured_output=True, meta=remote_execute_meta)
    async def remote_job_retry(machine: str, job_id: str, purpose: str | None = None, explanation: str | None = None) -> ToolResult:
        """Restart a stopped or exited tracked job on a remote worker. Optional purpose/explanation fields let agents state why the retry is needed."""
        return await _remote_call(machine, "job_retry", {"job_id": job_id, "purpose": purpose, "explanation": explanation})

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=remote_read_meta)
    async def remote_list_files(machine: str, path: str = ".", recursive: bool = False, max_entries: int = 500) -> ToolResult:
        """List files and directories on a remote worker."""
        return await _remote_call(machine, "list_files", {"path": path, "recursive": recursive, "max_entries": max_entries})

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=remote_read_meta)
    async def remote_tree_view(machine: str, cwd: str = ".", depth: int = 3, max_entries: int = 500) -> ToolResult:
        """Return a compact directory tree from a remote worker."""
        return await _remote_call(machine, "tree_view", {"cwd": cwd, "depth": depth, "max_entries": max_entries})

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=remote_read_meta)
    async def remote_glob_search(machine: str, pattern: str, cwd: str = ".", max_results: int = 500) -> ToolResult:
        """Find files by glob pattern on a remote worker."""
        return await _remote_call(machine, "glob_search", {"pattern": pattern, "cwd": cwd, "max_results": max_results})

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=remote_read_meta)
    async def remote_grep_search(machine: str, query: str, cwd: str = ".", glob: str | None = None, regex: bool = True, case_sensitive: bool = True, max_results: int | None = None) -> ToolResult:
        """Search remote file contents using ripgrep."""
        return await _remote_call(machine, "grep_search", {"query": query, "cwd": cwd, "glob": glob, "regex": regex, "case_sensitive": case_sensitive, "max_results": max_results})

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=remote_read_meta)
    async def remote_read_file(machine: str, path: str, start_line: int | None = None, end_line: int | None = None, binary_preview: str | None = None, binary_preview_bytes: int = 256) -> ToolResult:
        """Read a UTF-8 text file on a remote worker, optionally by line range."""
        return await _remote_call(machine, "read_file", {"path": path, "start_line": start_line, "end_line": end_line, "binary_preview": binary_preview, "binary_preview_bytes": binary_preview_bytes})

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=remote_read_meta)
    async def remote_read_many_files(machine: str, paths: list[str], start_line: int | None = None, end_line: int | None = None, binary_preview: str | None = None, binary_preview_bytes: int = 256) -> ToolResult:
        """Read multiple UTF-8 text files on a remote worker."""
        return await _remote_call(machine, "read_many_files", {"paths": paths, "start_line": start_line, "end_line": end_line, "binary_preview": binary_preview, "binary_preview_bytes": binary_preview_bytes})

    @mcp.tool(structured_output=True, meta=remote_write_meta)
    async def remote_write_file(machine: str, path: str, content: str, overwrite: bool = True) -> ToolResult:
        """Write a UTF-8 text file on a remote worker."""
        return await _remote_call(machine, "write_file", {"path": path, "content": content, "overwrite": overwrite})

    @mcp.tool(structured_output=True, meta=remote_write_meta)
    async def remote_edit_file(machine: str, path: str, old: str, new: str, replace_all: bool = False) -> ToolResult:
        """Replace exact text in a remote file."""
        return await _remote_call(machine, "edit_file", {"path": path, "old": old, "new": new, "replace_all": replace_all})

    @mcp.tool(structured_output=True, meta=remote_write_meta)
    async def remote_multi_edit_file(machine: str, path: str, edits: list[dict]) -> ToolResult:
        """Apply multiple exact-text edits to one remote file."""
        return await _remote_call(machine, "multi_edit_file", {"path": path, "edits": edits})

    @mcp.tool(structured_output=True, meta=remote_write_meta)
    async def remote_delete_file_or_dir(machine: str, path: str, recursive: bool = False) -> ToolResult:
        """Delete a file or directory on a remote worker."""
        return await _remote_call(machine, "delete_file_or_dir", {"path": path, "recursive": recursive})

    @mcp.tool(structured_output=True, meta=remote_write_meta)
    async def remote_copy_file(src_machine: str, src_path: str, dst_machine: str, dst_path: str, overwrite: bool = True, chunk_size: int | None = None) -> ToolResult:
        """Copy a file from one remote worker machine to another through the control server."""
        try:
            return _ok(await _copy_remote_file_to_remote(src_machine, src_path, dst_machine, dst_path, overwrite, chunk_size))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=remote_write_meta)
    async def remote_copy_dir(src_machine: str, src_path: str, dst_machine: str, dst_path: str, overwrite: bool = False, chunk_size: int | None = None) -> ToolResult:
        """Copy a directory tree from one remote worker machine to another through the control server."""
        try:
            return _ok(await _copy_remote_dir_to_remote(src_machine, src_path, dst_machine, dst_path, overwrite, chunk_size))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=remote_write_meta)
    async def remote_pull_file(machine: str, remote_path: str, local_path: str, overwrite: bool = True, chunk_size: int | None = None) -> ToolResult:
        """Copy a file from a remote worker to the control server workspace."""
        try:
            return _ok(await _copy_remote_file_to_local(machine, remote_path, local_path, overwrite, chunk_size))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=remote_write_meta)
    async def remote_push_file(local_path: str, machine: str, remote_path: str, overwrite: bool = True, chunk_size: int | None = None) -> ToolResult:
        """Copy a file from the control server workspace to a remote worker."""
        try:
            return _ok(await _copy_local_file_to_remote(local_path, machine, remote_path, overwrite, chunk_size))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=remote_write_meta)
    async def remote_pull_dir(machine: str, remote_path: str, local_path: str, overwrite: bool = False, chunk_size: int | None = None) -> ToolResult:
        """Copy a directory tree from a remote worker to the control server workspace."""
        try:
            return _ok(await _copy_remote_dir_to_local(machine, remote_path, local_path, overwrite, chunk_size))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=remote_write_meta)
    async def remote_push_dir(local_path: str, machine: str, remote_path: str, overwrite: bool = False, chunk_size: int | None = None) -> ToolResult:
        """Copy a directory tree from the control server workspace to a remote worker."""
        try:
            return _ok(await _copy_local_dir_to_remote(local_path, machine, remote_path, overwrite, chunk_size))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(structured_output=True, meta=remote_patch_meta)
    async def remote_apply_patch(machine: str, patch: str, cwd: str = ".", purpose: str | None = None, explanation: str | None = None) -> ToolResult:
        """Apply a unified diff on a remote worker using git apply. Optional purpose/explanation fields let agents state why the patch is needed."""
        return await _remote_call(machine, "apply_patch", {"patch": patch, "cwd": cwd, "purpose": purpose, "explanation": explanation})

    @mcp.tool(structured_output=True, meta=remote_git_write_meta)
    async def remote_git_clone_tool(machine: str, repo_url: str, dest: str | None = None, branch: str | None = None, cwd: str = ".") -> ToolResult:
        """Clone a Git repository on a remote worker."""
        return await _remote_call(machine, "git_clone_tool", {"repo_url": repo_url, "dest": dest, "branch": branch, "cwd": cwd})

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=remote_git_read_meta)
    async def remote_git_status_tool(machine: str, cwd: str = ".") -> ToolResult:
        """Run git status on a remote worker."""
        return await _remote_call(machine, "git_status_tool", {"cwd": cwd})

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=remote_git_read_meta)
    async def remote_git_diff_tool(machine: str, cwd: str = ".", staged: bool = False, path: str | None = None, stat: bool = False) -> ToolResult:
        """Run git diff on a remote worker."""
        return await _remote_call(machine, "git_diff_tool", {"cwd": cwd, "staged": staged, "path": path, "stat": stat})

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=remote_git_read_meta)
    async def remote_git_log_tool(machine: str, cwd: str = ".", max_count: int = 20) -> ToolResult:
        """Show recent git commits on a remote worker."""
        return await _remote_call(machine, "git_log_tool", {"cwd": cwd, "max_count": max_count})

    @mcp.tool(structured_output=True, meta=remote_git_write_meta)
    async def remote_git_checkout_tool(machine: str, cwd: str, ref: str, create: bool = False) -> ToolResult:
        """Checkout an existing ref or create a branch on a remote worker."""
        return await _remote_call(machine, "git_checkout_tool", {"cwd": cwd, "ref": ref, "create": create})

    @mcp.tool(structured_output=True, meta=remote_git_write_meta)
    async def remote_git_fetch_tool(machine: str, cwd: str = ".", remote: str = "origin", prune: bool = True) -> ToolResult:
        """Fetch a git remote on a remote worker."""
        return await _remote_call(machine, "git_fetch_tool", {"cwd": cwd, "remote": remote, "prune": prune})

    @mcp.tool(structured_output=True, meta=remote_git_write_meta)
    async def remote_git_pull_tool(machine: str, cwd: str = ".", ff_only: bool = True) -> ToolResult:
        """Pull current branch on a remote worker."""
        return await _remote_call(machine, "git_pull_tool", {"cwd": cwd, "ff_only": ff_only})

    @mcp.tool(structured_output=True, meta=remote_git_write_meta)
    async def remote_git_add_tool(machine: str, cwd: str = ".", paths: list[str] | None = None) -> ToolResult:
        """Stage paths on a remote worker."""
        return await _remote_call(machine, "git_add_tool", {"cwd": cwd, "paths": paths})

    @mcp.tool(structured_output=True, meta=remote_git_write_meta)
    async def remote_git_commit_tool(machine: str, cwd: str, message: str, all_changes: bool = False, purpose: str | None = None, explanation: str | None = None) -> ToolResult:
        """Create a git commit on a remote worker. Optional purpose/explanation fields let agents state why the commit is being created."""
        return await _remote_call(machine, "git_commit_tool", {"cwd": cwd, "message": message, "all_changes": all_changes, "purpose": purpose, "explanation": explanation})

    @mcp.tool(structured_output=True, meta=remote_git_write_meta)
    async def remote_git_push_tool(machine: str, cwd: str, remote: str = "origin", branch: str | None = None, set_upstream: bool = True, purpose: str | None = None, explanation: str | None = None) -> ToolResult:
        """Push current HEAD from a remote worker. Optional purpose/explanation fields let agents state why the push is being performed."""
        return await _remote_call(machine, "git_push_tool", {"cwd": cwd, "remote": remote, "branch": branch, "set_upstream": set_upstream, "purpose": purpose, "explanation": explanation})

    @mcp.tool(structured_output=True, annotations=read_only_tool, meta=remote_git_read_meta)
    async def remote_git_show_tool(machine: str, cwd: str = ".", ref: str = "HEAD", path: str | None = None) -> ToolResult:
        """Show a commit, object, or file at ref:path on a remote worker."""
        return await _remote_call(machine, "git_show_tool", {"cwd": cwd, "ref": ref, "path": path})

    @mcp.tool(structured_output=True, meta=remote_git_write_meta)
    async def remote_git_reset_tool(machine: str, cwd: str = ".", mode: str = "soft", ref: str = "HEAD") -> ToolResult:
        """Run git reset on a remote worker. Modes: soft, mixed, hard."""
        return await _remote_call(machine, "git_reset_tool", {"cwd": cwd, "mode": mode, "ref": ref})

    @mcp.tool(structured_output=True, meta=remote_browser_write_meta)
    async def remote_playwright_install_tool(machine: str, browser: str = "chromium", with_deps: bool = False) -> ToolResult:
        """Install Playwright browser binaries on a remote worker."""
        return await _remote_call(machine, "playwright_install_tool", {"browser": browser, "with_deps": with_deps})

    @mcp.tool(structured_output=True, meta=remote_browser_write_meta)
    async def remote_browser_screenshot_tool(machine: str, url: str, output_path: str = "screenshots/page.png", browser: str = "chromium", full_page: bool = True, width: int = 1440, height: int = 1000, wait_until: str = "networkidle") -> ToolResult:
        """Open a URL with Playwright on a remote worker and save a screenshot."""
        return await _remote_call(machine, "browser_screenshot_tool", {"url": url, "output_path": output_path, "browser": browser, "full_page": full_page, "width": width, "height": height, "wait_until": wait_until})

    @mcp.tool(structured_output=True, meta=remote_browser_meta)
    async def remote_browser_get_text_tool(machine: str, url: str, browser: str = "chromium", wait_until: str = "networkidle", selector: str = "body") -> ToolResult:
        """Open a URL with Playwright on a remote worker and return visible text."""
        return await _remote_call(machine, "browser_get_text_tool", {"url": url, "browser": browser, "wait_until": wait_until, "selector": selector})

    @mcp.tool(structured_output=True, meta=remote_browser_meta)
    async def remote_browser_eval_tool(machine: str, url: str, javascript: str, browser: str = "chromium", wait_until: str = "networkidle") -> ToolResult:
        """Open a URL with Playwright on a remote worker and evaluate JavaScript."""
        return await _remote_call(machine, "browser_eval_tool", {"url": url, "javascript": javascript, "browser": browser, "wait_until": wait_until})

    @mcp.tool(structured_output=True, meta=remote_browser_write_meta)
    async def remote_browser_pdf_tool(machine: str, url: str, output_path: str = "screenshots/page.pdf", width: int = 1440, height: int = 1000, wait_until: str = "networkidle") -> ToolResult:
        """Open a URL with Chromium on a remote worker and save a PDF."""
        return await _remote_call(machine, "browser_pdf_tool", {"url": url, "output_path": output_path, "width": width, "height": height, "wait_until": wait_until})

    @mcp.tool(structured_output=True, meta=remote_browser_execute_meta)
    async def remote_playwright_run_script_tool(machine: str, script: str, cwd: str = ".", timeout_s: int = 60) -> ToolResult:
        """Run a full Python Playwright script on a remote worker."""
        return await _remote_call(machine, "playwright_run_script_tool", {"script": script, "cwd": cwd, "timeout_s": timeout_s}, timeout_s)

    _remove_remote_tools_when_disabled(mcp)
    _install_tool_annotations(mcp)
    _install_mcp_tool_watchdogs(mcp)
    return mcp
