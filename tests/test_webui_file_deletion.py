"""Source deletion outcomes, safe publication rollback and restart recovery."""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.auth import Principal
from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import attachments
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.file_deletion import (
    AttachmentDeletionStore,
    delete_response,
    plan_resource_deletion,
)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    for key, value in {"WORKSPACE_ROOT": str(tmp_path), "STATE_DIR": str(tmp_path / ".local-shell-mcp"),
                       "AUTH_MODE": "none", "DISABLE_LOCAL": "false"}.items():
        monkeypatch.setenv("LOCAL_SHELL_MCP_" + key, value)
    get_settings.cache_clear()
    database = SQLiteDatabase(tmp_path / ".local-shell-mcp")
    monkeypatch.setattr(attachments, "_repo", lambda: SimpleNamespace(database=database))
    async def identity(request, call_next):
        request.state.principal = Principal(None, request.headers.get("x-owner", "alice"), {"auth": "none"})
        return await call_next(request)
    app = Starlette(routes=attachments.attachment_routes())
    from starlette.middleware.base import BaseHTTPMiddleware
    app.add_middleware(BaseHTTPMiddleware, dispatch=identity)
    yield database, app
    get_settings.cache_clear()


def blob(database, identity, owner="alice", *, payload=b"real file"):
    path = attachments._safe_attachment_path(owner, identity + ".txt", database.root)
    path.write_bytes(payload)
    with database.connect() as db:
        db.execute("INSERT INTO attachments(id,owner,name,path,content_type,metadata) VALUES(?,?,?,?,?,?)",
                   (identity, owner, identity, str(path), "text/plain", "{}"))
        return dict(db.execute("SELECT * FROM attachments WHERE id=?", (identity,)).fetchone())


def agent(database, owner="alice"):
    return AgentRepository(database).create(owner, {"name": "Files", "provider": "openAI", "model": None})["id"]


def descriptor(ident):
    return {"file_id": ident, "filepath": "/ignored/forged/path", "source": "forged"}


@pytest.mark.asyncio
async def test_original_delete_shape_uses_owned_metadata_and_cleans_all_agent_refs(setup):
    database, app = setup
    row = blob(database, "file-one")
    repository = AgentRepository(database)
    ids = [agent(database), agent(database)]
    for ident in ids:
        repository.add_resource_file("alice", ident, "context", row["id"])
    versions = [len(repository.versions("alice", ident)) for ident in ids]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        assert (await client.get("/api/files/agent/" + ids[0])).json()[0]["file_id"] == row["id"]
        response = await client.request("DELETE", "/api/files", json={"files": [descriptor(row["id"])] * 2})
        assert response.json() == {"message": "Files deleted successfully", "deletedFileIds": [row["id"]], "failedFileIds": []}
        assert not Path(row["path"]).exists()
        assert (await client.get("/api/files/download/" + row["id"])).status_code == 404
        assert (await client.get("/api/files/agent/" + ids[0])).json() == []
    for index, ident in enumerate(ids):
        assert repository.get("alice", ident)["tool_resources"]["context"]["file_ids"] == []
        assert len(repository.versions("alice", ident)) == versions[index]
    with database.connect() as db:
        assert not db.execute("SELECT 1 FROM attachments").fetchall()
        assert not db.execute("SELECT 1 FROM attachment_deletions").fetchall()


@pytest.mark.asyncio
async def test_mixed_foreign_delete_rejects_before_any_mutation(setup):
    database, app = setup
    rows = [blob(database, "file-own"), blob(database, "file-foreign", "bob")]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.request("DELETE", "/api/files", json={"files": [descriptor(row["id"]) for row in rows]})
        assert response.status_code == 403
        assert response.json()["unauthorizedFiles"] == ["file-foreign"]
    assert all(Path(row["path"]).exists() for row in rows)
    with database.connect() as db:
        assert db.execute("SELECT count(*) FROM attachments").fetchone()[0] == 2


@pytest.mark.asyncio
async def test_agent_shared_resource_unlinks_until_last_holder_then_deletes(setup):
    database, app = setup
    row = blob(database, "file-shared")
    repository = AgentRepository(database)
    first, second = agent(database), agent(database)
    for ident, resource in [(first, "context"), (first, "ocr"), (second, "context")]:
        repository.add_resource_file("alice", ident, resource, row["id"])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        for ident, resource in [(first, "context"), (first, "ocr")]:
            response = await client.request("DELETE", "/api/files", json={"files": [descriptor(row["id"])],
                                           "agent_id": ident, "tool_resource": resource})
            assert response.json() == {"message": "File associations removed successfully from agent"}
            assert Path(row["path"]).exists()
        response = await client.request("DELETE", "/api/files", json={"files": [descriptor(row["id"])],
                                       "agent_id": second, "tool_resource": "context"})
        assert response.json()["deletedFileIds"] == [row["id"]]
        assert not Path(row["path"]).exists()


