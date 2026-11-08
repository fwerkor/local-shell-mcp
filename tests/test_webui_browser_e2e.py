"""Real Chromium-to-React-to-Python-to-SQLite streaming-chat regression.

The browser dependency is optional at Controller startup. CI's browser matrix
installs it; source-only unit-test environments skip this integration test.
"""

from __future__ import annotations

import asyncio
import socket

import pytest
from starlette.applications import Starlette

from local_shell_mcp.main import _with_oauth_routes
from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui import generation_routes


@pytest.mark.asyncio
async def test_real_react_chat_uses_native_python_streaming_and_sqlite(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.async_api")
    import uvicorn

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_ENABLED", "true")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODEL_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODEL", "mock-test-model")
    monkeypatch.delenv("LOCAL_SHELL_MCP_STATE_BACKEND", raising=False)
    get_settings.cache_clear()

    async def generated_tokens(profile, messages, **_kwargs):
        assert profile.model == "mock-test-model"
        assert messages[-1]["content"] == "Verify Python streaming works."
        for chunk in ("Hello ", "from ", "the mocked model."):
            await asyncio.sleep(0.01)
            yield chunk

    monkeypatch.setattr(generation_routes, "stream_model", generated_tokens)
    app = _with_oauth_routes(Starlette())
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as port_probe:
        port_probe.bind(("127.0.0.1", 0))
        port = port_probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                          lifespan="on", log_level="error", access_log=False))
    task = asyncio.create_task(server.serve())
    browser = None
    try:
        for _ in range(100):
            if server.started:
                break
            if task.done():
                raise RuntimeError("WebUI test server exited prematurely")
            await asyncio.sleep(0.05)
        assert server.started
        async with playwright.async_playwright() as manager:
            browser = await manager.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1280, "height": 800})
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.goto(f"http://127.0.0.1:{port}/c/new", wait_until="domcontentloaded")
            await page.get_by_text("mock-test-model").first.wait_for(timeout=15_000)
            await page.locator("textarea").first.fill("Verify Python streaming works.")
            await page.locator('button[type="submit"]').first.click()
            await page.get_by_text("Hello from the mocked model.", exact=True).first.wait_for(timeout=15_000)
            assert not errors, errors
            assert "/c/" in page.url
            from local_shell_mcp.sqlite_store import shared_database

            db = shared_database(get_settings().state_dir.resolve())
            with db.connect() as connection:
                messages = connection.execute("SELECT role,text FROM messages ORDER BY created_at").fetchall()
                assert any(row["role"] == "user" and row["text"] == "Verify Python streaming works." for row in messages)
                assert any(row["role"] == "assistant" and row["text"] == "Hello from the mocked model." for row in messages)
                statuses = [row[0] for row in connection.execute("SELECT status FROM runs").fetchall()]
                assert "complete" in statuses
    finally:
        if browser is not None:
            await browser.close()
        server.should_exit = True
        await asyncio.wait_for(task, timeout=15)
        get_settings.cache_clear()
