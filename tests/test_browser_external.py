from __future__ import annotations

import sys
from pathlib import Path

import pytest

from local_shell_mcp import browser_sessions
from local_shell_mcp.browser_external_client import ExternalBrowserSessionManager
from local_shell_mcp.settings import get_settings


@pytest.fixture(autouse=True)
def _settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_PYTHON_BIN", sys.executable)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
    browser_sessions._BROWSER_MANAGERS.clear()


@pytest.mark.asyncio
async def test_external_session_process_and_rpc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_BROWSER_RUNTIME", "external")
    manager = browser_sessions.get_browser_session_manager(tmp_path / ".state")
    assert isinstance(manager, ExternalBrowserSessionManager)
    assert manager is browser_sessions.get_browser_session_manager(tmp_path / ".state")

    assert await manager.manage(action="list") == {"sessions": [], "cleanup_pending": []}
    with pytest.raises(ValueError, match="action must be"):
        await manager.manage(action="invalid")
    with pytest.raises(ValueError, match="unknown browser session"):
        await manager.close("does-not-exist")
    with pytest.raises(ValueError, match="Path escapes workspace"):
        await manager.start(storage_state_path="../outside.json")

    process = manager._process
    assert process is not None and process.returncode is None
    await manager._discard()
    assert process.returncode is not None
    assert await manager.manage(action="list") == {"sessions": [], "cleanup_pending": []}
    await manager._discard()


@pytest.mark.asyncio
async def test_external_browser_actions_and_storage(tmp_path: Path):
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            installed = Path(playwright.chromium.executable_path).is_file()
    except ImportError:
        installed = False
    if not installed:
        pytest.skip("Chromium is not installed")

    page = tmp_path / "page.html"
    page.write_text(
        "<html><head><title>External</title></head><body>"
        "<button onclick=\"document.querySelector('p').textContent='updated'\">Go</button>"
        "<p>initial</p></body></html>",
        encoding="utf-8",
    )
    manager = ExternalBrowserSessionManager(tmp_path / ".state")
    try:
        started = await manager.start(url=page.as_uri())
        session_id = started["session_id"]
        assert started["pages"][0]["title"] == "External"
        snap = await manager.snapshot(session_id, screenshot=True)
        assert Path(snap["screenshot_path"]).is_file()
        assert snap["interactive_elements"][0]["ref"] == "e1"
        await manager.act(session_id, [{"action": "click", "target": "e1"}])
        updated = await manager.snapshot(session_id, screenshot=False)
        assert "updated" in updated["text"]
        closed = await manager.close(session_id, save_storage_state_path="browser-state.json")
        assert closed["closed"]
        assert (tmp_path / "browser-state.json").is_file()
        assert (await manager.manage(action="list"))["sessions"] == []
    finally:
        await manager._discard()


@pytest.mark.asyncio
async def test_external_python_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_PYTHON_BIN", str(tmp_path / "missing-python"))
    get_settings.cache_clear()
    manager = ExternalBrowserSessionManager(tmp_path / ".state")
    with pytest.raises(RuntimeError, match="External Python is unavailable"):
        await manager.manage(action="list")


@pytest.mark.asyncio
async def test_external_playwright_missing_reports_install_instructions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import venv

    venv_dir = tmp_path / "isolated-python"
    venv.EnvBuilder(with_pip=False).create(venv_dir)
    executable = venv_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    monkeypatch.setenv("LOCAL_SHELL_MCP_PYTHON_BIN", str(executable))
    get_settings.cache_clear()
    manager = ExternalBrowserSessionManager(tmp_path / ".state")
    try:
        assert (await manager.manage(action="list"))["sessions"] == []
        with pytest.raises(RuntimeError, match="Playwright is not installed"):
            await manager.start()
    finally:
        await manager._discard()


def test_external_browser_path_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from local_shell_mcp.browser_external_paths import relative_display, resolve_path

    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(root))
    monkeypatch.setenv("LOCAL_SHELL_MCP_TEST_PATH", "a.txt")
    child = root / "a.txt"
    child.write_text("content", encoding="utf-8")
    assert resolve_path("$LOCAL_SHELL_MCP_TEST_PATH", must_exist=True) == child
    assert resolve_path(child) == child
    assert relative_display(Path("a.txt")) == "a.txt"
    assert relative_display(child) == "a.txt"
    assert relative_display(tmp_path) == str(tmp_path)
    with pytest.raises(FileNotFoundError):
        resolve_path("missing.txt", must_exist=True)


@pytest.mark.asyncio
async def test_external_browser_stdio_worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import io
    import json

    from local_shell_mcp import browser_external_service

    calls = []

    class FakeBrowserSessionManager:
        def __init__(self, state_dir):
            assert state_dir == tmp_path / ".state"

        async def manage(self, **kwargs):
            calls.append(kwargs)
            return {"closed": 0}

        async def snapshot(self, session_id):
            assert session_id == "session"
            return {"text": "汉字"}

    monkeypatch.setattr(
        browser_external_service, "BrowserSessionManager", FakeBrowserSessionManager
    )
    requests = [
        {"method": "snapshot", "args": ["session"], "kwargs": {}},
        {"method": "private_method", "args": [], "kwargs": {}},
        {"method": "manage", "args": [], "kwargs": {"action": "list"}},
        {"method": "snapshot", "args": [], "kwargs": {}},
    ]
    input_stream = io.BytesIO(
        ("\n".join(json.dumps(value) for value in requests) + "\n{invalid-json}\n").encode()
    )
    output_stream = io.StringIO()
    await browser_external_service._serve(
        tmp_path / ".state", input_stream=input_stream, output_stream=output_stream
    )
    responses = [json.loads(line) for line in output_stream.getvalue().splitlines()]
    assert len(responses) == 5
    assert responses[0] == {"ok": True, "result": {"text": "汉字"}}
    assert responses[1]["error_type"] == "ValueError"
    assert responses[2]["ok"] is True
    assert responses[3]["error_type"] == "TypeError"
    assert responses[4]["error_type"] == "JSONDecodeError"
    assert calls == [{"action": "list"}, {"action": "cleanup"}]
