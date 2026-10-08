from __future__ import annotations

import io
import os
import tarfile
from pathlib import Path

import pytest
from edge_case_support import symlink_or_skip
from edge_case_support import workspace as _transfer_workspace

import local_shell_mcp.transfer_ops as transfer_ops


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are unavailable on this platform")
def test_transfer_stat_reports_other_file_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _transfer_workspace(tmp_path, monkeypatch)
    fifo = root / "pipe"
    os.mkfifo(fifo)
    result = transfer_ops.transfer_stat("pipe")
    assert result["type"] == "other"

def test_transfer_begin_write_cleans_up_when_metadata_write_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _transfer_workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(
        transfer_ops,
        "_write_transfer_metadata",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("metadata failed")),
    )
    with pytest.raises(RuntimeError, match="metadata failed"):
        transfer_ops.transfer_begin_write("dest.bin")
    assert not list(root.glob(".dest.bin.local-shell-mcp-transfer-*"))

def test_transfer_prepare_and_refresh_missing_stream_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _transfer_workspace(tmp_path, monkeypatch)
    with pytest.raises(FileNotFoundError):
        transfer_ops.transfer_prepare_stream_write("dest.bin", "missing")
    with pytest.raises(FileNotFoundError):
        transfer_ops.transfer_refresh_stream_write("dest.bin", "missing")

def test_transfer_refresh_stream_write_detects_missing_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _transfer_workspace(tmp_path, monkeypatch)
    begin = transfer_ops.transfer_begin_write("dest.bin")
    dst = transfer_ops.resolve_path("dest.bin", follow_final_symlink=False)
    tmp = transfer_ops._transfer_temp_path(dst, begin["transfer_id"])
    transfer_ops._transfer_metadata_path(tmp).unlink()
    with pytest.raises(FileNotFoundError):
        transfer_ops.transfer_refresh_stream_write("dest.bin", begin["transfer_id"])
    tmp.unlink(missing_ok=True)

def test_transfer_mark_complete_rejects_missing_and_wrong_size(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _transfer_workspace(tmp_path, monkeypatch)
    with pytest.raises(FileNotFoundError):
        transfer_ops.transfer_mark_complete_write("dest.bin", "missing")

    begin = transfer_ops.transfer_begin_write("dest.bin", expected_bytes=2)
    with pytest.raises(ValueError, match="size mismatch"):
        transfer_ops.transfer_mark_complete_write("dest.bin", begin["transfer_id"])
    transfer_ops.transfer_abort_write("dest.bin", begin["transfer_id"])

def test_finish_verified_write_rejects_invalid_stream_digest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _transfer_workspace(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="must be a SHA-256"):
        transfer_ops.transfer_finish_verified_write("x", "id", 0, "0" * 64, "not-a-digest")
    with pytest.raises(ValueError, match="file sha256 mismatch"):
        transfer_ops.transfer_finish_verified_write("x", "id", 0, "0" * 64, "1" * 64)

def test_archive_path_and_cancelled_pack_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _transfer_workspace(tmp_path, monkeypatch)
    assert transfer_ops._archive_path_from_result({}) is None
    assert transfer_ops._archive_path_from_result({"archive_path": ""}) is None
    archive = root / "packed.tar"
    archive.write_bytes(b"x")
    transfer_ops.refresh_temp_file_lease(archive)
    assert transfer_ops._archive_path_from_result({"archive_path": "packed.tar"}) == archive
    transfer_ops._cleanup_cancelled_pack_result({"archive_path": "packed.tar"})
    assert not archive.exists()

def test_safe_members_rejects_duplicate_and_escape_via_symlink(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _transfer_workspace(tmp_path, monkeypatch)
    dst = root / "dst"
    dst.mkdir()
    archive = root / "dup.tar"
    with tarfile.open(archive, "w") as tar:
        for _ in range(2):
            info = tarfile.TarInfo("same.txt")
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))
    with (
        tarfile.open(archive, "r") as tar,
        pytest.raises(ValueError, match="duplicate archive member"),
    ):
        transfer_ops._safe_members(tar, dst)

    outside = root / "outside"
    outside.mkdir()
    symlink_or_skip(dst / "link", outside, target_is_directory=True)
    escape = root / "escape.tar"
    with tarfile.open(escape, "w") as tar:
        info = tarfile.TarInfo("link/file.txt")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    with (
        tarfile.open(escape, "r") as tar,
        pytest.raises(ValueError, match="escapes destination"),
    ):
        transfer_ops._safe_members(tar, dst)

