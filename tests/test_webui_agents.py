"""LibreChat Agent management contract against the native SQLite store."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import agent_routes, routes
from local_shell_mcp.webui.agents import AgentRepository


def test_agent_create_update_revision_and_restore(tmp_path):
    repo = AgentRepository(SQLiteDatabase(tmp_path))
    created = repo.create("alice", {
        "name": "Research", "provider": "openAI", "model": "gpt-4o-mini",
        "model_parameters": {"temperature": 0.5}, "instructions": "Use tools",
        "subagents": {"enabled": True}, "skills_enabled": True,
    })
    agent_id = created["id"]
    assert agent_id.startswith("agent_")
    assert created["version"] == 1
    assert created["subagents"] == {"enabled": True}
    assert created["model_parameters"]["temperature"] == 0.5
    assert repo.get("bob", agent_id) is None
    assert repo.list("bob")["data"] == []
    updated = repo.update("alice", agent_id, {"name": "Updated", "instructions": "New instructions"})
    assert updated["version"] == 2
    assert repo.get("alice", agent_id)["instructions"] == "New instructions"
    history = repo.versions("alice", agent_id)
    assert len(history) == 2
    assert history[-1]["instructions"] == "Use tools"
    restored = repo.revert("alice", agent_id, 1)
    assert restored["instructions"] == "Use tools"
    assert restored["version"] == 3
    clone = repo.duplicate("alice", agent_id)
    assert clone["agent"]["id"] != agent_id
    assert clone["agent"]["name"].endswith("(copy)")
    assert clone["actions"] == []
    assert not repo.delete("bob", agent_id)
    assert repo.delete("alice", agent_id)
    assert repo.versions("alice", agent_id) is None
    with repo.database.connect() as db:
        assert db.execute("SELECT count(*) FROM agent_versions WHERE agent_id=?", (agent_id,)).fetchone()[0] == 0


def test_agent_query_cursor_and_allowlist(tmp_path):
    repo = AgentRepository(SQLiteDatabase(tmp_path))
    for i in range(5):
        repo.create("local", {"name": f"NJU Agent {i}", "category": "research", "provider": "openAI",
                              "api_key": "secret-should-never-be-persisted", "password": "secret"})
    seen = []
    cursor = None
    while True:
        page = repo.list("local", limit=2, cursor=cursor, category="research")
        seen.extend(item["id"] for item in page["data"])
        assert all("api_key" not in item and "password" not in item for item in page["data"])
        if not page["has_more"]:
            break
        cursor = page["after"]
    assert len(set(seen)) == 5
    assert len(repo.list("local", search="NJU")["data"]) == 5
    assert repo.list("local", category="tools")["data"] == []
    with pytest.raises(ValueError):
        repo.create("local", {"name": "Missing provider"})
    with pytest.raises(ValueError):
        repo.create("local", {"name": "Invalid tools", "provider": "openAI", "tools": "not list"})


@pytest.mark.asyncio
async def test_agent_http_routes_enforce_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(state_dir=tmp_path, auth_mode="oauth"))
    monkeypatch.setattr(agent_routes, "get_settings", lambda: SimpleNamespace(state_dir=tmp_path, auth_mode="oauth"), raising=False)
    from local_shell_mcp import settings
    monkeypatch.setattr(settings, "get_settings", lambda: SimpleNamespace(state_dir=tmp_path, auth_mode="oauth"))
    app = Starlette(routes=agent_routes.agent_routes())

    async def principal(scope, receive, send):
        if scope.get("type") == "http":
            who = next((v.decode() for k,v in scope.get("headers", []) if k == b"x-test-principal"), None)
            if who:
                scope.setdefault("state", {})["principal"] = SimpleNamespace(subject=who)
        await app(scope, receive, send)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=principal), base_url="http://lsm") as client:
        alice = {"x-test-principal": "alice"}
        bob = {"x-test-principal": "bob"}
        assert (await client.get("/api/agents")).status_code == 401
        response = await client.post("/api/agents", headers=alice, json={"provider": "openAI", "name": "Research"})
        assert response.status_code == 201, response.text
        aid = response.json()["id"]
        assert (await client.get(f"/api/agents/{aid}", headers=bob)).status_code == 404
        assert len((await client.get("/api/agents", headers=alice)).json()["data"]) == 1
        assert (await client.patch(f"/api/agents/{aid}", headers=bob, json={"name": "Broken"})).status_code == 404
        assert (await client.patch(f"/api/agents/{aid}", headers=alice, json={"name": "Updated"})).json()["version"] == 2
        assert len((await client.get(f"/api/agents/{aid}/versions", headers=alice)).json()) == 2
        assert (await client.delete(f"/api/agents/{aid}", headers=bob)).status_code == 404
        assert (await client.delete(f"/api/agents/{aid}", headers=alice)).status_code == 200
