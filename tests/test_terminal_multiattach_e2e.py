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
            [tmux, "-L", socket, *args], capture_output=True, text=True, timeout=5,
        )

    if tmux_run("new-session", "-d", "-s", first, "-x", "90", "-y", "30").returncode:
        pytest.skip("isolated tmux server could not start")
    assert tmux_run("new-session", "-d", "-s", second, "-x", "90", "-y", "30").returncode == 0
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
        a = worker._TmuxPtyAttachment(first, 90, 30)
        b = worker._TmuxPtyAttachment(first, 90, 30)
        attachments.extend((a, b))
        async with asyncio.timeout(6):
            while tmux_run("list-clients", "-F", "#{session_name}").stdout.splitlines().count(first) < 2:
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
        assert tmux_run("list-sessions", "-F", "#{session_name}").stdout.splitlines() == [first, second]
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
        assert tmux_run("list-sessions", "-F", "#{session_name}").stdout.splitlines() == [first, second]
    finally:
        for attachment in attachments:
            await attachment.close()
        tmux_run("kill-server")
