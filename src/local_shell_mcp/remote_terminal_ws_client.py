"""Small RFC 6455 client for the self-contained POSIX worker bundle.

Only binary/text messages and control frames are needed by the terminal relay.
All client frames are masked; no compression or third-party packages are used.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import ssl
from urllib.parse import unquote, urlsplit
from urllib.request import getproxies, proxy_bypass


async def _dial_websocket(
    host: str, port: int, secure: bool
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    proxies = getproxies()
    proxy_url = proxies.get("https" if secure else "http") or proxies.get("all")
    if not proxy_url or proxy_bypass(host):
        return await asyncio.wait_for(
            asyncio.open_connection(
                host, port, ssl=ssl.create_default_context() if secure else None
            ),
            10,
        )

    proxy = urlsplit(proxy_url)
    if proxy.scheme not in {"http", "https"} or not proxy.hostname:
        raise ValueError("invalid terminal websocket proxy URL")
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(
            proxy.hostname,
            proxy.port or (443 if proxy.scheme == "https" else 80),
            ssl=ssl.create_default_context() if proxy.scheme == "https" else None,
        ),
        10,
    )
    try:
        authority = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
        authorization = ""
        if proxy.username is not None:
            credentials = f"{unquote(proxy.username)}:{unquote(proxy.password or '')}"
            encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
            authorization = f"Proxy-Authorization: Basic {encoded}\r\n"
        writer.write(
            (f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n{authorization}\r\n").encode(
                "ascii"
            )
        )
        await writer.drain()
        response = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
        if len(response) > 16_384 or response.split(b"\r\n", 1)[0].split()[1:2] != [b"200"]:
            raise ConnectionError("remote terminal websocket proxy CONNECT rejected")
        if secure:
            await asyncio.wait_for(
                writer.start_tls(ssl.create_default_context(), server_hostname=host), 10
            )
        return reader, writer
    except BaseException:
        writer.close()
        await writer.wait_closed()
        raise


class TerminalWebSocket:
    def __init__(self, url: str, token: str):
        self.url = url
        self.token = token
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.lock = asyncio.Lock()

    async def __aenter__(self) -> TerminalWebSocket:
        parsed = urlsplit(self.url)
        if (
            parsed.scheme not in {"ws", "wss"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("invalid terminal websocket URL")
        secure = parsed.scheme == "wss"
        reader, writer = await _dial_websocket(
            parsed.hostname, parsed.port or (443 if secure else 80), secure
        )
        self.reader, self.writer = reader, writer
        try:
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            host = parsed.netloc
            path = (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
            request = (
                f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n"
                f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n"
                f"Authorization: Bearer {self.token}\r\n\r\n"
            )
            writer.write(request.encode("ascii"))
            await writer.drain()
            headers = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
            if len(headers) > 16_384:
                raise ValueError("terminal websocket response headers too large")
            lines = headers.decode("latin-1").split("\r\n")
            values: dict[str, str] = {}
            for line in lines[1:]:
                if ":" in line:
                    name, value = line.split(":", 1)
                    name = name.lower()
                    values[name] = (
                        f"{values[name]}, {value.strip()}" if name in values else value.strip()
                    )
            accept = base64.b64encode(
                hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
            ).decode("ascii")  # noqa: S324
            if (
                not lines[0].startswith("HTTP/1.1 101 ")
                or values.get("sec-websocket-accept") != accept
                or values.get("upgrade", "").lower() != "websocket"
                or "upgrade"
                not in [item.strip() for item in values.get("connection", "").lower().split(",")]
            ):
                raise ConnectionError("remote terminal websocket handshake rejected")
            return self
        except BaseException:
            await self.close()
            raise

    async def send(self, data: bytes | str, *, opcode: int | None = None) -> None:
        writer = self.writer
        if writer is None:
            raise ConnectionError("terminal websocket is not connected")
        if opcode is None:
            opcode = 2 if isinstance(data, bytes) else 1
        payload = data.encode("utf-8") if isinstance(data, str) else data
        if len(payload) > 1024 * 1024:
            raise ValueError("terminal websocket message too large")
        mask = os.urandom(4)
        size = len(payload)
        if size < 126:
            header = bytes([0x80 | opcode, 0x80 | size])
        elif size < 65_536:
            header = bytes([0x80 | opcode, 0x80 | 126]) + size.to_bytes(2, "big")
        else:
            header = bytes([0x80 | opcode, 0x80 | 127]) + size.to_bytes(8, "big")
        framed = header + mask + bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        async with self.lock:
            writer.write(framed)
            await writer.drain()

    async def _frame(self) -> tuple[int, bool, bytes]:
        if self.reader is None:
            raise ConnectionError("terminal websocket is not connected")
        first, second = await self.reader.readexactly(2)
        length = second & 0x7F
        if second & 0x80:
            raise ValueError("server frames must not be masked")
        if length == 126:
            length = int.from_bytes(await self.reader.readexactly(2), "big")
        elif length == 127:
            length = int.from_bytes(await self.reader.readexactly(8), "big")
        if length > 1024 * 1024:
            raise ValueError("terminal websocket frame too large")
        return first & 0x0F, bool(first & 0x80), await self.reader.readexactly(length)

    async def receive(self) -> bytes | str | None:
        fragments = bytearray()
        kind = 0
        while True:
            opcode, final, payload = await self._frame()
            if opcode == 8:
                return None
            if opcode == 9:
                await self.send(payload, opcode=10)
                continue
            if opcode == 10:
                continue
            if opcode not in {0, 1, 2} or (opcode == 0 and not kind) or (opcode in {1, 2} and kind):
                raise ValueError("unexpected terminal websocket frame")
            if opcode:
                kind = opcode
            fragments.extend(payload)
            if len(fragments) > 1024 * 1024:
                raise ValueError("terminal websocket message too large")
            if final:
                return fragments.decode("utf-8") if kind == 1 else bytes(fragments)

    def __aiter__(self):  # noqa: ANN201
        return self

    async def __anext__(self) -> bytes | str:
        try:
            message = await self.receive()
        except (asyncio.IncompleteReadError, ConnectionError) as exc:
            raise StopAsyncIteration from exc
        if message is None:
            raise StopAsyncIteration
        return message

    async def close(self) -> None:
        writer = self.writer
        self.writer = None
        if writer is not None:
            writer.close()
            await writer.wait_closed()

    async def __aexit__(self, *_args: object) -> None:
        await self.close()
