from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import subprocess
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from ..state_store import get_state_store
from .base import GuiUnavailableError
from .linux_eis import EisSender

_PORTAL_INPUT_TIMEOUT_S = 15.0
_PORTAL_LIFECYCLE_TIMEOUT_S = 15.0
_PORTAL_RESTORE_TOKEN_KEY = "gui/remote-desktop-restore-token"
_PORTAL_RESTORE_TOKEN_MAX_BYTES = 4096


async def _portal_lifecycle_wait(awaitable: Any, operation: str) -> Any:
    try:
        return await asyncio.wait_for(
            awaitable,
            timeout=_PORTAL_LIFECYCLE_TIMEOUT_S,
        )
    except TimeoutError as exc:
        raise GuiUnavailableError(f"Timed out while {operation} on the desktop portal") from exc


def _portal_modules():  # noqa: ANN202
    try:
        from dbus_next import Variant
        from dbus_next.aio import MessageBus
    except ImportError as exc:  # pragma: no cover - Linux dependency guard
        raise GuiUnavailableError("Wayland GUI control requires the dbus-next package") from exc
    return MessageBus, Variant


def _load_portal_restore_token() -> str | None:
    raw = get_state_store().read_bytes(_PORTAL_RESTORE_TOKEN_KEY)
    if not raw or len(raw) > _PORTAL_RESTORE_TOKEN_MAX_BYTES:
        return None
    try:
        token = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not token or "\x00" in token:
        return None
    return token


def _save_portal_restore_token(token: str) -> None:
    encoded = token.encode("utf-8")
    if not encoded or len(encoded) > _PORTAL_RESTORE_TOKEN_MAX_BYTES:
        return
    get_state_store().write_bytes(_PORTAL_RESTORE_TOKEN_KEY, encoded)


def _clear_portal_restore_token() -> None:
    get_state_store().delete(_PORTAL_RESTORE_TOKEN_KEY)


