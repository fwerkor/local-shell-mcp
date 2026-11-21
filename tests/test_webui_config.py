"""Native React startup config and SQLite user preference HTTP contracts."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.webui import config_routes, routes


@pytest.mark.asyncio
async def test_startup_config_is_public_but_private_endpoints_require_auth(tmp_path, monkeypatch):
    settings = SimpleNamespace(auth_mode="oauth", public_base_url="https://lsm.example.invalid", state_dir=tmp_path)
    from local_shell_mcp import settings as settings_module

    monkeypatch.setattr(settings_module, "get_settings", lambda: settings)
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODEL_API_KEY", "very-private")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODEL", "gpt-4.1-mini")

    app = Starlette(routes=config_routes.config_routes())

    async def authenticated(scope, receive, send):
        if scope.get("type") == "http":
            owner = next((v.decode() for k, v in scope.get("headers", []) if k == b"x-test-owner"), None)
            if owner:
                scope.setdefault("state", {})["principal"] = SimpleNamespace(subject=owner)
        await app(scope, receive, send)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=authenticated),
                                base_url="https://lsm.example.invalid") as client:
        login_page_config = await client.get("/api/config")
        assert login_page_config.status_code == 200
        assert login_page_config.json()["appTitle"] == "local-shell-mcp"
        assert "interface" not in login_page_config.json()
        assert "very-private" not in login_page_config.text
        assert (await client.get("/api/endpoints")).status_code == 401
        alice = {"x-test-owner": "alice"}
        startup = (await client.get("/api/config", headers=alice)).json()
        assert startup["interface"]["agents"]["use"] is True
        assert startup["interface"]["contextUsage"] is True
        endpoints = (await client.get("/api/endpoints", headers=alice)).json()
        assert endpoints["agents"]["type"] == "agents"
        assert "openAI" in endpoints
        assert "very-private" not in str(endpoints)
        models = (await client.get("/api/models", headers=alice)).json()
        assert models["openAI"] == ["gpt-4.1-mini"]
        assert (await client.get("/api/endpoints/token-config", headers=alice)).json() == {}
        assert (await client.get("/api/user/preferences", headers=alice)).json() == {}
        assert (await client.put("/api/user/preferences", headers=alice,
                                 json={"lang": "zh-CN", "theme": "dark"})).status_code == 200
        assert (await client.get("/api/user/preferences", headers=alice)).json()["theme"] == "dark"
        assert (await client.get("/api/user/preferences", headers={"x-test-owner": "bob"})).json() == {}
        create = await client.post("/api/presets", headers=alice, json={"title": "Research"})
        assert create.status_code == 200
        preset = create.json()
        assert len((await client.get("/api/presets", headers=alice)).json()) == 1
        assert (await client.post("/api/presets/delete", headers=alice,
                                  json={"presetId": preset["presetId"]})).json()["success"] is True
        assert (await client.get("/api/presets", headers=alice)).json() == []
        assert (await client.get("/api/presets", headers={"x-test-owner": "bob"})).json() == []
