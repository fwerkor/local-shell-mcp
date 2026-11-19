"""React chat uploads never escape Controller private state or bypass LSM scopes."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote

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
            multipart = await client.post("/api/files", files={"file": ("chat.txt", b"chat attachment", "text/plain")},
                                          data={"file_id": "client-temp-id"})
            assert multipart.status_code == 200, multipart.text
            uploaded = multipart.json()
            assert uploaded["temp_file_id"] == "client-temp-id"
            assert uploaded["file_id"] != "client-temp-id"
            assert uploaded["bytes"] == 15
            assert uploaded["filepath"].startswith("/api/files/download/")
            download = await client.get(uploaded["filepath"])
            assert download.content == b"chat attachment"
            assert download.headers["x-content-type-options"] == "nosniff"
            # Pinned LibreChat data-service.ts uses /download/:userId/:file_id,
            # not the one-segment internal legacy URL returned on upload.
            original_url = f"/api/files/download/local/{uploaded['file_id']}"
            canonical = await client.get(original_url)
            assert canonical.status_code == 200
            assert canonical.content == b"chat attachment"
            metadata = json.loads(unquote(canonical.headers["x-file-metadata"]))
            assert metadata["file_id"] == uploaded["file_id"]
            assert metadata["filename"] == "chat.txt"
            assert metadata["filepath"] == uploaded["filepath"]
            assert metadata["source"] == "local"
            assert not {"owner", "user", "text", "machine", "path", "tenantId", "_id"}.intersection(metadata)
            assert (await client.get(f"/api/files/download/foreign/{uploaded['file_id']}")).status_code == 404
            assert (await client.get("/api/files/download/local/missing")).status_code == 404
            from local_shell_mcp.webui.generations import GenerationStore
            from local_shell_mcp.webui.routes import _repo
            store = GenerationStore(_repo().database)
            generation, _ = store.begin("local", {"text": "Read this", "files": [
                {"file_id": uploaded["file_id"], "filepath": "/forged/private"}]})
            history = store.history("local", generation.conversation_id)
            assert "/forged/private" not in str(history)
            descriptors = json.loads(history[-1]["content"].split("Controller attachments (use authorized LSM file tools):\n")[1])
            assert Path(descriptors[0]["path"]).is_relative_to(tmp_path / ".local-shell-mcp" / "attachments")
            assert Path(descriptors[0]["path"]).read_bytes() == b"chat attachment"
            assert _repo().messages("local", generation.conversation_id)["messages"][0]["files"][0]["file_id"] == uploaded["file_id"]
            with pytest.raises(KeyError, match="Attachment not found"):
                store.begin("foreign-owner", {"text": "Read stolen", "files": [uploaded]})
            bad = await client.post("/api/files", files={"file": ("empty.txt", b"", "text/plain")})
            assert bad.status_code == 400
            missing = await client.post("/api/files", data={"file_id": "no-file"})
            assert missing.status_code == 400
            assert (await client.get("/api/files/download/missing")).status_code == 404
            for extra in ({"file_id": "x" * 201}, {"tool_resource": "file_search"}):
                error = await client.post("/api/files", files={"file": ("bad.txt", b"body", "text/plain")}, data=extra)
                assert error.status_code == 400
            bad_form = await client.post("/api/files", content=b"broken", headers={"Content-Type": "multipart/form-data"})
            assert bad_form.status_code == 400
            from local_shell_mcp.webui import attachments
            with monkeypatch.context() as patch:
                patch.setattr(attachments, "MAX_ATTACHMENT_BYTES", 3)
                large = await client.post("/api/files", files={"file": ("big.txt", b"1234", "text/plain")})
                assert large.status_code == 400
                bounded = await client.post("/api/files", files={"file": ("big.txt", b"x" * 66000, "text/plain")})
                assert bounded.status_code == 400
            with _repo().database.connect() as db:
                for values in (None, ["bad"], [{}], [uploaded] * 33):
                    with pytest.raises(ValueError):
                        attachments.resolve_files(db, "local", values)
                assert len(attachments.resolve_files(db, "local", [uploaded, uploaded])) == 1
                row = db.execute("SELECT path FROM attachments WHERE id=?", (uploaded["file_id"],)).fetchone()
            Path(row["path"]).unlink()
            assert (await client.get(uploaded["filepath"])).status_code == 404


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


def test_attachment_directory_symlinks_are_not_followed(tmp_path):
    import hashlib

    state = tmp_path / ".local-shell-mcp"
    state.mkdir()
    container = state / "attachments"
    container.mkdir()
    outsider = tmp_path / "outsider"
    outsider.mkdir()
    unsafe = container / hashlib.sha256(b"alice").hexdigest()[:32]
    unsafe.symlink_to(outsider, target_is_directory=True)
    with pytest.raises(PermissionError, match="Unsafe"):
        _safe_attachment_path("alice", "notes.txt", state)
    assert list(outsider.iterdir()) == []


@pytest.mark.asyncio
async def test_upload_denies_disabled_local_and_malformed_content_length(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_DISABLE_LOCAL", "true")
    get_settings.cache_clear()
    try:
        app = _with_oauth_routes(Starlette())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            url = "/api/lsm/controller/attachments/upload?name=ordinary.txt"
            assert (await client.post(url, content=b"one")).status_code == 403
            assert (await client.post("/api/files", files={"file": ("blocked.txt", b"body")})).status_code == 403
            monkeypatch.setenv("LOCAL_SHELL_MCP_DISABLE_LOCAL", "false")
            get_settings.cache_clear()
            bad = await client.post(url, content=b"one", headers={"content-length": "NaN"})
            assert bad.status_code == 400
            assert (await client.post(url, content=b"one", headers={"content-length": "100"})).status_code == 400
            assert (await client.post(url, content=b"one-more", headers={"content-length": "3"})).status_code == 400
            assert (await client.post(url, content=b"one", headers={"content-length": str(40 * 1024 * 1024)})).status_code == 400
            root = tmp_path / ".local-shell-mcp" / "attachments"
            assert not list(root.glob("**/*txt"))
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_upload_rolls_back_when_db_or_disk_write_fails(tmp_path, monkeypatch):
    from local_shell_mcp.webui import attachments

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_DISABLE_LOCAL", "false")
    get_settings.cache_clear()
    try:
        app = _with_oauth_routes(Starlette())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            url = "/api/lsm/controller/attachments/upload?name=rollback.txt"
            class FailDatabase:
                def connect(self):
                    raise OSError("Simulated database unavailability")

            repo = attachments._repo()
            with monkeypatch.context() as patch:
                patch.setattr(attachments, "_repo", lambda: type("R", (), {"database": FailDatabase()})())
                response = await client.post(url, content=b"should be discarded")
                assert response.status_code == 500
            assert list((tmp_path / ".local-shell-mcp" / "attachments").glob("**/*.txt")) == []
            original_open = attachments.os.open

            def deny_attachment_open(path, *args, **kwargs):
                if "attachments" in str(path):
                    raise OSError("Simulated disk failure")
                return original_open(path, *args, **kwargs)

            with monkeypatch.context() as patch:
                patch.setattr(attachments.os, "open", deny_attachment_open)
                response = await client.post(url, content=b"not stored")
                assert response.status_code == 500
            assert list((tmp_path / ".local-shell-mcp" / "attachments").glob("**/*.txt")) == []
            assert repo is not None
    finally:
        get_settings.cache_clear()
