from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

import local_shell_mcp.downloads as downloads
import local_shell_mcp.fs_ops as fs
import local_shell_mcp.remote_transfer as remote_transfer
import local_shell_mcp.transfer_ops as transfer
from local_shell_mcp.settings import get_settings


def _configure(tmp_path, monkeypatch, **extra):
    values = {
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT": str(tmp_path),
        "LOCAL_SHELL_MCP_STATE_DIR": str(tmp_path / ".state"),
        "LOCAL_SHELL_MCP_AUDIT_LOG_PATH": str(tmp_path / "audit.jsonl"),
        "LOCAL_SHELL_MCP_AUTH_MODE": "none",
        "LOCAL_SHELL_MCP_PUBLIC_BASE_URL": "http://testserver",
    }
    values.update({key: str(value) for key, value in extra.items()})
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    remote_transfer._TICKETS.clear()


def test_filesystem_binary_glob_context_and_limits(tmp_path, monkeypatch):
    _configure(
        tmp_path,
        monkeypatch,
        LOCAL_SHELL_MCP_MAX_GLOB_RESULTS=1,
        LOCAL_SHELL_MCP_MAX_READ_MANY_FILES=1,
        LOCAL_SHELL_MCP_MAX_READ_MANY_TOTAL_BYTES=3,
    )
    (tmp_path / "a.txt").write_text("abcd", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "a.py").write_text("x", encoding="utf-8")
    assert len(fs.glob_paths("a*")) == 1
    with pytest.raises(NotADirectoryError):
        fs.list_dir("a.txt")

    context = fs.missing_path_context("missing/child", max_entries=1)
    assert context["exists"] is False
    assert context["nearest_existing_parent"] == str(tmp_path)
    assert context["truncated"] is True
    outside = fs.relative_display(Path("/outside/value"))
    assert Path(outside).is_absolute()

    assert fs._is_probably_binary(b"") is False
    assert fs._is_probably_binary(b"a\x00b") is True
    assert fs._is_probably_binary(b"\xff") is True
    assert fs._is_probably_binary(bytes([1, 2, 3, 65])) is True
    assert fs._is_probably_binary(b"plain\ntext") is False

    binary = tmp_path / "binary.bin"
    binary.write_bytes(b"\x00abc")
    metadata = fs._binary_metadata(binary, 4, "hex", 999)
    assert metadata["preview"] == "00616263"
    assert metadata["preview_bytes"] == 4
    metadata = fs._binary_metadata(binary, 4, "base64", 4)
    assert base64.b64decode(metadata["preview"]) == b"\x00abc"
    with pytest.raises(ValueError, match="binary_preview"):
        fs._binary_metadata(binary, 4, "unknown")

    with pytest.raises(ValueError, match="must not be empty"):
        fs.read_texts([])
    with pytest.raises(ValueError, match="max is 1"):
        fs.read_texts(["a.txt", "a.txt"])
    with pytest.raises(ValueError, match="Refusing to return"):
        fs.read_texts(["a.txt"])

    missing_parent = fs.resolve_path("missing/child", allow_missing_parent=True)
    assert missing_parent.name == "child"
    with pytest.raises(FileNotFoundError):
        fs.resolve_path("missing/child", allow_missing_parent=False)


