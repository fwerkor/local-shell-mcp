"""Original artifact editor route: ownership, durable edits and failure atomicity."""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.webui import routes
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.fixture
def artifact_app(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(auth_mode="oauth", state_dir=tmp_path))
    repo = routes._repo()
    convo = repo.create_conversation("alice", {"title": "Artifacts"})
    message = repo.add_message("alice", convo["conversationId"], {
        "role": "assistant", "text": "Keep this top-level value",
        "content": [{"type": "text", "text": 'before 😀\n:::artifact{identifier="code"}\n```html\n<p>old</p>\n```\n:::'}],
        "userSubmittedPaths": ["bad", None, "/earlier", "/earlier", "/" + "x" * 2048, "/" + "😀" * 1024],
        "toolCallMetadata": {"keep": True},
    })
    application = Starlette(routes=routes.webui_routes())

    async def authenticated(scope, receive, send):
        owner = next((value.decode() for key, value in scope.get("headers", []) if key == b"x-owner"), None)
        if owner:
            scope.setdefault("state", {})["principal"] = SimpleNamespace(subject=owner)
        await application(scope, receive, send)

    return repo, convo, message, authenticated


@pytest.mark.asyncio
async def test_original_editor_contract_persists_only_selected_text(artifact_app):
    repo, convo, message, app = artifact_app
    endpoint = "/api/messages/artifact/" + message["messageId"]
    body = {"index": 0, "original": "<p>old</p>", "updated": "<p>new 🚀</p>"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post(endpoint, json=body)).status_code == 401
        assert (await client.post(endpoint, headers={"x-owner": "bob"}, json=body)).status_code == 404
        assert (await client.post("/api/messages/artifact/missing", headers={"x-owner": "alice"}, json=body)).status_code == 404
        response = await client.post(endpoint, headers={"x-owner": "alice"}, json=body)
        assert response.status_code == 200, response.text
        assert response.json() == {"conversationId": convo["conversationId"], "text": message["text"],
                                   "content": [{"type": "text", "text": message["content"][0]["text"].replace("old", "new 🚀")}]}
        reloaded = WorkspaceRepository(repo.database).messages("alice", convo["conversationId"])["messages"][0]
        assert reloaded["content"] == response.json()["content"]
        assert reloaded["userSubmittedPaths"] == ["/earlier", "/content/0/text"]
        assert reloaded["toolCallMetadata"] == {"keep": True}
        again = await client.post(endpoint, headers={"x-owner": "alice"}, json={**body, "original": "new 🚀", "updated": "next"})
        assert again.status_code == 200
        assert repo.messages("alice", convo["conversationId"])["messages"][0]["userSubmittedPaths"] == ["/earlier", "/content/0/text"]


@pytest.mark.asyncio
async def test_invalid_edit_and_sql_failure_never_partially_change_message(artifact_app):
    repo, convo, message, app = artifact_app
    endpoint = "/api/messages/artifact/" + message["messageId"]
    body = {"index": 0, "original": "old", "updated": "new"}
    before = repo.messages("alice", convo["conversationId"])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"x-owner": "alice"}) as client:
        for change in ({"index": -1}, {"index": True}, {"index": 0.5}, {"index": "0"}, {"original": None}, {"updated": {}}, {"index": 1}, {"original": "absent"}):
            assert (await client.post(endpoint, json={**body, **change})).status_code == 400
            assert repo.messages("alice", convo["conversationId"]) == before
        with repo.database.connect() as db:
            db.execute("CREATE TRIGGER fail_artifact BEFORE UPDATE ON messages BEGIN SELECT RAISE(ABORT,'simulated disk failure'); END")
        response = await client.post(endpoint, json=body)
        assert response.status_code == 500 and response.json() == {"error": "Internal server error"}
        assert repo.messages("alice", convo["conversationId"]) == before
        with repo.database.connect() as db:
            db.execute("DROP TRIGGER fail_artifact")
        assert (await client.post(endpoint, json=body)).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("reserved", [False, True])
async def test_child_thread_artifacts_remain_view_only(artifact_app, reserved):
    repo, _, _, app = artifact_app
    payload = {"subagentThread": {"parentConversationId": "parent"}} if not reserved else {"conversationId": "12345678-1234-8123-b123-123456789abc"}
    convo = repo.create_conversation("alice", payload)
    message = repo.add_message("alice", convo["conversationId"], {"text": ":::artifact\nold\n:::"})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"x-owner": "alice"}) as client:
        response = await client.post("/api/messages/artifact/" + message["messageId"], json={"index": 0, "original": "old", "updated": "changed"})
        assert response.status_code == 409
        assert repo.messages("alice", convo["conversationId"])["messages"][0]["text"] == message["text"]


@pytest.mark.asyncio
async def test_legacy_text_artifact_edits_preserve_metadata(artifact_app):
    repo, convo, _, app = artifact_app
    message = repo.add_message("alice", convo["conversationId"], {"text": ":::artifact\n$14\n:::", "userSubmittedPaths": None})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"x-owner": "alice"}) as client:
        response = await client.post("/api/messages/artifact/" + message["messageId"], json={"index": 0, "original": r"\$14", "updated": "$20"})
        assert response.status_code == 200
        assert response.json()["text"] == ":::artifact\n$20\n:::"
        with repo.database.connect() as db:
            row = db.execute("SELECT metadata FROM messages WHERE id=?", (message["messageId"],)).fetchone()
        assert json.loads(row["metadata"])["userSubmittedPaths"] == ["/text"]
