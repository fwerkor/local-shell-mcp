"""Review regressions for file listing permissions and cloned attachment ownership."""

from __future__ import annotations

import json

import httpx
import pytest
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware

from local_shell_mcp.auth import Principal
from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import attachments, conversation_routes
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.file_deletion import AttachmentDeletionStore
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.storage import WorkspaceRepository
from local_shell_mcp.webui.tool_attachments import link_tool_attachment


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    database = SQLiteDatabase(tmp_path / ".local-shell-mcp")
    repository = WorkspaceRepository(database)
    monkeypatch.setattr(attachments, "_repo", lambda: repository)
    monkeypatch.setattr(conversation_routes, "_repo", lambda: repository)
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(database.root))
    get_settings.cache_clear()
    yield database
    get_settings.cache_clear()


def saved_file(database, ident="file-source"):
    path = attachments._safe_attachment_path("alice", ident + ".txt", database.root)
    path.write_bytes(b"immutable original document")
    with database.connect() as db:
        db.execute(
            "INSERT INTO attachments(id,owner,name,path,content_type,metadata) VALUES(?,?,?,?,?,?)",
            (ident, "alice", ident + ".txt", str(path), "text/plain",
             json.dumps({"status": "ready", "text": "protected preview", "textFormat": "text"})),
        )
    return path


@pytest.mark.asyncio
async def test_agent_file_listing_requires_read_scope_like_other_file_routes(workspace):
    agent = AgentRepository(workspace).create("alice", {"name": "Reader", "provider": "openAI", "model": None})
    saved_file(workspace)
    AgentRepository(workspace).add_resource_file("alice", agent["id"], "context", "file-source")

    async def principal(request, call_next):
        request.state.principal = Principal(None, request.headers.get("x-owner", "alice"), {
            "auth": "oauth", "scope": request.headers.get("x-scope", "browser:use"),
        })
        return await call_next(request)

    app = Starlette(routes=attachments.attachment_routes())
    app.add_middleware(BaseHTTPMiddleware, dispatch=principal)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        url = "/api/files/agent/" + agent["id"]
        for route in (url, "/api/files", "/api/files/file-source/preview"):
            forbidden = await client.get(route, headers={"x-scope": "browser:use"})
            assert forbidden.status_code == 403, (route, forbidden.text)
        allowed = await client.get(url, headers={"x-scope": "shell:read"})
        assert allowed.status_code == 200 and allowed.json()[0]["file_id"] == "file-source"
        assert allowed.json()[0]["text"] == "protected preview"
        foreign = await client.get(url, headers={"x-scope": "shell:read", "x-owner": "bob"})
        assert foreign.status_code == 200 and foreign.json() == []


def test_duplicate_and_fork_keep_canonical_tool_links_without_reviving_deleted_files(workspace):
    original = saved_file(workspace)
    generations = GenerationStore(workspace)
    generation, _ = generations.begin("alice", {"text": "Produce an attachment"})
    generations.append("alice", generation.run_id, {
        "event": "on_run_step", "data": {"id": "step-source", "stepDetails": {
            "type": "tool_calls", "tool_calls": [{"id": "source-call", "name": "file_write", "args": {}}],
        }},
    })
    link_tool_attachment(workspace, "alice", generation.run_id, "source-call", "file-source")
    assert generations.finish("alice", generation.run_id, status="complete", text="Attached")
    source = generation.conversation_id

    duplicate = conversation_routes._clone("alice", {"conversationId": source})
    fork = conversation_routes._clone("alice", {"conversationId": source},
                                      only_to_message=generation.response_message_id)
    user_only = conversation_routes._clone("alice", {"conversationId": source},
                                           only_to_message=generation.user_message_id)
    assert len(user_only["messages"]) == 1

    repository = WorkspaceRepository(workspace)
    for copy in (duplicate, fork):
        assert copy["conversationId"] != source
        assistant = next(message for message in copy["messages"] if message["role"] == "assistant")
        assert len(assistant["attachments"]) == 1
        record = assistant["attachments"][0]
        assert record["file_id"] == "file-source"
        assert record["messageId"] == assistant["messageId"]
        assert record["conversationId"] == copy["conversationId"]
        assert record["toolCallId"] == "source-call"
        assert repository.messages("alice", copy["conversationId"])["messages"][-1]["attachments"] == [record]
        with workspace.connect() as db:
            assert db.execute("SELECT count(*) FROM tool_attachment_links l JOIN runs r ON r.id=l.run_id "
                              "WHERE r.conversation_id=?", (copy["conversationId"],)).fetchone()[0] == 1
            assert db.execute("SELECT status FROM runs WHERE conversation_id=?", (
                copy["conversationId"],)).fetchone()[0] == "complete"

    with workspace.connect() as db:
        assert db.execute("SELECT count(*) FROM tool_attachment_links l JOIN runs r ON r.id=l.run_id "
                          "WHERE r.conversation_id=?", (user_only["conversationId"],)).fetchone()[0] == 0
        db.execute("DELETE FROM conversations WHERE id=?", (source,))
    assert original.is_file()
    assert repository.messages("alice", duplicate["conversationId"])["messages"][-1]["attachments"]
    assert AttachmentDeletionStore(workspace).delete(["file-source"], owner="alice") == {
        "deletedFileIds": ["file-source"], "failedFileIds": [],
    }
    assert not original.exists()
    for copy in (duplicate, fork):
        assert repository.messages("alice", copy["conversationId"])["messages"][-1]["attachments"] == []
        latest = generations.latest("alice", copy["conversationId"])
        assert latest is not None and latest.status == "complete"
        assert latest.response_message_id == copy["messages"][-1]["messageId"]
        assert latest.user_message_id == copy["messages"][0]["messageId"]
    followup, fresh = generations.begin("alice", {
        "conversationId": duplicate["conversationId"], "text": "Continue the cloned conversation",
    })
    assert fresh and followup.conversation_id == duplicate["conversationId"]


def test_duplicate_ignores_expired_files_and_cannot_copy_foreign_conversation(workspace):
    repository = WorkspaceRepository(workspace)
    created = repository.create_conversation("alice", {"title": "Source"})
    # A copied legacy metadata snapshot must not fabricate a live link.
    repository.add_message("alice", created["conversationId"], {
        "role": "assistant", "text": "Old preview", "attachments": [{"file_id": "removed"}],
    })
    duplicate = conversation_routes._clone("alice", {"conversationId": created["conversationId"]})
    assert duplicate["messages"][-1]["attachments"] == []
    assert repository.messages("alice", duplicate["conversationId"])["messages"][-1]["attachments"] == []
    from starlette.exceptions import HTTPException

    with pytest.raises(HTTPException) as error:
        conversation_routes._clone("bob", {"conversationId": created["conversationId"]})
    assert error.value.status_code == 404
