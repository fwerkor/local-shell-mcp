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
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import Page, expect, sync_playwright

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


def wait_for_stable_scroll_lines(
    page: Page,
    predicate: Callable[[list[int]], bool],
    *,
    timeout_s: float = 8,
    stable_s: float = 0.25,
) -> list[int]:
    deadline = time.monotonic() + timeout_s
    candidate: list[int] | None = None
    stable_since = 0.0
    latest: list[int] = []
    while time.monotonic() < deadline:
        latest = visible_scroll_line_numbers(page)
        if predicate(latest):
            if latest == candidate:
                if time.monotonic() - stable_since >= stable_s:
                    return latest
            else:
                candidate = latest
                stable_since = time.monotonic()
        else:
            candidate = None
            stable_since = 0.0
        page.wait_for_timeout(50)
    raise AssertionError(f"Terminal scroll view did not stabilize: {latest!r}")


def click_tui_label(
    page: Page,
    label: str,
    occurrence: int = 0,
    *,
    rightmost: bool = False,
) -> None:
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
    row_index, column = max(matches, key=lambda match: match[1]) if rightmost else matches[occurrence]
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


def click_until_terminal_text(
    page: Page,
    label: str,
    expected: str,
    *,
    rightmost: bool = False,
    timeout_s: float = 10,
) -> None:
    deadline = time.monotonic() + timeout_s
    retry_interval_s = 0.75
    while time.monotonic() < deadline:
        clicked_at = time.monotonic()
        click_tui_label(page, label, rightmost=rightmost)
        while time.monotonic() - clicked_at < retry_interval_s:
            if expected in page.locator("body").inner_text():
                return
            page.wait_for_timeout(100)
    text = page.locator("body").inner_text()
    raise AssertionError(
        f"Clicking terminal label {label!r} did not reveal {expected!r}\n{text[-5000:]}"
    )


def wait_for_terminal_text_absent(page: Page, needle: str, timeout_s: float = 10) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if needle not in page.locator("body").inner_text():
            return
        page.wait_for_timeout(100)
    text = page.locator("body").inner_text()
    raise AssertionError(f"Terminal text still contained {needle!r}\n{text[-5000:]}")


