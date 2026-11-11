"""LibreChat file-backed tool events: owner, replay, preview and deletion."""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware

from local_shell_mcp.auth import Principal
from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import attachments
from local_shell_mcp.webui.file_deletion import AttachmentDeletionStore
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.storage import WorkspaceRepository
from local_shell_mcp.webui.tool_attachments import (
    link_tool_attachment,
    response_attachments,
    update_attachment_preview,
)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    db = SQLiteDatabase(tmp_path / ".local-shell-mcp")
    monkeypatch.setattr(attachments, "_repo", lambda: SimpleNamespace(database=db))
    for key, value in {
        "WORKSPACE_ROOT": str(tmp_path),
        "STATE_DIR": str(db.root),
        "AUTH_MODE": "none",
    }.items():
        monkeypatch.setenv("LOCAL_SHELL_MCP_" + key, value)
    get_settings.cache_clear()
    yield db
    get_settings.cache_clear()


def file(db, ident, owner="alice", status="pending"):
    path = attachments._safe_attachment_path(owner, ident + ".txt", db.root)
    path.write_text("untrusted tool output", encoding="utf-8")
    with db.connect() as sql:
        sql.execute(
            "INSERT INTO attachments(id,owner,name,path,content_type,metadata) VALUES(?,?,?,?,?,?)",
            (ident, owner, ident + ".txt", str(path), "text/plain",
             json.dumps({"status": status, "machine": "local"}, ensure_ascii=False)),
        )
    return path


def run_with_step(db, owner="alice", tool_call_id="call-123"):
    generation, _ = GenerationStore(db).begin(owner, {"text": "Generate a file"})
    GenerationStore(db).append(owner, generation.run_id, {
        "event": "on_run_step", "data": {
            "id": "step-real", "stepDetails": {
                "type": "tool_calls", "tool_calls": [{
                    "id": tool_call_id, "name": "run_python", "args": {},
                }],
            },
        },
    })
    return generation


def test_link_emits_canonical_file_record_idempotently_and_replays_after_restart(workspace):
    path = file(workspace, "generated")
    run = run_with_step(workspace)
    item = link_tool_attachment(workspace, "alice", run.run_id, "call-123", "generated")
    assert item["file_id"] == "generated"
    assert item["messageId"] == run.response_message_id
    assert item["toolCallId"] == "call-123"
    assert item["conversationId"] == run.conversation_id
    assert item["status"] == "pending"
    assert item["filepath"] == "/api/files/download/generated"
    assert path.exists()
    assert link_tool_attachment(workspace, "alice", run.run_id, "call-123", "generated") is None
    events = GenerationStore(SQLiteDatabase(workspace.root)).events("alice", run.run_id)
    streamed = [value for _, value in events if value.get("event") == "attachment"]
    assert streamed == [{"event": "attachment", "data": item}]
    with workspace.connect() as sql:
        assert response_attachments(sql, "alice", [run.response_message_id])[run.response_message_id] == [item]


def test_link_rejects_cross_owner_run_file_and_unrecorded_call(workspace):
    file(workspace, "alice-file")
    file(workspace, "bob-file", owner="bob")
    run = run_with_step(workspace)
    with pytest.raises(PermissionError, match="run"):
        link_tool_attachment(workspace, "bob", run.run_id, "call-123", "alice-file")
    with pytest.raises(PermissionError, match="Tool call"):
        link_tool_attachment(workspace, "alice", run.run_id, "fake-call", "alice-file")
    with pytest.raises(PermissionError, match="Unowned"):
        link_tool_attachment(workspace, "alice", run.run_id, "call-123", "bob-file")
    with pytest.raises(ValueError):
        link_tool_attachment(workspace, "alice", run.run_id, "", "alice-file")
    with pytest.raises(PermissionError):
        link_tool_attachment(workspace, "alice", "fake-run", "call-123", "alice-file")
    with workspace.connect() as sql:
        assert sql.execute("SELECT count(*) FROM tool_attachment_links").fetchone()[0] == 0


def test_link_rejects_missing_or_replaced_bytes(workspace):
    path = file(workspace, "generated")
    run = run_with_step(workspace)
    path.unlink()
    with pytest.raises(OSError, match="unavailable"):
        link_tool_attachment(workspace, "alice", run.run_id, "call-123", "generated")


