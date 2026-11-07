from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from local_shell_mcp import browser_external_client
from local_shell_mcp.browser_external_client import ExternalBrowserSessionManager
from local_shell_mcp.settings import get_settings


class FakeProcess:
    def __init__(self, response: bytes = b"", *, returncode: int | None = None):
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(response)
        self.stdout.feed_eof()
        self.returncode = returncode

    def kill(self):
        self.returncode = -9

    async def wait(self):
        return self.returncode


def _frame(request_id: int) -> bytes:
    payload = json.dumps({"id": request_id, "ok": True, "result": {}}).encode("ascii")
    return str(len(payload)).encode() + b"\n" + payload


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response,error_text",
    [
        (b"", "exited unexpectedly"),
        (b"a" * 17 + b"\n", "Invalid browser RPC frame header"),
        (b"67108865\n", "exceeds maximum frame size"),
        (b"nope\n", "invalid literal"),
        (_frame(987), "exited unexpectedly"),
    ],
)
async def test_external_rpc_reader_errors(response: bytes, error_text: str, tmp_path: Path):
    manager = ExternalBrowserSessionManager(tmp_path)
    process = FakeProcess(response)
    manager._process = process
    pending = asyncio.get_running_loop().create_future()
    manager._pending[1] = pending
    await manager._read_responses(process)
    with pytest.raises(RuntimeError, match=error_text):
        await pending
    assert manager._process is None
    assert manager._pending == {}
    assert process.returncode == -9


@pytest.mark.asyncio
async def test_external_rpc_reader_ignores_completed_and_old_process(tmp_path: Path):
    manager = ExternalBrowserSessionManager(tmp_path)
    completed = asyncio.get_running_loop().create_future()
    completed.cancel()
    manager._pending[1] = completed
    process = FakeProcess(_frame(1), returncode=1)
    await manager._read_responses(process)
    assert completed.cancelled()
    assert process.returncode == 1

    another = FakeProcess(returncode=1)
    manager._process = process
    await manager._read_responses(another)
    assert manager._process is process


@pytest.mark.asyncio
async def test_external_discard_rejects_outstanding_calls(tmp_path: Path):
    manager = ExternalBrowserSessionManager(tmp_path)
    future = asyncio.get_running_loop().create_future()
    manager._pending[123] = future
    await manager._discard()
    with pytest.raises(RuntimeError, match="stopped"):
        await future
    await manager._discard()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_write", [True, False])
async def test_external_rpc_write_errors_preserve_or_discard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel_write: bool
):
    manager = ExternalBrowserSessionManager(tmp_path)

    class FakeStdin:
        def write(self, data):
            if not cancel_write:
                raise BrokenPipeError("broken pipe")

        async def drain(self):
            if cancel_write:
                raise asyncio.CancelledError()

    process = FakeProcess()
    process.stdin = FakeStdin()
    monkeypatch.setattr(manager, "_spawn", AsyncMock(return_value=process))
    discard = AsyncMock()
    monkeypatch.setattr(manager, "_discard", discard)
    if cancel_write:
        with pytest.raises(asyncio.CancelledError):
            await manager._request("snapshot", "session")
        discard.assert_not_awaited()
    else:
        with pytest.raises(BrokenPipeError, match="broken pipe"):
            await manager._request("snapshot", "session")
        discard.assert_awaited_once()
    assert not manager._pending


@pytest.mark.asyncio
async def test_external_spawn_reuses_stale_reader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    get_settings.cache_clear()
    manager = ExternalBrowserSessionManager(tmp_path)
    manager._process = FakeProcess(returncode=1)
    reader = asyncio.create_task(asyncio.sleep(0))
    await reader
    manager._reader_task = reader
    fresh = FakeProcess(returncode=1)
    monkeypatch.setattr(
        browser_external_client.asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=fresh),
    )
    try:
        assert await manager._spawn() is fresh
        await manager._discard()
    finally:
        get_settings.cache_clear()


def test_external_frozen_sidecar_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(browser_external_client.sys, "frozen", True, raising=False)
    monkeypatch.setattr(browser_external_client.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert ExternalBrowserSessionManager._service_path() == (
        tmp_path / "local_shell_mcp" / "browser_external" / "browser_external_service.py"
    )
