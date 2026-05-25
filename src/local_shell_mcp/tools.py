from __future__ import annotations

import asyncio
import json
import shlex
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

from .audit import audit
from .fs_ops import (
    delete_path,
    edit_text,
    glob_paths,
    list_dir,
    multi_edit_text,
    read_text,
    relative_display,
    resolve_path,
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
from .shell_ops import kill_shell, list_shells, read_shell, run_shell, send_shell, start_shell
from .todo_ops import todo_read, todo_write


def _ok(data: Any = None, message: str = "") -> dict:
    return {"ok": True, "message": message, "data": data}


def _error(exc: Exception) -> dict:
    audit("tool_error", error=repr(exc))
    return {"ok": False, "error": type(exc).__name__, "message": str(exc)}


def _sync(coro):  # noqa: ANN001
    return asyncio.get_event_loop().run_until_complete(coro)


async def _apply_patch_text(patch: str, cwd: str = ".") -> dict:
    patch_path = resolve_path(f".local-shell-mcp/tmp/patch-{uuid.uuid4().hex}.diff")
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text(patch, encoding="utf-8")
    quoted = shlex.quote(str(patch_path))
    result = await run_shell(f"git apply --check {quoted} && git apply {quoted}", cwd=cwd, timeout_s=120, max_output_bytes=500_000)
    return {**result.model_dump(), "patch_path": relative_display(patch_path)}


async def _run_python(code: str, cwd: str = ".", timeout_s: int = 120) -> dict:
    path = resolve_path(f".local-shell-mcp/tmp/script-{uuid.uuid4().hex}.py")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code, encoding="utf-8")
    result = await run_shell(f"python3 {shlex.quote(str(path))}", cwd=cwd, timeout_s=timeout_s, max_output_bytes=1_000_000)
    return {**result.model_dump(), "script_path": relative_display(path)}


SECRET_PATTERNS = {
    "github_token": r"gh[pousr]_[A-Za-z0-9_]{36,}",
    "aws_access_key": r"AKIA[0-9A-Z]{16}",
    "private_key": r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----",
    "generic_assignment": r"(?i)(token|secret|password|passwd|api_key|apikey)\s*[:=]\s*['\"][^'\"]{8,}['\"]",
}


