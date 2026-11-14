"""Original React steer chip and inline part after provider-safe interruption and reload."""

from __future__ import annotations

import asyncio
import socket

import pytest
from starlette.applications import Starlette

from local_shell_mcp.main import _with_oauth_routes
from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui import generation_routes
from local_shell_mcp.webui.providers import ProviderConfig


@pytest.mark.asyncio
async def test_original_react_applied_steer_survives_reload_and_reaches_model(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.async_api")
    import uvicorn

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_ENABLED", "true")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODEL_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODEL", "mock-steering")
    get_settings.cache_clear()

    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def provider(profile, history, *, tools, **kwargs):
        calls.append(list(history))
        if len(calls) == 1:
            started.set()
            await release.wait()
            yield "Old text before the instruction."
            yield "This old continuation must never reach the UI."
        else:
            assert history[-1].get("source") == "steer"
            assert history[-1]["content"].endswith("Change the task to review")
            yield "Steering accepted and applied."

    monkeypatch.setattr(generation_routes, "stream_model_with_tools", provider)
    monkeypatch.setattr(generation_routes, "provider_config", lambda *_: ProviderConfig(
        "openai", "mock-steering", "http://127.0.0.1:11434/v1/chat/completions", "",
    ))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(_with_oauth_routes(Starlette()),
                                          host="127.0.0.1", port=port, lifespan="on",
                                          log_level="error", access_log=False))
    server_task = asyncio.create_task(server.serve())
    browser = None
    try:
        for _ in range(100):
            if server.started:
                break
            if server_task.done():
                raise RuntimeError("Source React server stopped")
            await asyncio.sleep(0.05)
        assert server.started
        async with playwright.async_playwright() as manager:
            try:
                browser = await manager.chromium.launch(headless=True)
            except playwright.Error as exc:
                if "Executable doesn't exist" in str(exc):
                    pytest.skip("Chromium required for original React steering")
                raise
            page = await browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            created = await page.request.post(f"http://127.0.0.1:{port}/api/agents", data={
                "name": "Steering model", "provider": "openAI", "model": "mock-steering",
                "tools": ["plan_manage"],
            })
            assert created.status == 201, await created.text()
            agent_id = (await created.json())["id"]
            conversation = await page.request.post(f"http://127.0.0.1:{port}/api/convos", data={
                "title": "Steer a running generation", "endpoint": "agents",
                "agent_id": agent_id, "model": "mock-steering",
            })
            assert conversation.status == 201
            cid = (await conversation.json())["conversationId"]
            await page.goto(f"http://127.0.0.1:{port}/c/{cid}", wait_until="domcontentloaded")
            await page.locator("textarea").first.wait_for(timeout=10000)
            await page.locator("textarea").first.fill("Start the original task.")
            await page.locator('button[type="submit"]').first.click()
            await asyncio.wait_for(started.wait(), 10)
            status = await page.request.get(f"http://127.0.0.1:{port}/api/agents/chat/status/{cid}")
            assert status.status == 200
            created_at = (await status.json())["createdAt"]
            ack = await page.request.post(f"http://127.0.0.1:{port}/api/agents/chat/steer", data={
                "conversationId": cid, "generationCreatedAt": created_at,
                "clientSteerId": "browser-steer-id",
                "text": "Change the task to review", "preempt": True,
            })
            assert ack.status == 202, await ack.text()
            assert (await ack.json())["preempt"]
            release.set()
            try:
                await page.get_by_text("Steering accepted and applied.", exact=True).first.wait_for(timeout=10000)
            except playwright.Error as exc:
                snapshot = await (await page.request.get(
                    f"http://127.0.0.1:{port}/api/agents/chat/status/{cid}"
                )).json()
                raise AssertionError({
                    "status": snapshot, "calls": calls, "errors": errors,
                    "body": (await page.locator("body").inner_text())[-4000:],
                }) from exc
            receipt = page.get_by_test_id("steer-part")
            await receipt.first.wait_for(timeout=12000)
            assert await receipt.count() == 1
            assert "Change the task to review" in await receipt.first.inner_text()
            assert not await page.get_by_text(
                "This old continuation must never reach the UI.", exact=True,
            ).count()
            await page.reload(wait_until="domcontentloaded")
            await receipt.first.wait_for(timeout=15000)
            await page.get_by_text("Steering accepted and applied.", exact=True).first.wait_for(timeout=15000)
            assert await receipt.count() == 1
            assert "Change the task to review" in await receipt.first.inner_text()
            # React must preserve the SDK part sequence after page reload,
            # rather than fold the continuation back into the first text part.
            body_text = await page.locator("body").inner_text()
            old_pos = body_text.index("Old text before the instruction.")
            steer_pos = body_text.index("Change the task to review")
            new_pos = body_text.index("Steering accepted and applied.")
            assert old_pos < steer_pos < new_pos
            assert len(calls) == 2
            assert not errors, errors
    finally:
        release.set()
        if browser is not None:
            await browser.close()
        server.should_exit = True
        await asyncio.wait_for(server_task, 15)
        await generation_routes.shutdown_generations()
        get_settings.cache_clear()
