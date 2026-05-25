
import pytest

from local_shell_mcp.fs_ops import edit_text, read_text, resolve_path, write_text
from local_shell_mcp.settings import get_settings


def test_write_read_edit(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    write_text("a.txt", "hello world")
    assert read_text("a.txt")["content"] == "hello world"
    edit_text("a.txt", "world", "mcp")
    assert read_text("a.txt")["content"] == "hello mcp"


def test_reject_path_escape(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER", "false")
    get_settings.cache_clear()
    with pytest.raises(ValueError):
        resolve_path("/etc/passwd")
