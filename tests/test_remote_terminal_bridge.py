from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from local_shell_mcp import remote_terminal_stream as stream
from local_shell_mcp import remote_terminal_worker as worker


@pytest.mark.asyncio
async def test_controller_broker_rejects_unauthorized_and_consumes_ticket_once(monkeypatch):
    pending = stream._PendingTerminal("valid", asyncio.get_running_loop().create_future())
    stream._PENDING["test-ticket"] = pending
    monkeypatch.setattr(
        stream,
        "remote_manager",
        lambda: SimpleNamespace(
            _worker_by_token=lambda token: (
                SimpleNamespace(name="worker-a", token="valid")
                if token == "valid"
                else SimpleNamespace(name="worker-b", token="invalid")
            )
        ),
    )

    class Socket:
        def __init__(self, token):
            self.query_params = {"ticket": "test-ticket"}
            self.headers = {"authorization": "Bearer " + token}
            self.closed = []
            self.accepted = False

        async def accept(self):
            self.accepted = True

        async def close(self, code=1000):
            self.closed.append(code)

    try:
        denied = Socket("invalid")
        await stream.remote_terminal_websocket(denied)
        assert denied.closed == [4403]
        assert not pending.future.done()
        accepted = Socket("valid")
        task = asyncio.create_task(stream.remote_terminal_websocket(accepted))
        assert await asyncio.wait_for(pending.future, 1) is accepted
        assert accepted.accepted
        duplicate = Socket("valid")
        await stream.remote_terminal_websocket(duplicate)
        assert duplicate.closed == [4403]
        pending.released.set()
        await asyncio.wait_for(task, 1)
        assert accepted.closed == [1000]
    finally:
        stream._PENDING.clear()


@pytest.mark.asyncio
async def test_controller_open_stream_transfers_binary_keyboard_and_resize(monkeypatch):
    class Socket:
        def __init__(self):
            self.out = []
            self.queue = asyncio.Queue()

        async def send_bytes(self, data):
            self.out.append(data)

        async def send_text(self, data):
            self.out.append(json.loads(data))

        async def receive(self):
            return await self.queue.get()

    socket = Socket()

    async def remote_call(machine, tool, args, **_kwargs):
        assert machine == "worker-a" and tool == "ui_terminal_stream_start"
        assert args["session_id"] == "known"
        await socket.queue.put({"type": "websocket.receive", "bytes": b"\x1b[31mred\x1b[0m"})
        stream._PENDING[args["ticket"]].future.set_result(socket)
        return {"ok": True}

    monkeypatch.setattr(
        stream,
        "remote_manager",
        lambda: SimpleNamespace(call=remote_call, _worker_token=lambda _machine: "valid"),
    )
    process = await stream.open_remote_terminal("worker-a", "known", 90, 30)
    assert await process.read() == b"\x1b[31mred\x1b[0m"
    await process.write(b"pwd\r")
    await process.resize(120, 40)
    assert socket.out == [b"pwd\r", {"type": "resize", "cols": 120, "rows": 40}]
    await socket.queue.put({"type": "websocket.disconnect"})
    assert await process.read() == b""
    assert await process.exit_code() == 1
    await process.close()
    assert process.pending.released.is_set()
    assert not stream._PENDING


@pytest.mark.asyncio
async def test_controller_cleans_ticket_when_worker_fails(monkeypatch):
    async def fail(*_args, **_kwargs):
        return {"ok": False, "message": "unsupported worker tool"}

    monkeypatch.setattr(
        stream,
        "remote_manager",
        lambda: SimpleNamespace(call=fail, _worker_token=lambda _machine: "valid"),
    )
    with pytest.raises(RuntimeError, match="unsupported worker tool"):
        await stream.open_remote_terminal("worker-a", "known", 90, 30)
    assert not stream._PENDING


@pytest.mark.asyncio
async def test_native_terminal_remote_stream_and_snapshot_fallback(monkeypatch):
    from local_shell_mcp import human_ui

    async def dispatch(machine, local_call, tool, args):
        assert machine == "worker-a" and tool == "shell_list"
        return {"sessions": [{"session_id": "demo", "backend": "tmux-system"}]}

    async def good(*args):
        assert args == ("worker-a", "demo", 80, 24)
        return "real-pty"

    async def bad(*args):
        raise RuntimeError("old worker")

    monkeypatch.setattr(human_ui, "_machine_dispatch", dispatch)
    monkeypatch.setattr(human_ui, "_machine_uses_windows_paths", lambda machine: False)
    monkeypatch.setattr(stream, "open_remote_terminal", good)
    assert await human_ui._spawn_shell_process("worker-a", "demo", 80, 24) == "real-pty"
    monkeypatch.setattr(stream, "open_remote_terminal", bad)
    fallback = await human_ui._spawn_shell_process("worker-a", "demo", 80, 24)
    assert isinstance(fallback, human_ui._PollingShellProcess)
    assert fallback.machine == "worker-a"


@pytest.mark.asyncio
async def test_worker_dispatch_only_uses_controller_assigned_relay(monkeypatch):
    from local_shell_mcp import remote

    async def launch(*args):
        return {"received": args}

    monkeypatch.setattr(worker, "start_remote_terminal_stream", launch)
    monkeypatch.setattr(remote, "_WORKER_TERMINAL_SERVER", "https://controller")
    monkeypatch.setattr(remote, "_WORKER_TERMINAL_TOKEN", "worker-secret")
    result = await remote._execute_shell_worker_tool(
        "ui_terminal_stream_start",
        {"session_id": "demo", "cols": 90, "rows": 30, "ticket": "one-time-ticket"},
    )
    assert result == {
        "received": ("demo", 90, 30, "one-time-ticket", "https://controller", "worker-secret")
    }