def test_filesystem_mutation_and_temp_cleanup_edges(tmp_path, monkeypatch):
    _configure(
        tmp_path,
        monkeypatch,
        LOCAL_SHELL_MCP_MAX_TMP_FILES=1,
        LOCAL_SHELL_MCP_MAX_TMP_BYTES=3,
        LOCAL_SHELL_MCP_MAX_FILE_WRITE_BYTES=5,
    )
    temp = fs.temp_dir()
    older = temp / "old"
    newer = temp / "new"
    older.write_bytes(b"123")
    newer.write_bytes(b"456")
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))
    fs.prune_temp_dir()
    assert newer.exists()
    assert not older.exists()

    with pytest.raises(ValueError, match="Refusing to write"):
        fs.write_text("large.txt", "123456")
    with pytest.raises(fs.FileConflictError, match="deleted"):
        fs.write_text("missing.txt", "x", expected_sha256="0" * 64)

    fs.perform_file_action("mkdir", "folder")
    assert fs.perform_file_action("mkdir", "folder", exist_ok=True)["action"] == "mkdir"
    with pytest.raises(FileExistsError):
        fs.perform_file_action("touch", "folder", exist_ok=True)
    fs.perform_file_action("touch", "file")
    assert fs.perform_file_action("touch", "file", exist_ok=True)["action"] == "touch"
    with pytest.raises(FileExistsError):
        fs.perform_file_action("mkdir", "file", exist_ok=True)
    with pytest.raises(ValueError, match="destination"):
        fs.perform_file_action("copy", "file")
    with pytest.raises(FileNotFoundError):
        fs.perform_file_action("copy", "file", "missing-parent/target")
    with pytest.raises(ValueError, match="Unsupported"):
        fs.perform_file_action("bad", "file")

    fs.perform_file_action("copy", "file", "copy")
    fs.perform_file_action("move", "copy", "moved")
    fs.perform_file_action("rename", "moved", "renamed")
    assert (tmp_path / "renamed").is_file()
    with pytest.raises(FileExistsError):
        fs.perform_file_action("copy", "file", "renamed")

    directory = tmp_path / "delete-dir"
    directory.mkdir()
    with pytest.raises(IsADirectoryError):
        fs.delete_path("delete-dir")
    assert fs.delete_path("delete-dir", recursive=True)["deleted"] == "directory"
    assert fs.delete_path("renamed")["deleted"] == "file"

    if hasattr(os, "symlink"):
        target = tmp_path / "target"
        target.write_text("x", encoding="utf-8")
        link = tmp_path / "link"
        try:
            link.symlink_to(target)
        except OSError:
            return
        fs.perform_file_action("copy", "link", "link-copy")
        assert (tmp_path / "link-copy").is_symlink()
        assert fs.delete_path("link")["deleted"] == "link"


