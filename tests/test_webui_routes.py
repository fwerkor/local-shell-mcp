"""HTTP contract and ownership regression tests for Python WebUI routes."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.webui import routes


@pytest.mark.asyncio
async def test_private_chat_api_end_to_end(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(auth_mode="oauth", state_dir=tmp_path / ".local-shell-mcp"))

    app = Starlette(routes=routes.webui_routes())

    async def authenticated(scope, receive, send):
        if scope["type"] == "http" and scope.get("headers"):
            owner = next((v.decode() for k, v in scope["headers"] if k == b"x-test-owner"), None)
            if owner:
                scope.setdefault("state", {})["principal"] = SimpleNamespace(subject=owner)
        await app(scope, receive, send)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=authenticated), base_url="http://test") as client:
        assert (await client.get("/api/convos")).status_code == 401
        alice = {"x-test-owner": "alice"}
        bob = {"x-test-owner": "bob"}
        project_resp = await client.post("/api/projects", json={"name": "NJU", "description": "Research"}, headers=alice)
        assert project_resp.status_code == 201
        project = project_resp.json()
        create = await client.post("/api/convos", json={"title": "Hello", "projectId": project["_id"]}, headers=alice)
        assert create.status_code == 201, create.text
        cid = create.json()["conversationId"]
        add = await client.post(f"/api/messages/{cid}", json={"role": "user", "text": "你好，世界"}, headers=alice)
        assert add.status_code == 201, add.text
        assert len((await client.get("/api/convos", headers=alice)).json()["conversations"]) == 1
        assert (await client.get(f"/api/convos/{cid}", headers=bob)).status_code == 404
        assert (await client.get("/api/messages", params={"conversationId": cid}, headers=bob)).status_code == 404
        assert (await client.get("/api/messages", params={"conversationId": cid}, headers=alice)).json()["messages"][0]["text"] == "你好，世界"
        assert len((await client.get("/api/search/messages", params={"q": "你好，"}, headers=alice)).json()["messages"]) == 1
        assert (await client.request("DELETE", "/api/convos", json={"arg": {"conversationId": cid}}, headers=alice)).status_code == 200
        assert (await client.get(f"/api/convos/{cid}", headers=alice)).status_code == 404


@pytest.mark.asyncio
async def test_project_mutation_enforces_owner(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(auth_mode="none", state_dir=tmp_path / ".local-shell-mcp"))
    app = Starlette(routes=routes.webui_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        project = (await client.post("/api/projects", json={"name": "Project"})).json()
        assert project["name"] == "Project"
        result = await client.patch(f"/api/projects/{project['_id']}", json={"name": "Updated"})
        assert result.status_code == 200
        assert result.json()["name"] == "Updated"
        assert (await client.delete(f"/api/projects/{project['_id']}")).status_code == 200
        assert (await client.get(f"/api/projects/{project['_id']}")).status_code == 404
