from __future__ import annotations

import asyncio
import contextlib
import shutil
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from .base import GuiUnavailableError

_PORTAL_INPUT_TIMEOUT_S = 15.0
_PORTAL_LIFECYCLE_TIMEOUT_S = 15.0


async def _portal_lifecycle_wait(awaitable: Any, operation: str) -> Any:
    try:
        return await asyncio.wait_for(
            awaitable,
            timeout=_PORTAL_LIFECYCLE_TIMEOUT_S,
        )
    except TimeoutError as exc:
        raise GuiUnavailableError(
            f"Timed out while {operation} on the desktop portal"
        ) from exc


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
    "META": 0xFFEB,
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
        "type='signal',sender='org.freedesktop.portal.Desktop',"
        f"interface='org.freedesktop.portal.Request',path='{expected_path}'"
    )
    bus._add_match_rule(match_rule)
    bus.add_message_handler(handler)
    try:
        async def request_and_wait() -> tuple[int, dict[str, Any]]:
            path = str(await awaitable)
            if path != expected_path:
                raise GuiUnavailableError(
                    f"Desktop portal returned unexpected request path: {path}"
                )
            return await future

        code, results = await asyncio.wait_for(
            request_and_wait(),
            timeout=timeout_s,
        )
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
        self._session_iface = None
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
            connected = await _portal_lifecycle_wait(
                candidate.connect(),
                "connecting to D-Bus",
            )
            intro = await _portal_lifecycle_wait(
                connected.introspect(
                    "org.freedesktop.portal.Desktop",
                    "/org/freedesktop/portal/desktop",
                ),
                "introspecting the desktop portal",
            )
            obj = connected.get_proxy_object(
                "org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop",
                intro,
            )
            remote = obj.get_interface("org.freedesktop.portal.RemoteDesktop")
            screen = obj.get_interface("org.freedesktop.portal.ScreenCast")
        except BaseException:
            with contextlib.suppress(Exception):
                (connected or candidate).disconnect()
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

    def _on_session_closed(self, *_args: Any) -> None:
        self._session = None
        self._session_iface = None
        self._streams = []

    def _invalidate_transport(self) -> None:
        bus = self._bus
        self._bus = None
        self._remote = None
        self._screen = None
        self._session = None
        self._session_iface = None
        self._streams = []
        if bus is not None:
            with contextlib.suppress(Exception):
                bus.disconnect()

    async def close(self) -> None:
        async with self._lock:
            session = self._session
            if session is not None and self._bus is not None:
                with contextlib.suppress(BaseException):
                    await asyncio.shield(self._close_session(session))
            self._invalidate_transport()

    async def _call_remote(self, operation: Any, *args: Any) -> Any:
        try:
            return await asyncio.wait_for(
                operation(*args),
                timeout=_PORTAL_INPUT_TIMEOUT_S,
            )
        except BaseException:
            self._invalidate_transport()
            raise

    async def _observe_session_closed(self, session: str) -> None:
        if self._bus is None:
            return
        intro = await _portal_lifecycle_wait(
            self._bus.introspect(
                "org.freedesktop.portal.Desktop",
                session,
            ),
            "introspecting the portal session",
        )
        obj = self._bus.get_proxy_object(
            "org.freedesktop.portal.Desktop",
            session,
            intro,
        )
        iface = obj.get_interface("org.freedesktop.portal.Session")
        on_closed = getattr(iface, "on_closed", None)
        if not callable(on_closed):
            raise GuiUnavailableError(
                "Wayland portal Session interface does not expose a Closed signal"
            )
        on_closed(self._on_session_closed)
        if self._session == session:
            self._session_iface = iface

    async def _close_session(self, session: str) -> None:
        if self._bus is None:
            return
        intro = await _portal_lifecycle_wait(
            self._bus.introspect(
                "org.freedesktop.portal.Desktop",
                session,
            ),
            "introspecting the portal session",
        )
        obj = self._bus.get_proxy_object(
            "org.freedesktop.portal.Desktop",
            session,
            intro,
        )
        iface = obj.get_interface("org.freedesktop.portal.Session")
        await _portal_lifecycle_wait(
            iface.call_close(),
            "closing the portal session",
        )

    async def ensure_session(self) -> str:
        async with self._lock:
            if self._session is not None:
                return self._session
            await self._connect()
            assert self._remote is not None and self._screen is not None
            _MessageBus, Variant = _portal_modules()
            token = f"lsm_req_{uuid.uuid4().hex}"
            try:
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
            except BaseException:
                self._invalidate_transport()
                raise
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
                self._invalidate_transport()
                raise
            self._session = session
            self._session_iface = None
            self._streams = []
            for stream in started.get("streams", []):
                if not isinstance(stream, list) or not stream:
                    continue
                node_id = int(stream[0])
                props = stream[1] if len(stream) > 1 and isinstance(stream[1], dict) else {}
                self._streams.append({"node_id": node_id, "properties": props})
            try:
                await self._observe_session_closed(session)
            except Exception as exc:
                with contextlib.suppress(BaseException):
                    await asyncio.shield(self._close_session(session))
                self._invalidate_transport()
                raise GuiUnavailableError(
                    "Wayland portal session closure observation could not be installed"
                ) from exc
            if self._session != session:
                self._invalidate_transport()
                raise GuiUnavailableError("Wayland portal session closed during setup")
            return session

    def _require_session(self, session: str) -> Any:
        if not session or self._session != session or self._remote is None:
            raise GuiUnavailableError("Wayland portal session closed during the current gesture")
        return self._remote

    async def _bind_session(self, session: str | None) -> str:
        if session is None:
            return await self.ensure_session()
        self._require_session(session)
        return session

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

    async def move(self, x: int, y: int, *, session: str | None = None) -> None:
        session = await self._bind_session(session)
        remote = self._require_session(session)
        stream, local_x, local_y = self._stream_point(x, y)
        await self._call_remote(
            remote.call_notify_pointer_motion_absolute,
            session,
            {},
            stream,
            local_x,
            local_y,
        )

    async def button(
        self,
        button: int,
        pressed: bool,
        *,
        session: str | None = None,
    ) -> None:
        session = await self._bind_session(session)
        remote = self._require_session(session)
        codes = {1: 0x110, 2: 0x112, 3: 0x111}
        try:
            code = codes[int(button)]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Unsupported pointer button: {button}") from exc
        await self._call_remote(
            remote.call_notify_pointer_button,
            session,
            {},
            code,
            1 if pressed else 0,
        )

    async def click(
        self,
        x: int,
        y: int,
        button: int = 1,
        count: int = 1,
        *,
        session: str | None = None,
    ) -> None:
        session = await self._bind_session(session)
        await self.move(x, y, session=session)
        for _ in range(max(1, count)):
            pressed = False
            try:
                await self.button(button, True, session=session)
                pressed = True
                await self.button(button, False, session=session)
                pressed = False
            finally:
                if pressed:
                    with contextlib.suppress(BaseException):
                        await asyncio.shield(
                            self.button(button, False, session=session)
                        )

    async def drag(
        self,
        x: int,
        y: int,
        to_x: int,
        to_y: int,
        *,
        session: str | None = None,
    ) -> None:
        session = await self._bind_session(session)
        await self.move(x, y, session=session)
        pressed = False
        try:
            await self.button(1, True, session=session)
            pressed = True
            await self.move(to_x, to_y, session=session)
            await self.button(1, False, session=session)
            pressed = False
        finally:
            if pressed:
                with contextlib.suppress(BaseException):
                    await asyncio.shield(self.button(1, False, session=session))

    async def scroll(
        self,
        x: int,
        y: int,
        delta_x: float,
        delta_y: float,
        *,
        session: str | None = None,
    ) -> None:
        session = await self._bind_session(session)
        await self.move(x, y, session=session)
        remote = self._require_session(session)
        await self._call_remote(
            remote.call_notify_pointer_axis,
            session,
            {},
            -float(delta_x),
            -float(delta_y),
        )

    async def _key_event(
        self,
        keysym: int,
        pressed: bool,
        *,
        session: str | None = None,
    ) -> None:
        session = await self._bind_session(session)
        remote = self._require_session(session)
        await self._call_remote(
            remote.call_notify_keyboard_keysym,
            session,
            {},
            int(keysym),
            1 if pressed else 0,
        )

    async def type_text(self, text: str, *, session: str | None = None) -> None:
        session = await self._bind_session(session)
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        for char in normalized:
            if char == "\n":
                symbol = _keysym("ENTER")
            elif char == "\t":
                symbol = _keysym("TAB")
            else:
                symbol = _keysym(char)
            pressed = False
            try:
                await self._key_event(symbol, True, session=session)
                pressed = True
                await self._key_event(symbol, False, session=session)
                pressed = False
            finally:
                if pressed:
                    with contextlib.suppress(Exception):
                        await self._key_event(symbol, False, session=session)

    async def key_chord(self, keys: Any, *, session: str | None = None) -> None:
        session = await self._bind_session(session)
        parts = _key_parts(keys)
        modifiers = []
        ordinary = []
        for part in parts:
            symbol = _MODIFIERS.get(part.upper())
            if symbol is not None:
                modifiers.append(symbol)
            else:
                normalized = part.lower() if len(part) == 1 and part.isalpha() else part
                ordinary.append(_keysym(normalized))
        if len(ordinary) != 1:
            raise ValueError("key action requires exactly one non-modifier key")

        pressed: list[int] = []
        try:
            for symbol in modifiers:
                await self._key_event(symbol, True, session=session)
                pressed.append(symbol)
            ordinary_symbol = ordinary[0]
            await self._key_event(ordinary_symbol, True, session=session)
            pressed.append(ordinary_symbol)
            await self._key_event(ordinary_symbol, False, session=session)
            pressed.pop()
        finally:
            for symbol in reversed(pressed):
                with contextlib.suppress(Exception):
                    await self._key_event(symbol, False, session=session)


async def portal_screenshot(destination: Path, env: dict[str, str]) -> None:
    MessageBus, Variant = _portal_modules()
    address = env.get("DBUS_SESSION_BUS_ADDRESS")
    candidate = MessageBus(bus_address=address) if address else MessageBus()
    try:
        bus = await _portal_lifecycle_wait(
            candidate.connect(),
            "connecting to D-Bus",
        )
    except BaseException:
        with contextlib.suppress(Exception):
            candidate.disconnect()
        raise
    try:
        intro = await _portal_lifecycle_wait(
            bus.introspect(
                "org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop",
            ),
            "introspecting the screenshot portal",
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
        source = Path(url2pathname(unquote(parsed.path)))
        try:
            await asyncio.to_thread(shutil.copyfile, source, destination)
        finally:
            with contextlib.suppress(OSError):
                await asyncio.to_thread(source.unlink, missing_ok=True)
    finally:
        bus.disconnect()
