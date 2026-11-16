"""Integration and concurrency regressions for the SQLite attachment lifecycle."""
from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware

from local_shell_mcp.auth import Principal
from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import attachments
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.file_deletion import AttachmentDeletionStore


def _blob(database, ident="file-race"):
    path = attachments._safe_attachment_path("alice", ident + ".txt", database.root)
    path.write_bytes(b"real file bytes")
    with database.connect() as db:
        db.execute("INSERT INTO attachments(id,owner,name,path,content_type,metadata) "
                   "VALUES(?,?,?,?,?,?)", (ident, "alice", ident, str(path), "text/plain", "{}"))
    return path


def _agent(database):
    return AgentRepository(database).create("alice", {"name": "File Agent", "provider": "openAI", "model": None})["id"]


def _bind_worker(state_dir, agent_id, file_id, queue):
    try:
        db = SQLiteDatabase(Path(state_dir))
        AgentRepository(db).add_resource_file("alice", agent_id, "context", file_id)
        queue.put("ok")
    except Exception as exc:  # pragma: no cover - assertion in parent
        queue.put(repr(exc))


def _delete_worker(state_dir, agent_id, file_id, queue):
    try:
        db = SQLiteDatabase(Path(state_dir))
        result = AttachmentDeletionStore(db).delete([file_id], owner="alice",
                                                     agent_id=agent_id, resource="context")
        queue.put(result)
    except Exception as exc:  # pragma: no cover - assertion in parent
        queue.put(repr(exc))


def test_cross_process_resource_added_after_intent_before_final_check(tmp_path, monkeypatch):
    database = SQLiteDatabase(tmp_path)
    path = _blob(database)
    first, second = _agent(database), _agent(database)
    repository = AgentRepository(database)
    repository.add_resource_file("alice", first, "context", "file-race")
    store = AttachmentDeletionStore(database)
    finish = store._finish
    launched = []

    def concurrent_reference(ident, owner, agent_id, resource):
        assert len(launched) == 0
        ctx = multiprocessing.get_context("spawn")
        queue = ctx.Queue()
        process = ctx.Process(target=_bind_worker, args=(str(tmp_path), second, ident, queue))
        process.start()
        process.join(timeout=20)
        assert process.exitcode == 0
        assert queue.get(timeout=3) == "ok"
        launched.append(True)
        return finish(ident, owner, agent_id, resource)

    monkeypatch.setattr(store, "_finish", concurrent_reference)
    assert store.delete(["file-race"], owner="alice", agent_id=first, resource="context") == {
        "deletedFileIds": [], "failedFileIds": [],
    }
    assert path.read_bytes() == b"real file bytes"
    assert repository.get("alice", first)["tool_resources"]["context"]["file_ids"] == []
    assert repository.get("alice", second)["tool_resources"]["context"]["file_ids"] == ["file-race"]
    with database.connect() as db:
        assert not db.execute("SELECT 1 FROM attachment_deletions").fetchone()


def test_parallel_resource_deletes_use_cross_process_lock(tmp_path):
    database = SQLiteDatabase(tmp_path)
    path = _blob(database)
    first, second = _agent(database), _agent(database)
    for agent_id in (first, second):
        AgentRepository(database).add_resource_file("alice", agent_id, "context", "file-race")
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    procs = [ctx.Process(target=_delete_worker, args=(str(tmp_path), identity, "file-race", queue))
             for identity in (first, second)]
    for process in procs:
        process.start()
    for process in procs:
        process.join(timeout=20)
        assert process.exitcode == 0
    results = [queue.get(timeout=3) for _ in procs]
    assert all(isinstance(result, dict) for result in results), results
    assert sum(len(result["deletedFileIds"]) for result in results) == 1
    assert not path.exists()
    with database.connect() as db:
        assert db.execute("SELECT count(*) FROM attachments").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM attachment_deletions").fetchone()[0] == 0


def test_failed_commit_after_rename_recovers_without_stranding_reference(tmp_path, monkeypatch):
    database = SQLiteDatabase(tmp_path)
    path = _blob(database)
    owner_agent = _agent(database)
    AgentRepository(database).add_resource_file("alice", owner_agent, "context", "file-race")
    store = AttachmentDeletionStore(database)

    def refuse(_ident, _db):
        raise OSError("fault after rename, before SQLite commit")

    monkeypatch.setattr(store, "_commit_metadata", refuse)
    assert store.delete(["file-race"], owner="alice", agent_id=owner_agent, resource="context") == {
        "deletedFileIds": [], "failedFileIds": ["file-race"],
    }
    assert path.read_bytes() == b"real file bytes"
    assert AgentRepository(database).get("alice", owner_agent)["tool_resources"]["context"]["file_ids"] == [
        "file-race",
    ]
    assert not list(path.parent.glob(".delete-*"))


