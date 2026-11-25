"""Python serves the original React UI without a resident Node.js process."""

from pathlib import Path

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
        for uri in ("/skills", "/skills/new", "/skills/deployment:code-humanizer",
                    "/skills/deployment%3Acode-humanizer?file=references%2Fexample.md",
                    "/skills/example-id/edit"):
            response = await client.get(uri)
            assert response.status_code == 200 and "LSM WebUI" in response.text
            assert response.headers["Cache-Control"] == "no-store"
        assert "console.log" in (await client.get("/assets/app.js")).text
        assert (await client.get("/assets/secret.map")).status_code == 404
        assert (await client.get("/api/not-found")).status_code == 404
        assert (await client.get("/.env")).status_code == 404
        assert (await client.get("/foo")).status_code == 404


def test_skill_pages_are_registered_in_react_router():
    import re

    router = Path(__file__).parents[1] / "ui/workspace/client/src/routes/index.tsx"
    source = router.read_text(encoding="utf-8")
    assert "import('~/components/Skills/layouts/SkillsView')" in source
    for route in ("skills", "skills/new", "skills/:skillId", "skills/:skillId/edit"):
        assert re.search(r"path: '" + re.escape(route) + r"',\s*lazy: loadSkillsView", source), route


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
            assert (await client.get("/skills/deployment:code-humanizer")).status_code == 303
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_pwa_assets_are_public_without_login(tmp_path, monkeypatch):
    from local_shell_mcp.settings import get_settings

    bundle = tmp_path / "bundle"
    assets = bundle / "assets"
    assets.mkdir(parents=True)
    (bundle / "index.html").write_text("<title>LSM</title>")
    (bundle / "manifest.webmanifest").write_text('{"name": "local-shell-mcp"}')
    for script in ("sw.js", "sw-heal.js", "registerSW.js"):
        (bundle / script).write_text("// service worker")
    source = Path(__file__).parents[1] / "ui/workspace/client/public/assets"
    for icon in ("icon-192x192.png", "icon-512x512.png", "maskable-icon.png"):
        (assets / icon).write_bytes((source / icon).read_bytes())
    monkeypatch.setattr(frontend, "bundled_frontend", lambda: bundle)
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "oauth")
    get_settings.cache_clear()
    app = Starlette(routes=frontend.frontend_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.org") as client:
        assert (await client.get("/")).status_code == 303
        for method in ("GET", "HEAD"):
            response = await client.request(method, "/manifest.webmanifest")
            assert response.status_code == 200
            assert response.headers["content-type"] == "application/manifest+json"
            assert response.headers["cache-control"] == "no-cache"
        for script in ("sw.js", "sw-heal.js", "registerSW.js"):
            response = await client.get("/" + script)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-cache"
        for icon in ("icon-192x192.png", "icon-512x512.png", "maskable-icon.png"):
            response = await client.get("/assets/" + icon)
            assert response.status_code == 200
            assert response.headers["content-type"] == "image/png"
            assert response.content == (source / icon).read_bytes()
        assert (await client.get("/assets/missing-pwa-icon.png")).status_code == 404
        assert (await client.post("/manifest.webmanifest")).status_code == 404


def test_pwa_icon_dimensions():
    from PIL import Image

    assets = Path(__file__).parents[1] / "ui/workspace/client/public/assets"
    for name, size in (
        ("favicon-16x16.png", 16),
        ("favicon-32x32.png", 32),
        ("apple-touch-icon-180x180.png", 180),
        ("icon-192x192.png", 192),
        ("icon-512x512.png", 512),
        ("maskable-icon.png", 512),
    ):
        with Image.open(assets / name) as image:
            assert image.format == "PNG"
            assert image.size == (size, size)
            if name == "maskable-icon.png":
                assert image.convert("RGBA").getchannel("A").getextrema() == (255, 255)


def test_localized_webui_uses_lsm_brand():
    import json

    locales = Path(__file__).resolve().parents[1] / "ui/workspace/client/src/locales"
    for path in locales.glob("*/translation.json"):
        translations = json.loads(path.read_text(encoding="utf-8"))
        assert all("librechat" not in value.casefold() for value in translations.values()
                   if isinstance(value, str)), path
