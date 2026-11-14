"""Real original React OAuth result routes against LSM's Python SPA server."""
from __future__ import annotations

import asyncio
import os
import socket

import pytest
from starlette.applications import Starlette

from local_shell_mcp.main import _with_oauth_routes
from local_shell_mcp.settings import get_settings


@pytest.mark.asyncio
async def test_original_react_action_oauth_success_and_error_routes(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.async_api")
    import uvicorn

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_ENABLED", "true")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(_with_oauth_routes(Starlette()),
        host="127.0.0.1", port=port, lifespan="on", access_log=False, log_level="error"))
    task = asyncio.create_task(server.serve())
    browser = None
    try:
        for _ in range(80):
            if server.started:
                break
            if task.done():
                raise RuntimeError("OAuth browser test server stopped")
            await asyncio.sleep(.05)
        assert server.started
        async with playwright.async_playwright() as manager:
            launch = {"headless": True}
            if binary := os.environ.get("LSM_ACTION_CHROMIUM_BINARY"):
                launch.update(executable_path=binary, args=["--no-sandbox"])
            try:
                browser = await manager.chromium.launch(**launch)
            except playwright.Error as exc:
                if "Executable doesn't exist" in str(exc):
                    pytest.skip("Chromium is required in browser CI")
                raise
            context = await browser.new_context()
            page = await context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.goto(f"http://127.0.0.1:{port}/oauth/success?serverName=Action", wait_until="domcontentloaded")
            success = page.get_by_role("heading", level=1)
            await success.wait_for(timeout=12000)
            assert "success" in (await success.inner_text()).lower()
            assert "Action" in (await page.locator("body").inner_text())
            await page.goto(f"http://127.0.0.1:{port}/oauth/error?error=invalid_state", wait_until="domcontentloaded")
            failed = page.get_by_role("heading", level=1)
            await failed.wait_for(timeout=12000)
            assert "fail" in (await failed.inner_text()).lower()
            assert "state" in (await page.locator("body").inner_text()).lower()
            # The original ToolCall opens the IdP with noopener, so a popup
            # cannot address the chat tab through window.opener. Confirm that
            # the public Action completion signal crosses tabs directly.
            await page.evaluate("""() => {
              window.__oauthCompletion = null;
              window.__oauthChannel = new BroadcastChannel('lsm-action-oauth');
              window.__oauthChannel.onmessage = event => { window.__oauthCompletion = event.data; };
            }""")
            success_tab = await context.new_page()
            try:
                await success_tab.goto(
                    f"http://127.0.0.1:{port}/oauth/success?serverName=Action&actionId=test-action",
                    wait_until="domcontentloaded",
                )
                await page.wait_for_function(
                    "window.__oauthCompletion?.actionId === 'test-action'", timeout=12000,
                )
                received = await page.evaluate("window.__oauthCompletion")
                assert received == {"type": "action_oauth_complete", "actionId": "test-action"}
            finally:
                await success_tab.close()
                await page.evaluate("window.__oauthChannel.close()")
            assert not errors, errors
    finally:
        if browser is not None:
            await browser.close()
        server.should_exit = True
        await asyncio.wait_for(task, timeout=15)
        get_settings.cache_clear()
