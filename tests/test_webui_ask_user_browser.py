"""Original React batched Ask User interaction against the Python runtime."""
import asyncio
import json
import re
import socket

import pytest
from starlette.applications import Starlette

from local_shell_mcp.main import _with_oauth_routes
from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui import generation_routes
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_mode", ["ask", "native"])
async def test_original_react_batched_questions_submit_answers_by_id(tmp_path, monkeypatch, tool_mode):
    playwright = pytest.importorskip("playwright.async_api")
    import uvicorn

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_ENABLED", "true")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODEL_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODEL", "mock-test-model")
    get_settings.cache_clear()
    if tool_mode == "native":
        from local_shell_mcp.webui.routes import _repo

        _repo().save_setting("local", "agent.machine_policy.global", {"local": "read"})
        (tmp_path / "trace.txt").write_text("Native trace sample", encoding="utf-8")
    answers = []
    async def provider(profile, history, *, tools, **kwargs):
        if tool_mode == "native":
            assert "file_read" in {tool["function"]["name"] for tool in tools}
            if history[-1]["role"] == "tool":
                assert "Native trace sample" in history[-1]["content"]
                yield "Native tool result retained."
            else:
                yield ModelToolCall("native-trace", "file_read", {"path": "trace.txt"})
            return
        assert "ask_user_question" in {tool["function"]["name"] for tool in tools}
        if history[-1]["role"] == "tool":
            answers.append(json.loads(history[-1]["content"]))
            yield "Batch answers received correctly."
        else:
            yield ModelToolCall("ask-batch", "ask_user_question", {"questions": [
                {"id": "file", "header": "File", "question": "Which file?",
                 "options": [{"label": "README", "value": "README.md"}]},
                {"id": "format", "header": "Format", "question": "Which format?",
                 "options": [{"label": "JSON", "value": "json"}]},
            ]})
    monkeypatch.setattr(generation_routes, "stream_model_with_tools", provider)
    monkeypatch.setattr(generation_routes, "provider_config", lambda *_: ProviderConfig(
        "openai", "mock-test-model", "http://127.0.0.1:11434/v1/chat/completions", ""))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(_with_oauth_routes(Starlette()),
        host="127.0.0.1", port=port, lifespan="on", log_level="error", access_log=False))
    task = asyncio.create_task(server.serve())
    browser = None
    try:
        for _ in range(100):
            if server.started:
                break
            if task.done():
                raise RuntimeError("Test server stopped")
            await asyncio.sleep(0.05)
        assert server.started
        async with playwright.async_playwright() as manager:
            try:
                browser = await manager.chromium.launch(headless=True)
            except playwright.Error as exc:
                if "Executable doesn't exist" in str(exc):
                    pytest.skip("Chromium is required in browser CI")
                raise
            page = await browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            requests = []
            page.on("request", lambda request: requests.append(request.post_data_json) if "/api/agents/chat" in request.url and request.method == "POST" else None)
            agent = await page.request.post(f"http://127.0.0.1:{port}/api/agents", data={
                "name": "Source Ask User", "provider": "openAI", "model": "mock-test-model",
                "tools": ["ask_user_question" if tool_mode == "ask" else "file_read"]})
            assert agent.status == 201
            agent_id = (await agent.json())["id"]
            conversation = await page.request.post(f"http://127.0.0.1:{port}/api/convos", data={
                "title": "Batched source question", "endpoint": "agents", "agent_id": agent_id,
                "model": "mock-test-model"})
            assert conversation.status == 201
            cid = (await conversation.json())["conversationId"]
            await page.goto(f"http://127.0.0.1:{port}/c/{cid}", wait_until="domcontentloaded")
            try:
                await page.locator("textarea").first.wait_for(timeout=10000)
            except playwright.Error as exc:
                raise AssertionError({"errors": errors, "body": await page.locator("body").inner_text()}) from exc
            await page.locator("textarea").first.fill("Ask me two related questions.")
            await page.locator('button[type="submit"]').first.click()
            if tool_mode == "native":
                await page.get_by_text("Native tool result retained.", exact=True).first.wait_for(timeout=15000)
                await page.get_by_text(re.compile(r"file[_ ]read", re.I)).first.wait_for(timeout=10000)
                response = await page.request.get(f"http://127.0.0.1:{port}/api/messages/{cid}")
                messages = await response.json()
                assert "Native trace sample" in json.dumps(messages)
                await page.reload(wait_until="domcontentloaded")
                await page.get_by_text("Native tool result retained.", exact=True).first.wait_for(timeout=15000)
                await page.get_by_text(re.compile(r"file[_ ]read", re.I)).first.wait_for(timeout=10000)
            else:
                # The original React hook reconstructs this pending card
                # from /chat/status.resumeState and /chat/stream?resume=true.
                # Verify a full browser reload before answering, not merely
                # the initial on_pending_action live SSE.
                await page.get_by_role("button", name="README", exact=True).first.wait_for(timeout=15000)
                await page.reload(wait_until="domcontentloaded")
                await page.get_by_role("button", name="README", exact=True).first.wait_for(timeout=15000)
                try:
                    await page.get_by_role("button", name="README", exact=True).first.click(timeout=15000)
                except playwright.Error as exc:
                    raise AssertionError({"requests": requests, "body": await page.locator("body").inner_text()}) from exc
                await page.get_by_role("button", name="JSON", exact=True).first.click(timeout=15000)
                await page.get_by_role("button", name=re.compile(r"^(Submit|提交)$")).first.click()
                await page.get_by_text("Batch answers received correctly.", exact=True).first.wait_for(timeout=15000)
                assert answers == [{"answers": {"file": "README.md", "format": "json"}}]
                await page.reload(wait_until="domcontentloaded")
                await page.get_by_text("Batch answers received correctly.", exact=True).first.wait_for(timeout=15000)
            assert not errors
    finally:
        if browser is not None:
            await browser.close()
        server.should_exit = True
        await asyncio.wait_for(task, timeout=15)
        get_settings.cache_clear()