def wait_for_terminal_output(
    page: Page,
    session_id: str,
    needle: str,
    timeout_s: float = 10,
    *,
    exact_line: bool = False,
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
        matched = (
            any(line.strip() == needle for line in output.splitlines())
            if exact_line
            else needle in output
        )
        if matched:
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
        page.on("pageerror", lambda error: print(f"Browser error: {error}", flush=True))
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
            wallpaper_background = page.locator(".console-wallpaper").evaluate(
                "element => getComputedStyle(element).backgroundImage"
            )
            assert wallpaper_background == "none", wallpaper_background
            terminal_background = page.locator("#terminal .xterm-viewport").evaluate(
                "element => getComputedStyle(element).backgroundColor"
            )
            assert terminal_background == "rgb(17, 17, 17)", terminal_background

            bootstrap = api_request(page, "/api/ui/bootstrap")
            assert bootstrap["status"] == 200, bootstrap
            version_info = bootstrap["body"]["data"]["version"]
            displayed_version = version_info.get("version") or version_info.get("package_version")
            assert displayed_version, version_info
            wait_for_terminal_text(page, "System health")
            wait_for_terminal_text(page, f"LSM v{displayed_version}")
            dashboard = api_request(page, "/api/ui/dashboard")
            assert dashboard["status"] == 200, dashboard
            assert dashboard["body"]["data"]["health"] in {"healthy", "attention", "critical"}
            import runpy

            native_smoke = runpy.run_path(str(ROOT / "scripts/ui-native-smoke.py"))
            native_smoke["check_native_webui"](page)
            click_tui_label(page, "Files")
            wait_for_terminal_text(page, "mouse-second.txt")
            click_until_terminal_text(
                page,
                "mouse-second.txt",
                "Selected · mouse-second.txt",
                rightmost=True,
            )

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
            wait_for_terminal_text(page, "INPUT-CLEAR-ONE")
            page.keyboard.press("Enter")
            wait_for_terminal_output(
                page,
                second_session_id,
                "INPUT-CLEAR-ONE",
                exact_line=True,
            )
            wait_for_terminal_text(page, "Enter a command…")
            page.keyboard.type(r"printf 'INPUT-CLEAR-TWO\n'")
            wait_for_terminal_text(page, "INPUT-CLEAR-TWO")
            page.keyboard.press("Enter")
            wait_for_terminal_output(
                page,
                second_session_id,
                "INPUT-CLEAR-TWO",
                exact_line=True,
            )
            wait_for_terminal_text(page, "Enter a command…")

            page.keyboard.type("seq -f 'SCROLL-LINE-%03g' 1 120")
            wait_for_terminal_text(page, "SCROLL-LINE-%03g")
            page.keyboard.press("Enter")
            wait_for_terminal_output(
                page,
                second_session_id,
                "SCROLL-LINE-120",
                exact_line=True,
            )
            wait_for_terminal_text(page, "Enter a command…")
            wait_for_terminal_text(page, "SCROLL-LINE-120")
            initial_bottom_lines = visible_scroll_line_numbers(page)
            assert 120 in initial_bottom_lines, initial_bottom_lines
            page.keyboard.press("PageUp")
            page.keyboard.press("PageUp")
            older_lines = wait_for_stable_scroll_lines(
                page,
                lambda lines: bool(lines)
                and min(lines) < min(initial_bottom_lines)
                and 120 not in lines,
            )

            click_tui_label(page, f"SCROLL-LINE-{older_lines[-1]:03d}")
            page.mouse.wheel(0, -600)
            wait_for_stable_scroll_lines(
                page,
                lambda lines: bool(lines) and min(lines) < min(older_lines),
            )
            page.keyboard.press("PageDown")
            page.keyboard.press("PageDown")
            page.keyboard.press("PageDown")
            wait_for_terminal_text(page, "SCROLL-LINE-120")

            before_freeze_bottom = visible_scroll_line_numbers(page)
            page.keyboard.press("PageUp")
            page.keyboard.press("PageUp")
            frozen_lines = wait_for_stable_scroll_lines(
                page,
                lambda lines: bool(lines)
                and bool(before_freeze_bottom)
                and min(lines) < min(before_freeze_bottom)
                and 120 not in lines,
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

            assert page.evaluate("!matchMedia('(pointer: coarse)').matches")
            page.dispatch_event(
                "#keyboard-button",
                "pointerdown",
                {"pointerType": "touch", "bubbles": True},
            )
            page.dispatch_event("#keyboard-button", "click")
            first_hybrid_keyboard_tap = page.evaluate(
                """(() => {
                    const textarea = document.querySelector('.xterm-helper-textarea')
                    return {
                        readOnly: textarea.readOnly,
                        inputMode: textarea.inputMode,
                        pressed: document.querySelector('#keyboard-button').getAttribute('aria-pressed')
                    }
                })()"""
            )
            assert first_hybrid_keyboard_tap == {
                "readOnly": False,
                "inputMode": "text",
                "pressed": "true",
            }
            page.dispatch_event(
                "#touchbar [data-key='escape']",
                "pointerdown",
                {"pointerType": "touch", "bubbles": True},
            )
            page.dispatch_event("#touchbar [data-key='escape']", "click")
            enabled_shortcut_touch = page.evaluate(
                """(() => {
                    const textarea = document.querySelector('.xterm-helper-textarea')
                    return {
                        readOnly: textarea.readOnly,
                        inputMode: textarea.inputMode,
                        active: document.activeElement === textarea,
                        pressed: document.querySelector('#keyboard-button').getAttribute('aria-pressed')
                    }
                })()"""
            )
            assert enabled_shortcut_touch == {
                "readOnly": False,
                "inputMode": "text",
                "active": True,
                "pressed": "true",
            }

            page.dispatch_event(
                "#keyboard-button",
                "pointerdown",
                {"pointerType": "touch", "bubbles": True},
            )
            page.dispatch_event("#keyboard-button", "click")
            second_hybrid_keyboard_tap = page.evaluate(
                """(() => {
                    const textarea = document.querySelector('.xterm-helper-textarea')
                    return {
                        readOnly: textarea.readOnly,
                        inputMode: textarea.inputMode,
                        pressed: document.querySelector('#keyboard-button').getAttribute('aria-pressed')
                    }
                })()"""
            )
            assert second_hybrid_keyboard_tap == {
                "readOnly": True,
                "inputMode": "none",
                "pressed": "false",
            }

            page.dispatch_event(
                "#touchbar [data-key='escape']",
                "pointerdown",
                {"pointerType": "touch", "bubbles": True},
            )
            page.dispatch_event("#touchbar [data-key='escape']", "click")
            hybrid_shortcut_touch = page.evaluate(
                """(() => {
                    const textarea = document.querySelector('.xterm-helper-textarea')
                    return {
                        readOnly: textarea.readOnly,
                        inputMode: textarea.inputMode,
                        active: document.activeElement === textarea
                    }
                })()"""
            )
            assert hybrid_shortcut_touch == {
                "readOnly": True,
                "inputMode": "none",
                "active": False,
            }

            page.dispatch_event(
                "#terminal",
                "pointerdown",
                {"pointerType": "touch", "bubbles": True},
            )
            hybrid_touch = page.evaluate(
                """(() => {
                    const textarea = document.querySelector('.xterm-helper-textarea')
                    return {readOnly: textarea.readOnly, inputMode: textarea.inputMode}
                })()"""
            )
            assert hybrid_touch == {"readOnly": True, "inputMode": "none"}
            page.dispatch_event(
                "#terminal",
                "pointerdown",
                {"pointerType": "mouse", "bubbles": True},
            )
            hybrid_mouse = page.evaluate(
                """(() => {
                    const textarea = document.querySelector('.xterm-helper-textarea')
                    return {readOnly: textarea.readOnly, inputMode: textarea.inputMode}
                })()"""
            )
            assert hybrid_mouse == {"readOnly": False, "inputMode": "text"}

            page.dispatch_event(
                "#touchbar [data-key='tab']",
                "pointerdown",
                {"pointerType": "touch", "bubbles": True},
            )
            page.dispatch_event("#touchbar [data-key='tab']", "click")
            first_shortcut_after_mouse = page.evaluate(
                """(() => {
                    const textarea = document.querySelector('.xterm-helper-textarea')
                    return {
                        readOnly: textarea.readOnly,
                        inputMode: textarea.inputMode,
                        active: document.activeElement === textarea
                    }
                })()"""
            )
            assert first_shortcut_after_mouse == {
                "readOnly": True,
                "inputMode": "none",
                "active": False,
            }

            mobile_context = browser.new_context(
                viewport={"width": 390, "height": 844},
                has_touch=True,
                is_mobile=True,
            )
            mobile_page = mobile_context.new_page()
            touch_escape_frames: list[str | bytes] = []
            mobile_page.on("websocket", lambda ws: ws.on("framesent", lambda frame: touch_escape_frames.append(frame) if frame in ("\x1b", b"\x1b") else None))
            try:
                mobile_page.goto(f"{origin}/ui", wait_until="networkidle")
                mobile_page.locator("#login-button").click()
                mobile_page.wait_for_url("**/oauth/authorize**")
                mobile_page.get_by_role("button", name="Approve").click()
                mobile_page.wait_for_url("**/ui")
                mobile_page.locator("#connection-state").get_by_text("Connected").wait_for(timeout=15_000)
                mobile_page.locator("#terminal").tap(position={"x": 40, "y": 80})
                mobile_page.wait_for_timeout(100)
                locked = mobile_page.evaluate(
                    """(() => {
                        const textarea = document.querySelector('.xterm-helper-textarea')
                        return {
                            readOnly: textarea.readOnly,
                            inputMode: textarea.inputMode,
                            active: document.activeElement === textarea,
                            pressed: document.querySelector('#keyboard-button').getAttribute('aria-pressed')
                        }
                    })()"""
                )
                assert locked == {
                    "readOnly": True,
                    "inputMode": "none",
                    "active": False,
                    "pressed": "false",
                }, locked

                mobile_page.locator("#keyboard-button").tap()
                enabled = mobile_page.evaluate(
                    """(() => {
                        const textarea = document.querySelector('.xterm-helper-textarea')
                        return {
                            readOnly: textarea.readOnly,
                            inputMode: textarea.inputMode,
                            active: document.activeElement === textarea,
                            pressed: document.querySelector('#keyboard-button').getAttribute('aria-pressed')
                        }
                    })()"""
                )
                assert enabled == {
                    "readOnly": False,
                    "inputMode": "text",
                    "active": True,
                    "pressed": "true",
                }, enabled

                mobile_page.locator("#keyboard-button").tap()
                assert mobile_page.locator("#keyboard-button").get_attribute("aria-pressed") == "false"
                assert mobile_page.evaluate(
                    "document.activeElement !== document.querySelector('.xterm-helper-textarea')"
                )

                mobile_page.dispatch_event(
                    "#terminal",
                    "pointerdown",
                    {"pointerType": "mouse", "bubbles": True},
                )
                coarse_pointer_mouse = mobile_page.evaluate(
                    """(() => {
                        const textarea = document.querySelector('.xterm-helper-textarea')
                        return {readOnly: textarea.readOnly, inputMode: textarea.inputMode}
                    })()"""
                )
                assert coarse_pointer_mouse == {"readOnly": False, "inputMode": "text"}

                for touch_width in (640, 1024):
                    mobile_page.set_viewport_size({"width": touch_width, "height": 480})
                    mobile_page.locator("#terminal").tap(position={"x":40,"y":40})
                    expect(mobile_page.locator("#keyboard-button")).to_be_visible()
                    mobile_page.locator("#keyboard-button").tap()
                    assert mobile_page.locator("#keyboard-button").get_attribute("aria-pressed") == "true"
                    assert mobile_page.locator("#terminal textarea").evaluate("element => !element.readOnly")
                    mobile_page.locator("#keyboard-button").tap()
                    if touch_width == 640:
                        escape_count = len(touch_escape_frames)
                        mobile_page.locator("#fullscreen-button").tap()
                        mobile_page.wait_for_function(
                            "document.fullscreenElement?.id === 'console-view'"
                        )
                        mobile_page.locator(".navigation-toggle:visible").tap()
                        mobile_page.wait_for_function("document.fullscreenElement === null")
                        expect(mobile_page.locator("#navigation")).to_be_visible()
                        expect(mobile_page.locator("#navigation .nav-item").first).to_be_focused()
                        mobile_page.keyboard.press("Escape")
                        expect(mobile_page.locator("#navigation")).to_be_hidden()
                        expect(mobile_page.locator(".navigation-toggle:visible")).to_be_focused()
                        mobile_page.wait_for_timeout(100)
                        assert len(touch_escape_frames) == escape_count, "Drawer Escape reached remote TUI"
                        screenshots = Path(os.getenv("LSM_UI_SCREENSHOTS", "/tmp/lsm-incus-ui-screenshots"))
                        screenshots.mkdir(parents=True, exist_ok=True)
                        mobile_page.screenshot(path=str(screenshots / "tui-touch-landscape.png"), animations="disabled")
            finally:
                mobile_context.close()

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
