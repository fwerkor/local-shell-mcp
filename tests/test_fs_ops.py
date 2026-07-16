
import hashlib
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from local_shell_mcp.fs_ops import (
    FileConflictError,
    delete_path,
    edit_text,
    list_dir,
    perform_file_action,
    read_text,
    resolve_path,
    write_text,
)
from local_shell_mcp.settings import get_settings
from local_shell_mcp.shell_ops import check_command_policy
from local_shell_mcp.tools import build_mcp


def test_write_read_edit(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    write_text("a.txt", "hello world")
    assert read_text("a.txt")["content"] == "hello world"
    edit_text("a.txt", [{"old": "world", "new": "mcp"}])
    assert read_text("a.txt")["content"] == "hello mcp"


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        ({"old": "hello", "new": "hi", "replace_all": "false"}, "replace_all must be a boolean"),
        ({"old": 1, "new": "hi"}, "old must be a string"),
        ({"old": "hello", "new": 1}, "new must be a string"),
        ({"old": "hello"}, "missing field(s): new"),
        ({"old": "hello", "new": "hi", "unexpected": True}, "unsupported field(s): unexpected"),
        ({"old": "", "new": "hi"}, "old must not be empty"),
    ],
)
def test_edit_text_rejects_invalid_edit_objects(tmp_path, monkeypatch, edit, message):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    path = tmp_path / "a.txt"
    path.write_text("hello hello", encoding="utf-8")

    with pytest.raises(ValueError, match=re.escape(message)):
        edit_text("a.txt", [edit])

    assert path.read_text(encoding="utf-8") == "hello hello"


