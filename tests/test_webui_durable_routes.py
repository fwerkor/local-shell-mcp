"""Revocation hooks for every native WebUI conversation/project mutation path."""
from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui import conversation_routes, durable_tasks, routes


@pytest.fixture
def client_app(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    actions = []
    monkeypatch.setattr(durable_tasks, "mark_revoked", lambda owner: actions.append(owner))
    app = Starlette(routes=[*conversation_routes.conversation_routes(), *routes.webui_routes()])
    yield app, actions
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_mutations_schedule_revocation_on_all_route_aliases(client_app):
    app, actions = client_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        project = (await client.post("/api/projects", json={"name": "project"})).json()["_id"]
        child = (await client.post("/api/convos", json={"title": "child"})).json()["conversationId"]
        assert (await client.put("/api/convos", json={"conversationId": child, "projectId": project})).status_code == 200
        assert len(actions) == 1
        assert (await client.patch(f"/api/convos/{child}", json={"projectId": None})).status_code == 200
        assert len(actions) == 2
        assert (await client.post("/api/convos/update", json={"conversationId": child, "projectId": project})).status_code == 200
        assert len(actions) == 3
        assert (await client.put(f"/api/projects/conversations/{child}", json={"projectId": None})).status_code == 200
        assert len(actions) == 4
        assert (await client.delete(f"/api/projects/{project}")).status_code == 200
        assert len(actions) == 5
        assert (await client.delete(f"/api/convos/{child}")).status_code == 200
        assert len(actions) == 6
        assert (await client.delete("/api/convos/all")).status_code == 200
        assert len(actions) == 6
        other = (await client.post("/api/convos", json={"title": "other"})).json()["conversationId"]
        assert (await client.delete("/api/convos/all")).status_code == 200
        assert len(actions) == 7
        assert (await client.get(f"/api/convos/{other}")).status_code == 404
        assert actions == ["local"] * 7


@pytest.mark.asyncio
async def test_legacy_endpoints_and_error_paths(client_app):
    app, actions = client_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        create = await client.post("/api/convos", json={"title": "draft"})
        cid = create.json()["conversationId"]
        assert (await client.get(f"/api/convos/{cid}")).status_code == 200
        assert (await client.post("/api/convos/update", json={"arg": {"conversationId": cid, "title": "renamed"}})).status_code == 200
        assert not actions
        assert (await client.post("/api/convos/archive", json={"conversationId": cid})).status_code == 200
        assert (await client.post("/api/convos/pin", json={"conversationId": cid})).status_code == 200
        assert (await client.post("/api/convos/archive/all", json={})).status_code == 200
        assert (await client.get(f"/api/convos/gen_title/{cid}")).json()["title"] == "renamed"
        assert (await client.post("/api/convos/update", json={"arg": "bad"})).status_code == 400
        assert (await client.post("/api/convos/update", json={"title": "no id"})).status_code == 400
        assert (await client.post("/api/convos/fork", json={})).status_code == 400
        assert (await client.get("/api/convos/gen_title/missing")).status_code == 404
        assert (await client.post("/api/convos/update", json={"conversationId": "missing"})).status_code == 404
        assert (await client.post("/api/convos/duplicate", json={})).status_code == 400
        assert (await client.delete("/api/convos/not-found")).status_code == 404
        assert (await client.delete("/api/projects/not-found")).status_code == 404
        assert (await client.get("/api/projects/not-found")).status_code == 404
        assert (await client.patch("/api/projects/not-found", json={"name": "no"})).status_code == 404
        assert (await client.get("/api/convos", params={"limit": "invalid"})).status_code == 400
        assert (await client.get("/api/messages")).status_code == 400
        assert (await client.get("/api/messages", params={"conversationId": "not-found"})).status_code == 404
        assert (await client.post("/api/messages/not-found", json={"text": "x"})).status_code == 404
        assert (await client.get("/api/messages/not-found")).status_code == 404
        assert (await client.get("/api/search/messages", params={"q": "unknown"})).status_code == 200
        assert not actions
