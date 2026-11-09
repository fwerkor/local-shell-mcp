"""Real React regression for a first launch with no model credentials."""
from __future__ import annotations

import asyncio
import socket

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route
from local_shell_mcp.main import _with_oauth_routes
from local_shell_mcp.settings import get_settings


@pytest.mark.asyncio
@pytest.mark.parametrize("reject_provider", [False, True])
async def test_first_launch_composer_can_type_and_model_settings_are_discoverable(tmp_path, monkeypatch, reject_provider):
    playwright = pytest.importorskip("playwright.async_api")
    import uvicorn
    for name in ("LOCAL_SHELL_MCP_MODEL_BASE_URL", "LOCAL_SHELL_MCP_MODEL_API_KEY", "LOCAL_SHELL_MCP_MODEL", "OPENAI_API_KEY", "OPENAI_BASE_URL", "ANTHROPIC_API_KEY", "GOOGLE_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_ENABLED", "true")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    requests = []
    async def fake_model(request):
        body = await request.json()
        requests.append(body)
        assert request.headers.get("authorization") == "Bearer private-test-token"
        if reject_provider:
            return JSONResponse({"error": {"message": "Invalid API key"}}, status_code=401)
        return StreamingResponse(iter(['data: {"choices":[{"delta":{"content":"Model channel works."}}]}\n\n', 'data: [DONE]\n\n']), media_type="text/event-stream")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        model_port = probe.getsockname()[1]
    model_server = uvicorn.Server(uvicorn.Config(Starlette(routes=[Route("/v1/chat/completions", fake_model, methods=["POST"])]), host="127.0.0.1", port=model_port, log_level="error", access_log=False))
    model_task = asyncio.create_task(model_server.serve())
    server = uvicorn.Server(uvicorn.Config(_with_oauth_routes(Starlette()), host="127.0.0.1", port=port, log_level="error", access_log=False))
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started: break
            await asyncio.sleep(.05)
        assert server.started
        async with playwright.async_playwright() as manager:
            browser = await manager.chromium.launch(headless=True)
            try:
                page = await browser.new_page(viewport={"width": 1280, "height": 800})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                await page.goto(f"http://127.0.0.1:{port}/c/new", wait_until="domcontentloaded")
                textarea = page.get_by_test_id("text-input")
                await textarea.fill("Keep my draft while I configure a model.", timeout=15000)
                assert await textarea.input_value() == "Keep my draft while I configure a model."
                await page.get_by_role("link", name="Channels & models / 渠道与模型").click()
                await page.get_by_role("heading", name="Channels & models / 渠道与模型").wait_for()
                await page.get_by_label("Model provider", exact=True).select_option("openai")
                await page.get_by_label("Model API base URL").fill(f"http://127.0.0.1:{model_port}/v1")
                await page.get_by_label("Model API key").fill("private-test-token")
                await page.get_by_label("Model identifiers").fill("first-model\nsecond-model")
                async with page.expect_response(lambda response: response.request.method == "PUT" and response.url.endswith("/api/lsm/providers")) as saved:
                    await page.get_by_role("button", name="Save model channel", exact=True).click()
                response = await saved.value
                assert response.status == 200, await response.text()
                assert "private-test-token" not in await response.text()
                await page.get_by_role("link", name="Start a new chat and select a model").click()
                await page.get_by_text("first-model", exact=True).first.wait_for(timeout=15000)
                await page.get_by_test_id("text-input").fill("Verify configured model.")
                await page.locator('button[type="submit"]').first.click()
                if reject_provider:
                    await page.get_by_text("Model generation failed (HTTPStatusError)", exact=False).first.wait_for(timeout=15000)
                else:
                    await page.get_by_text("Model channel works.", exact=True).wait_for(timeout=15000)
                if reject_provider:
                    await page.reload()
                    await page.get_by_text("Model generation failed (HTTPStatusError)", exact=False).first.wait_for(timeout=15000)
                assert requests and requests[-1]["model"] == "first-model"
                assert not errors, errors
            except Exception:
                print(await page.locator("body").inner_text())
                raise
            finally:
                await browser.close()
    finally:
        server.should_exit = True
        model_server.should_exit = True
        await asyncio.wait_for(asyncio.gather(task, model_task), timeout=10)
        get_settings.cache_clear()
