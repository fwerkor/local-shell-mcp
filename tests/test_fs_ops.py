
import json
from pathlib import Path

import pytest

from local_shell_mcp.fs_ops import edit_text, multi_edit_text, read_text, resolve_path, write_text
from local_shell_mcp.settings import get_settings
from local_shell_mcp.shell_ops import check_command_policy
from local_shell_mcp.tools import build_mcp


def test_write_read_edit(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    write_text("a.txt", "hello world")
    assert read_text("a.txt")["content"] == "hello world"
    edit_text("a.txt", "world", "mcp")
    assert read_text("a.txt")["content"] == "hello mcp"


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


def test_edit_refuses_files_above_write_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_FILE_WRITE_BYTES", "5")
    get_settings.cache_clear()
    (tmp_path / "large.txt").write_text("hello world", encoding="utf-8")

    with pytest.raises(ValueError, match="Refusing to edit"):
        edit_text("large.txt", "world", "mcp")


def test_edits_refuse_binary_files(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    original = b"abc\x00world"
    (tmp_path / "blob.bin").write_bytes(original)

    with pytest.raises(ValueError, match="Refusing to read binary file as text"):
        edit_text("blob.bin", "world", "mcp")
    with pytest.raises(ValueError, match="Refusing to read binary file as text"):
        multi_edit_text("blob.bin", [{"old": "world", "new": "mcp"}])

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
async def test_read_many_files_rejects_too_many_files(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_READ_MANY_FILES", "1")
    get_settings.cache_clear()
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")

    response = await build_mcp().call_tool("read_many_files", {"paths": ["a.txt", "b.txt"]})
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
    assert str(resolve_path("/etc/passwd")) == "/etc/passwd"
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
