"""Original file-backed Artifact panel downloads bytes, never its HTML preview.

Uses the real SQLite attachment publisher and retained React card/panel. The
Office-to-HTML conversion itself is an upstream callback and is intentionally
represented by a trusted pre-rendered HTML fixture until that service is ported.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import socket
import uuid
from urllib.parse import unquote
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from starlette.applications import Starlette

from local_shell_mcp.main import _with_oauth_routes
from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import shared_database
from local_shell_mcp.webui.attachments import file_record, publish_attachment
from local_shell_mcp.webui.storage import WorkspaceRepository


def _docx_bytes() -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p/></w:body></w:document>')
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_original_office_file_download_preserves_binary_not_preview(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.async_api")
    import uvicorn

    for key, value in {
        "WORKSPACE_ROOT": str(tmp_path), "STATE_DIR": str(tmp_path / ".local-shell-mcp"),
        "AUTH_MODE": "none", "UI_ENABLED": "true", "REMOTE_ENABLED": "false",
    }.items():
        monkeypatch.setenv("LOCAL_SHELL_MCP_" + key, value)
    get_settings.cache_clear()
    db = shared_database(get_settings().state_dir.resolve())
    repo = WorkspaceRepository(db)
    conversation = repo.create_conversation("local", {"title": "Office output"})
    convo_id = conversation["conversationId"]
    user = repo.add_message("local", convo_id, {
        "role": "user", "text": "Produce report.docx", "sender": "User", "isCreatedByUser": True,
        "content": [{"type": "text", "text": "Produce report.docx"}],
    })
    source_bytes = _docx_bytes()
    html = '<!doctype html><html><body><h1>REPORT PREVIEW ONLY</h1></body></html>'

    async def original_bytes():
        yield source_bytes

    attachment_file = await publish_attachment(
        "local", "report.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        original_bytes(), get_settings().state_dir,
        metadata={"text": html, "textFormat": "html", "status": "ready"},
    )
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM attachments WHERE id=?", (attachment_file["file_id"],)).fetchone()
    original_attachment = file_record(row)
    message_id = str(uuid.uuid4())
    original_attachment.update({
        "user": "local", "messageId": message_id, "toolCallId": "call_docx",
        "conversationId": convo_id,
    })
    repo.add_message("local", convo_id, {
        "messageId": message_id, "parentMessageId": user["messageId"],
        "role": "assistant", "sender": "Assistant", "endpoint": "agents",
        "text": "Report attached.",
        "content": [{"type": "tool_call", "tool_call": {
            "id": "call_docx", "name": "execute_code", "args": {"lang": "python", "code": "print('report')"},
            "output": "Document generated", "progress": 1,
        }}],
        "attachments": [original_attachment],
    })

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(
        _with_oauth_routes(Starlette()), host="127.0.0.1", port=port,
        log_level="error", access_log=False,
    ))
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.05)
        assert server.started
        async with playwright.async_playwright() as manager:
            try:
                browser = await manager.chromium.launch(headless=True)
            except playwright.Error as exc:
                if "Executable doesn't exist" in str(exc):
                    pytest.skip("Optional Chromium not installed")
                raise
            page = await browser.new_page(viewport={"width": 1440, "height": 900}, accept_downloads=True)
            external = []
            errors = []

            async def local_only(route):
                if route.request.url.startswith((origin, "data:", "blob:")):
                    await route.continue_()
                else:
                    external.append(route.request.url)
                    await route.abort()

            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.route("**/*", local_only)
            try:
                await page.goto(origin + "/c/" + convo_id, wait_until="domcontentloaded")
                card = page.get_by_role("button", name=re.compile("report.docx", re.I))
                await card.first.wait_for(timeout=15000)
                await card.first.click()
                panel = page.locator("#artifact-viewer")
                await panel.wait_for(timeout=10000)
                assert await panel.get_by_role("radio", name="Code", exact=True).count() == 0
                async with page.expect_download(timeout=12000) as pending:
                    await panel.get_by_role("button", name=re.compile("Download", re.I)).click()
                download = await pending.value
                output = tmp_path / "received-original.docx"
                await download.save_as(output)
                assert download.suggested_filename == "report.docx"
                assert output.read_bytes() == source_bytes
                assert html.encode() not in output.read_bytes()
                canonical = await page.request.get(
                    f"{origin}/api/files/download/local/{attachment_file['file_id']}"
                )
                assert canonical.ok and await canonical.body() == source_bytes
                cache_metadata = json.loads(unquote(canonical.headers["x-file-metadata"]))
                assert cache_metadata["textFormat"] == "html"
                assert cache_metadata["status"] == "ready"
                assert "text" not in cache_metadata
                assert "REPORT PREVIEW ONLY" not in str(cache_metadata)
                assert not errors, errors
            finally:
                await browser.close()
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=15)
        get_settings.cache_clear()