def test_unpack_rejects_non_file_archive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = _transfer_workspace(tmp_path, monkeypatch)
    (root / "archive-dir").mkdir()
    with pytest.raises(FileNotFoundError):
        transfer_ops.transfer_unpack_archive("archive-dir", "dst")

def test_unpack_handles_missing_member_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _transfer_workspace(tmp_path, monkeypatch)
    archive = root / "payload.tar"
    archive.write_bytes(b"placeholder")
    info = tarfile.TarInfo("file.txt")
    info.size = 1

    class FakeTar:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extractfile(self, member):
            return None

    monkeypatch.setattr(transfer_ops.tarfile, "open", lambda *a, **k: FakeTar())
    monkeypatch.setattr(transfer_ops, "_safe_members", lambda *a, **k: [info])
    with pytest.raises(ValueError, match="has no file data"):
        transfer_ops.transfer_unpack_archive("payload.tar", "dst", cleanup_archive=False)

def test_unpack_rejects_unknown_member_after_validation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _transfer_workspace(tmp_path, monkeypatch)
    archive = root / "payload.tar"
    archive.write_bytes(b"placeholder")
    info = tarfile.TarInfo("odd")
    info.type = tarfile.FIFOTYPE

    class FakeTar:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(transfer_ops.tarfile, "open", lambda *a, **k: FakeTar())
    monkeypatch.setattr(transfer_ops, "_safe_members", lambda *a, **k: [info])
    with pytest.raises(ValueError, match="unsupported archive member type"):
        transfer_ops.transfer_unpack_archive("payload.tar", "dst", cleanup_archive=False)

def test_unpack_restores_backup_when_publish_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _transfer_workspace(tmp_path, monkeypatch)
    dst = root / "dst"
    dst.mkdir()
    (dst / "old.txt").write_text("old")
    payload = root / "new.txt"
    payload.write_text("new")
    archive = root / "payload.tar"
    with tarfile.open(archive, "w") as tar:
        tar.add(payload, arcname="new.txt")

    original_replace = transfer_ops.os.replace
    calls = 0

    def fail_publish(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("publish failed")
        return original_replace(source, target)

    monkeypatch.setattr(transfer_ops.os, "replace", fail_publish)
    with pytest.raises(OSError, match="publish failed"):
        transfer_ops.transfer_unpack_archive("payload.tar", "dst", cleanup_archive=False)
    assert (dst / "old.txt").read_text() == "old"

def test_unpack_reports_archive_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _transfer_workspace(tmp_path, monkeypatch)
    payload = root / "new.txt"
    payload.write_text("new")
    archive = root / "payload.tar"
    with tarfile.open(archive, "w") as tar:
        tar.add(payload, arcname="new.txt")
    original_unlink = Path.unlink

    def fail_archive_unlink(self: Path, *args, **kwargs):
        if self == archive:
            raise OSError("archive cleanup failed")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_archive_unlink)
    result = transfer_ops.transfer_unpack_archive("payload.tar", "dst")
    assert result["archive_deleted"] is False
    assert "archive cleanup failed" in result["cleanup_errors"][0]

def test_pack_dir_detects_source_change_before_add(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _transfer_workspace(tmp_path, monkeypatch)
    (root / "src").mkdir()
    (root / "src" / "file.txt").write_text("x")
    original_signature = transfer_ops._entry_signature
    seen = 0

    def changed(path: Path):
        nonlocal seen
        value = original_signature(path)
        if path.name == "file.txt":
            seen += 1
            if seen >= 2:
                return ("file", value[1] + 1, *value[2:])
        return value

    monkeypatch.setattr(transfer_ops, "_entry_signature", changed)
    with pytest.raises(RuntimeError, match="changed during packing"):
        transfer_ops.transfer_pack_dir("src", compression="none")
