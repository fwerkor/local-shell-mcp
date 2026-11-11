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
from local_shell_mcp.webui.file_deletion import (
    delete_response,
    partition_resource_files,
    plan_resource_deletion,
)


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
                       str(stat.st_dev) if signature else None,
                       str(stat.st_ino) if signature else None,
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


@pytest.mark.asyncio
async def test_controller_file_paths_remain_local_in_project_and_followup_conversation(uploads):
    from local_shell_mcp.webui.generations import GenerationStore
    from local_shell_mcp.webui.storage import WorkspaceRepository

    uploaded = await attachments.publish_attachment(
        "alice", "project.txt", "text/plain", _chunks(b"project-notes"),
        uploads.root, file_id="file-project",
    )
    project = WorkspaceRepository(uploads).create_project("alice", "Private project")
    store = GenerationStore(uploads)
    generation, fresh = store.begin("alice", {
        "text": "Summarize project evidence.",
        "projectId": project["id"],
        "files": [{"file_id": uploaded["file_id"], "filepath": "/forged-remote/path",
                   "machine": "remote-worker"}],
    })
    assert fresh
    with uploads.connect() as db:
        row = db.execute("SELECT project_id FROM conversations WHERE id=?",
                         (generation.conversation_id,)).fetchone()
    assert row["project_id"] == project["id"]
    history = store.history("alice", generation.conversation_id)
    item = history[-1]["content"]
    assert "Controller attachments" in item
    import json

    descriptor = json.loads(item.split("Controller attachments (use authorized LSM file tools):\n")[1])[0]
    assert descriptor["machine"] == "local"
    assert descriptor["path"] == uploaded["path"]
    assert Path(descriptor["path"]).read_bytes() == b"project-notes"
    assert "remote-worker" not in item and "/forged-remote/path" not in item

    store.finish("alice", generation.run_id, status="complete", text="Acknowledged.")
    followup, _ = store.begin("alice", {
        "text": "Continue this conversation.",
        "conversationId": generation.conversation_id,
        "parentMessageId": generation.response_message_id,
    })
    texts = [item["content"] for item in store.history(
        "alice", followup.conversation_id, message_id=followup.user_message_id)]
    assert any("Controller attachments" in text for text in texts)
    with pytest.raises(KeyError):
        store.begin("bob", {"text": "Try stealing a file", "files": [
            {"file_id": uploaded["file_id"]}]})


def test_context_rejects_other_owner_reference_and_unprocessed_resources(uploads):
    from local_shell_mcp.webui.agents import AgentRepository

    identity = AgentRepository(uploads).create(
        "alice", {"name": "Attached", "model": None, "provider": "openAI"},
    )
    config = {**identity, "tool_resources": {"context": {"file_ids": ["foreign"]}}}
    assert attachments.agent_context_messages(uploads, "alice", config) == []
    config["tool_resources"]["context"]["file_ids"] = ["foreign", "foreign"]
    assert attachments.agent_context_messages(uploads, "bob", config) == []



def test_librechat_full_resource_deletion_source_differential():
    """Compare original compiled Node deleteAgentResourceFiles and Python plan."""
    node = shutil.which("node") or "/root/.cache/lsm-attachments-node/bin/node"
    if not Path(node).is_file():
        pytest.skip("Node used only for offline source differential testing")
    fixture = Path(__file__).parent / "fixtures/librechat/file_deletion_reference.cjs"
    samples = []
    names = ["a", "b", "c"]
    for mask in range(72):
        sample = {
            "requested": ["a", "a", "b", "c", "other"],
            "attached": ["a", "b", "c"],
            "files": [{"file_id": name, "owner": "alice" if mask & (1 << idx) else "bob",
                       "file": {"id": name}} for idx, name in enumerate(names)],
            "shared": [name for idx, name in enumerate(names) if mask & (1 << (idx + 3))],
        }
        samples.append(sample)
    script = """
const fs=require('fs');const ref=require(process.argv[1]);
const samples=JSON.parse(fs.readFileSync(0,'utf8'));
(async()=>{
 const outputs=[];
 for(const sample of samples) {
  const destroyed=[],unlinked=[];
  const result=await ref.deleteAgentResourceFiles({
    agentId:'first',agentObjectId:'first',toolResource:'context',
    requestedFileIds:sample.requested,attachedFileIds:sample.attached,
    files:sample.files,userId:'alice'
  },{
    getSharedResourceFileIds:async()=>sample.shared,
    deleteFiles:async files=>{destroyed.push(...files);return {deletedFileIds:files.map(f=>f.id),failedFileIds:[]}},
    removeAgentResourceFiles:async ({files})=>{unlinked.push(...files)}
  });
  outputs.push({destroyed,unlinked,result});
 }
 process.stdout.write(JSON.stringify(outputs));
})();
"""
    out = subprocess.run([node, "-e", script, str(fixture)], input=json.dumps(samples),
                         text=True, capture_output=True, timeout=30, check=True)
    reference = json.loads(out.stdout)
    for sample, output in zip(samples, reference, strict=True):
        actual_destroy, actual_unlink = plan_resource_deletion(
            sample["requested"], sample["attached"], sample["files"],
            "context", "alice", sample["shared"],
        )
        assert actual_destroy == output["destroyed"]
        assert actual_unlink == output["unlinked"]
        assert output["result"]["destroyedFileIds"] == [file["id"] for file in actual_destroy]
        assert output["result"]["unlinkedFileIds"] == [file["file_id"] for file in actual_unlink]


