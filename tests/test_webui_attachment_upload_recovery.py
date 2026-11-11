"""Upload intent integrity, text/PDF/DOCX extraction and source parity."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.exceptions import HTTPException

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import attachments
from local_shell_mcp.webui.file_deletion import delete_response, partition_resource_files


@pytest.fixture
def uploads(tmp_path, monkeypatch):
    database = SQLiteDatabase(tmp_path)
    monkeypatch.setattr(attachments, "_repo", lambda: SimpleNamespace(database=database))
    return database


async def _chunks(*data):
    for item in data:
        yield item


@pytest.mark.asyncio
async def test_cancelled_upload_removes_known_inode_and_intent(uploads):
    with pytest.raises(HTTPException) as caught:
        await attachments.publish_attachment(
            "alice", "abort.txt", "text/plain", _chunks(b"partial", b"extra"),
            uploads.root, expected_size=2, file_id="file-abort",
        )
    assert caught.value.status_code == 400
    with uploads.connect() as db:
        assert db.execute("SELECT count(*) FROM attachments").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM attachment_uploads").fetchone()[0] == 0
    assert not list((uploads.root / "attachments").rglob("*-abort.txt"))


@pytest.mark.asyncio
async def test_upload_committed_acknowledgement_failed_preserves_published_bytes(uploads, monkeypatch):
    connect = uploads.connect
    from contextlib import contextmanager

    @contextmanager
    def after_commit_error():
        with connect() as db:
            yield db
        raise sqlite3.OperationalError("response lost after commit")

    call_count = 0

    def unreliable():
        nonlocal call_count
        call_count += 1
        # Prepare intent, record inode and digest, then fourth connection publishes.
        return after_commit_error() if call_count == 4 else connect()

    monkeypatch.setattr(uploads, "connect", unreliable)
    with pytest.raises(sqlite3.OperationalError):
        await attachments.publish_attachment(
            "alice", "ack.txt", "text/plain", _chunks(b"durable body"),
            uploads.root, file_id="file-committed",
        )
    with connect() as db:
        row = db.execute("SELECT * FROM attachments WHERE id='file-committed'").fetchone()
        assert row
        assert db.execute("SELECT count(*) FROM attachment_uploads").fetchone()[0] == 0
    assert Path(row["path"]).read_bytes() == b"durable body"


def _make_pending(database, ident="file-stale", payload=b"orphan", *, signature=True):
    path = attachments._safe_attachment_path("alice", ident + ".txt", database.root)
    path.write_bytes(payload)
    stat = path.stat()
    with database.connect() as db:
        db.execute("INSERT INTO attachment_uploads(file_id,owner,path,st_dev,st_ino,content_sha256,content_size,created_at) "
                   "VALUES(?,?,?,?,?,?,?,0)", (
                       ident, "alice", str(path),
                       stat.st_dev if signature else None,
                       stat.st_ino if signature else None,
                       hashlib.sha256(payload).hexdigest() if signature else None,
                       stat.st_size if signature else None,
                   ))
    return path


def test_restart_reclaims_only_unchanged_uncommitted_uploads(uploads):
    path = _make_pending(uploads)
    assert attachments.recover_attachment_uploads(uploads) == {
        "cleanedFileIds": ["file-stale"], "retainedFileIds": [],
    }
    assert not path.exists()
    assert attachments.recover_attachment_uploads(SQLiteDatabase(uploads.root)) == {
        "cleanedFileIds": [], "retainedFileIds": [],
    }


def test_restart_preserves_external_recreation_and_unknown_inode(uploads):
    path = _make_pending(uploads)
    original = path.read_bytes()
    path.unlink()
    path.write_bytes(b"external replacement")
    result = attachments.recover_attachment_uploads(uploads)
    assert result == {"cleanedFileIds": [], "retainedFileIds": ["file-stale"]}
    assert path.read_bytes() != original
    path2 = _make_pending(uploads, "file-unknown", signature=False)
    result = attachments.recover_attachment_uploads(uploads)
    assert set(result["retainedFileIds"]) == {"file-stale", "file-unknown"}
    assert path2.exists()


def test_restart_committed_upload_metadata_wins_even_if_intent_survives(uploads):
    path = _make_pending(uploads)
    with uploads.connect() as db:
        db.execute("INSERT INTO attachments(id,owner,name,path,content_type,metadata) "
                   "VALUES(?,?,?,?,?,?)", ("file-stale", "alice", "saved.txt", str(path), "text/plain", "{}"))
    assert attachments.recover_attachment_uploads(uploads)["cleanedFileIds"] == ["file-stale"]
    assert path.read_bytes() == b"orphan"


def test_restart_old_intent_without_inode_but_missing_path_cleans(uploads):
    path = _make_pending(uploads, signature=False)
    path.unlink()
    assert attachments.recover_attachment_uploads(uploads)["cleanedFileIds"] == ["file-stale"]


def test_context_rejects_unreadable_and_empty_text(tmp_path):
    path = tmp_path / "binary.txt"
    path.write_bytes(b"\xff\xfe\xff")
    with pytest.raises(HTTPException) as err:
        attachments.extract_context_text(path, path.name, "text/plain")
    assert err.value.status_code == 415
    path.write_text("  ")
    with pytest.raises(HTTPException) as err:
        attachments.extract_context_text(path, path.name, "text/plain")
    assert err.value.status_code == 422
    path.write_text("x" * (128 * 1024 + 1))
    with pytest.raises(HTTPException) as err:
        attachments.extract_context_text(path, path.name, "text/plain")
    assert err.value.status_code == 413


def test_context_optional_pdf_docx_fail_closed_when_dependency_absent(tmp_path, monkeypatch):
    path = tmp_path / "file.pdf"
    path.write_bytes(b"%PDF")
    with pytest.raises(HTTPException) as err:
        attachments.extract_context_text(path, "file.pdf", "application/pdf")
    assert err.value.status_code in {501, 422}
    path = tmp_path / "file.docx"
    path.write_bytes(b"invalid")
    with pytest.raises(HTTPException) as err:
        attachments.extract_context_text(path, "file.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert err.value.status_code in {501, 422}


def test_message_upload_uses_private_metadata_not_untrusted_filepath(uploads):
    path = _make_pending(uploads)
    with uploads.connect() as db:
        db.execute("INSERT INTO attachments(id,owner,name,path,content_type,metadata) VALUES(?,?,?,?,?,?)",
                   ("file-stale", "alice", "a.txt", str(path), "text/plain", "{}"))
        found = attachments.resolve_files(db, "alice", [{"file_id": "file-stale", "filepath": "/etc/shadow"}])
        assert found[0]["filepath"] == "/api/files/download/file-stale"
        with pytest.raises(KeyError):
            attachments.resolve_files(db, "mallory", [{"file_id": "file-stale"}])


def test_librechat_deletion_partition_source_differential():
    node = shutil.which("node") or "/root/.cache/lsm-attachments-node/bin/node"
    fixture = Path(__file__).parent / "fixtures/librechat/file_deletion_reference.cjs"
    if not Path(node).is_file():
        pytest.skip("Source Node fixture is optional in Python-only environments")
    examples = []
    for mask in range(96):
        owned = [
            {"file_id": name, "owner": owner, "file": {"id": name}}
            for idx, (name, owner) in enumerate(
                [("a", "alice"), ("b", "bob"), ("c", "alice"), ("d", None)]
            ) if mask & (1 << idx)
        ]
        selected = [name for idx, name in enumerate(["a", "b", "c", "d"]) if mask & (1 << (idx + 4))]
        examples.append({"requested": ["a", "a", "b", "missing", "c", "d"],
                         "attached": selected + ["missing"], "files": owned})
    script = """
const fs=require('fs');
const ref=require(process.argv[1]);
const samples=JSON.parse(fs.readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(samples.map(x=>ref.partitionAgentResourceFiles({
 requestedFileIds:x.requested,attachedFileIds:x.attached,files:x.files,
 toolResource:'context',userId:'alice'
}))));
"""
    out = subprocess.run([node, "-e", script, str(fixture)], input=json.dumps(examples),
                         text=True, capture_output=True, timeout=30, check=True)
    reference = json.loads(out.stdout)
    for sample, expected in zip(examples, reference, strict=True):
        assert partition_resource_files(sample["requested"], sample["attached"],
                                        sample["files"], "context", "alice") == expected
    assert delete_response({"deletedFileIds": ["ok"], "failedFileIds": ["bad"]}, "Success") == {
        "message": "Some files could not be deleted",
        "deletedFileIds": ["ok"], "failedFileIds": ["bad"],
    }
