"""Python serves the original React UI without a resident Node.js process."""

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.webui import frontend


@pytest.fixture(autouse=True)
def _unauthenticated_controller(tmp_path, monkeypatch):
    from local_shell_mcp.settings import get_settings

    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_react_assets_and_routes(tmp_path, monkeypatch):
    bundle = tmp_path / "assets"
    bundle.mkdir()
    (bundle / "index.html").write_text("<html><title>LSM WebUI</title></html>", encoding="utf-8")
    (bundle / "assets").mkdir()
    (bundle / "assets" / "app.js").write_text("console.log('app')")
    (bundle / "assets" / "secret.map").write_text("private")
    monkeypatch.setattr(frontend, "bundled_frontend", lambda: bundle)
    app = Starlette(routes=frontend.frontend_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/")).status_code == 200
        assert (await client.get("/c/new")).status_code == 200
        assert "LSM WebUI" in (await client.get("/control/files")).text
        assert "console.log" in (await client.get("/assets/app.js")).text
        assert (await client.get("/assets/secret.map")).status_code == 404
        assert (await client.get("/api/not-found")).status_code == 404
        assert (await client.get("/.env")).status_code == 404
        assert (await client.get("/foo")).status_code == 404


def test_only_safe_get_paths_are_public():
    assert frontend.is_public_frontend("/c/new", "GET")
    assert frontend.is_public_frontend("/assets/app.js", "HEAD")
    assert not frontend.is_public_frontend("/c/new", "POST")
    assert not frontend.is_public_frontend("/api/ui/settings", "GET")
    assert not frontend.is_public_frontend("/mcp", "GET")


@pytest.mark.asyncio
async def test_packaged_editor_assets_are_public_and_revalidate(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    editor = bundle / "monaco" / "vs"
    editor.mkdir(parents=True)
    (editor / "loader.js").write_text("self.hosted = true", encoding="utf-8")
    (editor / "loader.js.map").write_text("private", encoding="utf-8")
    monkeypatch.setattr(frontend, "bundled_frontend", lambda: bundle)
    app = Starlette(routes=frontend.frontend_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/monaco/vs/loader.js")
        assert response.status_code == 200 and response.text == "self.hosted = true"
        assert response.headers["cache-control"] == "no-cache"
        assert frontend.is_public_frontend("/monaco/vs/loader.js", "GET")
        assert not frontend.is_public_frontend("/monaco/vs/loader.js", "POST")
        assert (await client.get("/monaco/vs/loader.js.map")).status_code == 404
        assert (await client.get("/monaco/vs/.env")).status_code == 404
        assert (await client.get("/monaco/vs/missing.js")).status_code == 404


@pytest.mark.asyncio
async def test_oauth_result_pages_render_publicly_without_login(tmp_path, monkeypatch):
    from local_shell_mcp.settings import get_settings

    bundle = tmp_path / "oauth-ui"
    bundle.mkdir()
    (bundle / "index.html").write_text("<title>Action OAuth</title>", encoding="utf-8")
    monkeypatch.setattr(frontend, "bundled_frontend", lambda: bundle)
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "oauth")
    get_settings.cache_clear()
    try:
        app = Starlette(routes=frontend.frontend_routes())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="https://chat.example.org", follow_redirects=False) as client:
            for uri in ("/oauth/success?serverName=Example", "/oauth/error?error=invalid_state"):
                response = await client.get(uri)
                assert response.status_code == 200 and "Action OAuth" in response.text
                assert response.headers["Cache-Control"] == "no-store"
            assert (await client.get("/oauth/authorize")).status_code == 404
            assert (await client.get("/oauth/success/private")).status_code == 404
            assert (await client.get("/c/new")).status_code == 303
    finally:
        get_settings.cache_clear()
