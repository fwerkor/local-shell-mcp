from __future__ import annotations

import asyncio
import json
import shlex
import uuid
from contextlib import suppress
from typing import Any
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from .audit import audit
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
from .playwright_ops import (
    browser_eval,
    browser_get_text,
    browser_pdf,
    browser_screenshot,
    playwright_install,
    playwright_run_script,
)
from .search_ops import grep, tree
from .settings import get_settings
from .shell_ops import (
    PUBLIC_RUN_SHELL_TIMEOUT_CAP_S,
    kill_shell,
    list_shells,
    public_run_shell,
    public_run_shell_timeout,
    read_shell,
    run_shell,
    send_shell,
    start_shell,
)
from .todo_ops import todo_read, todo_write


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

OAUTH_SECURITY_SCHEMES = [
    {
        "type": "oauth2",
        "scopes": ["shell:read", "shell:write", "shell:execute", "git:write", "browser:use"],
    }
]
NOAUTH_SECURITY_SCHEMES = [{"type": "noauth"}]
PUBLIC_TOOL_TIMEOUT_S = PUBLIC_RUN_SHELL_TIMEOUT_CAP_S


class PublicToolTimeoutError(TimeoutError):
    pass


def _security_meta(schemes: list[dict[str, Any]]) -> dict[str, Any]:
    return {"securitySchemes": schemes}


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

        async def wrapped(*args, __original=original, __tool_name=tool_name, **kwargs):  # noqa: ANN002, ANN003
            try:
                return await asyncio.wait_for(__original(*args, **kwargs), timeout=PUBLIC_TOOL_TIMEOUT_S)
            except TimeoutError:
                exc = PublicToolTimeoutError(f"{__tool_name} exceeded {PUBLIC_TOOL_TIMEOUT_S} second public tool timeout")
                audit("tool_timeout", tool=__tool_name, timeout_s=PUBLIC_TOOL_TIMEOUT_S)
                return _timeout_payload_for_tool(__tool_name, exc)

        tool.fn = wrapped


def _install_full_container_auto_approval_hints(mcp: FastMCP) -> None:
    if not get_settings().allow_full_container:
        return
    for tool in mcp._tool_manager._tools.values():  # noqa: SLF001
        if tool.annotations and tool.annotations.readOnlyHint:
            continue
        tool.annotations = ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
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


def _secret_scan_sync(cwd: str = ".", glob: str | None = None, max_results: int = 200) -> dict:
    import re

    settings = get_settings()
    max_results = max(1, min(max_results, settings.max_grep_results))
    base = resolve_path(cwd, must_exist=True)
    findings = []
    truncated_files = 0
    for path in base.rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue
        if glob and not path.match(glob):
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
                line = text.count("\n", 0, match.start()) + 1
                findings.append({"type": name, "path": relative_display(path), "line": line})
                if len(findings) >= max_results:
                    return {"findings": findings, "truncated": True, "truncated_files": truncated_files}
    return {"findings": findings, "truncated": False, "truncated_files": truncated_files}


