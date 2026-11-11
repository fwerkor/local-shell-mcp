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
        expected_key = ({"independent-model": "secondary-private-token",
                         "recovered-model": "recovered-test-token"}.get(body["model"], "private-test-token"))
        assert request.headers.get("authorization") == "Bearer " + expected_key
        if reject_provider and body["model"] != "recovered-model":
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
                await page.get_by_test_id("model-selector-button").get_by_text("first-model", exact=True).wait_for(timeout=15000)
                await page.get_by_test_id("model-selector-button").click()
                await page.locator("#model-search").fill("second-model")
                await page.get_by_text("second-model", exact=True).first.click()
                await page.get_by_test_id("model-selector-button").get_by_text("second-model", exact=True).wait_for()
                await page.get_by_test_id("text-input").fill("Verify configured model.")
                await page.locator('button[type="submit"]').first.click()
                if reject_provider:
                    await page.get_by_test_id("screenshot-target").get_by_text("Model generation failed (HTTPStatusError)", exact=False).wait_for(timeout=15000)
                else:
                    await page.get_by_test_id("screenshot-target").get_by_text("Model channel works.", exact=True).wait_for(timeout=15000)
                if reject_provider:
                    await page.reload()
                    await page.get_by_test_id("screenshot-target").get_by_text("Model generation failed (HTTPStatusError)", exact=False).wait_for(timeout=15000)
                assert requests and requests[-1]["model"] == "second-model"
                if reject_provider:
                    # Correcting an invalid credential must recover without a
                    # server restart and without rewriting old conversations.
                    await page.get_by_role("link", name="Channels & models / 渠道与模型").click()
                    await page.get_by_label("Model API key").fill("recovered-test-token")
                    await page.get_by_label("Model identifiers").fill("recovered-model")
                    await page.get_by_role("button", name="Save model channel").click()
                    await page.get_by_role("link", name="Start a new chat and select a model").click()
                    await page.get_by_test_id("model-selector-button").get_by_text("recovered-model", exact=True).wait_for(timeout=15000)
                    await page.get_by_test_id("text-input").fill("Credential fixed.")
                    await page.locator('button[type="submit"]').first.click()
                    await page.get_by_test_id("screenshot-target").get_by_text("Model channel works.", exact=True).wait_for(timeout=15000)
                    assert requests[-1]["model"] == "recovered-model"
                if not reject_provider:
                    # Two OpenAI-compatible profiles with independent credentials
                    # must remain distinct through the actual original React
                    # model selector and Python streaming call, not just storage.
                    await page.get_by_role("link", name="Channels & models / 渠道与模型").click()
                    await page.get_by_role("button", name="Add named channel").click()
                    await page.get_by_label("Channel name").fill("Secondary Research")
                    await page.get_by_label("Model provider").select_option("openai")
                    await page.get_by_label("Model API base URL").fill(f"http://127.0.0.1:{model_port}/v1")
                    await page.get_by_label("Model API key").fill("secondary-private-token")
                    await page.get_by_label("Model identifiers").fill("independent-model")
                    async with page.expect_response(lambda response: response.request.method == "PUT" and response.url.endswith("/api/lsm/providers")) as named_saved:
                        await page.get_by_role("button", name="Save model channel").click()
                    named_response = await named_saved.value
                    assert named_response.status == 200, await named_response.text()
                    assert "secondary-private-token" not in await named_response.text()
                    inventory = await page.request.get(f"http://127.0.0.1:{port}/api/models")
                    assert (await inventory.json())["Secondary Research"] == ["independent-model"]
                    endpoint = await page.request.get(f"http://127.0.0.1:{port}/api/endpoints")
                    assert (await endpoint.json())["Secondary Research"]["type"] == "openAI"
                    await page.get_by_role("link", name="Start a new chat and select a model").click()
                    await page.get_by_test_id("model-selector-button").click()
                    await page.locator("#model-search").fill("independent-model")
                    await page.get_by_text("independent-model", exact=True).first.click()
                    await page.get_by_test_id("model-selector-button").get_by_text("independent-model", exact=True).wait_for(timeout=15000)
                    await page.get_by_test_id("text-input").fill("Verify secondary named channel.")
                    await page.locator('button[type="submit"]').first.click()
                    await page.get_by_test_id("screenshot-target").get_by_text("Model channel works.", exact=True).wait_for(timeout=15000)
                    assert requests[-1]["model"] == "independent-model"
                    # Agent authoring through the same browser login, save/reload
                    # and version evolution without exposing provider secrets.
                    agent = await page.request.post(f"http://127.0.0.1:{port}/api/agents", data={
                        "name": "Secondary Agent", "description": "Browser-created Agent",
                        "provider": "Secondary Research", "model": "independent-model",
                        "instructions": "Be concise.", "tools": ["ask_user_question"],
                        "model_parameters": {"maxTokens": 128, "topP": 0.75},
                    })
                    assert agent.status == 201, await agent.text()
                    agent_value = await agent.json()
                    assert "secondary-private-token" not in str(agent_value)
                    agent_id = agent_value["id"]
                    await page.reload()
                    saved_agent = await page.request.get(f"http://127.0.0.1:{port}/api/agents/{agent_id}")
                    assert (await saved_agent.json())["model_parameters"] == {"maxTokens": 128, "topP": 0.75}
                    assert (await saved_agent.json())["tools"] == ["ask_user_question"]
                    profiles = await page.request.get(f"http://127.0.0.1:{port}/api/lsm/providers")
                    payload = await profiles.json()
                    assert {p.get("name") for p in payload["providers"]} >= {"Secondary Research"}
                    assert "secondary-private-token" not in str(payload)
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
