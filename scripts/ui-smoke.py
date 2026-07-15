from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import suppress
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

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


def xterm_rows(page: Page) -> list[str]:
    return page.locator(".xterm-rows > div").all_text_contents()


def click_tui_label(page: Page, label: str) -> None:
    rows = xterm_rows(page)
    row_index = next(index for index, row in enumerate(rows) if label in row)
    column = rows[row_index].index(label) + max(1, len(label) // 2)
    screen = page.locator(".xterm-screen").bounding_box()
    if not screen:
        raise AssertionError("xterm screen has no bounding box")
    size = page.locator("#terminal-size").inner_text().split("×")
    columns, row_count = int(size[0].strip()), int(size[1].strip())
    x = screen["x"] + screen["width"] * (column + 0.5) / columns
    y = screen["y"] + screen["height"] * (row_index + 0.5) / row_count
    page.mouse.click(x, y)


def wait_for_terminal_text(page: Page, needle: str, timeout_s: float = 10) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if needle in page.locator("body").inner_text():
            return
        page.wait_for_timeout(100)
    text = page.locator("body").inner_text()
    raise AssertionError(f"Terminal text did not contain {needle!r}\n{text[-5000:]}")


def run_browser(port: int) -> None:
    origin = f"http://127.0.0.1:{port}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        session_id: str | None = None
        try:
            page.goto(f"{origin}/ui", wait_until="networkidle")

            assert page.locator("#auth-gate").is_visible()
            unauthenticated = page.evaluate(
                "fetch('/api/ui/bootstrap').then(response => response.status)"
            )
            assert unauthenticated == 401

            page.locator("#login-button").click()
            page.wait_for_url("**/oauth/authorize**")
            page.get_by_role("button", name="Approve").click()
            page.wait_for_url("**/ui")
            page.locator("#connection-state").get_by_text("Connected").wait_for(timeout=15_000)
            assert page.locator("#auth-gate").is_hidden()

            authenticated = page.evaluate(
                """fetch('/api/ui/bootstrap', {
                    headers: {Authorization: 'Bearer ' + sessionStorage.getItem('lsm.ui.access_token')}
                }).then(response => response.status)"""
            )
            assert authenticated == 200
            wait_for_terminal_text(page, "Alt+1 Files")

            session_name = f"ui-smoke-{os.getpid()}"
            created = page.evaluate(
                """name => fetch('/api/ui/terminals/start', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        Authorization: 'Bearer ' + sessionStorage.getItem('lsm.ui.access_token')
                    },
                    body: JSON.stringify({machine: 'local', name, cwd: '.'})
                }).then(async response => ({status: response.status, body: await response.json()}))""",
                session_name,
            )
            assert created["status"] == 200, created
            session_id = created["body"]["data"]["session_id"]
            click_tui_label(page, "Alt+2 Terminals")
            wait_for_terminal_text(page, "MCP audit · manual input excluded")
            wait_for_terminal_text(page, session_name, timeout_s=8)
            page.locator(".xterm-helper-textarea").focus()
            page.keyboard.press("F8")
            wait_for_terminal_text(page, "RAW INPUT")
            page.keyboard.press("Alt+1")
            page.wait_for_timeout(500)
            assert "MCP audit · manual input excluded" in page.locator("body").inner_text()
            page.keyboard.press("F8")
            wait_for_terminal_text(page, "F8 raw mode")

            expectations = [
                ("Alt+2 Terminals", "MCP audit · manual input excluded"),
                ("Alt+3 Todos", "Todos ·"),
                ("Alt+4 Audit", "Audit records"),
                ("Alt+5 Remotes", "Remote nodes"),
                ("Alt+1 Files", "Preview"),
            ]
            for label, expected in expectations:
                click_tui_label(page, label)
                wait_for_terminal_text(page, expected)

            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(600)
            metrics = page.evaluate(
                """({
                    width: innerWidth,
                    height: innerHeight,
                    scrollWidth: document.documentElement.scrollWidth,
                    scrollHeight: document.documentElement.scrollHeight,
                    shell: (() => {
                        const box = document.querySelector('.shell').getBoundingClientRect()
                        return {width: box.width, height: box.height}
                    })(),
                    size: document.querySelector('#terminal-size').textContent
                })"""
            )
            assert metrics["scrollWidth"] <= metrics["width"]
            assert metrics["scrollHeight"] <= metrics["height"]
            assert metrics["shell"]["width"] <= metrics["width"]
            assert metrics["shell"]["height"] <= metrics["height"]
            wait_for_terminal_text(page, "A1:Fil")
            wait_for_terminal_text(page, "A5:Rem")

            killed = page.evaluate(
                """sessionId => fetch('/api/ui/terminals/kill', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        Authorization: 'Bearer ' + sessionStorage.getItem('lsm.ui.access_token')
                    },
                    body: JSON.stringify({machine: 'local', session_id: sessionId})
                }).then(async response => ({status: response.status, body: await response.json()}))""",
                session_id,
            )
            assert killed["status"] == 200, killed
            assert killed["body"]["data"]["killed"] is True, killed
            session_id = None
        finally:
            if session_id and not page.is_closed():
                with suppress(Exception):
                    page.evaluate(
                        """sessionId => fetch('/api/ui/terminals/kill', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                Authorization: 'Bearer ' + sessionStorage.getItem('lsm.ui.access_token')
                            },
                            body: JSON.stringify({machine: 'local', session_id: sessionId})
                        })""",
                        session_id,
                    )
            browser.close()


def main() -> int:
    if not TUI_PATH.is_file():
        raise FileNotFoundError(f"Build the native TUI first: {TUI_PATH}")

    port = free_port()
    with tempfile.TemporaryDirectory(prefix="local-shell-mcp-ui-smoke-") as temp_dir:
        workspace = Path(temp_dir) / "workspace"
        state_dir = Path(temp_dir) / "state"
        workspace.mkdir()
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