def _unwrap(value: Any) -> Any:
    if hasattr(value, "value") and value.__class__.__name__ == "Variant":
        return _unwrap(value.value)
    if isinstance(value, dict):
        return {key: _unwrap(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_unwrap(item) for item in value]
    return value


async def _portal_introspect(
    bus: Any,
    bus_name: str,
    path: str,
    *,
    interfaces: set[str],
    operation: str,
) -> Any:
    try:
        return await _portal_lifecycle_wait(
            bus.introspect(bus_name, path),
            operation,
        )
    except Exception as exc:
        # dbus-next rejects KDE portal introspection XML when an unrelated
        # interface contains a non-member-safe property name (for example,
        # power-saver-enabled). Keep dbus-next optional on all normal paths
        # and only load the raw-introspection fallback for that exact failure.
        if type(exc).__name__ != "InvalidMemberNameError" or not type(exc).__module__.startswith(
            "dbus_next"
        ):
            raise

    from dbus_next import Message, MessageType
    from dbus_next.introspection import Node

    reply = await _portal_lifecycle_wait(
        bus.call(
            Message(
                destination=bus_name,
                path=path,
                interface="org.freedesktop.DBus.Introspectable",
                member="Introspect",
            )
        ),
        operation,
    )
    if reply is None or reply.message_type == MessageType.ERROR:
        detail = ""
        if reply is not None:
            detail = str(getattr(reply, "error_name", "") or "")
        raise GuiUnavailableError(
            f"Desktop portal introspection failed{f': {detail}' if detail else ''}"
        )
    body = list(getattr(reply, "body", []) or [])
    if not body or not isinstance(body[0], str):
        raise GuiUnavailableError("Desktop portal returned invalid introspection data")

    try:
        root = ET.fromstring(body[0])
    except ET.ParseError as parse_exc:
        raise GuiUnavailableError(
            "Desktop portal returned invalid introspection XML"
        ) from parse_exc
    for child in list(root):
        if child.tag == "interface" and child.attrib.get("name") not in interfaces:
            root.remove(child)
    return Node.parse(ET.tostring(root, encoding="unicode"))


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
        self._monitors: list[dict[str, Any]] = []
        self._eis_sender: EisSender | None = None
        self._eis_unavailable = False
        self._lock = asyncio.Lock()

    async def _connect(self) -> None:
        if self._bus is not None and self._remote is not None and self._screen is not None:
            return
        self._bus = None
        self._remote = None
        self._screen = None
        MessageBus, _Variant = _portal_modules()
        address = self._env.get("DBUS_SESSION_BUS_ADDRESS")
        candidate = (
            MessageBus(bus_address=address, negotiate_unix_fd=True)
            if address
            else MessageBus(negotiate_unix_fd=True)
        )
        connected = None
        try:
            connected = await _portal_lifecycle_wait(
                candidate.connect(),
                "connecting to D-Bus",
            )
            intro = await _portal_introspect(
                connected,
                "org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop",
                interfaces={
                    "org.freedesktop.portal.RemoteDesktop",
                    "org.freedesktop.portal.ScreenCast",
                },
                operation="introspecting the desktop portal",
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
        if self._eis_sender is not None:
            self._eis_sender.close()
        self._eis_sender = None
        self._eis_unavailable = False
        self._session = None
        self._session_iface = None
        self._streams = []

    def _invalidate_transport(self) -> None:
        bus = self._bus
        if self._eis_sender is not None:
            self._eis_sender.close()
        self._eis_sender = None
        self._eis_unavailable = False
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
        intro = await _portal_introspect(
            self._bus,
            "org.freedesktop.portal.Desktop",
            session,
            interfaces={"org.freedesktop.portal.Session"},
            operation="introspecting the portal session",
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
        intro = await _portal_introspect(
            self._bus,
            "org.freedesktop.portal.Desktop",
            session,
            interfaces={"org.freedesktop.portal.Session"},
            operation="introspecting the portal session",
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
                            "session_handle_token": Variant("s", f"lsm_session_{uuid.uuid4().hex}"),
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
                try:
                    restore_token = await asyncio.to_thread(_load_portal_restore_token)
                except Exception:
                    restore_token = None
                device_token = f"lsm_req_{uuid.uuid4().hex}"
                device_options = {
                    "handle_token": Variant("s", device_token),
                    "types": Variant("u", 3),
                    "persist_mode": Variant("u", 2),
                }
                if restore_token is not None:
                    device_options["restore_token"] = Variant("s", restore_token)
                await self._request(
                    self._remote.call_select_devices(session, device_options),
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
                new_restore_token = str(started.get("restore_token") or "")
                if new_restore_token:
                    with contextlib.suppress(Exception):
                        await asyncio.to_thread(
                            _save_portal_restore_token,
                            new_restore_token,
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

    def set_monitor_layout(self, monitors: list[dict[str, Any]]) -> None:
        normalized: list[dict[str, Any]] = []
        for monitor in monitors:
            if not isinstance(monitor, dict):
                continue
            try:
                x = int(monitor["x"])
                y = int(monitor["y"])
                width = int(monitor["width"])
                height = int(monitor["height"])
                scale = float(monitor.get("scale", 1) or 1)
            except (KeyError, TypeError, ValueError):
                continue
            if width <= 0 or height <= 0 or scale <= 0:
                continue
            normalized.append(
                {
                    "x": x,
                    "y": y,
                    "width": width,
                    "height": height,
                    "scale": scale,
                }
            )
        self._monitors = normalized

    @staticmethod
    def _stream_size_matches_monitor(
        stream_width: int,
        stream_height: int,
        monitor: dict[str, Any],
    ) -> bool:
        logical_width = int(monitor["width"])
        logical_height = int(monitor["height"])
        scale = float(monitor.get("scale", 1) or 1)
        candidates = {
            (logical_width, logical_height),
            (
                max(1, int(round(logical_width * scale))),
                max(1, int(round(logical_height * scale))),
            ),
        }
        return (stream_width, stream_height) in candidates

    def _stream_mapping(
        self,
        stream: dict[str, Any],
    ) -> tuple[int, int, int, int, int, int] | None:
        props = stream.get("properties")
        if not isinstance(props, dict):
            return None
        size = props.get("size")
        if not isinstance(size, list) or len(size) < 2:
            return None
        try:
            stream_width, stream_height = int(size[0]), int(size[1])
        except (TypeError, ValueError):
            return None
        if stream_width <= 0 or stream_height <= 0:
            return None

        position = props.get("position")
        if isinstance(position, list) and len(position) >= 2:
            try:
                px, py = int(position[0]), int(position[1])
            except (TypeError, ValueError):
                return None
            matches = [
                monitor
                for monitor in self._monitors
                if int(monitor["x"]) == px
                and int(monitor["y"]) == py
                and self._stream_size_matches_monitor(
                    stream_width,
                    stream_height,
                    monitor,
                )
            ]
            if len(matches) == 1:
                monitor = matches[0]
                return (
                    int(monitor["x"]),
                    int(monitor["y"]),
                    int(monitor["width"]),
                    int(monitor["height"]),
                    stream_width,
                    stream_height,
                )
            return px, py, stream_width, stream_height, stream_width, stream_height

        if int(props.get("source_type") or 0) != 1:
            return None
        matches = [
            monitor
            for monitor in self._monitors
            if self._stream_size_matches_monitor(
                stream_width,
                stream_height,
                monitor,
            )
        ]
        if len(matches) != 1:
            return None
        monitor = matches[0]
        return (
            int(monitor["x"]),
            int(monitor["y"]),
            int(monitor["width"]),
            int(monitor["height"]),
            stream_width,
            stream_height,
        )

    def _stream_geometry(
        self,
        stream: dict[str, Any],
    ) -> tuple[int, int, int, int] | None:
        mapping = self._stream_mapping(stream)
        if mapping is None:
            return None
        x, y, width, height, _stream_width, _stream_height = mapping
        return x, y, width, height

    def _stream_point(self, x: int, y: int) -> tuple[int, float, float]:
        if not self._streams:
            raise GuiUnavailableError(
                "Wayland portal did not provide a ScreenCast stream for absolute pointer input"
            )
        for stream in self._streams:
            mapping = self._stream_mapping(stream)
            if mapping is None:
                continue
            px, py, width, height, stream_width, stream_height = mapping
            if px <= x < px + width and py <= y < py + height:
                local_x = (x - px) * stream_width / width
                local_y = (y - py) * stream_height / height
                return stream["node_id"], float(local_x), float(local_y)
        raise GuiUnavailableError(
            "Target point is outside the ScreenCast streams granted by the desktop portal"
        )

    async def capture_monitor_frame(
        self,
        path: Path,
        monitor: dict[str, Any],
    ) -> None:
        session = await self.ensure_session()
        if self._screen is None:
            raise GuiUnavailableError("Wayland ScreenCast portal is unavailable")
        gst_launch = shutil.which("gst-launch-1.0")
        if gst_launch is None:
            raise GuiUnavailableError(
                "KDE Wayland PipeWire capture requires gst-launch-1.0 and pipewiresrc"
            )

        try:
            target = (
                int(monitor["x"]),
                int(monitor["y"]),
                int(monitor["width"]),
                int(monitor["height"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GuiUnavailableError("Target monitor geometry is invalid") from exc

        matches = [stream for stream in self._streams if self._stream_geometry(stream) == target]
        if len(matches) != 1:
            raise GuiUnavailableError(
                "Could not uniquely map the target monitor to a ScreenCast stream"
            )
        node_id = int(matches[0]["node_id"])

        fd_value: Any = None
        try:
            fd_value = await _portal_lifecycle_wait(
                self._screen.call_open_pipe_wire_remote(session, {}),
                "opening the ScreenCast PipeWire remote",
            )
            fd = int(fd_value)
        except Exception as exc:
            raise GuiUnavailableError("Could not open the ScreenCast PipeWire remote") from exc

        path.unlink(missing_ok=True)
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [
                    gst_launch,
                    "-q",
                    "pipewiresrc",
                    f"fd={fd}",
                    f"path={node_id}",
                    "num-buffers=1",
                    "do-timestamp=true",
                    "!",
                    "videoconvert",
                    "!",
                    "pngenc",
                    "!",
                    "filesink",
                    f"location={path}",
                ],
                pass_fds=(fd,),
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                umask=0o077,
            )
        except subprocess.TimeoutExpired as exc:
            raise GuiUnavailableError("PipeWire screenshot capture timed out") from exc
        finally:
            with contextlib.suppress(OSError):
                os.close(fd)

        if result.returncode != 0 or not path.is_file() or path.stat().st_size <= 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise GuiUnavailableError(
                "PipeWire screenshot capture failed" + (f": {detail[-1000:]}" if detail else "")
            )

    async def _ensure_eis(self, session: str) -> EisSender | None:
        self._require_session(session)
        if self._eis_sender is not None:
            return self._eis_sender
        if self._eis_unavailable or not EisSender.available():
            self._eis_unavailable = True
            return None

        remote = self._require_session(session)
        connect = getattr(remote, "call_connect_to_eis", None)
        if not callable(connect):
            self._eis_unavailable = True
            return None
        try:
            raw_fd = int(
                await asyncio.wait_for(
                    connect(session, {}),
                    timeout=_PORTAL_INPUT_TIMEOUT_S,
                )
            )
            fd = os.dup(raw_fd)
            with contextlib.suppress(OSError):
                os.close(raw_fd)
            construct = asyncio.create_task(asyncio.to_thread(EisSender, fd))
            try:
                sender = await asyncio.shield(construct)
            except asyncio.CancelledError:
                with contextlib.suppress(Exception):
                    late_sender = await construct
                    await asyncio.to_thread(late_sender.close)
                raise
        except (
            AttributeError,
            GuiUnavailableError,
            OSError,
            TimeoutError,
            TypeError,
            ValueError,
        ):
            self._eis_unavailable = True
            return None
        self._eis_sender = sender
        return sender

    async def _eis_gesture(
        self,
        session: str,
        method: str,
        *args: Any,
        **kwargs: Any,
    ) -> bool:
        sender = await self._ensure_eis(session)
        if sender is None:
            return False
        try:
            await asyncio.to_thread(getattr(sender, method), *args, **kwargs)
        except GuiUnavailableError:
            if self._eis_sender is sender:
                self._eis_sender = None
            with contextlib.suppress(Exception):
                await asyncio.to_thread(sender.close)
            return False
        return True

    async def move(self, x: int, y: int, *, session: str | None = None) -> None:
        session = await self._bind_session(session)
        if await self._eis_gesture(session, "move", float(x), float(y)):
            return
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
        if await self._eis_gesture(
            session,
            "click",
            float(x),
            float(y),
            button=int(button),
            count=int(count),
        ):
            return
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
                        await asyncio.shield(self.button(button, False, session=session))

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
        if await self._eis_gesture(
            session,
            "drag",
            float(x),
            float(y),
            float(to_x),
            float(to_y),
        ):
            return
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
        if await self._eis_gesture(
            session,
            "scroll",
            float(x),
            float(y),
            -float(delta_x),
            -float(delta_y),
        ):
            return
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
        intro = await _portal_introspect(
            bus,
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            interfaces={"org.freedesktop.portal.Screenshot"},
            operation="introspecting the screenshot portal",
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
