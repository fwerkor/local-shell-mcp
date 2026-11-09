"""Browser-discovered API dependencies backed by the native Python WebUI."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.webui import misc_routes, routes


@pytest.mark.asyncio
async def test_sidebar_preferences_are_server_side_and_owner_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(auth_mode="oauth", state_dir=tmp_path))
    app = Starlette(routes=misc_routes.misc_routes())

    async def authenticated(scope, receive, send):
        if scope.get("type") == "http":
            owner = next((v.decode() for k, v in scope.get("headers", []) if k == b"x-owner"), None)
            if owner:
                scope.setdefault("state", {})["principal"] = SimpleNamespace(subject=owner)
        await app(scope, receive, send)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=authenticated), base_url="http://test") as client:
        alice, bob = {"x-owner": "alice"}, {"x-owner": "bob"}
        assert (await client.get("/api/user/settings/favorites")).status_code == 401
        assert (await client.get("/api/user/settings/favorites", headers=alice)).json() == []
        items = [{"itemType": "tool", "itemId": "file_list"}]
        updated = await client.post("/api/user/settings/favorites", json={"favorites": items}, headers=alice)
        assert updated.status_code == 200
        assert updated.json() == items
        assert (await client.get("/api/user/settings/favorites", headers=alice)).json() == items
        assert (await client.get("/api/user/settings/favorites", headers=bob)).json() == []
        assert (await client.post("/api/user/settings/pinned-order", json={"pinnedOrder": ["fav:file_list"]},
                                  headers=alice)).status_code == 200
        assert (await client.get("/api/user/settings/pinned-order", headers=alice)).json() == ["fav:file_list"]
        assert (await client.post("/api/user/settings/pinned-order", json={"pinnedOrder": [1]},
                                  headers=alice)).status_code == 400
        assert (await client.post("/api/user/settings/favorites", json={"favorites": []},
                                  headers=bob)).status_code == 200
        assert (await client.get("/api/user/settings/favorites", headers=alice)).json() == items


@pytest.mark.asyncio
async def test_disabled_optional_capabilities_never_claim_unsupported_services(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(auth_mode="none", state_dir=tmp_path))
    app = Starlette(routes=misc_routes.misc_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/banner")).json() is None
        assert (await client.get("/api/search/enable")).json() is False
        assert (await client.get("/api/files")).json() == []
        assert (await client.get("/api/files/speech/config/get")).json()["speechToText"]["enabled"] is False
        assert (await client.get("/api/roles/USER")).json()["name"] == "USER"
        assert (await client.get("/api/roles/ADMIN")).json()["permissions"]["agents"]["use"] is True
        assert (await client.get("/api/roles/ROOT")).status_code == 404
        assert (await client.get("/api/balance")).json()["autoRefillEnabled"] is False
        assert (await client.get("/api/health")).json()["status"] == "ok"
        assert (await client.get("/health")).json()["status"] == "ok"
        assert (await client.get("/api/tags")).json() == []
        assert (await client.get("/api/files/config")).json()["serverFileSizeLimit"] == 32 * 1024 * 1024
        assert (await client.get("/api/agents/tools/web_search/auth")).json()["authenticated"] is False


@pytest.mark.asyncio
async def test_chat_tool_permission_prefs_are_private_and_secret_keys_not_exposed(tmp_path, monkeypatch):
    from local_shell_mcp import settings as settings_module

    settings = SimpleNamespace(auth_mode="oauth", state_dir=tmp_path)
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(settings_module, "get_settings", lambda: settings)
    monkeypatch.setenv("OPENAI_API_KEY", "very-secret-key")
    from local_shell_mcp.webui.routes import webui_routes

    app = Starlette(routes=[*misc_routes.misc_routes(), *webui_routes()])

    async def authenticated(scope, receive, send):
        if scope.get("type") == "http":
            owner = next((v.decode() for k, v in scope.get("headers", []) if k == b"x-test-owner"), None)
            if owner:
                scope.setdefault("state", {})["principal"] = SimpleNamespace(subject=owner)
        await app(scope, receive, send)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=authenticated), base_url="http://test") as client:
        alice = {"x-test-owner": "alice"}
        bob = {"x-test-owner": "bob"}
        cid = (await client.post("/api/convos", headers=alice, json={"title": "Tools"})).json()["conversationId"]
        assert (await client.get(f"/api/lsm/preferences/{cid}", headers=alice)).json()["effective"] == {}
        assert (await client.get(f"/api/lsm/preferences/{cid}", headers=bob)).status_code == 404
        prefs = {"web": True, "lsm": True, "mcp": False, "memory": False}
        updated = (await client.put(f"/api/lsm/preferences/{cid}", headers=alice, json=prefs)).json()
        assert all(updated[field] == value for field, value in prefs.items())
        stored = (await client.get(f"/api/lsm/preferences/{cid}", headers=alice)).json()
        assert all(stored[field] == value for field, value in prefs.items())
        assert stored["effective"] == {}
        # Legacy flags are retained for old clients but never grant a machine.
        prior = await client.put(f"/api/lsm/preferences/{cid}", headers=alice,
                                 json={"web": False, "lsm": True, "mcp": False, "memory": False})
        assert prior.status_code == 200
        assert prior.json()["effective"] == {}
        assert (await client.get("/api/keys?name=openAI", headers=alice)).status_code == 200
        assert "very-secret-key" not in (await client.get("/api/keys?name=openAI", headers=alice)).text
        assert (await client.get("/api/agents/tools/calls", headers=alice,
                                 params={"conversationId": cid})).json() == []
        assert (await client.get("/api/agents/tools/calls", headers=bob,
                                 params={"conversationId": cid})).status_code == 404


@pytest.mark.asyncio
async def test_misc_settings_and_permissions_reject_untrusted_json(tmp_path, monkeypatch):
    from local_shell_mcp import settings as settings_module

    settings = SimpleNamespace(auth_mode="none", state_dir=tmp_path,
                               disable_local=False, remote_enabled=False)
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(settings_module, "get_settings", lambda: settings)
    app = Starlette(routes=[*misc_routes.misc_routes(), *routes.webui_routes()])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/api/user/settings/pinned-order",
                                  json={"pinnedOrder": ["file_list"] * 501})).status_code == 400
        assert (await client.post("/api/user/settings/favorites",
                                  json={"favorites": ["not-an-object"]})).status_code == 400
        assert (await client.post("/api/user/settings/favorites",
                                  json={"favorites": [{"id": "x" * 263000}]})).status_code == 413
        cid = (await client.post("/api/convos", json={"title": "Scoped"})).json()["conversationId"]
        assert (await client.put(f"/api/lsm/preferences/{cid}",
                                 json={"web": "true"})).status_code == 400
        assert (await client.put(f"/api/lsm/preferences/{cid}",
                                 json={"machines": {"bad/machine": "read"}})).status_code == 400
        assert (await client.put(f"/api/lsm/preferences/{cid}",
                                 json={"machines": {"worker1": "read"}})).status_code == 403
        assert (await client.get("/api/keys?name=not-supported")).status_code == 404
        with monkeypatch.context() as patched:
            patched.setattr("local_shell_mcp.webui.providers.provider_config",
                            lambda *args: (_ for _ in ()).throw(ValueError("unconfigured")))
            assert (await client.get("/api/keys?name=google")).status_code == 404
        assert (await client.get("/api/agents/tools/calls")).status_code == 404