def test_read_text_refuses_binary_without_decoding(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    payload = b"\x89PNG\r\n\x1a\n\x00binary"
    (tmp_path / "image.png").write_bytes(payload)

    result = read_text("image.png")

    assert result == {
        "path": "image.png",
        "bytes": len(payload),
        "binary": True,
        "content": None,
        "message": "Refusing to read binary file as text",
    }


def test_read_text_binary_preview_is_explicit_and_limited(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01\x02\x03\x04")

    result = read_text("blob.bin", binary_preview="hex", binary_preview_bytes=2)

    assert result["content"] is None
    assert result["preview"] == "0001"
    assert result["preview_encoding"] == "hex"
    assert result["preview_bytes"] == 2


def test_binary_preview_does_not_read_entire_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01\x02\x03\x04")

    def fail_read_bytes(self):  # noqa: ANN001, ARG001
        raise AssertionError("read_bytes should not be used for bounded previews")

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)

    result = read_text("blob.bin", binary_preview="hex", binary_preview_bytes=2)

    assert result["preview"] == "0001"


def test_read_text_reports_original_size_and_truncation(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_FILE_READ_BYTES", "5")
    get_settings.cache_clear()
    (tmp_path / "long.txt").write_text("hello world", encoding="utf-8")

    result = read_text("long.txt")

    assert result["bytes"] == 11
    assert result["bytes_read"] == 5
    assert result["truncated_bytes"] == 6
    assert result["truncated"] is True
    assert result["content"] == "hello"


def test_write_text_does_not_read_existing_file_before_overwrite(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    (tmp_path / "existing.txt").write_text("old", encoding="utf-8")

    def fail_read_text(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ARG001
        raise AssertionError("write_text should not read old file contents")

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    result = write_text("existing.txt", "new")

    assert result["created"] is False
    assert (tmp_path / "existing.txt").read_bytes().decode("utf-8") == "new"



@pytest.mark.skipif(os.name == "nt", reason="symlink creation requires privileges on Windows")
def test_file_mutations_operate_on_symlink_instead_of_target(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    target = tmp_path / "target"
    target.mkdir()
    (target / "important.txt").write_text("keep", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)

    entries = {entry["path"]: entry for entry in list_dir(".")}
    assert entries["link"]["type"] == "link"
    assert entries["link"]["target"] == str(target)
    assert entries["target"]["type"] == "dir"

    copied = perform_file_action("copy", "link", "link-copy")
    assert copied["destination"] == "link-copy"
    assert (tmp_path / "link-copy").is_symlink()
    assert os.readlink(tmp_path / "link-copy") == str(target)

    result = delete_path("link", recursive=True)
    assert result == {"path": "link", "deleted": "link"}
    assert not link.exists()
    assert not link.is_symlink()
    assert (target / "important.txt").read_text(encoding="utf-8") == "keep"


def test_expected_revision_write_is_serialized(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    path = tmp_path / "shared.txt"
    path.write_text("opened", encoding="utf-8")
    expected_sha256 = read_text("shared.txt")["sha256"]
    barrier = threading.Barrier(2)

    def writer(content: str):
        barrier.wait(timeout=5)
        return write_text(
            "shared.txt",
            content,
            overwrite=True,
            expected_sha256=expected_sha256,
        )

    outcomes = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(writer, "first"), pool.submit(writer, "second")]
        for future in futures:
            try:
                outcomes.append(("success", future.result()))
            except FileConflictError as exc:
                outcomes.append(("conflict", str(exc)))

    assert [kind for kind, _ in outcomes].count("success") == 1
    assert [kind for kind, _ in outcomes].count("conflict") == 1
    assert path.read_text(encoding="utf-8") in {"first", "second"}

def test_edit_refuses_files_above_write_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_FILE_WRITE_BYTES", "5")
    get_settings.cache_clear()
    (tmp_path / "large.txt").write_text("hello world", encoding="utf-8")

    with pytest.raises(ValueError, match="Refusing to edit"):
        edit_text("large.txt", [{"old": "world", "new": "mcp"}])


def test_edits_refuse_binary_files(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    original = b"abc\x00world"
    (tmp_path / "blob.bin").write_bytes(original)

    with pytest.raises(ValueError, match="Refusing to read binary file as text"):
        edit_text("blob.bin", [{"old": "world", "new": "mcp"}])
    with pytest.raises(ValueError, match="Refusing to read binary file as text"):
        edit_text("blob.bin", [{"old": "world", "new": "mcp"}])

    assert (tmp_path / "blob.bin").read_bytes() == original


@pytest.mark.asyncio
async def test_fetch_omits_binary_content_from_text_field(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    (tmp_path / "blob.bin").write_bytes(b"abc\x00world")

    response = await build_mcp().call_tool("fetch", {"id": "blob.bin"})
    payload = json.loads(response[0][0].text)

    assert payload["text"] == "Refusing to read binary file as text"
    assert payload["metadata"]["binary"] is True
    assert payload["metadata"]["bytes"] == 9


@pytest.mark.asyncio
async def test_read_file_rejects_too_many_files(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_READ_MANY_FILES", "1")
    get_settings.cache_clear()
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")

    response = await build_mcp().call_tool("read_file", {"path": ["a.txt", "b.txt"]})
    payload = response[0][0].text

    assert "Refusing to read 2 files; max is 1" in payload


def test_reject_path_escape(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER", "false")
    get_settings.cache_clear()
    with pytest.raises(ValueError):
        resolve_path("/etc/passwd")


def test_full_container_mode_disables_builtin_restrictions(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER", "true")
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.command_denylist == []
    assert settings.path_denylist == []
    resolved = resolve_path("/etc/passwd")
    assert resolved.is_absolute()
    assert resolved.parts[-2:] == ("etc", "passwd")
    check_command_policy("mount /dev/null /mnt || true")


def test_read_text_handles_truncated_utf8_sequence(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_FILE_READ_BYTES", "4")
    get_settings.cache_clear()
    (tmp_path / "utf8.txt").write_text("你好", encoding="utf-8")

    result = read_text("utf8.txt")

    assert result["truncated"] is True
    assert result["bytes_read"] == 4
    assert result["content"] == "你�"


def test_path_lock_state_and_lock_files_are_bounded(tmp_path, monkeypatch):
    from local_shell_mcp.fs_ops import _PATH_LOCKS, _path_lock

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    get_settings.cache_clear()

    for index in range(600):
        with _path_lock(tmp_path / f"file-{index}.txt"):
            pass

    assert _PATH_LOCKS == {}
    lock_files = list((tmp_path / ".state" / "locks").glob("*.lock"))
    assert len(lock_files) <= 256
    assert all(path.name.startswith("shard-") for path in lock_files)


def test_multi_path_lock_deduplicates_colliding_file_shards(tmp_path, monkeypatch):
    from local_shell_mcp.fs_ops import _path_locks

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    get_settings.cache_clear()

    seen: dict[str, Path] = {}
    collision: tuple[Path, Path] | None = None
    for index in range(2_000):
        path = tmp_path / f"collision-{index}"
        shard = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:2]
        previous = seen.get(shard)
        if previous is not None:
            collision = (previous, path)
            break
        seen[shard] = path
    assert collision is not None

    completed = threading.Event()
    errors: list[BaseException] = []

    def acquire():
        try:
            with _path_locks(list(collision)):
                pass
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            completed.set()

    thread = threading.Thread(target=acquire, daemon=True)
    thread.start()
    thread.join(timeout=2)

    assert completed.is_set(), "colliding lock shards deadlocked"
    assert errors == []


def test_file_actions_exist_ok_requires_matching_object_type(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    (tmp_path / "file").write_text("data", encoding="utf-8")
    (tmp_path / "directory").mkdir()

    with pytest.raises(FileExistsError, match="not a directory"):
        perform_file_action("mkdir", "file", exist_ok=True)
    with pytest.raises(FileExistsError, match="not a regular file"):
        perform_file_action("touch", "directory", exist_ok=True)

    assert perform_file_action("mkdir", "directory", exist_ok=True)["action"] == "mkdir"
    assert perform_file_action("touch", "file", exist_ok=True)["action"] == "touch"
