from __future__ import annotations

import io
import tarfile

import pytest

import local_shell_mcp.transfer_ops as transfer_module
from local_shell_mcp.settings import get_settings
from local_shell_mcp.tools import build_mcp
from local_shell_mcp.transfer_ops import (
    transfer_abort_write,
    transfer_alloc_temp_path,
    transfer_begin_write,
    transfer_finish_write,
    transfer_pack_dir,
    transfer_read_chunk,
    transfer_stat,
    transfer_unpack_archive,
    transfer_write_chunk,
)


def _workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    get_settings.cache_clear()
    return tmp_path


def test_chunked_transfer_round_trip_and_checksum(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    data = bytes(range(256)) * 3000 + b"tail"
    (root / "source.bin").write_bytes(data)

    stat = transfer_stat("source.bin", sha256=True)
    begin = transfer_begin_write("nested/dest.bin", overwrite=True, expected_bytes=stat["size"])

    offset = 0
    chunks = 0
    while offset < stat["size"]:
        chunk = transfer_read_chunk("source.bin", offset=offset, chunk_size=10_000)
        transfer_write_chunk(
            "nested/dest.bin",
            begin["transfer_id"],
            offset,
            chunk["data_b64"],
            chunk["sha256"],
        )
        offset += chunk["bytes"]
        chunks += 1

    finish = transfer_finish_write(
        "nested/dest.bin",
        begin["transfer_id"],
        expected_bytes=stat["size"],
        expected_sha256=stat["sha256"],
    )

    assert chunks > 1
    assert finish["bytes"] == len(data)
    assert finish["sha256"] == stat["sha256"]
    assert (root / "nested" / "dest.bin").read_bytes() == data


def test_transfer_rejects_bad_chunk_checksum_and_abort_removes_temp(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    (root / "source.txt").write_text("hello", encoding="utf-8")
    begin = transfer_begin_write("dest.txt", overwrite=True, expected_bytes=5)
    chunk = transfer_read_chunk("source.txt", offset=0, chunk_size=128)

    with pytest.raises(ValueError, match="chunk sha256 mismatch"):
        transfer_write_chunk("dest.txt", begin["transfer_id"], 0, chunk["data_b64"], "0" * 64)

    abort = transfer_abort_write("dest.txt", begin["transfer_id"])
    assert abort["deleted"] is True
    assert not any(root.glob(".dest.txt.local-shell-mcp-transfer-*.tmp"))
    assert not (root / "dest.txt").exists()


def test_directory_pack_and_unpack_preserves_nested_files(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    (root / "src" / "sub").mkdir(parents=True)
    (root / "src" / "sub" / "file.txt").write_text("nested", encoding="utf-8")
    (root / "src" / "root.bin").write_bytes(b"\x00\x01")

    pack = transfer_pack_dir("src")
    unpack = transfer_unpack_archive(pack["archive_path"], "dst", overwrite=True)

    assert unpack["entries"] >= 2
    assert (root / "dst" / "sub" / "file.txt").read_text(encoding="utf-8") == "nested"
    assert (root / "dst" / "root.bin").read_bytes() == b"\x00\x01"
    assert not (root / pack["archive_path"]).exists()


def test_unpack_rejects_archive_path_traversal(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    archive = root / "bad.tar"
    payload = b"bad"
    info = tarfile.TarInfo("../escape.txt")
    info.size = len(payload)
    with tarfile.open(archive, "w") as tar:
        tar.addfile(info, io.BytesIO(payload))

    with pytest.raises(ValueError, match="unsafe archive member path"):
        transfer_unpack_archive("bad.tar", "dst", overwrite=True, cleanup_archive=False)

    assert not (root.parent / "escape.txt").exists()


def test_mcp_exposes_remote_transfer_tools(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    mcp = build_mcp()
    names = set(mcp._tool_manager._tools)  # noqa: SLF001
    assert {
        "remote_copy_file",
        "remote_copy_dir",
        "remote_pull_file",
        "remote_push_file",
        "remote_pull_dir",
        "remote_push_dir",
    } <= names


def test_directory_pack_rejects_symlinks_before_archive_creation(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    (root / "src").mkdir()
    (root / "src" / "target.txt").write_text("target", encoding="utf-8")
    try:
        (root / "src" / "link.txt").symlink_to("target.txt")
    except OSError:
        pytest.skip("symlinks are not available in this test environment")

    with pytest.raises(ValueError, match="does not support symlinks"):
        transfer_pack_dir("src")


def test_unpack_failure_preserves_existing_destination(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    destination = root / "dst"
    destination.mkdir()
    important = destination / "important.txt"
    important.write_text("keep", encoding="utf-8")
    archive = root / "bad-link.tar"
    info = tarfile.TarInfo("link")
    info.type = tarfile.SYMTYPE
    info.linkname = "target"
    with tarfile.open(archive, "w") as tar:
        tar.addfile(info)

    with pytest.raises(ValueError, match="unsupported archive member type"):
        transfer_unpack_archive(
            "bad-link.tar", "dst", overwrite=True, cleanup_archive=False
        )

    assert important.read_text(encoding="utf-8") == "keep"
    assert not list(root.glob(".dst.unpack-*"))


def test_transfer_overwrite_false_rechecks_destination_at_finish(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    begin = transfer_begin_write("dest.txt", overwrite=False, expected_bytes=3)
    transfer_write_chunk("dest.txt", begin["transfer_id"], 0, "bmV3")
    destination = root / "dest.txt"
    destination.write_text("important", encoding="utf-8")

    with pytest.raises(FileExistsError):
        transfer_finish_write("dest.txt", begin["transfer_id"], expected_bytes=3)

    assert destination.read_text(encoding="utf-8") == "important"
    transfer_abort_write("dest.txt", begin["transfer_id"])


def test_transfer_chunk_cannot_exceed_declared_size(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    begin = transfer_begin_write("dest.txt", expected_bytes=2)

    with pytest.raises(ValueError, match="exceeds expected transfer size"):
        transfer_write_chunk("dest.txt", begin["transfer_id"], 0, "dG9vLWxvbmc=")

    transfer_abort_write("dest.txt", begin["transfer_id"])


def test_unpack_enforces_expanded_size_limit_before_replacement(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_TRANSFER_UNPACKED_BYTES", "3")
    get_settings.cache_clear()
    destination = root / "dst"
    destination.mkdir()
    (destination / "important.txt").write_text("keep", encoding="utf-8")
    archive = root / "large.tar"
    info = tarfile.TarInfo("payload.txt")
    payload = b"four"
    info.size = len(payload)
    with tarfile.open(archive, "w") as tar:
        tar.addfile(info, io.BytesIO(payload))

    with pytest.raises(ValueError, match="expands to more than 3 bytes"):
        transfer_unpack_archive(
            "large.tar", "dst", overwrite=True, cleanup_archive=False
        )

    assert (destination / "important.txt").read_text(encoding="utf-8") == "keep"


def test_transfer_temp_entrypoints_trigger_unified_pruning(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    (root / "src").mkdir()
    (root / "src" / "file.txt").write_text("data", encoding="utf-8")
    calls = []

    monkeypatch.setattr(transfer_module, "prune_temp_dir", lambda: calls.append(True))

    transfer_alloc_temp_path(".bin")
    pack = transfer_pack_dir("src")

    assert calls == [True, True]
    (root / pack["archive_path"]).unlink()
