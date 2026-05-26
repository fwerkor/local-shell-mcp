
import pytest

from local_shell_mcp.fs_ops import edit_text, read_text, resolve_path, write_text
from local_shell_mcp.settings import get_settings
from local_shell_mcp.shell_ops import check_command_policy


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


def test_full_container_mode_disables_builtin_restrictions(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER", "true")
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.command_denylist == []
    assert settings.path_denylist == []
    assert str(resolve_path("/etc/passwd")) == "/etc/passwd"
    check_command_policy("mount /dev/null /mnt || true")
