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


def _portal_request_path(bus: Any, handle_token: str) -> str:
    unique_name = str(getattr(bus, "unique_name", "") or "")
    sender = unique_name.lstrip(":").replace(".", "_")
    if not sender:
        raise GuiUnavailableError("D-Bus connection has no unique name")
    return f"/org/freedesktop/portal/desktop/request/{sender}/{handle_token}"


async def _portal_request(
    bus: Any,
    awaitable: Any,
    *,
    handle_token: str,
    timeout_s: float = 120.0,
) -> dict[str, Any]:
    from dbus_next import MessageType

    expected_path = _portal_request_path(bus, handle_token)
    loop = asyncio.get_running_loop()
    future: asyncio.Future[tuple[int, dict[str, Any]]] = loop.create_future()

    def handler(message: Any) -> bool:
        if (
            message.message_type == MessageType.SIGNAL
            and message.path == expected_path
            and message.interface == "org.freedesktop.portal.Request"
            and message.member == "Response"
        ):
            body = list(message.body or [])
            if len(body) >= 2 and not future.done():
                future.set_result((int(body[0]), _unwrap(body[1])))
        return False

    match_rule = (
        "type='signal',sender=org.freedesktop.portal.Desktop,"
        f"interface=org.freedesktop.portal.Request,path={expected_path}"
    )
    bus._add_match_rule(match_rule)
    bus.add_message_handler(handler)
    try:
        path = str(await awaitable)
        if path != expected_path:
            raise GuiUnavailableError(
                f"Desktop portal returned unexpected request path: {path}"
            )
        code, results = await asyncio.wait_for(future, timeout=timeout_s)
    finally:
        with contextlib.suppress(Exception):
            bus.remove_message_handler(handler)
        with contextlib.suppress(Exception):
            bus._remove_match_rule(match_rule)
    if code != 0:
        raise GuiUnavailableError(f"Desktop portal request was denied or cancelled ({code})")
    return results


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
        if self._bus is not None and self._remote is not None and self._screen is not None:
            return
        self._bus = None
        self._remote = None
        self._screen = None
        MessageBus, _Variant = _portal_modules()
        address = self._env.get("DBUS_SESSION_BUS_ADDRESS")
        candidate = MessageBus(bus_address=address) if address else MessageBus()
        connected = None
        try:
            connected = await candidate.connect()
            intro = await connected.introspect(
                "org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop",
            )
            obj = connected.get_proxy_object(
                "org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop",
                intro,
            )
            remote = obj.get_interface("org.freedesktop.portal.RemoteDesktop")
            screen = obj.get_interface("org.freedesktop.portal.ScreenCast")
        except BaseException:
            if connected is not None:
                with contextlib.suppress(Exception):
                    connected.disconnect()
            raise
        self._bus = connected
        self._remote = remote
        self._screen = screen

    async def _request(
        self,
        awaitable: Any,
        *,
        handle_token: str,
        timeout_s: float = 120.0,
    ) -> dict[str, Any]:
        assert self._bus is not None
        return await _portal_request(
            self._bus,
            awaitable,
            handle_token=handle_token,
            timeout_s=timeout_s,
        )

    async def _close_session(self, session: str) -> None:
        if self._bus is None:
            return
        intro = await self._bus.introspect(
            "org.freedesktop.portal.Desktop",
            session,
        )
        obj = self._bus.get_proxy_object(
            "org.freedesktop.portal.Desktop",
            session,
            intro,
        )
        iface = obj.get_interface("org.freedesktop.portal.Session")
        await iface.call_close()

    async def ensure_session(self) -> None:
        async with self._lock:
            if self._session is not None:
                return
            await self._connect()
            assert self._remote is not None and self._screen is not None
            _MessageBus, Variant = _portal_modules()
            token = f"lsm_req_{uuid.uuid4().hex}"
            created = await self._request(
                self._remote.call_create_session(
                    {
                        "handle_token": Variant("s", token),
                        "session_handle_token": Variant(
                            "s", f"lsm_session_{uuid.uuid4().hex}"
                        ),
                    }
                ),
                handle_token=token,
            )
            session = str(created["session_handle"])
            try:
                source_token = f"lsm_req_{uuid.uuid4().hex}"
                await self._request(
                    self._screen.call_select_sources(
                        session,
                        {
                            "handle_token": Variant("s", source_token),
                            "types": Variant("u", 1),
                            "multiple": Variant("b", True),
                            "cursor_mode": Variant("u", 1),
                        },
                    ),
                    handle_token=source_token,
                )
                device_token = f"lsm_req_{uuid.uuid4().hex}"
                await self._request(
                    self._remote.call_select_devices(
                        session,
                        {
                            "handle_token": Variant("s", device_token),
                            "types": Variant("u", 3),
                        },
                    ),
                    handle_token=device_token,
                )
                start_token = f"lsm_req_{uuid.uuid4().hex}"
                started = await self._request(
                    self._remote.call_start(
                        session,
                        "",
                        {"handle_token": Variant("s", start_token)},
                    ),
                    handle_token=start_token,
                )
            except BaseException:
                with contextlib.suppress(BaseException):
                    await asyncio.shield(self._close_session(session))
                self._session = None
                self._streams = []
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
        raise GuiUnavailableError(
            "Target point is outside the ScreenCast streams granted by the desktop portal"
        )

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
        codes = {1: 0x110, 2: 0x112, 3: 0x111}
        try:
            code = codes[int(button)]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Unsupported pointer button: {button}") from exc
        await self._remote.call_notify_pointer_button(
            self._session,
            {},
            code,
            1 if pressed else 0,
        )

    async def click(self, x: int, y: int, button: int = 1, count: int = 1) -> None:
        await self.move(x, y)
        for _ in range(max(1, count)):
            pressed = False
            try:
                await self.button(button, True)
                pressed = True
                await self.button(button, False)
                pressed = False
            finally:
                if pressed:
                    with contextlib.suppress(BaseException):
                        await asyncio.shield(self.button(button, False))

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
            pressed = False
            try:
                await self._key_event(symbol, True)
                pressed = True
                await self._key_event(symbol, False)
                pressed = False
            finally:
                if pressed:
                    with contextlib.suppress(Exception):
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

        pressed: list[int] = []
        try:
            for symbol in modifiers:
                await self._key_event(symbol, True)
                pressed.append(symbol)
            ordinary_symbol = ordinary[0]
            await self._key_event(ordinary_symbol, True)
            pressed.append(ordinary_symbol)
            await self._key_event(ordinary_symbol, False)
            pressed.pop()
        finally:
            for symbol in reversed(pressed):
                with contextlib.suppress(Exception):
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
        token = f"lsm_shot_{uuid.uuid4().hex}"
        results = await _portal_request(
            bus,
            screenshot.call_screenshot(
                "",
                {
                    "handle_token": Variant("s", token),
                    "interactive": Variant("b", False),
                },
            ),
            handle_token=token,
        )
        uri = str(results.get("uri") or "")
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            raise GuiUnavailableError(f"Screenshot portal returned unsupported URI: {uri}")
        source = Path(unquote(parsed.path))
        await asyncio.to_thread(shutil.copyfile, source, destination)
    finally:
        bus.disconnect()
