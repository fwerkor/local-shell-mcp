"""The unified workspace goes directly to the Controller OAuth PIN flow."""
from __future__ import annotations

import asyncio
import socket
import time
from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.webui import auth, frontend


@pytest.mark.asyncio
async def test_workspace_navigation_requires_a_live_cookie(tmp_path, monkeypatch):
    from local_shell_mcp import settings as settings_module
    settings = SimpleNamespace(auth_mode="oauth", state_dir=tmp_path)
    monkeypatch.setattr(settings_module, "get_settings", lambda: settings)
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    bundle = tmp_path / "assets"
    bundle.mkdir()
    (bundle / "index.html").write_text("<title>React workspace</title>")
    monkeypatch.setattr(frontend, "bundled_frontend", lambda: bundle)
    app = Starlette(routes=auth.auth_routes() + frontend.frontend_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lsm.test") as client:
        for path in ("/", "/c/new", "/control/settings", "/login"):
            response = await client.get(path)
            assert response.status_code == 303
            assert response.headers["location"] == "/auth/login"
        bootstrap = await client.get("/auth/login")
        assert bootstrap.status_code == 200
        assert "code_challenge_method:'S256'" in bootstrap.text
        assert "Open WebUI" not in bootstrap.text
        assert bootstrap.headers["cache-control"] == "no-store"
        ticket = auth.WebAuthStore(tmp_path).issue_ticket("alice", "shell:read", int(time.time()) + 300)
        cookie, _ = auth.WebAuthStore(tmp_path).redeem(ticket)
        client.cookies.set(auth.COOKIE, cookie)
        assert "React workspace" in (await client.get("/c/new")).text
        assert (await client.get("/auth/login")).headers["location"] == "/c/new"
        auth.WebAuthStore(tmp_path).revoke(cookie)
        assert (await client.get("/c/new")).status_code == 303
    settings.auth_mode = "none"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        assert (await client.get("/auth/login")).headers["location"] == "/c/new"


@pytest.mark.asyncio
async def test_browser_default_entry_authenticates_without_an_open_button(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.async_api")
    import uvicorn

    from local_shell_mcp.auth import AuthMiddleware
    from local_shell_mcp.main import _with_oauth_routes
    from local_shell_mcp.settings import get_settings

    for key, value in {
        "WORKSPACE_ROOT": str(tmp_path), "STATE_DIR": str(tmp_path / ".local-shell-mcp"),
        "AUTH_MODE": "oauth", "UI_ENABLED": "true", "REMOTE_ENABLED": "false",
        "OAUTH_ADMIN_PIN": "246810", "OAUTH_ACCESS_TOKEN_TTL_S": "300",
    }.items():
        monkeypatch.setenv("LOCAL_SHELL_MCP_" + key, value)
    get_settings.cache_clear()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", origin)
    get_settings.cache_clear()
    server = uvicorn.Server(uvicorn.Config(AuthMiddleware(_with_oauth_routes(Starlette())),
        host="127.0.0.1", port=port, log_level="error", access_log=False))
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
                page = await browser.new_page()
                await page.goto(origin + "/", wait_until="domcontentloaded")
                await page.locator('input[name="pin"]').wait_for(timeout=15000)
                assert "/oauth/authorize?" in page.url
                assert await page.get_by_role("button", name="Open WebUI").count() == 0
                await page.locator('input[name="pin"]').fill("246810")
                await page.locator('button[type="submit"]').first.click()
                try:
                    await page.wait_for_url(origin + "/c/new", timeout=15000)
                except playwright.TimeoutError:
                    pytest.fail(f"Authentication stopped at {page.url}: {await page.locator('body').inner_text()}")
                cookies = await page.context.cookies()
                cookie = next(item for item in cookies if item["name"] == auth.COOKIE)
                assert cookie["httpOnly"] and cookie["sameSite"] == "Lax"
                token = await page.request.post(origin + "/api/auth/refresh")
                assert token.status == 200
                import jwt
                claims = jwt.decode((await token.json())["token"], options={"verify_signature": False})
                assert "admin:config" in claims["scope"].split()
                assert claims["exp"] <= time.time() + 301
                # Forged callbacks cannot exchange a code or replace the cookie.
                await page.goto(origin + "/auth/login?code=forged&state=forged")
                # A valid existing cookie returns to the workspace instead.
                await page.wait_for_url(origin + "/c/new")
                await page.context.clear_cookies()
                await page.goto(origin + "/auth/login?code=forged&state=forged")
                await page.get_by_role("status").filter(has_text="state verification failed").wait_for()
                assert not any(item["name"] == auth.COOKIE for item in await page.context.cookies())
            finally:
                await browser.close()
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=15)
        get_settings.cache_clear()
