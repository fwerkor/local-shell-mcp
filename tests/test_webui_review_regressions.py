"""Retained React payloads, branch graphs and server-boundary regressions."""
import json
from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route

from local_shell_mcp import auth
from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import generation_routes, routes
from local_shell_mcp.webui.conversation_routes import conversation_routes
from local_shell_mcp.webui.frontend import frontend_routes
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ProviderConfig, selected_provider
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.fixture
def repository(tmp_path, monkeypatch):
    config = SimpleNamespace(auth_mode="none", state_dir=tmp_path)
    monkeypatch.setattr(routes, "get_settings", lambda: config)
    return WorkspaceRepository(SQLiteDatabase(tmp_path))


@pytest.mark.parametrize("endpoint", ["anthropic", "google", "gemini", "openai"])
async def test_direct_provider_and_client_project_payload(repository, monkeypatch, endpoint):
    db = repository.database
    project = repository.create_project("local", "Client project")["id"]
    monkeypatch.setattr(generation_routes, "_database", lambda: db)
    monkeypatch.setattr(generation_routes, "_generation_store", lambda: GenerationStore(db))
    chosen = []
    monkeypatch.setattr(generation_routes, "provider_config", lambda kind, model: (
        chosen.append(kind) or ProviderConfig(kind, model or "test", "http://localhost/test", "test")
    ))
    async def no_network(*args, **kwargs):
        pass
    monkeypatch.setattr(generation_routes, "_start_task", no_network)
    app = Starlette(routes=generation_routes.generation_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/agents/chat/{endpoint}", json={
            "conversationId": "new", "text": "Hello", "model": "test",
            "endpoint": endpoint, "chatProjectId": project,
        })
    assert response.status_code == 202, response.text
    assert chosen == [endpoint]
    cid = response.json()["conversationId"]
    assert repository.conversation("local", cid)["chatProjectId"] == project
    with db.connect() as connection:
        state = json.loads(connection.execute("SELECT state FROM runs WHERE conversation_id=?", (cid,)).fetchone()[0])
    assert state["provider"] == endpoint
    assert selected_provider({"endpoint": "agents"}) == "openai"
    assert selected_provider({"endpoint": endpoint}, {"provider": "openai"}) == "openai"


def test_history_follows_active_ancestry_and_rejects_foreign_parent(repository):
    store = GenerationStore(repository.database)
    initial, _ = store.begin("local", {"text": "old root", "messageId": "old"})
    store.finish("local", initial.run_id, status="complete", text="old response")
    edited, _ = store.begin("local", {"text": "edited root", "messageId": "edit",
        "conversationId": initial.conversation_id,
        "parentMessageId": "00000000-0000-0000-0000-000000000000"})
    assert store.history("local", initial.conversation_id, message_id="edit") == [
        {"role": "user", "content": "edited root"}]
    store.finish("local", edited.run_id, status="complete", text="edited response")
    next_turn, _ = store.begin("local", {"text": "continue", "messageId": "next",
        "conversationId": initial.conversation_id, "parentMessageId": edited.response_message_id})
    assert [m["content"] for m in store.history("local", initial.conversation_id,
        message_id=next_turn.user_message_id)] == ["edited root", "edited response", "continue"]
    assert len(store.history("local", initial.conversation_id, max_messages=1, message_id="next")) == 1
    with pytest.raises(KeyError):
        store.history("other", initial.conversation_id, message_id="next")
    with repository.database.connect() as db:
        db.execute("UPDATE messages SET parent_id=id WHERE id='next'")
    with pytest.raises(ValueError, match="cycle"):
        store.history("local", initial.conversation_id, message_id="next")
    with repository.database.connect() as db:
        db.execute("UPDATE messages SET parent_id='missing' WHERE id='next'")
    with pytest.raises(KeyError, match="ancestor"):
        store.history("local", initial.conversation_id, message_id="next")


async def test_full_graph_and_fork_root_sentinel(repository):
    cid = repository.create_conversation("local", {"title": "Long graph"})["conversationId"]
    parent = "00000000-0000-0000-0000-000000000000"
    for index in range(205):
        mid = f"message-{index}"
        repository.add_message("local", cid, {"messageId": mid, "parentMessageId": parent,
            "text": str(index), "isCreatedByUser": True})
        parent = mid
    app = Starlette(routes=[*conversation_routes(), *routes.webui_routes()])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/messages/{cid}")
        assert response.status_code == 200
        assert len(response.json()) == 205
        fork = await client.post("/api/convos/fork", json={"conversationId": cid,
            "targetMessageId": "message-1"})
        assert fork.status_code == 201, fork.text
        result = await client.get(f"/api/messages/{fork.json()['conversationId']}")
        assert [m["text"] for m in result.json()] == ["0", "1"]


async def test_spa_does_not_intercept_mcp_or_other_inner_routes():
    async def inner(request):
        return PlainTextResponse("native MCP stream")
    app = Starlette(routes=[*frontend_routes(), Mount("/", app=Starlette(routes=[
        Route("/mcp", inner), Route("/other", inner)]))])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for path in ["/mcp", "/other"]:
            response = await client.get(path)
            assert response.status_code == 200
            assert response.text == "native MCP stream"


def test_controller_alias_rejects_cross_origin_none_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        request = Request({"type": "http", "method": "POST",
            "path": "/api/lsm/controller/files/write", "scheme": "http",
            "server": ("localhost", 8000), "client": ("203.0.113.10", 1234),
            "headers": [(b"host", b"localhost:8000"), (b"origin", b"https://evil.example")]})
        with pytest.raises(HTTPException) as error:
            auth.verify_request(request)
        assert error.value.status_code == 401
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("identifier", ["ask_user", "ask_user_question"])
def test_retained_agent_ask_user_identifier_survives_restart(repository, identifier):
    job, _ = GenerationStore(repository.database).begin("local", {"text": "question"},
        {"tools": [identifier]})
    with repository.database.connect() as db:
        state = json.loads(db.execute("SELECT state FROM runs WHERE id=?", (job.run_id,)).fetchone()[0])
    assert state["askUserEnabled"] is True


async def test_large_attachment_uses_streaming_exemption(repository, monkeypatch):
    from local_shell_mcp.webui import attachments

    monkeypatch.setattr(attachments, "_repo", lambda: repository)
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(repository.database.root))
    get_settings.cache_clear()
    try:
        app = auth.RequestBodyLimitMiddleware(Starlette(routes=attachments.attachment_routes()))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/lsm/controller/attachments/upload?name=large.txt",
                                         content=b"a" * (17 * 1024 * 1024))
        assert response.status_code == 200, response.text
        assert response.json()["data"]["size"] == 17 * 1024 * 1024
    finally:
        get_settings.cache_clear()