async def _secret_scan(cwd: str = ".", glob: str | None = None, max_results: int = 200) -> dict:
    import re

    base = resolve_path(cwd, must_exist=True)
    findings = []
    for path in base.rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue
        if glob and not path.match(glob):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for name, pattern in SECRET_PATTERNS.items():
            for match in re.finditer(pattern, text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append({"type": name, "path": relative_display(path), "line": line})
                if len(findings) >= max_results:
                    return {"findings": findings, "truncated": True}
    return {"findings": findings, "truncated": False}


def build_mcp() -> FastMCP:
    settings = get_settings()
    mcp = FastMCP("local-shell-mcp")

    @mcp.tool()
    async def environment_info() -> dict:
        """Return workspace, auth, policy, and basic environment information."""
        try:
            result = await run_shell("uname -a; echo '---'; id; echo '---'; pwd; echo '---'; python3 --version; git --version", cwd=".", timeout_s=10)
            return _ok({"settings": settings.model_dump(mode="json"), "probe": result.model_dump()})
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def run_shell_tool(command: str, cwd: str = ".", timeout_s: int | None = None, max_output_bytes: int | None = None) -> dict:
        """Run a shell command in the controlled container. This is the primary coding-agent tool."""
        try:
            return _ok((await run_shell(command, cwd, timeout_s, max_output_bytes)).model_dump())
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def run_python_tool(code: str, cwd: str = ".", timeout_s: int = 120) -> dict:
        """Write Python code to a temporary file and execute it."""
        try:
            return _ok(await _run_python(code, cwd, timeout_s))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def shell_start(cwd: str = ".", name: str | None = None, command: str | None = None) -> dict:
        """Start a persistent tmux-backed shell session."""
        try:
            return _ok(await start_shell(cwd, name, command))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def shell_send(session_id: str, input_text: str, enter: bool = True) -> dict:
        """Send input to a persistent shell session."""
        try:
            return _ok(await send_shell(session_id, input_text, enter))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def shell_read(session_id: str, lines: int = 200) -> dict:
        """Read recent output from a persistent shell session."""
        try:
            return _ok(await read_shell(session_id, lines))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def shell_kill(session_id: str) -> dict:
        """Kill a persistent shell session."""
        try:
            return _ok(await kill_shell(session_id))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def shell_list() -> dict:
        """List persistent shell sessions."""
        try:
            return _ok(await list_shells())
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def list_files(path: str = ".", recursive: bool = False, max_entries: int = 500) -> dict:
        """List files and directories."""
        try:
            return _ok(list_dir(path, recursive, max_entries))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def tree_view(cwd: str = ".", depth: int = 3, max_entries: int = 500) -> dict:
        """Return a compact directory tree."""
        try:
            return _ok(await tree(cwd, depth, max_entries))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def glob_search(pattern: str, cwd: str = ".", max_results: int = 500) -> dict:
        """Find files by glob pattern."""
        try:
            return _ok({"paths": glob_paths(pattern, cwd, max_results)})
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def grep_search(query: str, cwd: str = ".", glob: str | None = None, regex: bool = True, case_sensitive: bool = True, max_results: int | None = None) -> dict:
        """Search file contents using ripgrep."""
        try:
            return _ok(await grep(query, cwd, glob, regex, case_sensitive, max_results))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def read_file(path: str, start_line: int | None = None, end_line: int | None = None) -> dict:
        """Read a UTF-8 text file, optionally by line range."""
        try:
            return _ok(read_text(path, start_line, end_line))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def read_many_files(paths: list[str], start_line: int | None = None, end_line: int | None = None) -> dict:
        """Read multiple UTF-8 text files."""
        try:
            return _ok({"files": [read_text(p, start_line, end_line) for p in paths]})
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def write_file(path: str, content: str, overwrite: bool = True) -> dict:
        """Write a UTF-8 text file."""
        try:
            return _ok(write_text(path, content, overwrite))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def edit_file(path: str, old: str, new: str, replace_all: bool = False) -> dict:
        """Replace exact text in a file. Use this for precise code edits."""
        try:
            return _ok(edit_text(path, old, new, replace_all))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def multi_edit_file(path: str, edits: list[dict]) -> dict:
        """Apply multiple exact-text edits to one file. Each edit has old, new, replace_all."""
        try:
            return _ok(multi_edit_text(path, edits))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def delete_file_or_dir(path: str, recursive: bool = False) -> dict:
        """Delete a file or directory inside the controlled workspace/container."""
        try:
            return _ok(delete_path(path, recursive))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def apply_patch(patch: str, cwd: str = ".") -> dict:
        """Apply a unified diff using git apply."""
        try:
            return _ok(await _apply_patch_text(patch, cwd))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def git_clone_tool(repo_url: str, dest: str | None = None, branch: str | None = None, cwd: str = ".") -> dict:
        """Clone a Git repository."""
        try:
            return _ok(await git_clone(repo_url, dest, branch, cwd))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def git_status_tool(cwd: str = ".") -> dict:
        """Run git status and list remotes."""
        try:
            return _ok(await git_status(cwd))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def git_diff_tool(cwd: str = ".", staged: bool = False, path: str | None = None, stat: bool = False) -> dict:
        """Run git diff."""
        try:
            return _ok(await git_diff(cwd, staged, path, stat))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def git_log_tool(cwd: str = ".", max_count: int = 20) -> dict:
        """Show recent git commits."""
        try:
            return _ok(await git_log(cwd, max_count))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def git_checkout_tool(cwd: str, ref: str, create: bool = False) -> dict:
        """Checkout an existing ref or create a branch."""
        try:
            return _ok(await git_checkout(cwd, ref, create))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def git_fetch_tool(cwd: str = ".", remote: str = "origin", prune: bool = True) -> dict:
        """Fetch a git remote."""
        try:
            return _ok(await git_fetch(cwd, remote, prune))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def git_pull_tool(cwd: str = ".", ff_only: bool = True) -> dict:
        """Pull current branch."""
        try:
            return _ok(await git_pull(cwd, ff_only))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def git_add_tool(cwd: str = ".", paths: list[str] | None = None) -> dict:
        """Stage paths for commit."""
        try:
            return _ok(await git_add(cwd, paths))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def git_commit_tool(cwd: str, message: str, all_changes: bool = False) -> dict:
        """Create a git commit."""
        try:
            return _ok(await git_commit(cwd, message, all_changes))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def git_push_tool(cwd: str, remote: str = "origin", branch: str | None = None, set_upstream: bool = True) -> dict:
        """Push current HEAD to a remote branch."""
        try:
            return _ok(await git_push(cwd, remote, branch, set_upstream))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def git_show_tool(cwd: str = ".", ref: str = "HEAD", path: str | None = None) -> dict:
        """Show a commit, object, or file at ref:path."""
        try:
            return _ok(await git_show(cwd, ref, path))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def git_reset_tool(cwd: str = ".", mode: str = "soft", ref: str = "HEAD") -> dict:
        """Run git reset. Modes: soft, mixed, hard."""
        try:
            return _ok(await git_reset(cwd, mode, ref))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def secret_scan(cwd: str = ".", glob: str | None = None, max_results: int = 200) -> dict:
        """Scan workspace text files for common secrets before commit/push."""
        try:
            return _ok(await _secret_scan(cwd, glob, max_results))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def todo_read_tool() -> dict:
        """Read the agent todo list. Similar to Claude Code TodoRead."""
        try:
            return _ok(todo_read())
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def todo_write_tool(todos: list[dict]) -> dict:
        """Write the agent todo list. Each todo: id, content, status, priority."""
        try:
            return _ok(todo_write(todos))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def playwright_install_tool(browser: str = "chromium", with_deps: bool = False) -> dict:
        """Install Playwright browser binaries in the container."""
        try:
            return _ok(await playwright_install(browser, with_deps))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def browser_screenshot_tool(url: str, output_path: str = "screenshots/page.png", browser: str = "chromium", full_page: bool = True, width: int = 1440, height: int = 1000, wait_until: str = "networkidle") -> dict:
        """Open a URL with Playwright and save a screenshot."""
        try:
            return _ok(await browser_screenshot(url, output_path, browser, full_page, width, height, wait_until))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def browser_get_text_tool(url: str, browser: str = "chromium", wait_until: str = "networkidle", selector: str = "body") -> dict:
        """Open a URL with Playwright and return visible text for a selector."""
        try:
            return _ok(await browser_get_text(url, browser, wait_until, selector))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def browser_eval_tool(url: str, javascript: str, browser: str = "chromium", wait_until: str = "networkidle") -> dict:
        """Open a URL with Playwright and evaluate JavaScript."""
        try:
            return _ok(await browser_eval(url, javascript, browser, wait_until))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def browser_pdf_tool(url: str, output_path: str = "screenshots/page.pdf", width: int = 1440, height: int = 1000, wait_until: str = "networkidle") -> dict:
        """Open a URL with Chromium and save a PDF."""
        try:
            return _ok(await browser_pdf(url, output_path, width, height, wait_until))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def playwright_run_script_tool(script: str, cwd: str = ".", timeout_s: int = 300) -> dict:
        """Run a full Python Playwright script. Powerful; use in disposable containers."""
        try:
            return _ok(await playwright_run_script(script, cwd, timeout_s))
        except Exception as exc:
            return _error(exc)

    @mcp.tool()
    async def audit_tail(lines: int = 100) -> dict:
        """Read recent audit log entries."""
        try:
            path = settings.audit_log_path
            if not path.exists():
                return _ok({"entries": []})
            content = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, min(lines, 1000)) :]
            entries = []
            for line in content:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    entries.append({"raw": line})
            return _ok({"entries": entries})
        except Exception as exc:
            return _error(exc)

    return mcp
