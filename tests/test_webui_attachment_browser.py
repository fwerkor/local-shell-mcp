"""Retained React upload and authenticated in-browser attachment deletion."""
from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import pytest
from starlette.applications import Starlette

from local_shell_mcp.main import _with_oauth_routes
from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import shared_database


@pytest.mark.asyncio
async def test_original_react_browser_upload_then_click_remove_file(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.async_api")
    import uvicorn

    for key, value in {"WORKSPACE_ROOT": str(tmp_path), "STATE_DIR": str(tmp_path / ".local-shell-mcp"),
                       "AUTH_MODE": "none", "UI_ENABLED": "true", "REMOTE_ENABLED": "false",
                       "MODEL_BASE_URL": "http://127.0.0.1:11434/v1", "MODEL": "attachment-test-model"}.items():
        monkeypatch.setenv("LOCAL_SHELL_MCP_" + key, value)
    get_settings.cache_clear()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    app = _with_oauth_routes(Starlette())
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                          lifespan="on", log_level="error", access_log=False))
    task = asyncio.create_task(server.serve())
    browser = None
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
                    pytest.skip("Chromium is not installed")
                raise
            page = await browser.new_page(viewport={"width": 1280, "height": 800})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.goto(origin + "/c/new", wait_until="domcontentloaded")
            await page.get_by_text("attachment-test-model").first.wait_for(timeout=15000)
            async with page.expect_response(lambda response: response.request.method == "POST"
                                            and response.url.endswith("/api/files")) as event:
                await page.locator('input[type="file"]').first.set_input_files({
                    "name": "browser-delete.txt", "mimeType": "text/plain",
                    "buffer": b"actual Chromium upload",
                })
            response = await event.value
            assert response.status == 200, await response.text()
            uploaded = await response.json()
            ident = uploaded["file_id"]
            with shared_database(get_settings().state_dir.resolve()).connect() as db:
                row = db.execute("SELECT path FROM attachments WHERE id=?", (ident,)).fetchone()
                assert row and Path(row["path"]).read_bytes() == b"actual Chromium upload"
            await page.get_by_text("browser-delete.txt", exact=True).first.wait_for(timeout=10000)
            # Click the retained React FileRow/RemoveFile control, not a
            # synthetic fetch. This exercises its debounce and mutation hook.
            async with page.expect_response(lambda response: response.request.method == "DELETE"
                                            and response.url.endswith("/api/files"), timeout=20000) as event:
                await page.get_by_role("button", name="Remove file").first.click()
            deleted = await event.value
            assert deleted.status == 200, await deleted.text()
            outcome = await deleted.json()
            assert outcome["deletedFileIds"] == [ident]
            with shared_database(get_settings().state_dir.resolve()).connect() as db:
                assert db.execute("SELECT 1 FROM attachments WHERE id=?", (ident,)).fetchone() is None
            assert not Path(row["path"]).exists()
            await page.reload()
            files = await page.evaluate("async () => (await (await fetch('/api/files')).json())")
            assert not any(value["file_id"] == ident for value in files)
            assert not errors, errors
    finally:
        if browser is not None:
            await browser.close()
        server.should_exit = True
        await asyncio.wait_for(task, timeout=15)
        get_settings.cache_clear()
