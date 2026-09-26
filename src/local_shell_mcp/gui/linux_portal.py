from __future__ import annotations

import asyncio
import contextlib
import shutil
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .base import GuiUnavailableError


def _portal_modules():  # noqa: ANN202
    try:
        from dbus_next import Variant
        from dbus_next.aio import MessageBus
    except ImportError as exc:  # pragma: no cover - Linux dependency guard
        raise GuiUnavailableError(
            "Wayland GUI control requires the dbus-next package"
        ) from exc
    return MessageBus, Variant


def _unwrap(value: Any) -> Any:
    if hasattr(value, "value") and value.__class__.__name__ == "Variant":
        return _unwrap(value.value)
    if isinstance(value, dict):
        return {key: _unwrap(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_unwrap(item) for item in value]
    return value


_KEYSYMS = {
    "BACKSPACE": 0xFF08,
    "TAB": 0xFF09,
    "ENTER": 0xFF0D,
    "RETURN": 0xFF0D,
    "ESC": 0xFF1B,
    "ESCAPE": 0xFF1B,
    "HOME": 0xFF50,
    "LEFT": 0xFF51,
    "UP": 0xFF52,
    "RIGHT": 0xFF53,
    "DOWN": 0xFF54,
    "PAGEUP": 0xFF55,
    "PAGEDOWN": 0xFF56,
    "END": 0xFF57,
    "DELETE": 0xFFFF,
    "SPACE": 0x20,
}

_MODIFIERS = {
    "SHIFT": 0xFFE1,
    "CTRL": 0xFFE3,
    "CONTROL": 0xFFE3,
    "ALT": 0xFFE9,
    "OPTION": 0xFFE9,
    "META": 0xFFE7,
    "SUPER": 0xFFEB,
    "WIN": 0xFFEB,
    "CMD": 0xFFEB,
    "COMMAND": 0xFFEB,
}


def _keysym(text: str) -> int:
    upper = text.upper()
    if upper in _KEYSYMS:
        return _KEYSYMS[upper]
    if len(text) != 1:
        raise ValueError(f"Unsupported Wayland key name: {text}")
    codepoint = ord(text)
    if codepoint <= 0xFF:
        return codepoint
    return 0x01000000 | codepoint


def _key_parts(keys: Any) -> list[str]:
    if isinstance(keys, str):
        parts = [part.strip() for part in keys.replace("+", " ").split() if part.strip()]
    elif isinstance(keys, list):
        parts = [str(part).strip() for part in keys if str(part).strip()]
    else:
        raise ValueError("key action requires keys as a string or list")
    if not parts:
        raise ValueError("key action requires at least one key")
    return parts


class PortalDesktop:
    """XDG Desktop Portal RemoteDesktop/ScreenCast session for Wayland input."""

    def __init__(self, env: dict[str, str]) -> None:
        self._env = env
        self._bus = None
        self._remote = None
        self._screen = None
        self._session = None
        self._streams: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    async def _connect(self) -> None:
        if self._bus is not None:
            return
        MessageBus, _Variant = _portal_modules()
        address = self._env.get("DBUS_SESSION_BUS_ADDRESS")
        bus = MessageBus(bus_address=address) if address else MessageBus()
        self._bus = await bus.connect()
        intro = await self._bus.introspect(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
        )
        obj = self._bus.get_proxy_object(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            intro,
        )
        self._remote = obj.get_interface("org.freedesktop.portal.RemoteDesktop")
        self._screen = obj.get_interface("org.freedesktop.portal.ScreenCast")

    async def _request(self, awaitable: Any, *, timeout_s: float = 120.0) -> dict[str, Any]:
        assert self._bus is not None
        path = await awaitable
        intro = await self._bus.introspect("org.freedesktop.portal.Desktop", path)
        obj = self._bus.get_proxy_object("org.freedesktop.portal.Desktop", path, intro)
        interface = obj.get_interface("org.freedesktop.portal.Request")
        loop = asyncio.get_running_loop()
        future: asyncio.Future[tuple[int, dict[str, Any]]] = loop.create_future()

        def response(code: int, results: dict[str, Any]) -> None:
            if not future.done():
                future.set_result((int(code), _unwrap(results)))

        interface.on_response(response)
        try:
            code, results = await asyncio.wait_for(future, timeout=timeout_s)
        finally:
            with contextlib.suppress(Exception):
                interface.off_response(response)
        if code != 0:
            raise GuiUnavailableError(f"Desktop portal request was denied or cancelled ({code})")
        return results

    async def ensure_session(self) -> None:
        async with self._lock:
            if self._session is not None:
                return
            await self._connect()
            assert self._remote is not None and self._screen is not None
            _MessageBus, Variant = _portal_modules()
            token = uuid.uuid4().hex
            created = await self._request(
                self._remote.call_create_session(
                    {
                        "handle_token": Variant("s", f"lsm_req_{token}"),
                        "session_handle_token": Variant("s", f"lsm_session_{token}"),
                    }
                )
            )
            session = str(created["session_handle"])
            try:
                await self._request(
                    self._screen.call_select_sources(
                        session,
                        {
                            "types": Variant("u", 1),
                            "multiple": Variant("b", True),
                            "cursor_mode": Variant("u", 1),
                        },
                    )
                )
                await self._request(
                    self._remote.call_select_devices(
                        session,
                        {"types": Variant("u", 3)},
                    )
                )
                started = await self._request(self._remote.call_start(session, "", {}))
            except Exception:
                self._session = None
                raise
            self._session = session
            self._streams = []
            for stream in started.get("streams", []):
                if not isinstance(stream, list) or not stream:
                    continue
                node_id = int(stream[0])
                props = stream[1] if len(stream) > 1 and isinstance(stream[1], dict) else {}
                self._streams.append({"node_id": node_id, "properties": props})

    def _stream_point(self, x: int, y: int) -> tuple[int, float, float]:
        if not self._streams:
            raise GuiUnavailableError(
                "Wayland portal did not provide a ScreenCast stream for absolute pointer input"
            )
        for stream in self._streams:
            props = stream["properties"]
            position = props.get("position")
            size = props.get("size")
            if (
                isinstance(position, list)
                and len(position) >= 2
                and isinstance(size, list)
                and len(size) >= 2
            ):
                px, py = int(position[0]), int(position[1])
                width, height = int(size[0]), int(size[1])
                if px <= x < px + width and py <= y < py + height:
                    return stream["node_id"], float(x - px), float(y - py)
        return self._streams[0]["node_id"], float(x), float(y)

    async def move(self, x: int, y: int) -> None:
        await self.ensure_session()
        assert self._remote is not None and self._session is not None
        stream, local_x, local_y = self._stream_point(x, y)
        await self._remote.call_notify_pointer_motion_absolute(
            self._session,
            {},
            stream,
            local_x,
            local_y,
        )

    async def button(self, button: int, pressed: bool) -> None:
        await self.ensure_session()
        assert self._remote is not None and self._session is not None
        code = 0x110 + max(0, int(button) - 1)
        await self._remote.call_notify_pointer_button(
            self._session,
            {},
            code,
            1 if pressed else 0,
        )

    async def click(self, x: int, y: int, button: int = 1, count: int = 1) -> None:
        await self.move(x, y)
        for _ in range(max(1, count)):
            await self.button(button, True)
            await self.button(button, False)

    async def drag(self, x: int, y: int, to_x: int, to_y: int) -> None:
        await self.move(x, y)
        await self.button(1, True)
        try:
            await self.move(to_x, to_y)
        finally:
            await self.button(1, False)

    async def scroll(self, x: int, y: int, delta_x: float, delta_y: float) -> None:
        await self.move(x, y)
        assert self._remote is not None and self._session is not None
        await self._remote.call_notify_pointer_axis(
            self._session,
            {},
            float(delta_x),
            float(delta_y),
        )

    async def _key_event(self, keysym: int, pressed: bool) -> None:
        await self.ensure_session()
        assert self._remote is not None and self._session is not None
        await self._remote.call_notify_keyboard_keysym(
            self._session,
            {},
            int(keysym),
            1 if pressed else 0,
        )

    async def type_text(self, text: str) -> None:
        for char in text:
            symbol = _keysym("ENTER" if char == "\n" else char)
            await self._key_event(symbol, True)
            await self._key_event(symbol, False)

    async def key_chord(self, keys: Any) -> None:
        parts = _key_parts(keys)
        modifiers = []
        ordinary = []
        for part in parts:
            symbol = _MODIFIERS.get(part.upper())
            if symbol is not None:
                modifiers.append(symbol)
            else:
                ordinary.append(_keysym(part))
        if len(ordinary) != 1:
            raise ValueError("key action requires exactly one non-modifier key")
        for symbol in modifiers:
            await self._key_event(symbol, True)
        try:
            await self._key_event(ordinary[0], True)
            await self._key_event(ordinary[0], False)
        finally:
            for symbol in reversed(modifiers):
                await self._key_event(symbol, False)


async def portal_screenshot(destination: Path, env: dict[str, str]) -> None:
    MessageBus, Variant = _portal_modules()
    address = env.get("DBUS_SESSION_BUS_ADDRESS")
    bus = MessageBus(bus_address=address) if address else MessageBus()
    bus = await bus.connect()
    try:
        intro = await bus.introspect(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
        )
        obj = bus.get_proxy_object(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            intro,
        )
        screenshot = obj.get_interface("org.freedesktop.portal.Screenshot")
        path = await screenshot.call_screenshot(
            "",
            {
                "handle_token": Variant("s", f"lsm_shot_{uuid.uuid4().hex}"),
                "interactive": Variant("b", False),
            },
        )
        request_intro = await bus.introspect("org.freedesktop.portal.Desktop", path)
        request_obj = bus.get_proxy_object(
            "org.freedesktop.portal.Desktop",
            path,
            request_intro,
        )
        request = request_obj.get_interface("org.freedesktop.portal.Request")
        loop = asyncio.get_running_loop()
        future: asyncio.Future[tuple[int, dict[str, Any]]] = loop.create_future()

        def response(code: int, results: dict[str, Any]) -> None:
            if not future.done():
                future.set_result((int(code), _unwrap(results)))

        request.on_response(response)
        code, results = await asyncio.wait_for(future, timeout=120)
        if code != 0:
            raise GuiUnavailableError(f"Screenshot portal request was denied or cancelled ({code})")
        uri = str(results.get("uri") or "")
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            raise GuiUnavailableError(f"Screenshot portal returned unsupported URI: {uri}")
        source = Path(unquote(parsed.path))
        await asyncio.to_thread(shutil.copyfile, source, destination)
    finally:
        bus.disconnect()
