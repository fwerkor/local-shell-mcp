from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace

import pytest

from local_shell_mcp import remote_terminal_worker as worker


def test_relay_url_and_invalid_url():
    assert (
        worker._bridge_url("https://controller.test:443", "key")
        == "wss://controller.test:443/remote/terminal/ws?ticket=key"
    )
    assert (
        worker._bridge_url("http://localhost:1000", "key")
        == "ws://localhost:1000/remote/terminal/ws?ticket=key"
    )
    assert (
        worker._bridge_url("https://controller.test/mcp", "key")
        == "wss://controller.test/mcp/remote/terminal/ws?ticket=key"
    )
    with pytest.raises(ValueError):
        worker._bridge_url("file:///etc/passwd", "key")


@pytest.mark.skipif(os.name != "posix", reason="POSIX PTY only")
@pytest.mark.asyncio
async def test_worker_rejects_non_tmux_sessions_and_invalid_input(monkeypatch):
    monkeypatch.setattr(
        worker,
        "list_shells",
        lambda: asyncio.sleep(
            0, result={"sessions": [{"session_id": "native", "backend": "native"}]}
        ),
    )
    ticket = "x" * 40
    with pytest.raises(ValueError, match="tmux"):
        await worker.start_remote_terminal_stream("native", 90, 30, ticket, "https://test", "token")
    with pytest.raises(ValueError, match="dimensions"):
        await worker.start_remote_terminal_stream("native", 0, 30, ticket, "https://test", "token")
    with pytest.raises(ValueError, match="credentials"):
        await worker.start_remote_terminal_stream("native", 90, 30, "bad", "https://test", "token")


@pytest.mark.asyncio
async def test_worker_stream_forwards_raw_bytes_resizes_and_closes(monkeypatch):
    events = []

    class Attachment:
        def __init__(self, session, cols, rows):
            events.append(("open", session, cols, rows))

        async def read(self):
            await asyncio.sleep(0.05)
            return b"\x1b[32mOK\x1b[0m"

        async def write(self, data):
            events.append(("input", data))

        def resize(self, cols, rows):
            events.append(("resize", cols, rows))

        async def close(self):
            events.append(("close",))

    class Socket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def send(self, data):
            events.append(("output", data))

        async def __aiter__(self):
            yield b"ls\r"
            yield json.dumps({"type": "resize", "cols": 110, "rows": 40})
            yield json.dumps({"type": "resize", "cols": -10, "rows": 5})
            await asyncio.sleep(0.1)

    from local_shell_mcp import remote_terminal_ws_client

    monkeypatch.setattr(worker, "_TmuxPtyAttachment", Attachment)
    monkeypatch.setattr(remote_terminal_ws_client, "TerminalWebSocket", lambda *_args: Socket())
    future = asyncio.get_running_loop().create_future()
    await worker._run_attachment("demo", 80, 24, "ws://test", "secret", future)
    await future
    assert ("open", "demo", 80, 24) in events
    assert ("input", b"ls\r") in events
    assert ("resize", 110, 40) in events
    assert ("output", b"\x1b[32mOK\x1b[0m") in events
    assert events[-1] == ("close",)


@pytest.mark.skipif(os.name != "posix", reason="POSIX PTY only")
@pytest.mark.asyncio
async def test_worker_validates_session_before_start(monkeypatch):
    monkeypatch.setattr(
        worker,
        "list_shells",
        lambda: asyncio.sleep(
            0, result={"sessions": [{"session_id": "demo", "backend": "tmux-system"}]}
        ),
    )

    async def started(*args):
        _ = args
        return None

    monkeypatch.setattr(worker, "_run_attachment", lambda *_args: started(*_args))

    # A background task without a handshake must time out; use a short mocked wait.
    async def short_wait(future, timeout):
        raise TimeoutError("worker never connected")

    monkeypatch.setattr(worker.asyncio, "wait_for", short_wait)
    with pytest.raises(TimeoutError):
        await worker.start_remote_terminal_stream("demo", 80, 24, "x" * 40, "https://test", "token")


@pytest.mark.asyncio
async def test_real_tmux_attached_pty_preserves_ansi_and_detach(monkeypatch):
    import shutil
    import subprocess
    import uuid

    if os.name != "posix" or not shutil.which("tmux"):
        pytest.skip("tmux POSIX backend unavailable")
    socket_name = "lsm-ws-test-" + uuid.uuid4().hex[:12]
    session_name = "lsm-ws-test-" + uuid.uuid4().hex[:12]
    tmux = shutil.which("tmux")

    def command(*args):
        return subprocess.run([tmux, "-L", socket_name, *args], capture_output=True, text=True)

    started = command(
        "new-session",
        "-d",
        "-s",
        session_name,
        "-x",
        "80",
        "-y",
        "24",
        "bash --noprofile --norc -i",
    )
    if started.returncode:
        pytest.skip("tmux cannot create isolated test server")
    monkeypatch.setattr(worker, "tmux_socket_name", lambda: socket_name)
    monkeypatch.setattr(worker, "resolve_tmux", lambda: SimpleNamespace(path=tmux))
    # This PTY test does not require a configured LSM workspace directory.
    # CI runners cannot create the default /workspace path.
    monkeypatch.setattr(worker, "subprocess_env", lambda: os.environ.copy())
    attachment = None
    try:
        attachment = worker._TmuxPtyAttachment(session_name, 80, 24)
        await asyncio.sleep(0.1)
        await attachment.write(b"printf '\\033[31mREAL-PTY\\033[0m\\n'\r")
        output = bytearray()
        for _ in range(25):
            output.extend(await asyncio.wait_for(attachment.read(), 2))
            if b"\x1b[31mREAL-PTY" in output:
                break
        assert b"\x1b[31mREAL-PTY" in output
        attachment.resize(101, 38)
        await asyncio.sleep(0.15)
        assert "101x38" in command("list-clients", "-F", "#{client_width}x#{client_height}").stdout
        await attachment.close()
        attachment = None
        assert session_name in command("list-sessions", "-F", "#{session_name}").stdout
    finally:
        if attachment is not None:
            await attachment.close()
        command("kill-server")