def test_windows_unsigned_ntfs_file_identity_is_exact_sqlite_text(uploads):
    """Windows NTFS st_ino may exceed SQLite's signed 64-bit INTEGER limit."""
    path = _make_pending(uploads, "file-ntfs")
    huge = str((1 << 64) - 1)
    with uploads.connect() as db:
        db.execute("UPDATE attachment_uploads SET st_ino=?,st_dev=? WHERE file_id=?",
                   (huge, huge, "file-ntfs"))
        row = db.execute("SELECT st_ino,st_dev,typeof(st_ino),typeof(st_dev) "
                         "FROM attachment_uploads WHERE file_id=?", ("file-ntfs",)).fetchone()
        assert tuple(row) == (huge, huge, "text", "text")
    # A fabricated Windows identity must never authorize cleanup of another inode.
    assert attachments.recover_attachment_uploads(uploads)["retainedFileIds"] == ["file-ntfs"]
    assert path.exists()


@pytest.mark.asyncio
async def test_non_destructive_upload_intent_upgrade_from_integer_inode_schema(tmp_path, monkeypatch):
    """Older draft installations had INTEGER affinity (unsafe for NTFS IDs)."""
    from local_shell_mcp.sqlite_store import DB_NAME

    root = tmp_path / ".local-shell-mcp"
    root.mkdir()
    path = root / DB_NAME
    import sqlite3

    with sqlite3.connect(path) as sql:
        sql.execute(
            "CREATE TABLE attachment_uploads("
            "file_id TEXT PRIMARY KEY,owner TEXT NOT NULL,path TEXT NOT NULL,"
            "st_dev INTEGER,st_ino INTEGER,content_sha256 TEXT,content_size INTEGER,"
            "created_at INTEGER NOT NULL DEFAULT(unixepoch()))",
        )
        sql.execute(
            "INSERT INTO attachment_uploads(file_id,owner,path,st_dev,st_ino) VALUES(?,?,?,?,?)",
            ("legacy", "alice", str(root / "legacy.txt"), 3, 7),
        )
    db = SQLiteDatabase(root)
    monkeypatch.setattr(attachments, "_repo", lambda: SimpleNamespace(database=db))
    with db.connect() as sql:
        assert "file_identity" in {
            row["name"] for row in sql.execute("PRAGMA table_info(attachment_uploads)")
        }
        assert tuple(sql.execute(
            "SELECT st_dev,st_ino FROM attachment_uploads WHERE file_id='legacy'",
        ).fetchone()) == (3, 7)
    record = await attachments.publish_attachment(
        "alice", "modern.txt", "text/plain", _chunks(b"Windows-safe bytes"),
        root, file_id="modern",
    )
    with db.connect() as sql:
        assert sql.execute("SELECT count(*) FROM attachment_uploads").fetchone()[0] == 1
        assert sql.execute("SELECT count(*) FROM attachments WHERE id='modern'").fetchone()[0] == 1
    assert Path(record["path"]).read_bytes() == b"Windows-safe bytes"


def test_real_optional_docx_extraction(tmp_path):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("Source-based document content")
    path = tmp_path / "source.docx"
    document.save(path)
    result = attachments.extract_context_text(
        path, "source.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert result["processed"] is True
    assert result["extraction"] == "docx"
    assert "Source-based document content" in result["extracted_text"]


def test_real_optional_pdf_extraction(tmp_path):
    pytest.importorskip("pypdf")
    # A minimal valid single-page PDF with an actual extractable text operator.
    stream = b"BT /F1 12 Tf 72 720 Td (Source PDF text is extractable) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
        + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    data = bytearray(b"%PDF-1.4\n")
    positions = [0]
    for index, content in enumerate(objects, 1):
        positions.append(len(data))
        data.extend(f"{index} 0 obj\n".encode() + content + b"\nendobj\n")
    marker = len(data)
    data.extend(f"xref\n0 {len(positions)}\n".encode())
    data.extend(b"0000000000 65535 f \n")
    for offset in positions[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer\n<< /Size {len(positions)} /Root 1 0 R >>\n"
        f"startxref\n{marker}\n%%EOF".encode(),
    )
    path = tmp_path / "source.pdf"
    path.write_bytes(data)
    result = attachments.extract_context_text(path, "source.pdf", "application/pdf")
    assert result["processed"] is True
    assert result["extraction"] == "pypdf"
    assert "Source PDF text is extractable" in result["extracted_text"]
