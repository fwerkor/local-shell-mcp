"""Original React Artifact preview uses sandboxed templates, not Monaco assets.

Capture off-origin requests in a real Chromium browser while enforcing a fully
blocked network; this test prevents treating local Monaco as proof of offline
Sandpack/React previews.
"""

from __future__ import annotations

import asyncio
import re
import socket

import pytest
from starlette.applications import Starlette

from local_shell_mcp.main import _with_oauth_routes
from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui import generation_routes

SAMPLES = [
    ("HTML preview", "text/html", "<html><body><h1>HTML rendering check</h1></body></html>"),
    (
        "React preview",
        "application/vnd.react",
        "export default function App(){ return <h1>React rendering check</h1> }",
    ),
    ("Mermaid preview", "application/vnd.mermaid", "graph TD; A-->B"),
    (
        "SVG preview",
        "image/svg+xml",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 150 50"><text x="5" y="30">SVG render</text></svg>',
    ),
    ("Markdown preview", "text/markdown", "# Markdown rendering check"),
    ("SVG alias preview", "image/svg", '<svg viewBox="0 0 40 20"><text y="12">SVG alias</text></svg>'),
    # These synthetic MIME types are the pinned original viewer contracts.
    # A real Office attachment must be converted to sanitized HTML by the
    # shared file pipeline; this browser test checks the *retained viewer*,
    # not the still-unported binary conversion path.
    ("Document preview", "application/vnd.librechat.docx-preview", "<html><body><h1>DOCX check</h1></body></html>"),
    ("Spreadsheet preview", "application/vnd.librechat.spreadsheet-preview", "<html><body><table><tr><td>Sheet check</td></tr></table></body></html>"),
    ("Presentation preview", "application/vnd.librechat.presentation-preview", "<html><body><section>Slides check</section></body></html>"),
    ("Source code preview", "application/vnd.code", "def fixture(): return 1"),
]


@pytest.mark.asyncio
async def test_artifact_types_preview_dependency_inventory(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.async_api")
    import uvicorn

    for key, value in {
        "WORKSPACE_ROOT": str(tmp_path),
        "STATE_DIR": str(tmp_path / ".local-shell-mcp"),
        "AUTH_MODE": "none",
        "UI_ENABLED": "true",
        "REMOTE_ENABLED": "false",
        "MODEL_BASE_URL": "http://127.0.0.1:11434/v1",
        "MODEL": "artifact-preview-model",
    }.items():
        monkeypatch.setenv("LOCAL_SHELL_MCP_" + key, value)
    get_settings.cache_clear()

    async def generated(_profile, messages, **_kwargs):
        chunks = [
            f':::artifact{{identifier="preview-{i}" type="{type_}" title="{title}"}}\n'
            f"````\n{body}\n````\n:::"
            for i, (title, type_, body) in enumerate(SAMPLES)
        ]
        for chunk in chunks:
            yield chunk + "\n\n"

    monkeypatch.setattr(generation_routes, "stream_model_with_tools", generated)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(
        uvicorn.Config(
            _with_oauth_routes(Starlette()),
            host="127.0.0.1",
            port=port,
            log_level="error",
            access_log=False,
        )
    )
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
            external: list[str] = []
            failures: list[str] = []

            async def local_only(route):
                url = route.request.url
                if url.startswith((origin, "data:", "blob:")):
                    await route.continue_()
                else:
                    if url not in external:
                        external.append(url)
                    await route.abort()

            await page.route("**/*", local_only)
            page.on("pageerror", lambda error: failures.append(str(error)))
            try:
                await page.goto(origin + "/c/new", wait_until="domcontentloaded")
                await page.get_by_test_id("text-input").fill("Produce the ten sample artifacts.")
                await page.locator('button[type="submit"]').first.click()
                for title, _, _ in SAMPLES:
                    await page.get_by_text(title, exact=True).first.wait_for(timeout=20000)
                panel = page.locator("#artifact-viewer")
                seen = {}
                for title, _, _ in SAMPLES:
                    await page.get_by_role(
                        "button", name=re.compile(re.escape(title))
                    ).first.click()
                    if await panel.count() == 0:
                        await page.get_by_role(
                            "button", name=re.compile(re.escape(title))
                        ).first.click()
                    await panel.wait_for(timeout=10000)
                    radio = panel.get_by_role("radio", name="Preview", exact=True)
                    if await radio.count():
                        await radio.click()
                    if title in {"Document preview", "Spreadsheet preview", "Presentation preview"}:
                        # Original Office buckets are preview-only, not an
                        # editable HTML code document.
                        assert await panel.get_by_role("radio", name="Code", exact=True).count() == 0
                        assert await panel.get_by_role("radio").count() == 1
                    if title == "Source code preview":
                        # The generated code bucket has a source-only view.
                        assert await panel.get_by_role("radio", name="Preview", exact=True).count() == 0
                        assert await panel.get_by_role("radio").count() == 1
                    if title in {"Document preview", "Source code preview"}:
                        # Unlike an original-file attachment, these model-only
                        # artifacts must export the preview/source as real
                        # downloadable bytes using the existing UI hook.
                        async with page.expect_download(timeout=10000) as pending:
                            await panel.get_by_role("button", name=re.compile("Download", re.I)).click()
                        download = await pending.value
                        target = tmp_path / ("office-preview-export.html" if title == "Document preview" else "code-export.txt")
                        await download.save_as(target)
                        marker = "DOCX check" if title == "Document preview" else "def fixture"
                        assert marker in target.read_text(encoding="utf-8")
                        assert download.suggested_filename.lower().endswith(
                            ".html" if title == "Document preview" else ".txt"
                        )
                    await page.wait_for_timeout(700)
                    seen[title] = {
                        "iframes": await panel.locator("iframe").count(),
                        "external": list(external),
                        "panel_text_tail": (await panel.inner_text())[-170:],
                    }
                print("ARTIFACT_PREVIEW_DIAGNOSTICS", seen, "PAGE_ERRORS", failures)
                assert len(seen) == len(SAMPLES)
            finally:
                await browser.close()
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=15)
        get_settings.cache_clear()