@pytest.mark.asyncio
async def test_partial_storage_failure_keeps_metadata_and_references_for_retry(setup, monkeypatch):
    database, app = setup
    rows = [blob(database, "file-ok"), blob(database, "file-fail")]
    ident = agent(database)
    repository = AgentRepository(database)
    for row in rows:
        repository.add_resource_file("alice", ident, "context", row["id"])
    replace = os.replace
    def refuse(source, target):
        if str(source) == rows[1]["path"]:
            raise PermissionError("simulated storage denial")
        return replace(source, target)
    with monkeypatch.context() as patch:
        patch.setattr("local_shell_mcp.webui.file_deletion.os.replace", refuse)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            result = await client.request("DELETE", "/api/files", json={"files": [descriptor(row["id"]) for row in rows]})
    assert result.json() == {"message": "Some files could not be deleted", "deletedFileIds": ["file-ok"], "failedFileIds": ["file-fail"]}
    assert repository.get("alice", ident)["tool_resources"]["context"]["file_ids"] == ["file-fail"]
    assert Path(rows[1]["path"]).read_bytes() == b"real file"
    assert AttachmentDeletionStore(database).delete([rows[1]])["deletedFileIds"] == ["file-fail"]


@pytest.mark.asyncio
async def test_metadata_failure_restores_bytes_and_keeps_agent_reference(setup, monkeypatch):
    database, app = setup
    row = blob(database, "file-rollback")
    ident = agent(database)
    repository = AgentRepository(database)
    repository.add_resource_file("alice", ident, "context", row["id"])
    with database.connect() as db:
        db.execute("CREATE TRIGGER reject_file_delete BEFORE DELETE ON attachments BEGIN SELECT RAISE(ABORT,'storage unavailable'); END")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        result = await client.request("DELETE", "/api/files", json={"files": [descriptor(row["id"])]})
    assert result.status_code == 400
    assert Path(row["path"]).read_bytes() == b"real file"
    assert repository.get("alice", ident)["tool_resources"]["context"]["file_ids"] == [row["id"]]
    with database.connect() as db:
        assert db.execute("SELECT count(*) FROM attachment_deletions").fetchone()[0] == 0


@pytest.mark.parametrize("committed,moved", [(False, False), (False, True), (True, True), (True, False)])
def test_restart_recovers_each_durable_crash_boundary(tmp_path, committed, moved):
    database = SQLiteDatabase(tmp_path)
    row = blob(database, "file-restart")
    original = Path(row["path"])
    quarantine = original.with_name(".delete-persisted")
    with database.connect() as db:
        db.execute("INSERT INTO attachment_deletions VALUES(?,?,?,?,?,unixepoch())",
                   (row["id"], row["owner"], str(original), str(quarantine), "committed" if committed else "prepared"))
    if moved:
        os.replace(original, quarantine)
    if committed:
        with database.connect() as db:
            db.execute("DELETE FROM attachments WHERE id=?", (row["id"],))
    result = AttachmentDeletionStore(SQLiteDatabase(tmp_path)).recover()
    assert result == {"recoveredFileIds": [row["id"]], "failedFileIds": []}
    assert not quarantine.exists()
    if not committed:
        assert original.read_bytes() == b"real file"
    assert AttachmentDeletionStore(database).recover() == {"recoveredFileIds": [], "failedFileIds": []}


def test_recovery_collision_keeps_original_quarantine_and_intent(tmp_path):
    database = SQLiteDatabase(tmp_path)
    row = blob(database, "file-collision")
    original = Path(row["path"])
    quarantine = original.with_name(".delete-collision")
    quarantine.write_bytes(b"retained original")
    with database.connect() as db:
        db.execute("INSERT INTO attachment_deletions VALUES(?,?,?,?,?,unixepoch())",
                   (row["id"], row["owner"], str(original), str(quarantine), "prepared"))
    result = AttachmentDeletionStore(database).recover()
    assert result["failedFileIds"] == [row["id"]]
    assert original.read_bytes() == b"real file"
    assert quarantine.read_bytes() == b"retained original"
    original.unlink()
    assert AttachmentDeletionStore(database).recover()["recoveredFileIds"] == [row["id"]]
    assert original.read_bytes() == b"retained original"


def test_missing_storage_and_unsafe_or_symlink_paths(tmp_path):
    database = SQLiteDatabase(tmp_path)
    row = blob(database, "file-missing")
    Path(row["path"]).unlink()
    store = AttachmentDeletionStore(database)
    assert store.delete([row])["deletedFileIds"] == [row["id"]]
    unsafe = blob(database, "file-unsafe")
    outside = tmp_path / "outside.txt"
    outside.write_text("do not delete")
    with database.connect() as db:
        db.execute("UPDATE attachments SET path=? WHERE id=?", (str(outside), unsafe["id"]))
    unsafe["path"] = str(outside)
    assert store.delete([unsafe])["failedFileIds"] == [unsafe["id"]]
    assert outside.read_text() == "do not delete"
    if os.name != "nt":
        linked = blob(database, "file-link")
        Path(linked["path"]).unlink()
        Path(linked["path"]).symlink_to(outside)
        assert store.delete([linked])["failedFileIds"] == [linked["id"]]
        assert outside.read_text() == "do not delete"


