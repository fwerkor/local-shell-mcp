"""React chat uploads never escape Controller private state or bypass LSM scopes."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.main import _with_oauth_routes
from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui.attachments import _safe_attachment_path


def test_attachments_have_per_owner_private_paths(tmp_path):
    first = _safe_attachment_path("alice", "../../../notes.txt", tmp_path / ".local-shell-mcp")
    second = _safe_attachment_path("bob", "notes.txt", tmp_path / ".local-shell-mcp")
    assert first.parent != second.parent
    assert first.name.endswith("-notes.txt")
    assert first.is_relative_to(tmp_path / ".local-shell-mcp")
    assert not (tmp_path / "notes.txt").exists()
    for name in ("", ".", "..", "\x00hidden", "a\nb", "a" * 201):
        with pytest.raises(ValueError):
            _safe_attachment_path("alice", name, tmp_path / ".local-shell-mcp")


@pytest.mark.asyncio
async def test_controller_chat_attachment_upload_and_sqlite_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_ENABLED", "true")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    monkeypatch.delenv("LOCAL_SHELL_MCP_STATE_BACKEND", raising=False)
    get_settings.cache_clear()
    try:
        app = _with_oauth_routes(Starlette())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            path = "/api/lsm/controller/attachments/upload?name=../../hello.txt"
            result = await client.post(path, content=b"hello from React", headers={"Content-Type": "text/plain"})
            assert result.status_code == 200, result.text
            payload = result.json()
            assert payload["ok"] is True
            attachment = Path(payload["data"]["path"])
            assert attachment.is_relative_to(tmp_path / ".local-shell-mcp" / "attachments")
            assert attachment.read_bytes() == b"hello from React"
            assert payload["data"]["size"] == len(b"hello from React")
            assert not (tmp_path / ".lsm-chat-uploads").exists()
            listed = await client.get("/api/files")
            assert listed.status_code == 200
            assert any(item["file_id"] == payload["data"]["file_id"] for item in listed.json())
            for name in ("bad%00name", ".", "a" * 201):
                error = await client.post("/api/lsm/controller/attachments/upload?name=" + name, content=b"body")
                assert error.status_code == 400, error.text
            empty = await client.post(path, content=b"")
            assert empty.status_code == 400
    finally:
        get_settings.cache_clear()
