"""Negative and ownership contract tests for the first-party WebUI endpoints."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.webui import agent_routes, routes


@pytest.mark.asyncio
async def test_agent_api_validation_and_version_lifecycle(tmp_path, monkeypatch):
    from local_shell_mcp import settings as settings_module

    config = SimpleNamespace(auth_mode="oauth", state_dir=tmp_path)
    monkeypatch.setattr(settings_module, "get_settings", lambda: config)
    monkeypatch.setattr(routes, "get_settings", lambda: config)
    app = Starlette(routes=agent_routes.agent_routes())

    async def principal(scope, receive, send):
        if scope.get("type") == "http":
            owner = next((v.decode() for k, v in scope.get("headers", []) if k == b"x-owner"), None)
            if owner:
                scope.setdefault("state", {})["principal"] = SimpleNamespace(subject=owner)
        await app(scope, receive, send)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=principal), base_url="http://test") as client:
        alice = {"x-owner": "alice"}
        assert (await client.get("/api/agents")).status_code == 401
        assert (await client.get("/api/agents", params={"limit": "nonnumeric"}, headers=alice)).status_code == 400
        assert (await client.get("/api/agents", params={"cursor": "not-base64"}, headers=alice)).status_code == 400
        assert (await client.post("/api/agents", json={"name": "missing-provider"}, headers=alice)).status_code == 400
        assert (await client.post("/api/agents", content="broken-json", headers=alice)).status_code == 400
        assert (await client.post("/api/agents", json=[], headers=alice)).status_code == 400
        created = await client.post("/api/agents", json={
            "name": "My agent", "provider": "openAI", "model": "test", "tools": []
        }, headers=alice)
        assert created.status_code == 201
        aid = created.json()["id"]
        assert (await client.get(f"/api/agents/{aid}/expanded", headers=alice)).json()["name"] == "My agent"
        assert len((await client.get(f"/api/agents/{aid}/versions", headers=alice)).json()) == 1
        assert (await client.get(f"/api/agents/{aid}/versions", headers={"x-owner": "bob"})).status_code == 404
        assert (await client.get(f"/api/agents/{aid}/expanded", headers={"x-owner": "bob"})).status_code == 404
        assert (await client.patch(f"/api/agents/{aid}", json={"tools": "invalid"}, headers=alice)).status_code == 400
        assert (await client.patch(f"/api/agents/{aid}", json={"name": "Updated"}, headers=alice)).json()["version"] == 2
        assert (await client.post(f"/api/agents/{aid}/revert", json={"version_index": "xyz"}, headers=alice)).status_code == 400
        assert (await client.post(f"/api/agents/{aid}/revert", json={"version_index": 99}, headers=alice)).status_code == 400
        restored = await client.post(f"/api/agents/{aid}/revert", json={"version_index": 1}, headers=alice)
        assert restored.status_code == 200
        assert restored.json()["name"] == "My agent"
        copied = await client.post(f"/api/agents/{aid}/duplicate", headers=alice)
        assert copied.status_code == 201
        assert copied.json()["agent"]["name"] == "My agent (copy)"
        assert (await client.delete(f"/api/agents/{aid}", headers=alice)).status_code == 200
        for path in (f"/api/agents/{aid}", f"/api/agents/{aid}/expanded", f"/api/agents/{aid}/versions"):
            assert (await client.get(path, headers=alice)).status_code == 404
        assert (await client.delete(f"/api/agents/{aid}", headers=alice)).status_code == 404
        assert (await client.post(f"/api/agents/{aid}/duplicate", headers=alice)).status_code == 404
        assert (await client.post(f"/api/agents/{aid}/revert", json={"version_index": 0}, headers=alice)).status_code == 404
        assert (await client.patch(f"/api/agents/{aid}", json={"name": "oops"}, headers=alice)).status_code == 404


@pytest.mark.asyncio
async def test_conversation_project_message_api_error_paths(tmp_path, monkeypatch):
    config = SimpleNamespace(auth_mode="none", state_dir=tmp_path)
    monkeypatch.setattr(routes, "get_settings", lambda: config)
    app = Starlette(routes=routes.webui_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/messages")).status_code == 400
        assert (await client.get("/api/convos", params={"limit": "bad"})).status_code == 400
        assert (await client.post("/api/convos", json=[])).status_code == 400
        assert (await client.post("/api/convos", content="not-json")).status_code == 400
        assert (await client.request("DELETE", "/api/convos", json={})).status_code == 400
        assert (await client.request("DELETE", "/api/convos", json={"conversationId": "missing"})).status_code == 404
        assert (await client.get("/api/convos/missing")).status_code == 404
        assert (await client.patch("/api/convos/missing", json={"title": "none"})).status_code == 404
        assert (await client.delete("/api/convos/missing")).status_code == 404
        assert (await client.get("/api/messages/missing")).status_code == 404
        assert (await client.post("/api/messages/missing", json={"role": "user", "text": "x"})).status_code == 404
        assert (await client.post("/api/projects", json={"name": ""})).status_code == 400
        assert (await client.get("/api/projects/missing")).status_code == 404
        assert (await client.patch("/api/projects/missing", json={"name": "X"})).status_code == 404
        assert (await client.delete("/api/projects/missing")).status_code == 404
        project = (await client.post("/api/projects", json={"name": "Research"})).json()
        project_id = project["_id"]
        assert (await client.patch(f"/api/projects/{project_id}", json={"name": "R&D"})).json()["name"] == "R&D"
        cid = (await client.post("/api/convos", json={"title": "hello"})).json()["conversationId"]
        assert (await client.post("/api/convos", json={"conversationId": cid, "title": "updated"})).json()["title"] == "updated"
        assert (await client.put(f"/api/convos/{cid}", json={"title": "again"})).json()["title"] == "again"
        assert (await client.post("/api/convos", json={"title": "bad FK", "projectId": "missing"})).status_code == 409
        assert (await client.put(f"/api/projects/conversations/{cid}", json={"projectId": "missing"})).status_code == 404
        assert (await client.put(f"/api/projects/conversations/{cid}", json={"projectId": project_id})).json()["projectId"] == project_id
        assert (await client.put("/api/projects/conversations/missing", json={"projectId": project_id})).status_code == 404
        message = (await client.post(f"/api/messages/{cid}", json={"role": "user", "text": "Searchable", "messageId": "known-id"})).json()
        assert message["messageId"] == "known-id"
        assert (await client.post(f"/api/messages/{cid}", json={"role": "user", "text": "Dup", "messageId": "known-id"})).status_code == 409
        assert (await client.get("/api/messages", params={"conversationId": cid, "pageSize": 1})).json()["messages"]
        assert (await client.get("/api/messages", params={"conversationId": "missing"})).status_code == 404
        assert (await client.get("/api/messages", params={"search": "Searchable"})).json()["messages"]
        assert (await client.get("/api/search/messages", params={"q": "Searchable"})).json()["messages"]
        assert (await client.get("/api/messages", params={"search": "a", "pageSize": "bad"})).status_code == 400
        assert (await client.delete(f"/api/convos/{cid}")).status_code == 200
        assert (await client.get("/api/convos", params={"projectId": project_id})).json()["conversations"] == []
