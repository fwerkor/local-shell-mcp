from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
TUI_NAME = "local-shell-mcp-tui.exe" if os.name == "nt" else "local-shell-mcp-tui"
TUI_PATH = ROOT / "ui" / "dist" / TUI_NAME


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_health(port: int, process: subprocess.Popen[str], timeout_s: float = 30) -> None:
    deadline = time.monotonic() + timeout_s
    url = f"http://127.0.0.1:{port}/healthz"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(
                f"UI smoke server exited with {process.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}"
            )
        try:
            with urllib.request.urlopen(url, timeout=1) as response:  # noqa: S310
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.1)
    raise TimeoutError(f"Server did not become healthy within {timeout_s}s: {url}")


def run_browser(port: int) -> None:
    origin = f"http://127.0.0.1:{port}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="en-US")
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            # No intermediate Open WebUI button: the initial request enters LSM OAuth.
            page.goto(origin + "/ui")
            page.wait_for_url("**/oauth/authorize**")
            expect(page.get_by_role("button", name="Approve", exact=True)).to_be_visible()
            assert page.evaluate("fetch('/api/ui/bootstrap').then(r => r.status)") == 401
            page.get_by_role("button", name="Approve", exact=True).click()
            page.wait_for_url("**/c/new", timeout=30_000)
            expect(page.locator("#root")).not_to_be_empty(timeout=30_000)
            # All control routes are the retained React application, not an iframe/old UI.
            for section, title in [("overview", "Overview"), ("files", "Files"),
                                   ("terminals", "Terminals"), ("desktop", "Desktop"),
                                   ("sessions", "Sessions"), ("remotes", "Remotes"),
                                   ("audit", "Audit"), ("settings", "Settings")]:
                page.goto(origin + "/control/" + section)
                expect(page.get_by_role("heading", name=title, exact=True).first).to_be_visible(timeout=20_000)
                assert page.locator("#application").count() == 0
                assert page.locator("iframe").count() == 0
            page.goto(origin + "/control/files")
            expect(page.get_by_text("mouse-second.txt", exact=True)).to_be_visible(timeout=20_000)
            # The modern file browser edits through the native LSM API.
            page.get_by_text("mouse-second.txt", exact=True).click()
            page.get_by_role("button", name="Edit", exact=True).click()
            editor = page.get_by_role("textbox", name="File editor", exact=True)
            expect(editor).to_be_visible(timeout=10_000)
            editor.fill("React workspace smoke edited this file")
            page.get_by_role("button", name="Save", exact=True).click()
            page.reload()
            page.get_by_text("mouse-second.txt", exact=True).click()
            page.get_by_role("button", name="Edit", exact=True).click()
            expect(page.get_by_role("textbox", name="File editor", exact=True)).to_have_value("React workspace smoke edited this file")
            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(origin + "/control/overview")
            expect(page.get_by_role("heading", name="Overview", exact=True)).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
            assert not errors, errors
        finally:
            browser.close()


def main() -> int:
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="local-shell-mcp-ui-smoke-") as temp_dir:
        workspace = Path(temp_dir) / "workspace"
        state_dir = Path(temp_dir) / "state"
        workspace.mkdir()
        (workspace / "mouse-first.txt").write_text("first", encoding="utf-8")
        (workspace / "mouse-second.txt").write_text("second", encoding="utf-8")
        state_dir.mkdir()
        now = time.time()
        audit_records = [
            {
                "ts": now - 21,
                "event": "mcp_tool_call_start",
                "call_id": "audit-old-call",
                "tool": "audit-old-tool",
                "machine": "local",
                "arguments": {"keyword_args": {"command": "audit-old-input"}},
            },
            {
                "ts": now - 20,
                "event": "mcp_tool_call_end",
                "call_id": "audit-old-call",
                "tool": "audit-old-tool",
                "machine": "local",
                "ok": True,
                "result": {"detail": "audit-old-detail"},
            },
            {
                "ts": now - 11,
                "event": "mcp_tool_call_start",
                "call_id": "audit-new-call",
                "tool": "audit-new-tool",
                "machine": "local",
                "arguments": {"keyword_args": {"command": "audit-new-input"}},
            },
            {
                "ts": now - 10,
                "event": "mcp_tool_call_end",
                "call_id": "audit-new-call",
                "tool": "audit-new-tool",
                "machine": "local",
                "ok": True,
                "result": {"detail": "audit-new-detail"},
            },
        ]
        (state_dir / "audit.jsonl").write_text(
            "\n".join(json.dumps(record) for record in audit_records) + "\n",
            encoding="utf-8",
        )
        env = os.environ.copy()
        env.update(
            {
                "PYTHONPATH": str(ROOT / "src"),
                "LOCAL_SHELL_MCP_HOST": "127.0.0.1",
                "LOCAL_SHELL_MCP_PORT": str(port),
                "LOCAL_SHELL_MCP_MODE": "mcp",
                "LOCAL_SHELL_MCP_WORKSPACE_ROOT": str(workspace),
                "LOCAL_SHELL_MCP_STATE_DIR": str(state_dir),
                "LOCAL_SHELL_MCP_AUTH_MODE": "oauth",
                "LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST": "false",
                "LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN": "",
                "LOCAL_SHELL_MCP_OAUTH_JWT_SECRET": "0123456789abcdef" * 4,
                "LOCAL_SHELL_MCP_REMOTE_ENABLED": "false",
                "LOCAL_SHELL_MCP_UI_WALLPAPER": "none",
                "LOCAL_SHELL_MCP_UI_TUI_COMMAND": str(TUI_PATH),
            }
        )
        if os.getenv("LOCAL_SHELL_MCP_COVERAGE") == "1":
            env["COVERAGE_PROCESS_START"] = str(ROOT / "pyproject.toml")
            env["COVERAGE_FILE"] = str(ROOT / ".coverage")
            env["PYTHONPATH"] = os.pathsep.join(
                item
                for item in (str(ROOT), str(ROOT / "src"), env.get("PYTHONPATH", ""))
                if item
            )
        process = subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "local_shell_mcp.main", "--mode", "mcp", "--no-remote"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            wait_for_health(port, process)
            run_browser(port)
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if process.returncode not in {0, -15}:
            stdout, stderr = process.communicate()
            raise RuntimeError(
                f"UI smoke server stopped with {process.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}"
            )

    print("Human UI browser smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
