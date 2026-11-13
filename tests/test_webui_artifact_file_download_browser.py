"""Original file-backed Artifact panel downloads bytes, never its HTML preview.

Uses the pinned LibreChat sample DOCX, real source-ported Office preview
producer, atomic SQLite SSE attachment publication, persisted final message
and retained React card/panel to distinguish preview HTML from source bytes.
"""

from __future__ import annotations

import asyncio
import json
import re
import socket
from pathlib import Path
from urllib.parse import unquote

import pytest
from starlette.applications import Starlette

from local_shell_mcp.main import _with_oauth_routes
from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import shared_database
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.office_preview import DOCX_MIME, publish_office_tool_output


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
    store = GenerationStore(db)
    generation, _ = store.begin("local", {"text": "Produce report.docx"})
    convo_id = generation.conversation_id
    source_bytes = (Path(__file__).parent / "fixtures/librechat/office/sample.docx").read_bytes()
    store.append("local", generation.run_id, {"event": "on_run_step_completed", "data": {
        "result": {"id": "step_office", "index": 1, "completed_at": 1,
                   "type": "tool_call", "tool_call": {
                       "id": "call_docx", "name": "execute_code", "args": {"lang": "python", "code": "print('report')"},
                       "type": "tool_call", "output": "Document generated", "progress": 1,
                   }},
    }})
    attachment_file = await publish_office_tool_output(
        "local", generation.run_id, "call_docx", "report.docx", DOCX_MIME,
        source_bytes, database=db, state_dir=get_settings().state_dir,
    )
    html = attachment_file["text"]
    assert "This is a sample DOCX file." in html
    assert store.finish("local", generation.run_id, status="complete", text="Report attached.")

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
                card = page.get_by_role("button", name=re.compile(r"report\.docx.*Click to open", re.I))
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
                assert "This is a sample DOCX file." not in str(cache_metadata)
                assert not errors, errors
            finally:
                await browser.close()
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=15)
        get_settings.cache_clear()