def test_pending_then_ready_updates_same_file_event_and_final_snapshot(workspace):
    file(workspace, "generated")
    run = run_with_step(workspace)
    link_tool_attachment(workspace, "alice", run.run_id, "call-123", "generated")
    result = update_attachment_preview(
        workspace, "alice", "generated", "ready", text="A\nB", text_format="text",
    )
    assert len(result) == 1
    assert result[0]["status"] == "ready"
    assert result[0]["text"] == "A\nB"
    records = [value for _, value in GenerationStore(workspace).events(
        "alice", run.run_id) if value.get("event") == "attachment"]
    assert len(records) == 2
    assert [record["data"]["status"] for record in records] == ["pending", "ready"]
    assert {record["data"]["file_id"] for record in records} == {"generated"}
    assert {record["data"]["toolCallId"] for record in records} == {"call-123"}
    assert GenerationStore(workspace).finish("alice", run.run_id, status="complete", text="Done.")
    final = GenerationStore(workspace).events("alice", run.run_id)[-1][1]
    assert final["responseMessage"]["attachments"] == [result[0]]
    messages = WorkspaceRepository(SQLiteDatabase(workspace.root)).messages(
        "alice", run.conversation_id)["messages"]
    assert messages[-1]["attachments"] == [result[0]]


def test_deferred_preview_updates_after_run_finish_and_reloads_history(workspace):
    file(workspace, "generated")
    run = run_with_step(workspace)
    link_tool_attachment(workspace, "alice", run.run_id, "call-123", "generated")
    GenerationStore(workspace).finish("alice", run.run_id, status="complete", text="Done.")
    before = len(GenerationStore(workspace).events("alice", run.run_id))
    event = update_attachment_preview(
        workspace, "alice", "generated", "ready", text="new text",
    )[0]
    assert len(GenerationStore(workspace).events("alice", run.run_id)) == before
    assert WorkspaceRepository(workspace).messages("alice", run.conversation_id)[
        "messages"][-1]["attachments"] == [event]
    with workspace.connect() as sql:
        metadata = json.loads(sql.execute(
            "SELECT metadata FROM messages WHERE id=?", (run.response_message_id,),
        ).fetchone()["metadata"])
    assert metadata["attachments"] == [event]


def test_preview_status_failure_does_not_expose_untrusted_html_or_cross_owner(workspace):
    file(workspace, "generated")
    run = run_with_step(workspace)
    link_tool_attachment(workspace, "alice", run.run_id, "call-123", "generated")
    with pytest.raises(ValueError):
        update_attachment_preview(workspace, "alice", "generated", "ready",
                                  text="<script>x</script>", text_format="html")
    with pytest.raises(ValueError):
        update_attachment_preview(workspace, "alice", "generated", "ready",
                                  text="x" * (128 * 1024 + 1))
    with pytest.raises(ValueError):
        update_attachment_preview(workspace, "alice", "generated", "failed", error="secrets")
    with pytest.raises(ValueError):
        update_attachment_preview(workspace, "alice", "generated", "pending", text="not ready")
    with pytest.raises(KeyError):
        update_attachment_preview(workspace, "bob", "generated", "failed", error="timeout")
    item = update_attachment_preview(workspace, "alice", "generated", "failed", error="timeout")[0]
    assert item["previewError"] == "timeout"
    assert item["status"] == "failed"
    with pytest.raises(ValueError):
        update_attachment_preview(workspace, "alice", "generated", "pending")
    with pytest.raises(ValueError):
        update_attachment_preview(workspace, "alice", "generated", "ready")


def test_global_deletion_cascades_all_live_links_and_history_never_resurrects(workspace):
    path = file(workspace, "generated")
    run = run_with_step(workspace)
    link_tool_attachment(workspace, "alice", run.run_id, "call-123", "generated")
    GenerationStore(workspace).finish("alice", run.run_id, status="complete", text="Done")
    assert AttachmentDeletionStore(workspace).delete(
        ["generated"], owner="alice")["deletedFileIds"] == ["generated"]
    assert not path.exists()
    with workspace.connect() as sql:
        assert sql.execute("SELECT count(*) FROM tool_attachment_links").fetchone()[0] == 0
    messages = WorkspaceRepository(workspace).messages("alice", run.conversation_id)["messages"]
    assert messages[-1]["attachments"] == []