def test_recovery_fails_closed_when_original_and_quarantine_absent(tmp_path):
    database = SQLiteDatabase(tmp_path)
    path = _blob(database)
    quarantine = path.with_name(".delete-interrupted")
    with database.connect() as db:
        db.execute("INSERT INTO attachment_deletions(file_id,owner,original_path,quarantine_path,phase) "
                   "VALUES(?,?,?,?,'prepared')", ("file-race", "alice", str(path), str(quarantine)))
    path.unlink()
    assert AttachmentDeletionStore(database).recover() == {
        "recoveredFileIds": [], "failedFileIds": ["file-race"],
    }
    with database.connect() as db:
        assert db.execute("SELECT 1 FROM attachment_deletions WHERE file_id='file-race'").fetchone()


def test_recovery_finishes_same_inode_after_hardlink_restore_crash(tmp_path):
    database = SQLiteDatabase(tmp_path)
    path = _blob(database)
    quarantine = path.with_name(".delete-interrupted")
    with database.connect() as db:
        db.execute("INSERT INTO attachment_deletions(file_id,owner,original_path,quarantine_path,phase) "
                   "VALUES(?,?,?,?,'prepared')", ("file-race", "alice", str(path), str(quarantine)))
    os.replace(path, quarantine)
    os.link(quarantine, path)
    assert AttachmentDeletionStore(database).recover()["recoveredFileIds"] == ["file-race"]
    assert path.read_bytes() == b"real file bytes"
    assert not quarantine.exists()


@pytest.fixture
def app(tmp_path, monkeypatch):
    for name, value in {"WORKSPACE_ROOT": str(tmp_path), "STATE_DIR": str(tmp_path / ".local-shell-mcp"),
                        "AUTH_MODE": "none", "DISABLE_LOCAL": "false"}.items():
        monkeypatch.setenv("LOCAL_SHELL_MCP_" + name, value)
    get_settings.cache_clear()
    database = SQLiteDatabase(tmp_path / ".local-shell-mcp")
    monkeypatch.setattr(attachments, "_repo", lambda: SimpleNamespace(database=database))

    async def identity(request, call_next):
        request.state.principal = Principal(None, request.headers.get("x-owner", "alice"), {"auth": "none"})
        return await call_next(request)

    service = Starlette(routes=attachments.attachment_routes())
    service.add_middleware(BaseHTTPMiddleware, dispatch=identity)
    yield database, service
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_agent_context_file_upload_is_processed_and_referenced_in_one_transaction(app):
    database, service = app
    identity = _agent(database)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(service), base_url="http://test") as client:
        result = await client.post("/api/files", data={"agent_id": identity, "tool_resource": "context"},
                                   files={"file": ("notes.txt", b"A project-specific fact", "text/plain")})
        assert result.status_code == 200, result.text
        file_id = result.json()["file_id"]
        files = (await client.get("/api/files")).json()
        assert [f["file_id"] for f in files] == [file_id]
        assert "extracted_text" not in files[0]
        assert (await client.get("/api/files/agent/" + identity)).json()[0]["file_id"] == file_id
        assert (await client.get("/api/files/download/" + file_id)).content == b"A project-specific fact"
    agent = AgentRepository(database).get("alice", identity)
    assert file_id in agent["tool_resources"]["context"]["file_ids"]
    context = attachments.agent_context_messages(database, "alice", agent)
    assert len(context) == 1 and "A project-specific fact" in context[0]["content"]
    assert "Controller path:" in context[0]["content"]
    with database.connect() as db:
        row = db.execute("SELECT path,metadata FROM attachments WHERE id=?", (file_id,)).fetchone()
    assert Path(row["path"]).is_file()
    assert json.loads(row["metadata"])["processed"] is True