@pytest.mark.skipif(os.name != "posix", reason="POSIX PTY only")
@pytest.mark.asyncio
async def test_worker_start_returns_success_and_shutdown_does_not_leak(monkeypatch):
    from local_shell_mcp import remote_terminal_ws_client

    closed = asyncio.Event()
    finish = asyncio.Event()

    class FakeAttachment:
        def __init__(self, *args):
            assert args == ("demo", 90, 30)

        async def read(self):
            await asyncio.Event().wait()

        async def write(self, _data):
            pass

        async def close(self):
            closed.set()

    class FakeSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def __aiter__(self):
            await finish.wait()
            if False:
                yield b""

        async def send(self, _data):
            pass

    async def sessions():
        return {"sessions": [{"session_id": "demo", "backend": "tmux-system"}]}

    monkeypatch.setattr(worker, "list_shells", sessions)
    monkeypatch.setattr(worker, "_TmuxPtyAttachment", FakeAttachment)
    monkeypatch.setattr(remote_terminal_ws_client, "TerminalWebSocket", lambda *_args: FakeSocket())
    result = await worker.start_remote_terminal_stream(
        "demo", 90, 30, "x" * 40, "http://127.0.0.1", "secret"
    )
    assert result == {"status": "attached"}
    finish.set()
    await asyncio.wait_for(closed.wait(), 2)
    await asyncio.sleep(0)
    assert not worker._ACTIVE_ATTACHMENTS


@pytest.mark.skipif(os.name != "posix", reason="POSIX PTY only")
@pytest.mark.asyncio
async def test_worker_rejects_unavailable_tmux_and_failing_attachment(monkeypatch):

    monkeypatch.setattr(worker, "resolve_tmux", lambda: SimpleNamespace(path=None))
    with pytest.raises(RuntimeError, match="tmux is unavailable"):
        worker._TmuxPtyAttachment("demo", 80, 24)

    async def list_sessions():
        return {"sessions": [{"session_id": "demo", "backend": "tmux-system"}]}

    def cannot_attach(*_args):
        raise OSError("tmux attach failed")

    monkeypatch.setattr(worker, "list_shells", list_sessions)
    monkeypatch.setattr(worker, "_TmuxPtyAttachment", cannot_attach)
    with pytest.raises(OSError, match="tmux attach failed"):
        await worker.start_remote_terminal_stream(
            "demo", 90, 30, "x" * 40, "https://controller", "token"
        )
    await asyncio.sleep(0)
    assert not worker._ACTIVE_ATTACHMENTS


@pytest.mark.asyncio
async def test_native_pty_read_and_write_errors():
    attachment = object.__new__(worker._TmuxPtyAttachment)
    attachment.fd = -1
    assert await attachment.read() == b""
    with pytest.raises(OSError):
        await attachment.write(b"keyboard")


@pytest.mark.skipif(os.name != "posix", reason="POSIX PTY only")
@pytest.mark.asyncio
async def test_native_pty_process_creation_error_closes_descriptors(monkeypatch):
    import subprocess

    def cannot_start(*_args, **_kwargs):
        raise OSError("tmux startup rejected")

    monkeypatch.setattr(worker, "resolve_tmux", lambda: SimpleNamespace(path="/usr/bin/tmux"))
    monkeypatch.setattr(worker, "tmux_socket_name", lambda: "isolated-test")
    monkeypatch.setattr(worker, "subprocess_env", lambda: os.environ.copy())
    monkeypatch.setattr(subprocess, "Popen", cannot_start)
    with pytest.raises(OSError, match="tmux startup rejected"):
        worker._TmuxPtyAttachment("broken", 80, 24)


@pytest.mark.asyncio
async def test_pty_write_rejects_stalled_fd(monkeypatch):
    attachment = object.__new__(worker._TmuxPtyAttachment)
    attachment.fd = 42
    monkeypatch.setattr(worker.os, "write", lambda *_args: 0)
    with pytest.raises(OSError, match="PTY write stopped"):
        await attachment.write(b"x")


@pytest.mark.skipif(os.name != "posix", reason="POSIX PTY only")
@pytest.mark.asyncio
async def test_pty_close_force_kills_unresponsive_attach(monkeypatch):
    attachment = object.__new__(worker._TmuxPtyAttachment)
    attachment.fd = 42
    attachment.process = SimpleNamespace(pid=1234, poll=lambda: None, wait=lambda: None)
    signals = []
    monkeypatch.setattr(worker.os, "close", lambda fd: signals.append(("fd", fd)))
    monkeypatch.setattr(worker.os, "killpg", lambda pid, sig: signals.append((pid, sig)))

    async def timeout(*_args, **_kwargs):
        raise TimeoutError

    monkeypatch.setattr(worker.asyncio, "wait_for", timeout)
    await attachment.close()
    assert ("fd", 42) in signals
    assert (1234, worker.signal.SIGTERM) in signals
    assert (1234, worker.signal.SIGKILL) in signals
