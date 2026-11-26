"""Native React startup config and SQLite user preference HTTP contracts."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp import __version__
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
        assert "compactionEnabled" not in login_page_config.json()
        assert "lsmVersion" not in login_page_config.json()
        assert "very-private" not in login_page_config.text
        assert (await client.get("/api/endpoints")).status_code == 401
        alice = {"x-test-owner": "alice"}
        startup = (await client.get("/api/config", headers=alice)).json()
        assert startup["lsmVersion"] == __version__
        assert startup["interface"]["agents"]["use"] is True
        assert startup["interface"]["contextUsage"] is True
        assert startup["compactionEnabled"] is True
        repo = routes._repo()
        repo.save_setting("alice", "endpoints", {"summarization": {"enabled": False}})
        assert (await client.get("/api/config", headers=alice)).json()["compactionEnabled"] is False
        assert (await client.get("/api/config", headers={"x-test-owner": "bob"})).json()["compactionEnabled"] is True
        repo.save_setting("alice", "endpoints", {"summarization": {"enabled": True}})
        assert (await client.get("/api/config", headers=alice)).json()["compactionEnabled"] is True
        repo.save_setting("alice", "endpoints", {"summarization": "invalid"})
        assert (await client.get("/api/config", headers=alice)).json()["compactionEnabled"] is True
        repo.save_setting("alice", "endpoints", {})
        assert startup["interface"]["schedules"] == {
            "use": True, "create": True, "maxPerUser": 25,
            "minIntervalMinutes": 5, "requireProject": False,
        }
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
        assert (await client.patch("/api/user/preferences", headers=alice,
                                   json={"autoExpandTools": False})).json() == {
            "lang": "zh-CN", "theme": "dark", "autoExpandTools": False,
        }
        assert (await client.patch("/api/user/preferences", headers=alice,
                                   json={"theme": "light"})).json()["autoExpandTools"] is False
        assert (await client.patch("/api/user/preferences", json={"theme": "dark"})).status_code == 401
        assert (await client.get("/api/user/preferences", headers={"x-test-owner": "bob"})).json() == {}
        assert (await client.patch("/api/user/preferences", headers=alice,
                                   json={"large": "x" * (128 * 1024)})).status_code == 413
        assert (await client.get("/api/user/preferences", headers=alice)).json()["theme"] == "light"
        from local_shell_mcp.webui.auth import public_owner_id

        assert (await client.patch("/api/user/preferences", headers=alice,
                                   params={"owner": public_owner_id("bob")},
                                   json={"theme": "dark"})).status_code == 409
        assert (await client.get("/api/user/preferences", headers=alice,
                                 params={"owner": public_owner_id("alice")})).status_code == 200
        assert (await client.get("/api/user/preferences", headers=alice)).json()["theme"] == "light"
        create = await client.post("/api/presets", headers=alice, json={"title": "Research"})
        assert create.status_code == 200
        preset = create.json()
        assert len((await client.get("/api/presets", headers=alice)).json()) == 1
        assert (await client.post("/api/presets/delete", headers=alice,
                                  json={"presetId": preset["presetId"]})).json()["success"] is True
        assert (await client.get("/api/presets", headers=alice)).json() == []
        assert (await client.get("/api/presets", headers={"x-test-owner": "bob"})).json() == []


@pytest.mark.asyncio
async def test_startup_config_real_auth_middleware_preserves_optional_identity(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from local_shell_mcp import auth, settings as settings_module

    settings = SimpleNamespace(auth_mode="oauth", public_base_url="https://lsm.example.invalid",
                               state_dir=tmp_path)
    monkeypatch.setattr(settings_module, "get_settings", lambda: settings)
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(auth, "get_settings", lambda: settings)

    def verify(request, _settings):
        token = request.headers.get("authorization")
        if token not in {"Bearer alice", "Bearer bob"}:
            raise HTTPException(401, detail="Invalid bearer")
        return SimpleNamespace(subject=token.split()[1])

    monkeypatch.setattr(auth, "_verify_oauth", verify)
    app = auth.AuthMiddleware(Starlette(routes=config_routes.config_routes()))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                base_url="https://lsm.example.invalid") as client:
        anonymous = await client.get("/api/config")
        assert anonymous.status_code == 200
        assert "compactionEnabled" not in anonymous.json()
        assert anonymous.headers["cache-control"] == "no-store"
        invalid = await client.get("/api/config", headers={"Authorization": "Bearer expired"})
        assert invalid.status_code == 200
        assert "compactionEnabled" not in invalid.json()
        repo = routes._repo()
        repo.save_setting("alice", "endpoints", {"summarization": {"enabled": False}})
        alice = await client.get("/api/config", headers={"Authorization": "Bearer alice"})
        bob = await client.get("/api/config", headers={"Authorization": "Bearer bob"})
        assert alice.json()["compactionEnabled"] is False
        assert bob.json()["compactionEnabled"] is True
        assert alice.headers["cache-control"] == "no-store"
        assert "compactionEnabled" not in (await client.get("/api/config")).json()
