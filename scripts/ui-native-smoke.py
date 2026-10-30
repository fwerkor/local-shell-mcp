"""Native React WebUI checks, run with the isolated server from ui-smoke.py."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from threading import Thread

from playwright.sync_api import Page, expect
from websockets.sync.server import serve


def check_native_webui(page: Page) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    artifacts = Path(os.getenv("LSM_UI_SCREENSHOTS", "/tmp/lsm-incus-ui-screenshots"))
    artifacts.mkdir(parents=True, exist_ok=True)

    def capture(name: str) -> None:
        expect(page.locator(".native-toast.visible")).to_have_count(0, timeout=7000)
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(artifacts / name), full_page="dialog" not in name, animations="disabled")
    page.locator('[data-interface-mode="web"]').click()
    expect(page.locator(".overview-metrics")).to_be_visible()
    expect(page.locator("#page-title")).to_have_text("Overview")
    capture("overview-desktop.png")

    # The isolated CI server has no graphical session. Exercise the browser's
    # real JPEG/WebSocket/input pipeline against a deterministic window fixture.
    jpeg = base64.b64decode(page.evaluate("""() => {
        const canvas = document.createElement('canvas'); canvas.width = 960; canvas.height = 540;
        const ctx = canvas.getContext('2d'); ctx.fillStyle = '#f2f2f2'; ctx.fillRect(0,0,960,540);
        ctx.fillStyle = '#292929'; ctx.fillRect(0,0,960,40);
        ctx.fillStyle = '#fff'; ctx.font = '16px sans-serif'; ctx.fillText('Desktop stream test window',20,26);
        ctx.fillStyle = '#262626'; ctx.font = '24px sans-serif'; ctx.fillText('WebSocket display and input',40,110);
        return canvas.toDataURL('image/jpeg').split(',')[1];
    }"""))
    actions: list[dict] = []
    page.route("**/api/ui/gui/windows?*", lambda route: route.fulfill(json={
        "ok": True, "data": {"machine":"local", "backend":"test-stream", "windows":[
            {"id":"test-window", "title":"Desktop stream test window", "bounds":{"x":0,"y":0,"width":960,"height":540}}
        ]}
    }))

    def desktop_socket(ws):
        def frame():
            ws.send(json.dumps({"type":"frame", "bounds":{"x":0,"y":0,"width":960,"height":540},
                "observation_id":"test-observation", "ttl_s":600, "coordinate_input":True, "image":True}))
            ws.send(jpeg)

        def received(raw):
            message = json.loads(raw)
            if message["type"] == "refresh":
                frame()
            elif message["type"] == "action":
                actions.append(message)
                ws.send(json.dumps({"type":"action-ack", "request_id":message["request_id"], "ok":True}))
        frame()
        for raw in ws:
            received(raw)

    fixture_server = serve(desktop_socket, "127.0.0.1", 0, subprotocols=["lsm-ui"])
    fixture_thread = Thread(target=fixture_server.serve_forever, daemon=True)
    fixture_thread.start()
    fixture_port = fixture_server.socket.getsockname()[1]
    page.evaluate("""port => {
        const Original = window.WebSocket;
        window.__originalWebSocket = Original;
        window.WebSocket = class extends Original {
            constructor(url, protocols) {
                super(String(url).includes('/ui/ws/desktop') ? 'ws://127.0.0.1:' + port : url, protocols);
            }
        };
    }""", fixture_port)

    try:
        for view, selector in [
            ("files", ".explorer-host"),
            ("sessions", ".sessions-layout"),
            ("remotes", ".remotes-page"),
            ("audit", ".audit-page"),
            ("desktop", ".desktop-page"),
            ("terminals", ".terminals-page"),
        ]:
            page.locator(f'.nav-item[data-view="{view}"]').click()
            expect(page.locator(selector)).to_be_visible()
            page.wait_for_timeout(200)
            if view == "files":
                centers = page.locator(".explorer-head").evaluate("""head =>
                    [...head.querySelectorAll('[data-role=machine], [data-action=up], [data-role=location], [data-action=go], .native-toggle, [data-action=refresh], [data-action=upload]')]
                        .map(element => { const rect = element.getBoundingClientRect(); return rect.top + rect.height / 2; })""")
                assert max(centers) - min(centers) < 1, centers
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), view
            capture(f"{view}-desktop.png")

        page.locator('.nav-item[data-view="desktop"]').click()
        expect(page.locator('[data-role="desktop-frame"]')).to_be_visible()
        expect(page.locator('[data-role="desktop-connection"]')).to_contain_text("Live")
        page.locator('[data-role="desktop-frame"]').click(position={"x":100,"y":100})
        page.wait_for_timeout(650)
        assert any(item["action"]["type"] == "click" for item in actions), actions
        page.locator('[data-action="desktop-scale-mode"]').click()
        expect(page.locator('[data-role="desktop-stage"]')).to_have_attribute("data-scale", "actual")
        page.locator('[data-action="desktop-scale-mode"]').click()
        page.locator('[data-action="desktop-fullscreen"]').click()
        page.wait_for_function("document.fullscreenElement !== null")
        page.locator('[data-action="desktop-fullscreen"]').click()
        page.wait_for_function("document.fullscreenElement === null")
        page.locator('[data-role="desktop-text"]').fill("Desktop input test")
        page.locator('[data-role="desktop-text"]').press("Enter")
        page.wait_for_timeout(100)
        assert any(item["action"].get("text") == "Desktop input test" for item in actions), actions
        capture("desktop-connected.png")
        page.locator('.nav-item[data-view="terminals"]').click()

        page.locator('.nav-item[data-view="sessions"]').click()
        page.locator('[data-action="new-session"]').click()
        session_dialog = page.get_by_role("dialog")
        session_dialog.get_by_label("Label", exact=True).fill("WebUI verification")
        session_dialog.get_by_label("Prompt", exact=True).fill("Verify terminal interaction, inspect audit records, and check the responsive layouts.")
        session_dialog.get_by_role("button", name="Create session", exact=True).click()
        expect(page.locator('[data-role="session-title"]')).to_contain_text("WebUI verification")
        capture("sessions-desktop.png")
        page.locator('.nav-item[data-view="audit"]').click()
        audit_record = page.locator(".audit-table tbody tr").filter(has_text="audit-new-tool").first
        expect(audit_record).to_be_visible()
        audit_record.click()
        expect(page.locator(".audit-detail-panel")).to_contain_text("audit-new-detail")
        capture("audit-desktop.png")
        page.locator('.nav-item[data-view="terminals"]').click()

        page.locator('[data-action="new-session"]').click()
        dialog = page.get_by_role("dialog")
        expect(dialog).to_be_visible()
        expect(dialog.get_by_label("Name", exact=True)).to_be_focused()
        # Canonical modal must trap focus and restore it when dismissed.
        page.keyboard.press("Shift+Tab")
        assert dialog.evaluate("element => element.contains(document.activeElement)")
        page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)
        expect(page.locator('[data-action="new-session"]')).to_be_focused()

        page.locator('[data-action="new-session"]').click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_label("Name", exact=True).fill("native-react-smoke")
        bounds = dialog.bounding_box()
        assert bounds is not None
        viewport = page.viewport_size
        assert viewport is not None
        assert abs(bounds["x"] + bounds["width"] / 2 - viewport["width"] / 2) < 2
        capture("terminal-create-dialog.png")
        dialog.get_by_role("button", name="Start terminal", exact=True).click()
        expect(page.locator('[data-role="connection"]')).to_contain_text("Connected", timeout=15000)
        expect(page.locator('[data-role="command-form"]')).to_have_count(0)
        page.locator(".persistent-terminal .xterm-helper-textarea").focus()
        page.keyboard.type("printf 'NATIVE-%s\\n' 'REACT-SMOKE'; pwd; ls -lah")
        page.keyboard.press("Enter")
        expect(page.locator(".persistent-terminal .xterm-rows")).to_contain_text("NATIVE-REACT-SMOKE", timeout=10000)
        capture("terminal-connected.png")
        page.locator('[data-action="reconnect"]').click()
        expect(page.locator('[data-role="connection"]')).to_contain_text("Connected", timeout=15000)

        for width in (768, 390):
            page.set_viewport_size({"width": width, "height": 844})
            for view in ("overview", "files", "terminals", "desktop", "sessions", "remotes", "audit"):
                page.locator(".navigation-toggle:visible").click()
                expect(page.locator("#navigation")).to_be_visible()
                expect(page.locator(".navigation-toggle:visible")).to_have_attribute("aria-expanded", "true")
                page.locator(f'.nav-item[data-view="{view}"]').click()
                expect(page.locator("#page-title")).to_have_text(view.title())
                expect(page.locator("#navigation")).to_be_hidden()
                page.wait_for_timeout(150)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (view, width)
                if width == 390 and view == "terminals":
                    keys = page.locator(".terminal-touchbar")
                    expect(keys).to_be_visible()
                    metrics = keys.evaluate("""bar => ({
                        width: bar.clientWidth, content: bar.scrollWidth,
                        buttons: [...bar.querySelectorAll('button')].map(button => ({
                            width: button.clientWidth, content: button.scrollWidth,
                            height: button.getBoundingClientRect().height,
                            foreground: getComputedStyle(button).color,
                            background: getComputedStyle(button).backgroundColor
                        }))
                    })""")
                    assert metrics["content"] <= metrics["width"], metrics
                    assert all(button["height"] >= 44 and button["content"] <= button["width"] for button in metrics["buttons"]), metrics
                    assert all(button["foreground"] != button["background"] for button in metrics["buttons"]), metrics
                    page.locator(".persistent-terminal .xterm-helper-textarea").focus()
                    page.keyboard.type("printf 'TOUCH-%s\\n' 'KEYS'")
                    page.locator('[data-terminal-key="enter"]').click()
                    expect(page.locator(".persistent-terminal .xterm-rows")).to_contain_text("TOUCH-KEYS", timeout=10000)
                if width == 390:
                    capture(f"{view}-mobile.png")
            page.locator(".navigation-toggle:visible").click()
            if width == 390:
                capture("navigation-mobile.png")
            page.keyboard.press("Escape")
            expect(page.locator("#navigation")).to_be_hidden()
            expect(page.locator(".navigation-toggle:visible")).to_be_focused()

        page.set_viewport_size({"width": 1440, "height": 900})
        page.locator('.nav-item[data-view="terminals"]').click()
        page.locator('[data-action="kill-session"]').click()
        page.get_by_role("dialog").get_by_role("button", name="Kill session", exact=True).click()
        expect(page.get_by_role("dialog")).to_have_count(0)
        page.locator('[data-interface-mode="tui"]').click()
        expect(page.locator("#connection-state")).to_contain_text("Connected", timeout=15000)
        assert not errors, errors
    finally:
        page.evaluate("() => { window.WebSocket = window.__originalWebSocket; }")
        fixture_server.shutdown()
        fixture_thread.join(timeout=2)