@pytest.mark.asyncio
async def test_unsupported_rag_ocr_and_binary_context_do_not_publish_false_success(app):
    database, service = app
    identity = _agent(database)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(service), base_url="http://test") as client:
        for resource, name, mime in [
            ("file_search", "knowledge.txt", "text/plain"),
            ("ocr", "scan.png", "image/png"),
            ("execute_code", "code.py", "text/plain"),
            ("context", "scan.png", "image/png"),
        ]:
            response = await client.post("/api/files",
                                         data={"agent_id": identity, "tool_resource": resource},
                                         files={"file": (name, b"not an extracted document", mime)})
            assert response.status_code == 501, (resource, response.text)
        missing = await client.post("/api/files",
                                    data={"agent_id": "absent", "tool_resource": "context"},
                                    files={"file": ("notes.txt", b"valid", "text/plain")})
        assert missing.status_code == 404
        foreign = await client.post("/api/files",
                                    data={"agent_id": identity, "tool_resource": "context"},
                                    files={"file": ("notes.txt", b"valid", "text/plain")},
                                    headers={"Origin": "https://evil.invalid"})
        assert foreign.status_code == 403
    with database.connect() as db:
        assert db.execute("SELECT count(*) FROM attachments").fetchone()[0] == 0
    assert not list((database.root / "attachments").rglob("*-notes.txt"))


def test_deletion_rejects_foreign_or_missing_agent_and_requires_owner(tmp_path):
    database = SQLiteDatabase(tmp_path)
    path = _blob(database)
    store = AttachmentDeletionStore(database)
    with pytest.raises(ValueError):
        store.delete(["file-race"])
    with pytest.raises(KeyError):
        store.delete(["file-race"], owner="alice", agent_id="unknown", resource="context")
    assert store.delete(["file-race"], owner="bob") == {
        "deletedFileIds": [], "failedFileIds": ["file-race"],
    }
    assert path.exists()


def test_agent_unlinks_stale_metadata_without_trying_filesystem(tmp_path):
    database = SQLiteDatabase(tmp_path)
    first = _agent(database)
    with database.connect() as db:
        row = db.execute("SELECT config FROM agents WHERE id=?", (first,)).fetchone()
        config = json.loads(row["config"])
        config["tool_resources"] = {"context": {"file_ids": ["file-stale"]}}
        db.execute("UPDATE agents SET config=? WHERE id=?", (json.dumps(config), first))
    assert AttachmentDeletionStore(database).delete(
        ["file-stale"], owner="alice", agent_id=first, resource="context",
    ) == {"deletedFileIds": [], "failedFileIds": []}
    assert AgentRepository(database).get("alice", first)["tool_resources"]["context"]["file_ids"] == []


def test_deletion_pending_intent_refuses_second_request(tmp_path):
    database = SQLiteDatabase(tmp_path)
    path = _blob(database)
    quarantine = path.with_name(".delete-pending")
    with database.connect() as db:
        db.execute("INSERT INTO attachment_deletions(file_id,owner,original_path,quarantine_path,phase) "
                   "VALUES(?,?,?,?,'prepared')", ("file-race", "alice", str(path), str(quarantine)))
    assert AttachmentDeletionStore(database).delete(["file-race"], owner="alice") == {
        "deletedFileIds": [], "failedFileIds": ["file-race"],
    }
    assert path.exists()
    assert AttachmentDeletionStore(database).recover()["recoveredFileIds"] == ["file-race"]


def test_recovery_keeps_unsafe_quarantine_intent_and_bytes(tmp_path):
    database = SQLiteDatabase(tmp_path)
    path = _blob(database)
    quarantine = path.with_name("wrong-quarantine-name")
    with database.connect() as db:
        db.execute("INSERT INTO attachment_deletions(file_id,owner,original_path,quarantine_path,phase) "
                   "VALUES(?,?,?,?,'prepared')", ("file-race", "alice", str(path), str(quarantine)))
    assert AttachmentDeletionStore(database).recover()["failedFileIds"] == ["file-race"]
    assert path.read_bytes() == b"real file bytes"


def test_deletion_final_check_refuses_metadata_path_reassignment(tmp_path, monkeypatch):
    database = SQLiteDatabase(tmp_path)
    path = _blob(database)
    original_finish = AttachmentDeletionStore._finish

    def move_metadata(self, ident, owner, agent_id, resource):
        with database.connect() as db:
            db.execute("UPDATE attachments SET path=? WHERE id=?", (
                str(path.with_name("reassigned.txt")), ident))
        return original_finish(self, ident, owner, agent_id, resource)

    monkeypatch.setattr(AttachmentDeletionStore, "_finish", move_metadata)
    assert AttachmentDeletionStore(database).delete(["file-race"], owner="alice") == {
        "deletedFileIds": [], "failedFileIds": ["file-race"],
    }
    assert path.read_bytes() == b"real file bytes"
    with database.connect() as db:
        assert db.execute("SELECT count(*) FROM attachment_deletions").fetchone()[0] == 0


