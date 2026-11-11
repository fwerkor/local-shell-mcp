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
@pytest.mark.parametrize("controller_mode,origin_configuration", [
    ("http", "origin"), ("stdio", "origin"),
    ("http", "public"), ("http", "resource"),
])
async def test_browser_default_entry_authenticates_without_an_open_button(
        tmp_path, monkeypatch, controller_mode, origin_configuration):
    playwright = pytest.importorskip("playwright.async_api")
    import uvicorn

    from local_shell_mcp.auth import AuthMiddleware
    from local_shell_mcp.main import _with_oauth_routes
    from local_shell_mcp.settings import get_settings

    for key, value in {
        "WORKSPACE_ROOT": str(tmp_path), "STATE_DIR": str(tmp_path / ".local-shell-mcp"),
        "AUTH_MODE": "oauth", "UI_ENABLED": "true", "REMOTE_ENABLED": "false",
        "OAUTH_ADMIN_PIN": "246810", "OAUTH_ACCESS_TOKEN_TTL_S": "300",
        "MODE": controller_mode, "AUTH_BYPASS_LOCALHOST": "true",
    }.items():
        monkeypatch.setenv("LOCAL_SHELL_MCP_" + key, value)
    get_settings.cache_clear()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    advertised = "https://controller.example.invalid" if origin_configuration == "public" else origin
    resource = "https://api.example.invalid/lsm" if origin_configuration == "resource" else advertised
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", advertised)
    monkeypatch.setenv("LOCAL_SHELL_MCP_OAUTH_RESOURCE", resource)
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
                assert "admin:config" in (await page.locator('input[name="scope"]').input_value()).split(), page.url
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
                assert claims["aud"] == resource
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


@pytest.mark.asyncio
@pytest.mark.parametrize("scopes", ["shell:read", "shell:read admin:config"])
async def test_local_bypass_does_not_replace_explicit_oauth_grant(tmp_path, monkeypatch, scopes):
    from local_shell_mcp.auth import AuthMiddleware
    from local_shell_mcp.oauth import issue_access_token
    from local_shell_mcp.settings import get_settings

    for key, value in {
        "WORKSPACE_ROOT": str(tmp_path), "STATE_DIR": str(tmp_path / ".local-shell-mcp"),
        "AUTH_MODE": "oauth", "MODE": "http", "AUTH_BYPASS_LOCALHOST": "true",
        "PUBLIC_BASE_URL": "http://127.0.0.1:8765", "OAUTH_ACCESS_TOKEN_TTL_S": "300",
    }.items():
        monkeypatch.setenv("LOCAL_SHELL_MCP_" + key, value)
    get_settings.cache_clear()
    origin = "http://127.0.0.1:8765"
    token = issue_access_token(client_id="browser", scope=scopes, resource=origin,
                               subject="oauth-alice", issuer=origin)
    app = AuthMiddleware(Starlette(routes=auth.auth_routes()))
    try:
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12345))
        async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
            response = await client.post("/api/ui/webui-ticket", headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 200, response.text
            _, grant = auth.WebAuthStore(get_settings().state_dir).redeem(response.json()["ticket"])
            assert grant.owner == "oauth-alice"
            assert set(grant.scopes.split()) == set(scopes.split())
            assert grant.grant_until <= int(time.time()) + 300
            # A local connection cannot turn a forged bearer into a valid grant.
            rejected = await client.post("/api/ui/webui-ticket", headers={"Authorization": "Bearer forged"})
            assert rejected.status_code == 401
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("origin,client_host,forwarded,allowed", [
    ("http://127.0.0.1:8765", "127.0.0.1", False, True),
    ("http://127.0.0.1:8765", "127.0.0.1", True, False),
    ("http://127.0.0.1:8765", "203.0.113.1", False, False),
    ("https://attacker.example", "127.0.0.1", False, False),
    ("null", "127.0.0.1", False, False),
    ("https://controller.example", "203.0.113.1", True, True),
])
def test_public_origin_exception_requires_a_direct_local_connection(
        monkeypatch, origin, client_host, forwarded, allowed):
    from starlette.exceptions import HTTPException
    from starlette.requests import Request

    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(
        public_base_url="https://controller.example"))
    headers = [(b"host", b"127.0.0.1:8765"), (b"origin", origin.encode())]
    if forwarded:
        headers.extend([(b"x-forwarded-for", b"203.0.113.1"),
                        (b"x-forwarded-host", b"controller.example")])
    request = Request({"type": "http", "method": "POST", "scheme": "http",
                       "path": "/api/auth/lsm", "headers": headers,
                       "server": ("127.0.0.1", 8765), "client": (client_host, 12345)})
    if allowed:
        auth._same_origin(request)
    else:
        with pytest.raises(HTTPException) as denied:
            auth._same_origin(request)
        assert denied.value.status_code == 403
