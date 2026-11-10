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