@pytest.mark.asyncio
async def test_browser_preview_contract_owner_state_and_expiry(workspace):
    run = run_with_step(workspace)
    file(workspace, "generated")
    link_tool_attachment(workspace, "alice", run.run_id, "call-123", "generated")

    async def attach_principal(request, call_next):
        request.state.principal = Principal(None, request.headers.get("x-owner", "alice"), {"auth": "none"})
        return await call_next(request)

    app = Starlette(routes=attachments.attachment_routes())
    app.add_middleware(BaseHTTPMiddleware, dispatch=attach_principal)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/api/files/generated/preview")
        assert response.status_code == 200 and response.json() == {
            "file_id": "generated", "status": "pending",
        }
        assert "no-store" in response.headers["cache-control"]
        assert (await client.get("/api/files/generated/preview", headers={"x-owner": "bob"})).status_code == 404
        update_attachment_preview(workspace, "alice", "generated", "ready", text="clear text")
        assert (await client.get("/api/files/generated/preview")).json() == {
            "file_id": "generated", "status": "ready", "text": "clear text", "textFormat": "text",
        }
        assert (await client.get("/api/files/missing/preview")).status_code == 404
        assert AttachmentDeletionStore(workspace).delete(
            ["generated"], owner="alice")["deletedFileIds"] == ["generated"]
        assert (await client.get("/api/files/generated/preview")).status_code == 404


@pytest.mark.asyncio
async def test_real_agent_tool_completion_emits_owned_canonical_artifact_file(workspace):
    from local_shell_mcp.webui.agent_runner import AgentRunner
    from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig

    file(workspace, "generated")
    file(workspace, "foreign", owner="bob")
    generation = run_with_step(workspace)
    profile = ProviderConfig("openai", "mock", "https://example.invalid", "")
    async def silent(*args, **kwargs):
        return None
    runner = AgentRunner(
        "alice", generation, workspace, GenerationStore(workspace),
        scopes=frozenset(), grant_expires=None,
        stream_tools=silent, stream_text=silent, on_text=silent, profile=profile,
    )
    await runner._completed(ModelToolCall("call-123", "run_python", {}), {
        "output": {"artifact": {"files": [
            {"file_id": "generated", "name": "generated.txt"},
            {"file_id": "foreign", "name": "do-not-leak"},
            {"file_id": "generated", "name": "duplicate"},
            {"path": "/tmp/unauthorized.txt", "name": "ignored"},
        ]}},
    })
    records = [data["data"] for _, data in GenerationStore(workspace).events(
        "alice", generation.run_id) if data.get("event") == "attachment"]
    assert len(records) == 1
    assert records[0]["file_id"] == "generated"
    assert records[0]["toolCallId"] == "call-123"
    assert records[0]["messageId"] == generation.response_message_id


def test_tool_file_ids_require_structured_artifact_not_random_paths_or_text():
    from local_shell_mcp.webui.tool_attachments import controller_tool_file_ids

    assert controller_tool_file_ids("not valid json") == []
    assert controller_tool_file_ids('{"path":"/home/secret","file_id":"fake"}') == []
    assert controller_tool_file_ids({"artifact": {"files": "not-list"}}) == []
    assert controller_tool_file_ids({"artifact": {"files": [
        {"file_id": "one"}, {"file_id": "one"}, {"file_id": None},
        "/tmp/secret", {"path": "/tmp/secret"}, {"file_id": "two"},
    ]}}) == ["one", "two"]
    assert controller_tool_file_ids('{"data":{"artifact":{"files":[{"file_id":"nested"}]}}}') == [
        "nested",
    ]
    assert controller_tool_file_ids("{" + " " * (256 * 1024) + "}") == []


def test_attachment_only_final_message_is_persisted(workspace):
    file(workspace, "generated")
    generation = run_with_step(workspace)
    link_tool_attachment(workspace, "alice", generation.run_id, "call-123", "generated")
    assert GenerationStore(workspace).finish("alice", generation.run_id, status="complete", text="")
    messages = WorkspaceRepository(workspace).messages("alice", generation.conversation_id)["messages"]
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["attachments"][0]["file_id"] == "generated"


def test_agent_resource_unlink_preserves_tool_produced_message_reference(workspace):
    from local_shell_mcp.webui.agents import AgentRepository

    file_path = file(workspace, "generated")
    agent = AgentRepository(workspace).create(
        "alice", {"name": "Test", "provider": "openAI", "model": None},
    )
    AgentRepository(workspace).add_resource_file("alice", agent["id"], "context", "generated")
    run = run_with_step(workspace)
    link_tool_attachment(workspace, "alice", run.run_id, "call-123", "generated")
    outcome = AttachmentDeletionStore(workspace).delete(
        ["generated"], owner="alice", agent_id=agent["id"], resource="context",
    )
    assert outcome == {"deletedFileIds": [], "failedFileIds": []}
    assert file_path.exists()
    with workspace.connect() as sql:
        assert sql.execute("SELECT count(*) FROM tool_attachment_links").fetchone()[0] == 1
    assert AgentRepository(workspace).get(
        "alice", agent["id"])["tool_resources"]["context"]["file_ids"] == []


