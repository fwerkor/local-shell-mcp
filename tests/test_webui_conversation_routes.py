"""Original LibreChat conversation and message lifecycle endpoints."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.webui import conversation_routes, routes


@pytest.mark.asyncio
async def test_archive_pin_update_duplicate_and_message_listing(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(auth_mode="none", state_dir=tmp_path))
    app = Starlette(routes=[*conversation_routes.conversation_routes(), *routes.webui_routes()])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        convo = (await client.post("/api/convos", json={"title": "Project chat"})).json()
        cid = convo["conversationId"]
        user = (await client.post(f"/api/messages/{cid}", json={"role": "user", "text": "Hello"})).json()
        (await client.post(f"/api/messages/{cid}", json={
            "role": "assistant", "text": "Hello there", "parentMessageId": user["messageId"],
        })).json()
        messages = await client.get(f"/api/messages/{cid}")
        assert isinstance(messages.json(), list)
        assert len(messages.json()) == 2
        assert messages.json()[1]["parentMessageId"] == user["messageId"]

        updated = await client.post("/api/convos/update", json={"arg": {"conversationId": cid, "title": "Renamed"}})
        assert updated.status_code == 200
        assert updated.json()["title"] == "Renamed"
        pinned = await client.post("/api/convos/pin", json={"arg": {"conversationId": cid, "pinned": True}})
        assert pinned.json()["pinned"] is True
        archived = await client.post("/api/convos/archive", json={"arg": {"conversationId": cid, "isArchived": True}})
        assert archived.json()["isArchived"] is True
        assert (await client.get("/api/convos", params={"isArchived": True})).json()["conversations"]
        duplicated = await client.post("/api/convos/duplicate", json={"conversationId": cid})
        assert duplicated.status_code == 201, duplicated.text
        duplicate_id = duplicated.json()["conversationId"]
        assert duplicate_id != cid
        duplicate_messages = (await client.get(f"/api/messages/{duplicate_id}")).json()
        assert len(duplicate_messages) == 2
        assert duplicate_messages[0]["messageId"] != user["messageId"]
        assert duplicate_messages[1]["parentMessageId"] == duplicate_messages[0]["messageId"]
        fork = await client.post("/api/convos/fork", json={
            "conversationId": cid, "targetMessageId": user["messageId"],
        })
        assert fork.status_code == 201
        assert len((await client.get(f"/api/messages/{fork.json()['conversationId']}")).json()) == 1
        assert (await client.get(f"/api/convos/gen_title/{cid}")).json()["title"] == "Renamed"
        assert (await client.post("/api/convos/archive/all", json={})).json()["success"] is True
        cleared = await client.delete("/api/convos/all")
        assert cleared.json()["deletedCount"] == 3
        assert (await client.get("/api/convos")).json()["conversations"] == []


@pytest.mark.asyncio
async def test_conversation_mutations_cannot_read_another_users_messages(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(auth_mode="oauth", state_dir=tmp_path))
    app = Starlette(routes=[*conversation_routes.conversation_routes(), *routes.webui_routes()])

    async def as_owner(scope, receive, send):
        if scope.get("type") == "http":
            name = next((v.decode() for k, v in scope.get("headers", []) if k == b"x-test-owner"), None)
            if name:
                scope.setdefault("state", {})["principal"] = SimpleNamespace(subject=name)
        await app(scope, receive, send)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=as_owner), base_url="http://localhost") as client:
        alice = {"x-test-owner": "alice"}
        bob = {"x-test-owner": "bob"}
        cid = (await client.post("/api/convos", json={"title": "Private"}, headers=alice)).json()["conversationId"]
        user = (await client.post(f"/api/messages/{cid}", json={"role": "user", "text": "Private content"}, headers=alice)).json()
        assert (await client.post("/api/convos/duplicate", json={"conversationId": cid}, headers=bob)).status_code == 404
        assert (await client.post("/api/convos/fork", json={"conversationId": cid,
              "targetMessageId": user["messageId"]}, headers=bob)).status_code == 404
        assert (await client.post("/api/convos/pin", json={"arg": {"conversationId": cid}}, headers=bob)).status_code == 404
        assert (await client.get(f"/api/messages/{cid}", headers=bob)).status_code == 404
        assert (await client.delete("/api/convos/all", headers=bob)).json()["deletedCount"] == 0
        assert (await client.get(f"/api/convos/{cid}", headers=alice)).status_code == 200
