from __future__ import annotations

import asyncio
import base64
import hashlib

import pytest

from local_shell_mcp.remote_terminal_ws_client import TerminalWebSocket


@pytest.mark.asyncio
async def test_dependency_free_websocket_handshake_masked_io_and_ping():
    messages = []

    async def handle(reader, writer):
        request = await reader.readuntil(b"\r\n\r\n")
        assert b"Authorization: Bearer secret\r\n" in request
        key = next(
            line.split(b": ", 1)[1]
            for line in request.split(b"\r\n")
            if line.startswith(b"Sec-WebSocket-Key:")
        )
        accept = base64.b64encode(
            hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest()
        )
        writer.write(
            b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: "
            + accept
            + b"\r\n\r\n"
        )
        writer.write(b"\x89\x02hi")
        writer.write(b"\x82\x08\x1b[34mhi\x1b")
        writer.write(b"\x82\x04[0m!")
        await writer.drain()
        for _ in range(2):
            first, second = await reader.readexactly(2)
            assert second & 128
            count = second & 0x7F
            if count == 126:
                count = int.from_bytes(await reader.readexactly(2), "big")
            mask = await reader.readexactly(4)
            payload = await reader.readexactly(count)
            data = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
            messages.append((first & 15, data))
        writer.write(b"\x88\x00")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        async with TerminalWebSocket(
            f"ws://127.0.0.1:{port}/remote/terminal/ws?ticket=ok", "secret"
        ) as ws:
            assert await ws.receive() == b"\x1b[34mhi\x1b"
            assert await ws.receive() == b"[0m!"
            await ws.send(b"pwd\r")
            assert await ws.receive() is None
        assert messages == [(10, b"hi"), (2, b"pwd\r")]
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_worker_websocket_frame_length_variants_and_fragmentation():
    messages = []
    received = asyncio.Event()

    async def handle(reader, writer):
        request = await reader.readuntil(b"\r\n\r\n")
        key = next(
            line.split(b": ", 1)[1]
            for line in request.split(b"\r\n")
            if line.startswith(b"Sec-WebSocket-Key:")
        )
        accept = base64.b64encode(
            hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest()
        )
        writer.write(
            b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: keep-alive, Upgrade\r\nSec-WebSocket-Accept: "
            + accept
            + b"\r\n\r\n"
        )
        writer.write(b"\x01\x03one\x80\x03two")
        writer.write(b"\x82\x7e" + (180).to_bytes(2, "big") + b"y" * 180)
        writer.write(b"\x82\x7f" + (70000).to_bytes(8, "big") + b"z" * 70000)
        await writer.drain()
        for _ in range(3):
            first, second = await reader.readexactly(2)
            length = second & 0x7F
            if length == 126:
                length = int.from_bytes(await reader.readexactly(2), "big")
            elif length == 127:
                length = int.from_bytes(await reader.readexactly(8), "big")
            mask = await reader.readexactly(4)
            raw = await reader.readexactly(length)
            messages.append((first & 0x0F, bytes(byte ^ mask[i % 4] for i, byte in enumerate(raw))))
        received.set()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        async with TerminalWebSocket(
            f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/", "secret"
        ) as websocket:
            assert await websocket.receive() == "onetwo"
            assert await websocket.receive() == b"y" * 180
            assert await websocket.receive() == b"z" * 70000
            await websocket.send("hi")
            await websocket.send(b"x" * 180)
            await websocket.send(b"z" * 70000)
            await asyncio.wait_for(received.wait(), 2)
        assert messages == [(1, b"hi"), (2, b"x" * 180), (2, b"z" * 70000)]
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_worker_websocket_rejects_bad_handshake_and_invalid_frames():
    async def refused(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(refused, "127.0.0.1", 0)
    try:
        with pytest.raises(ConnectionError, match="handshake rejected"):
            async with TerminalWebSocket(
                f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/", "secret"
            ):
                pass
    finally:
        server.close()
        await server.wait_closed()
    with pytest.raises(ValueError, match="invalid terminal websocket URL"):
        async with TerminalWebSocket("file:///not-websocket", "secret"):
            pass

    for frame, message in [
        (b"\x82\x80", "server frames must not be masked"),
        (b"\x80\x00", "unexpected terminal websocket frame"),
        (b"\x82\x7f" + (2**22).to_bytes(8, "big"), "frame too large"),
    ]:
        client = TerminalWebSocket("ws://example.invalid", "secret")
        client.reader = asyncio.StreamReader()
        client.reader.feed_data(frame)
        client.reader.feed_eof()
        with pytest.raises(ValueError, match=message):
            await client.receive()


@pytest.mark.asyncio
async def test_client_rejects_unconnected_oversized_and_invalid_sequences():
    client = TerminalWebSocket("ws://127.0.0.1", "token")
    assert client.__aiter__() is client
    with pytest.raises(ConnectionError, match="not connected"):
        await client.send(b"a")
    with pytest.raises(ConnectionError, match="not connected"):
        await client._frame()

    class Writer:
        def __init__(self):
            self.data = []

        def write(self, value):
            self.data.append(value)

        async def drain(self):
            pass

        def close(self):
            pass

        async def wait_closed(self):
            pass

    writer = Writer()
    client.writer = writer
    with pytest.raises(ValueError, match="message too large"):
        await client.send(b"x" * (1024 * 1024 + 1))
    assert not writer.data
    await client.close()
    assert client.writer is None

    client.reader = asyncio.StreamReader()
    client.reader.feed_data(b"\x8a\x00\x88\x00")
    assert await client.receive() is None
    client.reader = asyncio.StreamReader()
    client.reader.feed_data(b"\x81\x01\xff")
    with pytest.raises(UnicodeDecodeError):
        await client.receive()
    client.reader = asyncio.StreamReader()
    client.reader.feed_data(b"\x88\x00")
    with pytest.raises(StopAsyncIteration):
        await client.__anext__()


@pytest.mark.asyncio
async def test_client_enforces_fragmented_message_size():
    client = TerminalWebSocket("ws://127.0.0.1", "token")
    frames = iter([(2, False, b"x" * 800_000), (0, True, b"x" * 300_000)])

    async def next_frame():
        return next(frames)

    client._frame = next_frame
    with pytest.raises(ValueError, match="message too large"):
        await client.receive()


@pytest.mark.asyncio
async def test_ws_iterator_stops_when_socket_eof():
    websocket = TerminalWebSocket("ws://127.0.0.1", "token")
    websocket.reader = asyncio.StreamReader()
    websocket.reader.feed_eof()
    with pytest.raises(StopAsyncIteration):
        await websocket.__anext__()


@pytest.mark.asyncio
async def test_websocket_iterator_yields_raw_bytes():
    client = TerminalWebSocket("ws://127.0.0.1", "token")
    client.reader = asyncio.StreamReader()
    client.reader.feed_data(b"\x82\x03raw")
    assert await client.__anext__() == b"raw"