def test_deletion_final_check_detects_quarantine_collision(tmp_path, monkeypatch):
    database = SQLiteDatabase(tmp_path)
    path = _blob(database)
    original_finish = AttachmentDeletionStore._finish
    collision = []

    def add_collision(self, ident, owner, agent_id, resource):
        with database.connect() as db:
            row = db.execute("SELECT quarantine_path FROM attachment_deletions WHERE file_id=?",
                             (ident,)).fetchone()
        quarantine = Path(row["quarantine_path"])
        quarantine.write_text("external")
        collision.append(quarantine)
        return original_finish(self, ident, owner, agent_id, resource)

    monkeypatch.setattr(AttachmentDeletionStore, "_finish", add_collision)
    assert AttachmentDeletionStore(database).delete(["file-race"], owner="alice") == {
        "deletedFileIds": [], "failedFileIds": ["file-race"],
    }
    assert path.read_bytes() == b"real file bytes"
    assert collision[0].read_text() == "external"


def test_deletion_final_check_handles_agent_unlink_between_transactions(tmp_path, monkeypatch):
    database = SQLiteDatabase(tmp_path)
    path = _blob(database)
    first = _agent(database)
    AgentRepository(database).add_resource_file("alice", first, "context", "file-race")
    original_finish = AttachmentDeletionStore._finish

    def concurrent_unlink(self, ident, owner, agent_id, resource):
        AgentRepository(database).remove_resource_files(
            "alice", first, [{"tool_resource": "context", "file_id": "file-race"}],
        )
        return original_finish(self, ident, owner, agent_id, resource)

    monkeypatch.setattr(AttachmentDeletionStore, "_finish", concurrent_unlink)
    assert AttachmentDeletionStore(database).delete(
        ["file-race"], owner="alice", agent_id=first, resource="context",
    ) == {"deletedFileIds": [], "failedFileIds": []}
    assert path.exists()


def test_deletion_final_check_rejects_owner_change_between_transactions(tmp_path, monkeypatch):
    database = SQLiteDatabase(tmp_path)
    path = _blob(database)
    original_finish = AttachmentDeletionStore._finish

    def reassign_owner(self, ident, owner, agent_id, resource):
        with database.connect() as db:
            db.execute("UPDATE attachments SET owner=? WHERE id=?", ("bob", ident))
        return original_finish(self, ident, owner, agent_id, resource)

    monkeypatch.setattr(AttachmentDeletionStore, "_finish", reassign_owner)
    assert AttachmentDeletionStore(database).delete(["file-race"], owner="alice") == {
        "deletedFileIds": [], "failedFileIds": ["file-race"],
    }
    assert path.exists()


def test_deletion_success_when_storage_missing_before_quarantine(tmp_path):
    database = SQLiteDatabase(tmp_path)
    path = _blob(database)
    path.unlink()
    assert AttachmentDeletionStore(database).delete(["file-race"], owner="alice")["deletedFileIds"] == [
        "file-race",
    ]


def test_nonresource_deletion_preserves_missing_metadata_and_invalid_refs(tmp_path):
    database = SQLiteDatabase(tmp_path)
    path = _blob(database)
    first = _agent(database)
    with database.connect() as db:
        config = json.loads(db.execute("SELECT config FROM agents WHERE id=?", (first,)).fetchone()["config"])
        config["tool_resources"] = {
            "context": {"file_ids": ["file-race"]},
            "ocr": {"file_ids": "not-a-list"},
        }
        db.execute("UPDATE agents SET config=? WHERE id=?", (json.dumps(config), first))
    assert AttachmentDeletionStore(database).delete(["file-race"], owner="alice")["deletedFileIds"] == [
        "file-race",
    ]
    with database.connect() as db:
        config = json.loads(db.execute("SELECT config FROM agents WHERE id=?", (first,)).fetchone()["config"])
    assert config["tool_resources"]["context"]["file_ids"] == []
    assert config["tool_resources"]["ocr"]["file_ids"] == "not-a-list"
    assert not path.exists()
