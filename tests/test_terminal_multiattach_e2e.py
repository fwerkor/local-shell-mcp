"""Real tmux PTYs: concurrent viewers, switching and reconnecting."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import uuid

import pytest

from local_shell_mcp import remote_terminal_worker as worker


@pytest.mark.skipif(os.name != "posix", reason="tmux PTYs require POSIX")
@pytest.mark.asyncio
async def test_two_terminal_clients_switch_and_reattach_without_killing_sessions(monkeypatch):
    tmux = shutil.which("tmux")
    if tmux is None:
        pytest.skip("tmux is not installed")
    socket = "lsm-concurrent-" + uuid.uuid4().hex[:12]
    first = "e2e-first-" + uuid.uuid4().hex[:10]
    second = "e2e-second-" + uuid.uuid4().hex[:10]

    def tmux_run(*args):
        return subprocess.run(
            [tmux, "-L", socket, *args],
            capture_output=True,
            text=True,
            timeout=5,
        )

    monkeypatch.setattr(worker, "tmux_socket_name", lambda: socket)
    monkeypatch.setattr(worker, "resolve_tmux", lambda: type("Selection", (), {"path": tmux})())
    monkeypatch.setattr(worker, "subprocess_env", lambda: os.environ.copy())
    attachments = []

    async def contains(handle, marker):
        output = bytearray()
        async with asyncio.timeout(8):
            while marker not in output:
                data = await handle.read()
                assert data, "terminal disconnected before marker arrived"
                output.extend(data)
        return bytes(output)

    a = b = switched = reconnect = None
    try:
        if tmux_run("new-session", "-d", "-s", first, "-x", "90", "-y", "30").returncode:
            pytest.skip("isolated tmux server could not start")
        assert tmux_run("new-session", "-d", "-s", second, "-x", "90", "-y", "30").returncode == 0
        a = worker._TmuxPtyAttachment(first, 90, 30)
        b = worker._TmuxPtyAttachment(first, 90, 30)
        attachments.extend((a, b))
        async with asyncio.timeout(6):
            while (
                tmux_run("list-clients", "-F", "#{session_name}").stdout.splitlines().count(first)
                < 2
            ):
                assert a.process.poll() is None and b.process.poll() is None
                await asyncio.sleep(0.05)

        # Output from one live PTY must remain observable by another attached client.
        marker = b"TWO-VIEWERS-" + uuid.uuid4().hex[:8].encode()
        await a.write(b"printf '" + marker + b"\\n'\r")
        await asyncio.gather(contains(a, marker), contains(b, marker))

        # Simulate a client switching sessions while another viewer stays attached.
        await a.close()
        attachments.remove(a)
        a = None
        switched = worker._TmuxPtyAttachment(second, 90, 30)
        attachments.append(switched)
        second_marker = b"SWITCHED-" + uuid.uuid4().hex[:8].encode()
        await switched.write(b"printf '" + second_marker + b"\\n'\r")
        await contains(switched, second_marker)
        assert tmux_run("list-sessions", "-F", "#{session_name}").stdout.splitlines() == [
            first,
            second,
        ]
        assert b.process.poll() is None

        # Closing the remaining viewer does not kill its shell; a fresh PTY can
        # reconnect to the existing session without losing its state.
        await b.close()
        attachments.remove(b)
        b = None
        reconnect = worker._TmuxPtyAttachment(first, 90, 30)
        attachments.append(reconnect)
        marker = b"REATTACHED-" + uuid.uuid4().hex[:8].encode()
        await reconnect.write(b"printf '" + marker + b"\\n'\r")
        await contains(reconnect, marker)
        assert tmux_run("list-sessions", "-F", "#{session_name}").stdout.splitlines() == [
            first,
            second,
        ]
    finally:
        for attachment in attachments:
            await attachment.close()
        tmux_run("kill-server")


@pytest.mark.skipif(os.name != "posix", reason="tmux PTYs require POSIX")
@pytest.mark.asyncio
async def test_native_websocket_two_clients_switch_and_reconnect(tmp_path, monkeypatch):
    """Exercise real HTTP upgrade, WebSocket relay, local PTY and tmux together."""
    import socket

    import uvicorn
    from websockets.legacy.client import connect

    from local_shell_mcp.http_app import build_http_app
    from local_shell_mcp.settings import get_settings
    from local_shell_mcp.shell_ops import kill_shell, list_shells, start_shell

    if shutil.which("tmux") is None:
        pytest.skip("system tmux is not installed")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()
    sessions = []
    server_task = None
    server = None
    listener = None
    try:
        for name in ("ws-first", "ws-second"):
            result = await start_shell(cwd=".", name=name)
            assert str(result["backend"]).startswith("tmux-")
            sessions.append(result["session_id"])

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                build_http_app(),
                host="127.0.0.1",
                port=port,
                log_level="error",
                access_log=False,
                lifespan="off",
            )
        )
        server_task = asyncio.create_task(server.serve(sockets=[listener]))
        async with asyncio.timeout(8):
            while not server.started:
                assert not server_task.done(), "HTTP server terminated during startup"
                await asyncio.sleep(0.05)

        def terminal_url(session):
            return (
                f"ws://127.0.0.1:{port}/ui/ws/shell?machine=local"
                f"&session_id={session}&cols=90&rows=30"
            )

        async def expect_marker(websocket, marker):
            output = bytearray()
            async with asyncio.timeout(8):
                while marker not in output:
                    packet = await websocket.recv()
                    if isinstance(packet, bytes):
                        output.extend(packet)
            return bytes(output)

        async def expect_pty_ready(websocket):
            # Binary terminal output proves that the PTY was attached and its
            # server-side relay has started, not just the WebSocket handshake.
            async with asyncio.timeout(8):
                while True:
                    packet = await websocket.recv()
                    if isinstance(packet, bytes) and packet:
                        assert b"Unable to attach terminal:" not in packet
                        return

        async with connect(terminal_url(sessions[0]), subprotocols=["lsm-ui"]) as first:
            async with connect(terminal_url(sessions[0]), subprotocols=["lsm-ui"]) as second:
                await asyncio.gather(expect_pty_ready(first), expect_pty_ready(second))
                marker = b"WEB-MULTICLIENT-" + uuid.uuid4().hex[:8].encode()
                await first.send(b"printf '" + marker + b"\\n'\r")
                await asyncio.gather(expect_marker(first, marker), expect_marker(second, marker))

                # The first viewer switches to a different shell while the
                # second viewer remains attached to the original session.
                await first.close()
                async with connect(terminal_url(sessions[1]), subprotocols=["lsm-ui"]) as switched:
                    marker = b"WEB-SWITCH-" + uuid.uuid4().hex[:8].encode()
                    await switched.send(b"printf '" + marker + b"\\n'\r")
                    await expect_marker(switched, marker)
                    original = b"ORIGINAL-STILL-OPEN-" + uuid.uuid4().hex[:8].encode()
                    await second.send(b"printf '" + original + b"\\n'\r")
                    await expect_marker(second, original)

            # The browser can reconnect to an existing persistent shell even
            # after its last viewer leaves; no shell ownership is transferred.
            async with connect(terminal_url(sessions[0]), subprotocols=["lsm-ui"]) as reattached:
                marker = b"WEB-RECONNECTED-" + uuid.uuid4().hex[:8].encode()
                await reattached.send(b"printf '" + marker + b"\\n'\r")
                await expect_marker(reattached, marker)
            active = {row["session_id"] for row in (await list_shells())["sessions"]}
            assert set(sessions) <= active
    finally:
        if server is not None:
            server.should_exit = True
        try:
            if server_task is not None:
                await asyncio.wait_for(server_task, timeout=10)
        finally:
            if server_task is not None and not server_task.done():
                server_task.cancel()
            if listener is not None:
                listener.close()
            try:
                results = await asyncio.gather(
                    *(kill_shell(session_id) for session_id in sessions),
                    return_exceptions=True,
                )
                for result in results:
                    if isinstance(result, BaseException):
                        raise result
            finally:
                get_settings.cache_clear()


@pytest.mark.skipif(os.name != "posix", reason="tmux PTYs require POSIX")
@pytest.mark.asyncio
async def test_failed_second_tmux_session_does_not_leak_first(monkeypatch):
    tmux = shutil.which("tmux")
    if tmux is None:
        pytest.skip("tmux is not installed")

    actual_run = subprocess.run
    socket_name = None

    def fail_second_session(command, *args, **kwargs):
        nonlocal socket_name
        if "new-session" in command and any(arg.startswith("e2e-second-") for arg in command):
            socket_name = command[2]
            return subprocess.CompletedProcess(command, returncode=1, stdout="", stderr="injected")
        return actual_run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fail_second_session)
    with pytest.raises(AssertionError):
        await test_two_terminal_clients_switch_and_reattach_without_killing_sessions(monkeypatch)
    assert socket_name is not None, "the second session failure was not injected"
    assert (
        actual_run(
            [tmux, "-L", socket_name, "list-sessions"],
            capture_output=True,
            text=True,
            timeout=5,
        ).returncode
        != 0
    ), "the first session survived failed setup"


@pytest.mark.skipif(os.name != "posix", reason="tmux PTYs require POSIX")
@pytest.mark.asyncio
async def test_native_websocket_server_failure_cleans_up_shells(tmp_path, monkeypatch):
    """A failed server task must not skip PTY cleanup or leave stale settings."""
    import uvicorn

    from local_shell_mcp.settings import get_settings
    from local_shell_mcp.shell_ops import list_shells

    if shutil.which("tmux") is None:
        pytest.skip("system tmux is not installed")
    original_serve = uvicorn.Server.serve

    async def fail_after_shutdown(server, *args, **kwargs):
        await original_serve(server, *args, **kwargs)
        raise RuntimeError("injected HTTP shutdown failure")

    monkeypatch.setattr(uvicorn.Server, "serve", fail_after_shutdown)
    with pytest.raises(RuntimeError, match="injected HTTP shutdown failure"):
        await test_native_websocket_two_clients_switch_and_reconnect(tmp_path, monkeypatch)

    assert get_settings.cache_info().currsize == 0
    assert (await list_shells())["sessions"] == []
