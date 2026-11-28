"""Long chat history uses bounded bodies and keeps message-level navigation."""

import asyncio
import socket

import pytest
from starlette.applications import Starlette

from local_shell_mcp.main import _with_oauth_routes
from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import shared_database
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.mark.asyncio
async def test_long_history_lands_at_tail_and_hydrates_on_scroll(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.async_api")
    import uvicorn

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_ENABLED", "true")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODEL_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODEL", "history-test-model")
    get_settings.cache_clear()
    app = _with_oauth_routes(Starlette())
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                          lifespan="on", log_level="error", access_log=False))
    task = asyncio.create_task(server.serve())
    browser = None
    try:
        for _ in range(100):
            if server.started:
                break
            if task.done():
                raise RuntimeError("Source React server stopped")
            await asyncio.sleep(.05)
        assert server.started
        async with playwright.async_playwright() as manager:
            try:
                browser = await manager.chromium.launch(headless=True)
            except playwright.Error as exc:
                if "Executable doesn't exist" in str(exc):
                    pytest.skip("Chromium required")
                raise
            page = await browser.new_page(viewport={"width": 1100, "height": 760})
            errors = []
            body_requests = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda request: body_requests.append(request.post_data_json)
                    if request.url.endswith("/history-bodies") and request.method == "POST" else None)
            base = f"http://127.0.0.1:{port}"
            created = await page.request.post(f"{base}/api/convos", data={
                "title": "Long history", "endpoint": "openAI", "model": "history-test-model",
            })
            assert created.status == 201, await created.text()
            cid = (await created.json())["conversationId"]
            db = shared_database(get_settings().state_dir.resolve())
            with db.connect() as connection:
                owner = connection.execute("SELECT owner FROM conversations WHERE id=?", (cid,)).fetchone()[0]
            repo = WorkspaceRepository(db)
            parent = None
            messages = []
            for i in range(120):
                is_user = i % 2 == 0
                payload = {
                    "role": "user" if is_user else "assistant",
                    "isCreatedByUser": is_user, "sender": "User" if is_user else "history-test-model",
                    "text": f"History message {i:03d}",
                    "parentMessageId": parent, "endpoint": "openAI", "unfinished": False,
                }
                if not is_user:
                    payload["content"] = [{"type": "text", "text": payload["text"]}]
                message = repo.add_message(owner, cid, payload)
                parent = message["messageId"]
                messages.append(message)
            await page.goto(f"{base}/c/{cid}", wait_until="domcontentloaded")
            latest = page.get_by_text("History message 119", exact=True)
            await latest.first.wait_for(timeout=20000)
            await page.wait_for_function("""() => {
              const end = document.querySelector('#messages-end');
              const el = end?.parentElement?.parentElement;
              return el && el.scrollHeight - el.scrollTop - el.clientHeight < 60;
            }""", timeout=10000)
            old_id = messages[3]["messageId"]
            old = page.locator(f'[data-history-row="{old_id}"]')
            assert await old.get_attribute("data-history-body") == "placeholder"
            assert not any(old_id in body.get("messageIds", []) for body in body_requests)
            await old.evaluate("(el) => el.scrollIntoView({block:'center'})")
            await page.get_by_text("History message 003", exact=True).first.wait_for(timeout=15000)
            assert await old.get_attribute("data-history-body") == "mounted"
            assert any(old_id in body.get("messageIds", []) for body in body_requests)
            await page.locator("#messages-end").evaluate("(el) => el.scrollIntoView({block:'end'})")
            await page.wait_for_function("""id => document.querySelector('[data-history-row="' + id + '"]')?.dataset.historyBody === 'placeholder'""", arg=old_id)
            # After the idle eviction delay, revisiting must fetch the body again.
            await page.wait_for_timeout(1200)
            count = sum(old_id in body.get("messageIds", []) for body in body_requests)
            await old.evaluate("(el) => el.scrollIntoView({block:'center'})")
            await page.get_by_text("History message 003", exact=True).first.wait_for(timeout=15000)
            assert sum(old_id in body.get("messageIds", []) for body in body_requests) > count
            await page.goto(f"{base}/c/{cid}?message={old_id}", wait_until="domcontentloaded")
            await page.get_by_text("History message 003", exact=True).first.wait_for(timeout=15000)
            await page.wait_for_function("""id => {
              const el = document.getElementById(id);
              if (!el || el.closest('[data-history-body="placeholder"]')) return false;
              const rect = el.getBoundingClientRect();
              return rect.top >= 0 && rect.top < innerHeight;
            }""", arg=old_id)
            assert "?message=" + old_id in page.url
            assert not errors, errors
    finally:
        if browser is not None:
            await browser.close()
        server.should_exit = True
        await asyncio.wait_for(task, timeout=15)
        get_settings.cache_clear()
