"""Retained React artifact editor persists through the original message endpoint."""
from __future__ import annotations

import asyncio
import re
import socket

import pytest
from starlette.applications import Starlette

from local_shell_mcp.main import _with_oauth_routes
from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui import generation_routes


@pytest.mark.asyncio
async def test_original_react_artifact_edit_and_reload(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.async_api")
    import uvicorn

    for key, value in {"WORKSPACE_ROOT": str(tmp_path), "STATE_DIR": str(tmp_path / ".local-shell-mcp"),
                       "AUTH_MODE": "none", "UI_ENABLED": "true", "REMOTE_ENABLED": "false",
                       "MODEL_BASE_URL": "http://127.0.0.1:11434/v1", "MODEL": "artifact-test-model"}.items():
        monkeypatch.setenv("LOCAL_SHELL_MCP_" + key, value)
    get_settings.cache_clear()

    async def generated(*_args, **_kwargs):
        yield ':::artifact{identifier="diagram" type="application/vnd.mermaid" title="Source diagram"}\n```mermaid\ngraph TD; A-->B\n```\n:::'

    monkeypatch.setattr(generation_routes, "stream_model_with_tools", generated)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(_with_oauth_routes(Starlette()), host="127.0.0.1", port=port, log_level="error", access_log=False))
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(.05)
        assert server.started
        async with playwright.async_playwright() as manager:
            try:
                browser = await manager.chromium.launch(headless=True)
            except playwright.Error as exc:
                if "Executable doesn't exist" in str(exc):
                    pytest.skip("Optional Chromium executable is not installed in this CI job")
                raise
            page = await browser.new_page(viewport={"width": 1440, "height": 900})
            external = []
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            async def local_only(route):
                if route.request.url.startswith((origin, "data:", "blob:")):
                    await route.continue_()
                else:
                    external.append(route.request.url)
                    await route.abort()

            await page.route("**/*", local_only)
            try:
                await page.goto(origin + "/c/new", wait_until="domcontentloaded")
                await page.get_by_test_id("text-input").fill("Create a diagram artifact.")
                await page.locator('button[type="submit"]').first.click()
                await page.get_by_text("Source diagram", exact=True).first.wait_for(timeout=15000)
                panel = page.locator("#artifact-viewer")
                try:
                    await panel.wait_for(timeout=5000)
                except playwright.TimeoutError:
                    await page.get_by_role("button", name=re.compile("Source diagram")).first.click()
                    await panel.wait_for(timeout=5000)
                await panel.get_by_role("radio", name="Code", exact=True).click()
                editor = panel.locator(".monaco-editor").get_by_role("textbox")
                await editor.wait_for(state="attached", timeout=20000)
                await editor.focus()
                await page.keyboard.press("ControlOrMeta+A")
                async with page.expect_response(lambda response: "/api/messages/artifact/" in response.url and response.request.method == "POST", timeout=15000) as saved:
                    await page.keyboard.insert_text("graph TD; A-->C")
                response = await saved.value
                assert response.status == 200, await response.text()
                assert "A-->C" in str(await response.json())
                await page.reload()
                await page.get_by_text("Source diagram", exact=True).first.wait_for(timeout=15000)
                try:
                    await panel.wait_for(timeout=5000)
                except playwright.TimeoutError:
                    await page.get_by_role("button", name=re.compile("Source diagram")).first.click()
                    await panel.wait_for(timeout=5000)
                await panel.get_by_role("radio", name="Code", exact=True).click()
                await panel.locator(".monaco-editor").get_by_role("textbox").wait_for()
                rendered = await panel.locator(".monaco-editor .view-lines").inner_text()
                assert "A-->C" in rendered.replace("\u00a0", " "), rendered
                assert not external, external
                assert not errors, errors
            except Exception:
                print("BODY", (await page.locator("body").inner_text())[-5000:])
                print("EXTERNAL", external)
                print("ERRORS", errors)
                raise
            finally:
                await browser.close()
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=15)
        get_settings.cache_clear()
