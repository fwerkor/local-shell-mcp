from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import suppress
from pathlib import Path
from urllib.parse import quote

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


def visible_scroll_line_numbers(page: Page) -> list[int]:
    return [
        int(match)
        for row in xterm_rows(page)
        for match in re.findall(r"SCROLL-LINE-(\d+)", row)
    ]


def click_tui_label(page: Page, label: str, occurrence: int = 0) -> None:
    rows = xterm_rows(page)
    matches: list[tuple[int, int]] = []
    for row_index, row in enumerate(rows):
        start = 0
        while True:
            column = row.find(label, start)
            if column < 0:
                break
            matches.append((row_index, column))
            start = column + max(1, len(label))
    if not matches:
        raise AssertionError(f"Terminal label not found: {label!r}")
    row_index, column = matches[occurrence]
    column += max(1, len(label) // 2)
    screen = page.locator(".xterm-screen").bounding_box()
    if not screen:
        raise AssertionError("xterm screen has no bounding box")
    size = page.locator("#terminal-size").inner_text().split("×")
    columns, row_count = int(size[0].strip()), int(size[1].strip())
    x = screen["x"] + screen["width"] * (column + 0.5) / columns
    y = screen["y"] + screen["height"] * (row_index + 0.5) / row_count
    page.mouse.click(x, y)


def api_request(page: Page, path: str, method: str = "GET", body: object | None = None) -> dict:
    return page.evaluate(
        """async ({path, method, body}) => {
            const response = await fetch(path, {
                method,
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: 'Bearer ' + sessionStorage.getItem('lsm.ui.access_token')
                },
                body: body === null ? undefined : JSON.stringify(body)
            })
            return {status: response.status, body: await response.json()}
        }""",
        {"path": path, "method": method, "body": body},
    )


def wait_for_terminal_session(page: Page, session_id: str, timeout_s: float = 10) -> str:
    deadline = time.monotonic() + timeout_s
    sessions: list[dict] = []
    while time.monotonic() < deadline:
        response = api_request(page, "/api/ui/terminals?machine=local")
        assert response["status"] == 200, response
        sessions = response["body"]["data"]["sessions"]
        if any(session["session_id"] == session_id for session in sessions):
            return session_id
        page.wait_for_timeout(100)
    raise AssertionError(
        f"Terminal session did not appear: {session_id!r}; "
        f"sessions={[session.get('session_id') for session in sessions]!r}"
    )


def selected_terminal_session(page: Page) -> str | None:
    marker = "local / "
    for row in xterm_rows(page):
        if marker not in row:
            continue
        suffix = row.split(marker, 1)[1].strip()
        if suffix:
            return suffix.split()[0]
    return None


def wait_for_selected_terminal(page: Page, expected: str, timeout_s: float = 10) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if selected_terminal_session(page) == expected:
            return
        page.wait_for_timeout(100)
    matching_rows = [row for row in xterm_rows(page) if "local / " in row]
    raise AssertionError(
        f"Selected terminal did not become {expected!r}; current={selected_terminal_session(page)!r}; "
        f"matching_rows={matching_rows!r}"
    )


def wait_for_terminal_text(page: Page, needle: str, timeout_s: float = 10) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if needle in page.locator("body").inner_text():
            return
        page.wait_for_timeout(100)
    text = page.locator("body").inner_text()
    raise AssertionError(f"Terminal text did not contain {needle!r}\n{text[-5000:]}")


def wait_for_terminal_text_absent(page: Page, needle: str, timeout_s: float = 10) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if needle not in page.locator("body").inner_text():
            return
        page.wait_for_timeout(100)
    text = page.locator("body").inner_text()
    raise AssertionError(f"Terminal text still contained {needle!r}\n{text[-5000:]}")


def wait_for_terminal_output(
    page: Page, session_id: str, needle: str, timeout_s: float = 10
) -> None:
    deadline = time.monotonic() + timeout_s
    output = ""
    path = (
        "/api/ui/terminals/read?machine=local"
        f"&session_id={quote(session_id)}&lines=500"
    )
    while time.monotonic() < deadline:
        response = api_request(page, path)
        assert response["status"] == 200, response
        output = response["body"]["data"]["output"]
        if needle in output:
            return
        page.wait_for_timeout(100)
    raise AssertionError(
        f"Terminal API output did not contain {needle!r}\n{output[-5000:]}"
    )


def run_browser(port: int) -> None:
    origin = f"http://127.0.0.1:{port}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        session_ids: list[str] = []
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
            wait_for_terminal_text(page, "Files")
            wait_for_terminal_text(page, "mouse-second.txt")
            click_tui_label(page, "mouse-second.txt")
            wait_for_terminal_text(page, "Preview · mouse-second.txt")

            todo_seed = api_request(page, "/api/ui/todos")
            assert todo_seed["status"] == 200, todo_seed
            todo_items = [
                {"id": "ui-smoke-first", "content": "mouse todo first", "status": "pending", "priority": "medium"},
                {"id": "ui-smoke-second", "content": "mouse todo second", "status": "pending", "priority": "medium"},
                {"id": "ui-smoke-done", "content": "mouse todo done", "status": "completed", "priority": "low"},
            ]
            todo_write = api_request(
                page,
                "/api/ui/todos",
                "PUT",
                {"todos": todo_items, "expected_revision": todo_seed["body"]["data"]["revision"]},
            )
            assert todo_write["status"] == 200, todo_write

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
            first_session_id = created["body"]["data"]["session_id"]
            session_ids.append(first_session_id)
            click_tui_label(page, "Terminals")
            wait_for_terminal_text(page, "MCP audit · manual input excluded")
            wait_for_terminal_text(page, session_name, timeout_s=8)
            page.locator(".xterm-helper-textarea").focus()

            page_count = len(page.context.pages)
            second_name = f"ui-mouse-{os.getpid()}"
            page.keyboard.press("Alt+n")
            wait_for_terminal_text(page, "New persistent terminal")
            page.keyboard.type(second_name)
            page.keyboard.press("Enter")
            wait_for_terminal_text(page, second_name, timeout_s=8)
            assert len(page.context.pages) == page_count

            second_session_id = wait_for_terminal_session(page, second_name, timeout_s=10)
            session_ids.append(second_session_id)
            url_before_switch = page.url
            page.keyboard.press("Alt+ArrowLeft")
            wait_for_selected_terminal(page, second_name, timeout_s=8)
            assert page.url == url_before_switch
            click_tui_label(page, session_name, occurrence=-1)
            wait_for_selected_terminal(page, session_name, timeout_s=8)
            page.keyboard.press("Alt+ArrowLeft")
            wait_for_selected_terminal(page, second_name, timeout_s=8)

            page.keyboard.press("F8")
            wait_for_terminal_text(page, "RAW INPUT")
            page.keyboard.press("Alt+q")
            page.wait_for_timeout(500)
            assert page.locator("#connection-state strong").inner_text() == "Connected"
            wait_for_terminal_text(page, "RAW INPUT")
            page.keyboard.press("Alt+1")
            page.wait_for_timeout(500)
            assert "MCP audit · manual input excluded" in page.locator("body").inner_text()
            page.keyboard.press("F8")
            wait_for_terminal_text_absent(page, "RAW INPUT")
            wait_for_terminal_text(page, "Enter a command…")

            page.keyboard.type(r"printf 'INPUT-CLEAR-ONE\n'")
            page.keyboard.press("Enter")
            wait_for_terminal_output(page, second_session_id, "INPUT-CLEAR-ONE")
            wait_for_terminal_text(page, "INPUT-CLEAR-ONE")
            page.keyboard.type(r"printf 'INPUT-CLEAR-TWO\n'")
            page.keyboard.press("Enter")
            wait_for_terminal_output(page, second_session_id, "INPUT-CLEAR-TWO")
            wait_for_terminal_text(page, "INPUT-CLEAR-TWO")

            page.keyboard.type("seq -f 'SCROLL-LINE-%03g' 1 120")
            page.keyboard.press("Enter")
            wait_for_terminal_output(page, second_session_id, "SCROLL-LINE-120")
            wait_for_terminal_text(page, "SCROLL-LINE-120")
            initial_bottom_lines = visible_scroll_line_numbers(page)
            assert 120 in initial_bottom_lines, initial_bottom_lines
            page.keyboard.press("PageUp")
            page.keyboard.press("PageUp")
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                older_lines = visible_scroll_line_numbers(page)
                if older_lines and min(older_lines) < min(initial_bottom_lines) and 120 not in older_lines:
                    break
                page.wait_for_timeout(100)
            else:
                raise AssertionError(
                    f"PageUp did not reveal older output: {initial_bottom_lines!r}"
                )

            click_tui_label(page, f"SCROLL-LINE-{older_lines[-1]:03d}")
            page.mouse.wheel(0, -600)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                wheel_lines = visible_scroll_line_numbers(page)
                if wheel_lines and min(wheel_lines) < min(older_lines):
                    break
                page.wait_for_timeout(100)
            else:
                raise AssertionError(
                    f"Terminal mouse wheel did not reveal older output: {older_lines!r}"
                )
            page.keyboard.press("PageDown")
            page.keyboard.press("PageDown")
            page.keyboard.press("PageDown")
            wait_for_terminal_text(page, "SCROLL-LINE-120")

            before_freeze_bottom = visible_scroll_line_numbers(page)
            page.keyboard.press("PageUp")
            page.keyboard.press("PageUp")
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                frozen_lines = visible_scroll_line_numbers(page)
                if (
                    frozen_lines
                    and before_freeze_bottom
                    and min(frozen_lines) < min(before_freeze_bottom)
                    and 120 not in frozen_lines
                ):
                    break
                page.wait_for_timeout(100)
            else:
                raise AssertionError(
                    f"PageUp did not establish a frozen history view: {before_freeze_bottom!r}"
                )
            repeated = api_request(
                page,
                "/api/ui/terminals/send",
                "POST",
                {
                    "machine": "local",
                    "session_id": second_session_id,
                    "input_text": "for i in $(seq 1 40); do echo REPEAT-$((i % 2)); done; echo REPEAT-END",
                    "enter": True,
                },
            )
            assert repeated["status"] == 200, repeated
            wait_for_terminal_output(page, second_session_id, "REPEAT-END")
            page.wait_for_timeout(1_200)
            frozen_after_output = visible_scroll_line_numbers(page)
            assert frozen_after_output == frozen_lines, (frozen_lines, frozen_after_output)

            page.keyboard.press("PageDown")
            page.keyboard.press("PageDown")
            wait_for_terminal_text(page, "REPEAT-END")

            click_tui_label(page, "Todos")
            wait_for_terminal_text(page, "mouse todo second")
            click_tui_label(page, "mouse todo second")
            page.locator(".xterm-helper-textarea").focus()
            page.keyboard.press("p")
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                todo_state = api_request(page, "/api/ui/todos")
                priorities = {item["id"]: item["priority"] for item in todo_state["body"]["data"]["todos"]}
                if priorities.get("ui-smoke-second") == "high":
                    break
                page.wait_for_timeout(100)
            else:
                raise AssertionError(f"Todo mouse selection did not target the second row: {priorities}")
            assert priorities["ui-smoke-first"] == "medium"
            click_tui_label(page, "Open")
            wait_for_terminal_text(page, "OPEN")

            click_tui_label(page, "Audit")
            wait_for_terminal_text(page, "Audit records")
            wait_for_terminal_text(page, "audit-old-tool")
            click_tui_label(page, "audit-old-tool")
            wait_for_terminal_text(page, "audit-old-detail")
            click_tui_label(page, "24h")
            wait_for_terminal_text(page, "7d")

            for label, expected in [("Remotes", "Remote nodes"), ("Files", "Preview")]:
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
            wait_for_terminal_text(page, "Fil")
            wait_for_terminal_text(page, "Rem")

            for session_id in list(session_ids):
                killed = api_request(
                    page,
                    "/api/ui/terminals/kill",
                    "POST",
                    {"machine": "local", "session_id": session_id},
                )
                assert killed["status"] == 200, killed
                assert killed["body"]["data"]["killed"] is True, killed
                session_ids.remove(session_id)

            page.locator(".xterm-helper-textarea").focus()
            page.keyboard.press("Alt+q")
            page.locator("#connection-state").get_by_text("Disconnected").wait_for(timeout=5_000)
            page.wait_for_timeout(1_200)
            assert page.locator("#connection-state strong").inner_text() == "Disconnected"
        finally:
            if not page.is_closed():
                for session_id in session_ids:
                    with suppress(Exception):
                        api_request(
                            page,
                            "/api/ui/terminals/kill",
                            "POST",
                            {"machine": "local", "session_id": session_id},
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