def test_agent_resource_unlink_preserves_historical_user_message_reference(workspace):
    from local_shell_mcp.webui.agents import AgentRepository

    path = file(workspace, "generated")
    agent = AgentRepository(workspace).create(
        "alice", {"name": "Test", "provider": "openAI", "model": None},
    )
    AgentRepository(workspace).add_resource_file("alice", agent["id"], "context", "generated")
    # begin publishes the user file reference and new message in the same
    # BEGIN IMMEDIATE transaction as a competing last-reference deletion.
    run, _ = GenerationStore(workspace).begin("alice", {
        "text": "Review", "files": [{"file_id": "generated"}],
    })
    outcome = AttachmentDeletionStore(workspace).delete(
        ["generated"], owner="alice", agent_id=agent["id"], resource="context",
    )
    assert outcome == {"deletedFileIds": [], "failedFileIds": []}
    assert path.exists()
    assert "Controller attachments" in GenerationStore(workspace).history(
        "alice", run.conversation_id)[0]["content"]
    # The owner is still allowed to delete globally; message history then
    # marks its missing file rather than exposing invalid filesystem bytes.
    assert AttachmentDeletionStore(workspace).delete(
        ["generated"], owner="alice")["deletedFileIds"] == ["generated"]
    assert "unavailable" in GenerationStore(workspace).history(
        "alice", run.conversation_id)[0]["content"]


def test_tool_completion_and_link_roll_back_together_on_database_fault(workspace):
    import sqlite3

    file(workspace, "generated")
    run = run_with_step(workspace)
    event = {
        "event": "on_run_step_completed",
        "data": {"result": {"id": "step-real", "tool_call": {"id": "call-123"}}},
    }
    store = GenerationStore(workspace)
    before = store.events("alice", run.run_id)
    with workspace.connect() as sql:
        sql.execute(
            "CREATE TRIGGER reject_link BEFORE INSERT ON tool_attachment_links "
            "BEGIN SELECT RAISE(ABORT,'injected fault'); END",
        )
    with pytest.raises(sqlite3.DatabaseError, match="injected fault"):
        store.append_tool_completion("alice", run.run_id, event, "call-123", ["generated"])
    assert store.events("alice", run.run_id) == before
    with workspace.connect() as sql:
        assert sql.execute("SELECT count(*) FROM tool_attachment_links").fetchone()[0] == 0
        sql.execute("DROP TRIGGER reject_link")
    store.append_tool_completion("alice", run.run_id, event, "call-123", ["generated"])
    attachments_for_run = [
        value for _, value in store.events("alice", run.run_id)
        if value.get("event") == "attachment"
    ]
    assert len(attachments_for_run) == 1
    assert attachments_for_run[0]["data"]["file_id"] == "generated"
    assert store.events("alice", run.run_id)[-2][1] == event
    events_before = store.events("alice", run.run_id)
    step = store.append_tool_completion("alice", run.run_id, event, "call-123", ["generated"])
    assert events_before == store.events("alice", run.run_id)
    assert step == events_before[-2][0]
    with pytest.raises(ValueError, match="Cannot change"):
        store.append_tool_completion("alice", run.run_id, {
            **event, "data": {"result": {**event["data"]["result"], "mutated": True}},
        }, "call-123", ["generated"])


def test_completed_tool_does_not_link_file_from_different_owner_during_atomic_append(workspace):
    file(workspace, "foreign", owner="bob")
    run = run_with_step(workspace)
    store = GenerationStore(workspace)
    event = {"event": "on_run_step_completed", "data": {"result": {
        "id": "step-real", "tool_call": {"id": "call-123"},
    }}}
    store.append_tool_completion("alice", run.run_id, event, "call-123", ["foreign"])
    assert [value for _, value in store.events("alice", run.run_id)
            if value.get("event") == "attachment"] == []
    with workspace.connect() as sql:
        assert sql.execute("SELECT count(*) FROM tool_attachment_links").fetchone()[0] == 0
