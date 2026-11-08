"""Integrated Controller routing and crash-recovery contract for native chat."""

from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.main import _with_oauth_routes
from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui.generations import GenerationStore


@pytest.mark.asyncio
async def test_unified_routes_are_mounted_with_sqlite_default(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_ENABLED", "true")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    monkeypatch.delenv("LOCAL_SHELL_MCP_STATE_BACKEND", raising=False)
    get_settings.cache_clear()
    try:
        app = _with_oauth_routes(Starlette())
        installed = {getattr(route, "path", "") for route in app.routes}
        for path in (
            "/api/config", "/api/models", "/api/endpoints", "/api/auth/lsm",
            "/api/convos", "/api/convos/update", "/api/convos/archive",
            "/api/messages", "/api/agents", "/api/agents/chat",
            "/api/agents/chat/stream/{stream_id}", "/api/agents/chat/active",
            "/api/lsm/controller/gui/frame", "/api/lsm/controller/settings/{action}",
            "/{path:path}",
        ):
            assert path in installed, path
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/config")
            assert resp.status_code == 200, resp.text
            assert resp.json()["appTitle"] == "local-shell-mcp"
            created = await client.post("/api/convos", json={"title": "Integrated UI"})
            assert created.status_code == 201, created.text
            cid = created.json()["conversationId"]
            assert (await client.get(f"/api/convos/{cid}")).status_code == 200
            active = await client.get("/api/agents/chat/active")
            assert active.status_code == 200
            assert active.json()["activeJobIds"] == []
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_controller_lifespan_repairs_orphaned_generations(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_ENABLED", "true")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    monkeypatch.delenv("LOCAL_SHELL_MCP_STATE_BACKEND", raising=False)
    get_settings.cache_clear()
    try:
        from local_shell_mcp.sqlite_store import shared_database

        repo = GenerationStore(shared_database(get_settings().state_dir.resolve()))
        generation, _ = repo.begin("local", {"text": "Unfinished prior generation"})
        assert repo.get("local", generation.run_id).status == "running"
        app = _with_oauth_routes(Starlette())
        async with app.router.lifespan_context(app):
            assert repo.get("local", generation.run_id).status == "interrupted"
            assert repo.events("local", generation.run_id)[-1][1]["final"] is True
    finally:
        get_settings.cache_clear()