async def _secret_scan(cwd: str = ".", glob: str | None = None, max_results: int = 200) -> dict:
    return await _to_thread(_secret_scan_sync, cwd, glob, max_results)


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
    mcp = FastMCP("local-shell-mcp", transport_security=_transport_security_settings())
    read_only_tool = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    read_only_meta = _security_meta([*NOAUTH_SECURITY_SCHEMES, *OAUTH_SECURITY_SCHEMES])
    oauth_meta = _security_meta(OAUTH_SECURITY_SCHEMES)

    @mcp.tool(annotations=read_only_tool, meta=read_only_meta)
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

    @mcp.tool(annotations=read_only_tool, meta=read_only_meta)
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

    @mcp.tool(meta=oauth_meta)
    async def environment_info() -> dict:
        """Return workspace, auth, policy, and basic environment information."""
        try:
            result = await run_shell("uname -a; echo '---'; id; echo '---'; pwd; echo '---'; python3 --version; git --version", cwd=".", timeout_s=10)
            return _ok({"settings": settings.model_dump(mode="json"), "probe": result.model_dump()})
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def run_shell_tool(command: str, cwd: str = ".", timeout_s: int | None = None, max_output_bytes: int | None = None) -> dict:
        """Run a shell command in the controlled container. This is the primary coding-agent tool."""
        try:
            return _ok((await public_run_shell(command, cwd, timeout_s, max_output_bytes)).model_dump())
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def run_python_tool(code: str, cwd: str = ".", timeout_s: int = 60) -> dict:
        """Write Python code to a temporary file and execute it."""
        try:
            return _ok(await _run_python(code, cwd, timeout_s))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def shell_start(cwd: str = ".", name: str | None = None, command: str | None = None) -> dict:
        """Start a persistent tmux-backed shell session."""
        try:
            return _ok(await start_shell(cwd, name, command))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def shell_send(session_id: str, input_text: str, enter: bool = True) -> dict:
        """Send input to a persistent shell session."""
        try:
            return _ok(await send_shell(session_id, input_text, enter))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def shell_read(session_id: str, lines: int = 200) -> dict:
        """Read recent output from a persistent shell session."""
        try:
            return _ok(await read_shell(session_id, lines))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def shell_kill(session_id: str) -> dict:
        """Kill a persistent shell session."""
        try:
            return _ok(await kill_shell(session_id))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def shell_list() -> dict:
        """List persistent shell sessions."""
        try:
            return _ok(await list_shells())
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def list_files(path: str = ".", recursive: bool = False, max_entries: int = 500) -> dict:
        """List files and directories."""
        try:
            return _ok(await _to_thread(list_dir, path, recursive, max_entries))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def tree_view(cwd: str = ".", depth: int = 3, max_entries: int = 500) -> dict:
        """Return a compact directory tree."""
        try:
            return _ok(await tree(cwd, depth, max_entries))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def glob_search(pattern: str, cwd: str = ".", max_results: int = 500) -> dict:
        """Find files by glob pattern."""
        try:
            return _ok({"paths": await _to_thread(glob_paths, pattern, cwd, max_results)})
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def grep_search(query: str, cwd: str = ".", glob: str | None = None, regex: bool = True, case_sensitive: bool = True, max_results: int | None = None) -> dict:
        """Search file contents using ripgrep."""
        try:
            return _ok(await grep(query, cwd, glob, regex, case_sensitive, max_results))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def read_file(
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        binary_preview: str | None = None,
        binary_preview_bytes: int = 256,
    ) -> dict:
        """Read a UTF-8 text file, optionally by line range."""
        try:
            return _ok(await _to_thread(read_text, path, start_line, end_line, binary_preview, binary_preview_bytes))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def read_many_files(
        paths: list[str],
        start_line: int | None = None,
        end_line: int | None = None,
        binary_preview: str | None = None,
        binary_preview_bytes: int = 256,
    ) -> dict:
        """Read multiple UTF-8 text files."""
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

    @mcp.tool(meta=oauth_meta)
    async def write_file(path: str, content: str, overwrite: bool = True) -> dict:
        """Write a UTF-8 text file."""
        try:
            return _ok(await _to_thread(write_text, path, content, overwrite))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def edit_file(path: str, old: str, new: str, replace_all: bool = False) -> dict:
        """Replace exact text in a file. Use this for precise code edits."""
        try:
            return _ok(await _to_thread(edit_text, path, old, new, replace_all))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def multi_edit_file(path: str, edits: list[dict]) -> dict:
        """Apply multiple exact-text edits to one file. Each edit has old, new, replace_all."""
        try:
            return _ok(await _to_thread(multi_edit_text, path, edits))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def delete_file_or_dir(path: str, recursive: bool = False) -> dict:
        """Delete a file or directory inside the controlled workspace/container."""
        try:
            return _ok(await _to_thread(delete_path, path, recursive))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def apply_patch(patch: str, cwd: str = ".") -> dict:
        """Apply a unified diff using git apply."""
        try:
            return _ok(await _apply_patch_text(patch, cwd))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_clone_tool(repo_url: str, dest: str | None = None, branch: str | None = None, cwd: str = ".") -> dict:
        """Clone a Git repository."""
        try:
            return _ok(await git_clone(repo_url, dest, branch, cwd))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_status_tool(cwd: str = ".") -> dict:
        """Run git status and list remotes."""
        try:
            return _ok(await git_status(cwd))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_diff_tool(cwd: str = ".", staged: bool = False, path: str | None = None, stat: bool = False) -> dict:
        """Run git diff."""
        try:
            return _ok(await git_diff(cwd, staged, path, stat))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_log_tool(cwd: str = ".", max_count: int = 20) -> dict:
        """Show recent git commits."""
        try:
            return _ok(await git_log(cwd, max_count))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_checkout_tool(cwd: str, ref: str, create: bool = False) -> dict:
        """Checkout an existing ref or create a branch."""
        try:
            return _ok(await git_checkout(cwd, ref, create))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_fetch_tool(cwd: str = ".", remote: str = "origin", prune: bool = True) -> dict:
        """Fetch a git remote."""
        try:
            return _ok(await git_fetch(cwd, remote, prune))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_pull_tool(cwd: str = ".", ff_only: bool = True) -> dict:
        """Pull current branch."""
        try:
            return _ok(await git_pull(cwd, ff_only))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_add_tool(cwd: str = ".", paths: list[str] | None = None) -> dict:
        """Stage paths for commit."""
        try:
            return _ok(await git_add(cwd, paths))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_commit_tool(cwd: str, message: str, all_changes: bool = False) -> dict:
        """Create a git commit."""
        try:
            return _ok(await git_commit(cwd, message, all_changes))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_push_tool(cwd: str, remote: str = "origin", branch: str | None = None, set_upstream: bool = True) -> dict:
        """Push current HEAD to a remote branch."""
        try:
            return _ok(await git_push(cwd, remote, branch, set_upstream))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_show_tool(cwd: str = ".", ref: str = "HEAD", path: str | None = None) -> dict:
        """Show a commit, object, or file at ref:path."""
        try:
            return _ok(await git_show(cwd, ref, path))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def git_reset_tool(cwd: str = ".", mode: str = "soft", ref: str = "HEAD") -> dict:
        """Run git reset. Modes: soft, mixed, hard."""
        try:
            return _ok(await git_reset(cwd, mode, ref))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def secret_scan(cwd: str = ".", glob: str | None = None, max_results: int = 200) -> dict:
        """Scan workspace text files for common secrets before commit/push."""
        try:
            return _ok(await _secret_scan(cwd, glob, max_results))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def todo_read_tool() -> dict:
        """Read the agent todo list. Similar to Claude Code TodoRead."""
        try:
            return _ok(await _to_thread(todo_read))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def todo_write_tool(todos: list[dict]) -> dict:
        """Write the agent todo list. Each todo: id, content, status, priority."""
        try:
            return _ok(await _to_thread(todo_write, todos))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def playwright_install_tool(browser: str = "chromium", with_deps: bool = False) -> dict:
        """Install Playwright browser binaries in the container."""
        try:
            return _ok(await playwright_install(browser, with_deps))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def browser_screenshot_tool(url: str, output_path: str = "screenshots/page.png", browser: str = "chromium", full_page: bool = True, width: int = 1440, height: int = 1000, wait_until: str = "networkidle") -> dict:
        """Open a URL with Playwright and save a screenshot."""
        try:
            return _ok(await browser_screenshot(url, output_path, browser, full_page, width, height, wait_until))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def browser_get_text_tool(url: str, browser: str = "chromium", wait_until: str = "networkidle", selector: str = "body") -> dict:
        """Open a URL with Playwright and return visible text for a selector."""
        try:
            return _ok(await browser_get_text(url, browser, wait_until, selector))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def browser_eval_tool(url: str, javascript: str, browser: str = "chromium", wait_until: str = "networkidle") -> dict:
        """Open a URL with Playwright and evaluate JavaScript."""
        try:
            return _ok(await browser_eval(url, javascript, browser, wait_until))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def browser_pdf_tool(url: str, output_path: str = "screenshots/page.pdf", width: int = 1440, height: int = 1000, wait_until: str = "networkidle") -> dict:
        """Open a URL with Chromium and save a PDF."""
        try:
            return _ok(await browser_pdf(url, output_path, width, height, wait_until))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def playwright_run_script_tool(script: str, cwd: str = ".", timeout_s: int = 60) -> dict:
        """Run a full Python Playwright script. Powerful; use in disposable containers."""
        try:
            return _ok(await playwright_run_script(script, cwd, timeout_s))
        except Exception as exc:
            return _handled_error(exc)

    @mcp.tool(meta=oauth_meta)
    async def audit_tail(lines: int = 100) -> dict:
        """Read recent audit log entries."""
        try:
            return _ok(await _to_thread(_read_audit_tail_entries, lines))
        except Exception as exc:
            return _handled_error(exc)

    _install_full_container_auto_approval_hints(mcp)
    _install_mcp_tool_watchdogs(mcp)
    return mcp