def test_download_store_urls_coercion_and_corruption(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    assert downloads._snapshot_name("token").endswith(".bin")
    with pytest.raises(ValueError, match="metadata"):
        downloads._snapshot_path({"snapshot_name": "../bad"})
    assert downloads._safe_filename("../bad\x01name.txt", tmp_path / "source") == "badname.txt"
    assert downloads._safe_filename("\x01", tmp_path / "") == "download"

    monkeypatch.delenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL")
    monkeypatch.setenv("LOCAL_SHELL_MCP_HOST", "0.0.0.0")
    get_settings.cache_clear()
    assert downloads._public_base_url().startswith("http://127.0.0.1:")
    monkeypatch.setenv("LOCAL_SHELL_MCP_HOST", "::1")
    get_settings.cache_clear()
    assert "[::1]" in downloads._public_base_url()

    with pytest.raises(ValueError, match="positive"):
        downloads._coerce_ttl(0)
    assert downloads._coerce_ttl(10**9) == get_settings().file_download_max_ttl_s
    with pytest.raises(ValueError, match=">= 0"):
        downloads._coerce_max_downloads(-1)

    store_path = downloads._store_path()
    snapshot_dir = downloads._snapshot_dir()
    orphan = snapshot_dir / "orphan.bin"
    orphan.write_bytes(b"x")
    store_path.write_text("bad", encoding="utf-8")
    assert downloads._read_store_locked() == downloads._empty_store()
    assert not orphan.exists()

    for payload in ({"version": 3, "links": []}, {"version": 2, "links": {}}):
        orphan.write_bytes(b"x")
        store_path.write_text(json.dumps(payload), encoding="utf-8")
        assert downloads._read_store_locked() == downloads._empty_store()
        assert not orphan.exists()

    store = downloads._empty_store()
    now = 100.0
    expired_snapshot = snapshot_dir / "expired.bin"
    exhausted_snapshot = snapshot_dir / "exhausted.bin"
    expired_snapshot.write_bytes(b"x")
    exhausted_snapshot.write_bytes(b"x")
    store["links"] = {
        "expired": {"expires_at": 99, "snapshot_name": expired_snapshot.name},
        "exhausted": {
            "expires_at": 200,
            "max_downloads": 1,
            "downloads": 1,
            "snapshot_name": exhausted_snapshot.name,
        },
    }
    assert downloads._prune_locked(store, now) is True
    assert store["links"] == {}


def test_download_claim_failures_head_stream_and_link_errors(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    source = tmp_path / "source.txt"
    source.write_text("payload", encoding="utf-8")
    link = downloads.create_share_link("source.txt", ttl_s=60, max_downloads=1)
    token = link["token"]

    app = Starlette(routes=downloads.download_routes())
    client = TestClient(app)
    head = client.head(f"/download/{token}")
    assert head.status_code == 200
    assert head.headers["content-length"] == "7"
    get = client.get(f"/download/{token}")
    assert get.status_code == 200
    assert get.content == b"payload"
    assert client.get(f"/download/{token}").status_code == 410

    disabled = get_settings()
    disabled.file_download_enabled = False
    response = downloads._claim_download("missing", consume=False)
    assert response.status_code == 404
    disabled.file_download_enabled = True
    assert downloads._claim_download("missing", consume=False).status_code == 404

    store = downloads._empty_store()
    store["links"] = {
        "expired": {"expires_at": 0, "snapshot_name": "missing.bin"},
        "exhausted": {
            "expires_at": 10**10,
            "max_downloads": 1,
            "downloads": 1,
            "snapshot_name": "missing.bin",
        },
        "missing": {
            "expires_at": 10**10,
            "max_downloads": 0,
            "downloads": 0,
            "snapshot_name": "missing.bin",
        },
    }
    downloads._write_store_locked(store)
    assert downloads._claim_download("expired", consume=False).status_code == 410
    assert downloads._claim_download("exhausted", consume=False).status_code == 410
    assert downloads._claim_download("missing", consume=False).status_code == 404

    monkeypatch.setenv("LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED", "false")
    get_settings.cache_clear()
    with pytest.raises(PermissionError):
        downloads.create_share_link("source.txt")

    monkeypatch.setenv("LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED", "true")
    get_settings.cache_clear()
    directory = tmp_path / "directory"
    directory.mkdir()
    with pytest.raises(ValueError, match="shareable"):
        downloads.create_share_link("directory")

    monkeypatch.setattr(downloads, "_write_store_locked", lambda store: (_ for _ in ()).throw(OSError("write")))
    with pytest.raises(OSError, match="write"):
        downloads.create_share_link("source.txt")
    assert not list(downloads._snapshot_dir().glob("*.bin"))


def test_transfer_metadata_chunks_and_finish_edges(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    assert transfer.normalize_chunk_size(None) == transfer.DEFAULT_TRANSFER_CHUNK_BYTES
    assert transfer.normalize_chunk_size(10**9) == transfer.MAX_TRANSFER_CHUNK_BYTES
    with pytest.raises(ValueError):
        transfer.normalize_chunk_size(0)
    with pytest.raises(ValueError, match="transfer_id"):
        transfer._transfer_temp_path(tmp_path / "x", "bad/id")

    invalid = tmp_path / "invalid.tmp"
    invalid.write_text("bad", encoding="utf-8")
    with pytest.raises(ValueError, match="metadata"):
        transfer._read_transfer_metadata(invalid)
    transfer._transfer_metadata_path(invalid).write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="metadata"):
        transfer._read_transfer_metadata(invalid)

    for raw in ("bad", [[-1, 2]], [[2, 1]], [[1]], [[1, "2"]]):
        with pytest.raises(ValueError, match="received_ranges"):
            transfer._received_ranges({"received_ranges": raw})
    metadata = {"received_ranges": []}
    transfer._record_received_range(metadata, 0, 0)
    transfer._record_received_range(metadata, 0, 2)
    transfer._record_received_range(metadata, 2, 4)
    assert metadata["received_ranges"] == [[0, 4]]
    with pytest.raises(ValueError, match="invalid"):
        transfer._record_received_range(metadata, 2, 1)

    directory = tmp_path / "dir"
    directory.mkdir()
    with pytest.raises(IsADirectoryError):
        transfer.transfer_begin_write("dir")
    existing = tmp_path / "existing"
    existing.write_text("x", encoding="utf-8")
    with pytest.raises(FileExistsError):
        transfer.transfer_begin_write("existing", overwrite=False)
    with pytest.raises(ValueError, match="expected_bytes"):
        transfer.transfer_begin_write("x", expected_bytes=-1)

    begin = transfer.transfer_begin_write("target", expected_bytes=2)
    with pytest.raises(ValueError, match="offset"):
        transfer.transfer_write_chunk("target", begin["transfer_id"], -1, "")
    with pytest.raises(ValueError, match="base64"):
        transfer.transfer_write_chunk("target", begin["transfer_id"], 0, "***")
    with pytest.raises(ValueError, match="exceeds"):
        transfer.transfer_write_bytes("target", begin["transfer_id"], 0, b"123")
    with pytest.raises(ValueError, match="offset"):
        transfer.transfer_write_bytes("target", begin["transfer_id"], -1, b"")
    with pytest.raises(FileNotFoundError):
        transfer.transfer_write_bytes("target", "missing", 0, b"")

    temp_path = fs.resolve_path(begin["temp_path"])
    temp_path.write_bytes(b"x")
    with pytest.raises(ValueError, match="size mismatch"):
        transfer.transfer_mark_complete_write("target", begin["transfer_id"])
    temp_path.write_bytes(b"12")
    assert transfer.transfer_mark_complete_write("target", begin["transfer_id"])["bytes"] == 2
    finished = transfer.transfer_finish_write("target", begin["transfer_id"], expected_bytes=2)
    assert finished["completed"] is True
    assert transfer.transfer_abort_write("target", begin["transfer_id"])["deleted"] is False

    empty = transfer.transfer_begin_write("empty", expected_bytes=0)
    transfer.transfer_mark_complete_write("empty", empty["transfer_id"])
    assert transfer.transfer_finish_write("empty", empty["transfer_id"])["bytes"] == 0
    with pytest.raises(IsADirectoryError):
        transfer.transfer_read_chunk("dir")
    with pytest.raises(ValueError, match="offset"):
        transfer.transfer_read_chunk("target", -1)


def _tar_with_members(members):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for member, content in members:
            archive.addfile(member, io.BytesIO(content) if content is not None else None)
    buffer.seek(0)
    return tarfile.open(fileobj=buffer, mode="r")


def test_transfer_archive_validation_pack_and_unpack(tmp_path, monkeypatch):
    _configure(
        tmp_path,
        monkeypatch,
        LOCAL_SHELL_MCP_MAX_TRANSFER_ARCHIVE_ENTRIES=1,
        LOCAL_SHELL_MCP_MAX_TRANSFER_UNPACKED_BYTES=2,
    )
    (tmp_path / "file").write_text("x", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        transfer.transfer_pack_dir("file")

    source = tmp_path / "source"
    source.mkdir()
    (source / "a").write_text("x", encoding="utf-8")
    packed = transfer.transfer_pack_dir("source", compression="none")
    assert packed["compression"] == "none"

    member = tarfile.TarInfo("a")
    member.size = 1
    duplicate = tarfile.TarInfo("a")
    duplicate.size = 1
    with (
        _tar_with_members([(member, b"x"), (duplicate, b"y")]) as archive,
        pytest.raises(ValueError, match="entries|duplicate"),
    ):
        transfer._safe_members(archive, tmp_path / "dst")

    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_TRANSFER_ARCHIVE_ENTRIES", "10")
    get_settings.cache_clear()
    large = tarfile.TarInfo("large")
    large.size = 3
    with (
        _tar_with_members([(large, b"abc")]) as archive,
        pytest.raises(ValueError, match="expands"),
    ):
        transfer._safe_members(archive, tmp_path / "dst")
    sparse = tarfile.TarInfo("sparse")
    sparse.size = 0
    sparse.sparse = [(0, 0)]
    fake_archive = SimpleNamespace(getmembers=lambda: [sparse])
    with pytest.raises(ValueError, match="sparse"):
        transfer._safe_members(fake_archive, tmp_path / "dst")

    archive_path = fs.resolve_path(packed["archive_path"])
    empty_dst = tmp_path / "empty-dst"
    empty_dst.mkdir()
    unpacked = transfer.transfer_unpack_archive(
        packed["archive_path"], "empty-dst", overwrite=False, cleanup_archive=False
    )
    assert unpacked["completed"] is True
    assert archive_path.exists()

    packed_again = transfer.transfer_pack_dir("source")
    nonempty = tmp_path / "nonempty"
    nonempty.mkdir()
    (nonempty / "existing").write_text("x", encoding="utf-8")
    with pytest.raises(FileExistsError):
        transfer.transfer_unpack_archive(packed_again["archive_path"], "nonempty", overwrite=False)

    file_target = tmp_path / "file-target"
    file_target.write_text("x", encoding="utf-8")
    transfer._remove_existing_path(file_target)
    assert not file_target.exists()
    dir_target = tmp_path / "dir-target"
    dir_target.mkdir()
    transfer._remove_existing_path(dir_target)
    assert not dir_target.exists()


def test_remote_transfer_validation_claim_and_endpoint_errors(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    digest = hashlib.sha256(b"data").hexdigest()
    for size, value in ((-1, digest), (1, "bad")):
        with pytest.raises(ValueError):
            remote_transfer._validate_expected(size, value)
    assert remote_transfer._validate_expected(4, digest) == (4, digest)

    monkeypatch.delenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL")
    monkeypatch.setenv("LOCAL_SHELL_MCP_HOST", "::1")
    get_settings.cache_clear()
    assert "[::1]" in remote_transfer._public_base_url()
    assert remote_transfer._ticket_ttl_s() >= 60

    cleanup = tmp_path / "cleanup"
    cleanup.write_text("x", encoding="utf-8")
    expired = remote_transfer._TransferTicket(
        "expired", "upload", "x", 0, hashlib.sha256(b"").hexdigest(), True, 0, 0, cleanup_path=str(cleanup)
    )
    remote_transfer._TICKETS["expired"] = expired
    remote_transfer._prune_locked(now=1)
    assert not cleanup.exists()

    upload = remote_transfer.create_upload_ticket("dest", 4, digest)
    token = upload["token"]
    with pytest.raises(PermissionError, match="direction"):
        remote_transfer._claim_ticket(token, "download")
    claimed = remote_transfer._claim_ticket(token, "upload")
    with pytest.raises(RuntimeError, match="already"):
        remote_transfer._claim_ticket(token, "upload")
    remote_transfer._release_ticket(token)
    assert claimed.claimed is False
    assert remote_transfer.revoke_transfer_ticket(token)["revoked"] is True
    assert remote_transfer.revoke_transfer_ticket(token)["revoked"] is False

    app = Starlette(routes=remote_transfer.remote_transfer_routes())
    client = TestClient(app)
    assert client.put("/remote/transfer/upload/missing", content=b"").status_code == 404

    ticket = remote_transfer.create_upload_ticket("dest", 4, digest)
    assert client.put(
        f"/remote/transfer/upload/{ticket['token']}",
        content=b"data",
        headers={"content-length": "invalid"},
    ).status_code == 400
    assert client.put(
        f"/remote/transfer/upload/{ticket['token']}",
        content=b"data",
        headers={"content-length": "3"},
    ).status_code == 400
    short = remote_transfer.create_upload_ticket("dest", 4, digest)
    assert client.put(
        f"/remote/transfer/upload/{short['token']}", content=b"dat"
    ).status_code == 400
    long_ticket = remote_transfer.create_upload_ticket("dest", 4, digest)
    assert client.put(
        f"/remote/transfer/upload/{long_ticket['token']}", content=b"datax"
    ).status_code == 400

    source = tmp_path / "source"
    source.write_bytes(b"data")
    download = remote_transfer.create_download_ticket("source", 4, digest)
    remote_transfer._TICKETS[download["token"]].path = str(tmp_path / "missing")
    assert client.get(
        f"/remote/transfer/download/{download['token']}"
    ).status_code == 404

    with pytest.raises(ValueError, match="source is not a file"):
        directory = tmp_path / "directory"
        directory.mkdir()
        remote_transfer.create_download_ticket("directory", 0, hashlib.sha256(b"").hexdigest())
    with pytest.raises(ValueError, match="size mismatch"):
        remote_transfer.create_download_ticket("source", 5, digest)
    with pytest.raises(ValueError, match="sha256"):
        remote_transfer.create_download_ticket("source", 4, hashlib.sha256(b"other").hexdigest())