@pytest.mark.asyncio
async def test_route_shapes_invalid_inputs_agent_permissions_and_noops(setup, monkeypatch):
    database, app = setup
    row = blob(database, "file-foreign", "bob")
    foreign = agent(database, "bob")
    own = agent(database)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        for body in [{}, {"files": [None]}, {"files": [descriptor("file-x")] * 501}]:
            assert (await client.request("DELETE", "/api/files", json=body)).status_code == 400
        for files in [[], [{}], [{"file_id": "invalid", "filepath": "x"}], [{"file_id": "file-x"}]]:
            assert (await client.request("DELETE", "/api/files", json={"files": files})).status_code == 204
        for ident, resource, status in [("missing", "context", 404), (foreign, "context", 403), (own, "bad", 400)]:
            response = await client.request("DELETE", "/api/files", json={"files": [descriptor(row["id"])],
                                           "agent_id": ident, "tool_resource": resource})
            assert response.status_code == status
        assert (await client.get("/api/files/agent/missing")).json() == []
        assert (await client.get("/api/files/agent/" + foreign)).json() == []
        assert (await client.request("DELETE", "/api/files", json={"files": [descriptor("file-absent")]})).json()["deletedFileIds"] == []
        monkeypatch.setenv("LOCAL_SHELL_MCP_DISABLE_LOCAL", "true")
        get_settings.cache_clear()
        assert (await client.request("DELETE", "/api/files", json={"files": [descriptor(row["id"])]})).status_code == 403


def test_source_response_and_partition_examples():
    assert delete_response(None, "ok") == {"message": "ok", "deletedFileIds": [], "failedFileIds": []}
    records = [{"file_id": "a", "owner": "alice", "file": {"id": "a"}},
               {"file_id": "b", "owner": "bob", "file": {"id": "b"}}]
    destroy, unlink = plan_resource_deletion(["a", "a", "b", "missing", "not-attached"],
        ["a", "b", "missing"], records, "context", "alice", ["a"])
    assert destroy == []
    assert unlink == [{"tool_resource": "context", "file_id": "b"},
                      {"tool_resource": "context", "file_id": "missing"},
                      {"tool_resource": "context", "file_id": "a"}]


def test_commit_acknowledgement_failure_does_not_restore_deleted_bytes(tmp_path, monkeypatch):
    database = SQLiteDatabase(tmp_path)
    row = blob(database, "file-commit-uncertain")
    store = AttachmentDeletionStore(database)
    def committed_then_failed(_ident):
        raise OSError("commit acknowledgement lost")

    monkeypatch.setattr(store, "_after_commit", committed_then_failed)
    assert store.delete([row]) == {"deletedFileIds": [row["id"]], "failedFileIds": []}
    assert not Path(row["path"]).exists()
    with database.connect() as db:
        assert db.execute("SELECT 1 FROM attachments WHERE id=?", (row["id"],)).fetchone() is None
        assert db.execute("SELECT 1 FROM attachment_deletions").fetchone() is None
    assert not list(Path(row["path"]).parent.glob(".delete-*"))


@pytest.mark.asyncio
async def test_cross_origin_delete_cannot_mutate_owned_files(setup):
    database, app = setup
    row = blob(database, "file-cross-origin")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.request("DELETE", "/api/files", headers={"Origin": "https://foreign.invalid"},
                                       json={"files": [descriptor(row["id"])]})
    assert response.status_code == 403
    assert Path(row["path"]).read_bytes() == b"real file"
    with database.connect() as db:
        assert db.execute("SELECT 1 FROM attachments WHERE id=?", (row["id"],)).fetchone() is not None


def test_commit_and_readback_failure_preserves_intent_for_restart(tmp_path, monkeypatch):
    database = SQLiteDatabase(tmp_path)
    row = blob(database, "file-commit-readback")
    store = AttachmentDeletionStore(database)
    connect = database.connect

    def unavailable():
        raise OSError("database temporarily unavailable")

    def committed_then_disconnected(_ident):
        monkeypatch.setattr(database, "connect", unavailable)
        raise OSError("commit acknowledgement lost")

    monkeypatch.setattr(store, "_after_commit", committed_then_disconnected)
    assert store.delete([row])["failedFileIds"] == [row["id"]]
    monkeypatch.setattr(database, "connect", connect)
    original = Path(row["path"])
    assert not original.exists()
    retained = list(original.parent.glob(".delete-*"))
    assert len(retained) == 1 and retained[0].read_bytes() == b"real file"
    with database.connect() as db:
        assert db.execute("SELECT 1 FROM attachment_deletions").fetchone() is not None
    assert AttachmentDeletionStore(SQLiteDatabase(tmp_path)).recover()["recoveredFileIds"] == [row["id"]]
    assert not retained[0].exists()
    assert not original.exists()
