"""Actual machine read/write permission enforcement for local and remote tools."""

from __future__ import annotations

import json

import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui.native_tools import _remote_read, run_machine_tool
from local_shell_mcp.webui.providers import ModelToolCall
from local_shell_mcp.webui.routes import _repo


@pytest.mark.asyncio
async def test_local_file_write_requires_explicit_machine_write(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    repo = _repo()
    cid = repo.create_conversation("local", {"title": "Writer"})["conversationId"]
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "read"})
    call = ModelToolCall("call-1", "file_write", {"path": "notes.txt", "content": "hello"})
    try:
        with pytest.raises(PermissionError, match="read"):
            await run_machine_tool("local", cid, call)
        assert not (tmp_path / "notes.txt").exists()
        repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "write"})
        written = json.loads(await run_machine_tool("local", cid, call))
        assert written["bytes"] == 5
        assert (tmp_path / "notes.txt").read_text() == "hello"
        with pytest.raises(FileExistsError):
            await run_machine_tool("local", cid, call)
        over = json.loads(await run_machine_tool("local", cid, ModelToolCall("call-2", "file_write", {
            "path": "notes.txt", "content": "updated", "overwrite": True,
        })))
        assert over["bytes"] == 7
        assert (tmp_path / "notes.txt").read_text() == "updated"
        with pytest.raises(PermissionError, match="workspace-relative|private state"):
            await run_machine_tool("local", cid, ModelToolCall("call-3", "file_write", {
                "path": ".local-shell-mcp/config.json", "content": "danger",
            }))
        with pytest.raises(PermissionError):
            await run_machine_tool("local", cid, ModelToolCall("call-4", "file_write", {
                "path": "../escape.txt", "content": "danger",
            }))
        with pytest.raises(ValueError):
            await run_machine_tool("local", cid, ModelToolCall("call-5", "file_write", {
                "path": "other.txt", "content": "a" * 20000,
            }))
        assert not (tmp_path.parent / "escape.txt").exists()
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_oauth_write_scope_cannot_be_inferred_from_machine_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "oauth")
    get_settings.cache_clear()
    repo = _repo()
    cid = repo.create_conversation("alice", {"title": "Scoped"})["conversationId"]
    repo.save_setting("alice", "agent.machine_policy.global", {"local": "write"})
    call = ModelToolCall("one", "file_write", {"path": "user.txt", "content": "hi"})
    try:
        with pytest.raises(PermissionError, match="shell:write"):
            await run_machine_tool("alice", cid, call, granted_scopes={"shell:read"})
        with pytest.raises(PermissionError, match="expired"):
            await run_machine_tool("alice", cid, call,
                                   granted_scopes={"shell:read", "shell:write"}, grant_expires=1)
        assert not (tmp_path / "user.txt").exists()
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_remote_file_tools_are_bounded_and_call_exact_worker_rpc(monkeypatch):
    from local_shell_mcp import human_ui

    operations = []

    async def fake_remote(machine, tool, args):
        operations.append((machine, tool, args))
        if tool == "list_files":
            return [{"name": "okay.txt", "type": "file"}, {"name": ".private", "type": "file"}]
        if tool == "read_file":
            return {"content": "a" * 9000, "truncated": False}
        if tool == "write_file":
            return {"bytes": len(args["content"]), "created": True}
        raise AssertionError(tool)

    monkeypatch.setattr(human_ui, "_remote_call", fake_remote)
    listing = json.loads(await _remote_read("worker1", ModelToolCall("call", "file_list", {"path": "."})))
    assert [item["name"] for item in listing["entries"]] == ["okay.txt"]
    assert operations[0][1] == "list_files"
    preview = json.loads(await _remote_read("worker1", ModelToolCall("call", "file_read", {"path": "readme.md"})))
    assert preview["truncated"] is True
    assert len(preview["text"]) == 8192
    result = json.loads(await _remote_read("worker1", ModelToolCall("call", "file_write", {
        "path": "notes.txt", "content": "new remote contents",
    })))
    assert result == {"path": "notes.txt", "bytes": 19, "created": True}
    assert operations[2][1] == "write_file"
    for path in ("../hidden", "/etc/passwd", ".env", "C:\\Windows"):
        with pytest.raises((ValueError, PermissionError)):
            await _remote_read("worker1", ModelToolCall("call", "file_read", {"path": path}))
