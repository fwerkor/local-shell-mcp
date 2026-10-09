from __future__ import annotations

import asyncio
import os
import sys

import pytest

from local_shell_mcp.human_ui import UI_LOCAL_TOKEN_FD_ENV, _UnixPtyProcess


@pytest.mark.skipif(os.name == "nt", reason="Unix PTYs require POSIX")
@pytest.mark.asyncio
@pytest.mark.parametrize("token", [None, "private-ui-token"])
async def test_unix_pty_lifecycle_with_optional_private_token(token: str | None) -> None:
    program = (
        "import os, sys; "
        f"fd = os.getenv({UI_LOCAL_TOKEN_FD_ENV!r}); "
        "token = os.read(int(fd), 100).decode() if fd else 'none'; "
        "print('token=' + token, flush=True); "
        "line = sys.stdin.readline(); "
        "print('reply=' + line.strip(), flush=True)"
    )
    process = _UnixPtyProcess(
        [sys.executable, "-u", "-c", program], os.environ.copy(), 80, 24, ui_token=token
    )

    async def read_until(expected: bytes) -> bytes:
        output = bytearray()
        for _ in range(100):
            output.extend(await asyncio.wait_for(process.read(), timeout=1))
            if expected in output:
                return bytes(output)
        raise AssertionError(f"Expected {expected!r} in PTY output: {output!r}")

    try:
        assert f"token={token or 'none'}".encode() in await read_until(
            f"token={token or 'none'}".encode()
        )
        process.resize(100, 40)
        await process.write(b"hello-pty\n")
        assert b"reply=hello-pty" in await read_until(b"reply=hello-pty")
        for _ in range(10):
            exit_code = await asyncio.wait_for(process.exit_code(), timeout=1)
            if exit_code is not None:
                break
        assert exit_code == 0
    finally:
        await process.close()


@pytest.mark.skipif(os.name == "nt", reason="Unix PTYs require POSIX")
@pytest.mark.asyncio
async def test_unix_pty_close_terminates_live_process() -> None:
    process = _UnixPtyProcess(
        [sys.executable, "-u", "-c", "import time; time.sleep(30)"],
        os.environ.copy(),
        80,
        24,
    )
    try:
        assert await process.exit_code() is None
    finally:
        await process.close()
    assert process.process.poll() is not None


@pytest.mark.skipif(os.name == "nt", reason="Unix PTYs require POSIX")
@pytest.mark.asyncio
async def test_unix_pty_read_closed_master_and_reject_zero_length_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _UnixPtyProcess.__new__(_UnixPtyProcess)
    process.master_fd = -1
    assert await process.read() == b""

    monkeypatch.setattr("local_shell_mcp.human_ui.os.write", lambda fd, data: 0)
    with pytest.raises(OSError, match="no progress"):
        await process.write(b"input")
