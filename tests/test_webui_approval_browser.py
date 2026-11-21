"""Source React tool-review panel: persisted pause, reload, reject, resume."""

from __future__ import annotations

import asyncio
import re
import socket

import pytest
from starlette.applications import Starlette

from local_shell_mcp.main import _with_oauth_routes
from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui import generation_routes
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig
from local_shell_mcp.webui.routes import _repo


@pytest.mark.asyncio
async def test_original_react_approval_panel_survives_reload_and_rejects_without_dispatch(
    tmp_path, monkeypatch,
):
    playwright = pytest.importorskip("playwright.async_api")
    import uvicorn

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_ENABLED", "true")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODEL_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODEL", "mock-review")
    get_settings.cache_clear()
    _repo().save_setting("local", "endpoints", {"agents": {"toolApproval": {
        "enabled": True, "ask": ["plan_manage"], "allow": ["session_manage"],
    }}})

    calls = []

    async def model(profile, history, *, tools, **kwargs):
        assert "plan_manage" in {tool["function"]["name"] for tool in tools}
        if history[-1].get("role") == "tool":
            calls.append(history[-1]["content"])
            assert history[-1]["tool_call_id"] == "review-plan"
            assert history[-1]["content"].startswith("Blocked: ")
            yield "Rejected tool did not execute."
        else:
            yield ModelToolCall("review-plan", "plan_manage", {"action": "list"})

    monkeypatch.setattr(generation_routes, "stream_model_with_tools", model)
    monkeypatch.setattr(generation_routes, "provider_config", lambda *_: ProviderConfig(
        "openai", "mock-review", "http://127.0.0.1:11434/v1/chat/completions", "",
    ))

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    app = _with_oauth_routes(Starlette())
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           lifespan="on", log_level="error", access_log=False))
    server_task = asyncio.create_task(server.serve())
    browser = None
    try:
        for _ in range(100):
            if server.started:
                break
            if server_task.done():
                raise RuntimeError("Server exited before browser")
            await asyncio.sleep(.05)
        assert server.started
        async with playwright.async_playwright() as manager:
            try:
                browser = await manager.chromium.launch(headless=True)
            except playwright.Error as exc:
                if "Executable doesn't exist" in str(exc):
                    pytest.skip("Chromium required by browser CI")
                raise
            page = await browser.new_page()
            errors, submissions = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda request: submissions.append(request.post_data_json)
                    if "/api/agents/chat/resume" in request.url and request.method == "POST" else None)

            agent_response = await page.request.post(f"http://127.0.0.1:{port}/api/agents", data={
                "name": "Approval Reviewer", "provider": "openAI",
                "model": "mock-review", "tools": ["plan_manage"],
            })
            assert agent_response.status == 201, await agent_response.text()
            agent_id = (await agent_response.json())["id"]
            conversation_response = await page.request.post(f"http://127.0.0.1:{port}/api/convos", data={
                "title": "Approval page", "endpoint": "agents",
                "agent_id": agent_id, "model": "mock-review",
            })
            assert conversation_response.status == 201
            cid = (await conversation_response.json())["conversationId"]
            await page.goto(f"http://127.0.0.1:{port}/c/{cid}", wait_until="domcontentloaded")
            await page.locator("textarea").first.wait_for(timeout=10000)
            await page.locator("textarea").first.fill("Review the proposed tool")
            await page.locator('button[type="submit"]').first.click()
            await page.get_by_role("button", name="Reject", exact=True).first.wait_for(timeout=15000)

            status = (await (await page.request.get(
                f"http://127.0.0.1:{port}/api/agents/chat/status/{cid}"
            )).json())
            assert status["status"] == "requires_action"
            assert status["pendingAction"]["payload"]["type"] == "tool_approval"
            assert status["pendingAction"]["payload"]["action_requests"][0]["tool_call_id"] == "review-plan"
            assert status["resumeState"]["pendingAction"] == status["pendingAction"]

            await page.reload(wait_until="domcontentloaded")
            await page.get_by_role("button", name="Reject", exact=True).first.wait_for(timeout=15000)
            await page.get_by_role("button", name="Reject", exact=True).first.click()
            await page.get_by_role("button", name=re.compile(r"^Continue$")).first.click()
            await page.get_by_text("Rejected tool did not execute.", exact=True).first.wait_for(timeout=20000)
            assert len(calls) == 1
            assert len(submissions) == 1
            assert submissions[0]["actionId"] == status["pendingAction"]["actionId"]
            assert submissions[0]["decisions"][0]["decision"] == "reject"
            assert submissions[0]["decisions"][0]["tool_call_id"] == "review-plan"
            await page.reload(wait_until="domcontentloaded")
            await page.get_by_text("Rejected tool did not execute.", exact=True).first.wait_for(timeout=15000)
            assert not errors, errors
    finally:
        if browser:
            await browser.close()
        server.should_exit = True
        await asyncio.wait_for(server_task, timeout=15)
        await generation_routes.shutdown_generations()
        get_settings.cache_clear()