@pytest.mark.asyncio
async def test_controller_broker_rejects_unknown_ticket_and_accept_error(monkeypatch):
    monkeypatch.setattr(
        stream,
        "remote_manager",
        lambda: SimpleNamespace(
            _worker_by_token=lambda _token: SimpleNamespace(name="worker-a", token="valid")
        ),
    )

    class Socket:
        query_params = {"ticket": "does-not-exist"}
        headers = {"authorization": "Bearer valid"}
        closed = []

        async def close(self, code=1000):
            self.closed.append(code)

        async def accept(self):
            raise RuntimeError("cannot upgrade")

    socket = Socket()
    await stream.remote_terminal_websocket(socket)
    assert socket.closed == [4403]
    pending = stream._PendingTerminal("valid", asyncio.get_running_loop().create_future())
    stream._PENDING["ticket"] = pending
    socket.query_params = {"ticket": "ticket"}
    await stream.remote_terminal_websocket(socket)
    assert pending.released.is_set()
    with pytest.raises(RuntimeError, match="cannot upgrade"):
        await pending.future
    assert "ticket" not in stream._PENDING


@pytest.mark.asyncio
async def test_remote_process_closed_and_unexpected_disconnect():
    from starlette.websockets import WebSocketDisconnect

    class Socket:
        async def receive(self):
            raise WebSocketDisconnect(code=1006)

        async def send_bytes(self, _data):
            raise AssertionError("closed socket wrote bytes")

        async def send_text(self, _data):
            raise AssertionError("closed socket wrote resize")

    pending = stream._PendingTerminal("worker", asyncio.get_running_loop().create_future())
    process = stream.RemoteTerminalProcess(Socket(), pending)
    assert await process.exit_code() is None
    assert await process.read() == b""
    assert await process.exit_code() == 1
    await process.write(b"ignored")
    await process.resize(90, 25)
    await process.close()
    assert pending.released.is_set()


@pytest.mark.asyncio
async def test_remote_broker_invalid_worker_token_keeps_ticket(monkeypatch):
    def unauthorized(_token):
        raise PermissionError("token rejected")

    monkeypatch.setattr(
        stream, "remote_manager", lambda: SimpleNamespace(_worker_by_token=unauthorized)
    )
    pending = stream._PendingTerminal("valid", asyncio.get_running_loop().create_future())
    stream._PENDING["ticket"] = pending

    class Socket:
        query_params = {"ticket": "ticket"}
        headers = {"authorization": "Bearer invalid"}
        closed = []

        async def close(self, code=1000):
            self.closed.append(code)

    try:
        socket = Socket()
        await stream.remote_terminal_websocket(socket)
        assert socket.closed == [4403]
        assert "ticket" in stream._PENDING
    finally:
        stream._PENDING.clear()


@pytest.mark.asyncio
async def test_pending_relay_survives_worker_rename_and_revocation_closes_active_stream(
    monkeypatch,
):
    active = True
    renamed = False
    accepted = asyncio.Event()

    def by_token(token):
        if not active or token != "stable-token":
            raise PermissionError("revoked")
        return SimpleNamespace(token=token, name="renamed" if renamed else "original")

    monkeypatch.setattr(
        stream, "remote_manager", lambda: SimpleNamespace(_worker_by_token=by_token)
    )
    pending = stream._PendingTerminal("stable-token", asyncio.get_running_loop().create_future())
    stream._PENDING["rename-ticket"] = pending

    class Socket:
        query_params = {"ticket": "rename-ticket"}
        headers = {"authorization": "Bearer stable-token"}

        def __init__(self):
            self.closed = []

        async def accept(self):
            accepted.set()

        async def close(self, code=1000):
            self.closed.append(code)

    socket = Socket()
    task = None
    try:
        renamed = True
        task = asyncio.create_task(stream.remote_terminal_websocket(socket))
        await asyncio.wait_for(accepted.wait(), 1)
        assert await pending.future is socket
        active = False
        await asyncio.wait_for(task, 2)
        assert pending.released.is_set()
        assert socket.closed == [1000]
    finally:
        pending.released.set()
        if task is not None:
            await task
        stream._PENDING.clear()


@pytest.mark.asyncio
async def test_worker_token_lookup_stays_stable_after_rename(tmp_path, monkeypatch):
    from local_shell_mcp import remote
    from local_shell_mcp.settings import get_settings

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    get_settings.cache_clear()
    manager = remote.RemoteManager()
    manager._registry_loaded = True
    remote_worker = remote.RemoteWorker(name="original", token="stable-token")
    manager.workers = {"original": remote_worker}
    manager.tokens = {"stable-token": "original"}
    try:
        assert manager._worker_token("original") == "stable-token"
        manager.rename("original", "renamed")
        assert manager._worker_token("renamed") == "stable-token"
        assert manager._worker_by_token("stable-token") is remote_worker
        manager.revoke("renamed")
        with pytest.raises(PermissionError):
            manager._worker_by_token("stable-token")
    finally:
        get_settings.cache_clear()
