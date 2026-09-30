from __future__ import annotations

import contextlib
import ctypes
import ctypes.util
import os
import select
import time
from typing import Any

from .base import GuiUnavailableError

_CAP_POINTER = 1 << 0
_CAP_POINTER_ABSOLUTE = 1 << 1
_CAP_SCROLL = 1 << 4
_CAP_BUTTON = 1 << 5

_EVENT_DISCONNECT = 2
_EVENT_SEAT_ADDED = 3
_EVENT_DEVICE_REMOVED = 6
_EVENT_DEVICE_RESUMED = 8

_BTN_LEFT = 0x110
_BTN_RIGHT = 0x111
_BTN_MIDDLE = 0x112


class EisSender:
    """Small optional libei sender for portal-provided EIS file descriptors."""

    @staticmethod
    def available() -> bool:
        return bool(ctypes.util.find_library("ei"))

    def __init__(self, fd: int, *, timeout_s: float = 5.0) -> None:
        library_name = ctypes.util.find_library("ei")
        if not library_name:
            os.close(fd)
            raise GuiUnavailableError("Wayland EIS input requires libei")
        try:
            self._lib = ctypes.CDLL(library_name)
        except OSError as exc:
            os.close(fd)
            raise GuiUnavailableError("Wayland EIS input requires libei") from exc
        self._configure_api()
        self._ei = self._lib.ei_new_sender(None)
        self._devices: list[int] = []
        self._started: set[int] = set()
        self._sequence = 1
        if not self._ei:
            os.close(fd)
            raise GuiUnavailableError("Could not create a libei sender")
        self._lib.ei_configure_name(self._ei, b"local-shell-mcp")
        rc = int(self._lib.ei_setup_backend_fd(self._ei, int(fd)))
        if rc < 0:
            self._lib.ei_unref(self._ei)
            self._ei = None
            os.close(fd)
            raise GuiUnavailableError(f"Could not connect to the EIS input backend ({rc})")
        try:
            self._discover_devices(timeout_s)
        except BaseException:
            self.close()
            raise

    def _configure_api(self) -> None:
        lib = self._lib
        pointer = ctypes.c_void_p

        def signature(name: str, args: list[Any], restype: Any = None) -> None:
            fn = getattr(lib, name)
            fn.argtypes = args
            fn.restype = restype

        signature("ei_new_sender", [pointer], pointer)
        signature("ei_configure_name", [pointer, ctypes.c_char_p])
        signature("ei_setup_backend_fd", [pointer, ctypes.c_int], ctypes.c_int)
        signature("ei_get_fd", [pointer], ctypes.c_int)
        signature("ei_dispatch", [pointer])
        signature("ei_get_event", [pointer], pointer)
        signature("ei_event_get_type", [pointer], ctypes.c_int)
        signature("ei_event_get_seat", [pointer], pointer)
        signature("ei_event_get_device", [pointer], pointer)
        signature("ei_seat_has_capability", [pointer, ctypes.c_int], ctypes.c_bool)
        signature("ei_event_unref", [pointer], pointer)
        signature("ei_device_ref", [pointer], pointer)
        signature("ei_device_unref", [pointer], pointer)
        signature("ei_device_has_capability", [pointer, ctypes.c_int], ctypes.c_bool)
        signature("ei_device_start_emulating", [pointer, ctypes.c_uint32])
        signature("ei_device_stop_emulating", [pointer])
        signature(
            "ei_device_pointer_motion",
            [pointer, ctypes.c_double, ctypes.c_double],
        )
        signature(
            "ei_device_pointer_motion_absolute",
            [pointer, ctypes.c_double, ctypes.c_double],
        )
        signature(
            "ei_device_button_button",
            [pointer, ctypes.c_uint32, ctypes.c_bool],
        )
        signature(
            "ei_device_scroll_delta",
            [pointer, ctypes.c_double, ctypes.c_double],
        )
        signature("ei_device_frame", [pointer, ctypes.c_uint64])
        signature("ei_now", [pointer], ctypes.c_uint64)
        signature("ei_disconnect", [pointer])
        signature("ei_unref", [pointer], pointer)
        # ei_seat_bind_capabilities() is variadic. Declare only its fixed
        # argument so ctypes applies the platform's normal C varargs ABI to the
        # capability enum arguments that follow.
        lib.ei_seat_bind_capabilities.argtypes = [pointer]
        lib.ei_seat_bind_capabilities.restype = None

    def _bind_seat_capabilities(self, seat: int) -> None:
        requested = (
            _CAP_POINTER,
            _CAP_POINTER_ABSOLUTE,
            _CAP_SCROLL,
            _CAP_BUTTON,
        )
        supported = [
            capability
            for capability in requested
            if bool(self._lib.ei_seat_has_capability(seat, capability))
        ]
        self._lib.ei_seat_bind_capabilities(
            seat,
            *[ctypes.c_int(capability) for capability in supported],
            ctypes.c_void_p(0),
        )

    def _handle_event(self, event: int) -> None:
        event_type = int(self._lib.ei_event_get_type(event))
        if event_type == _EVENT_DISCONNECT:
            raise GuiUnavailableError("EIS input session was disconnected")
        if event_type == _EVENT_SEAT_ADDED:
            seat = self._lib.ei_event_get_seat(event)
            self._bind_seat_capabilities(seat)
            return
        if event_type == _EVENT_DEVICE_RESUMED:
            device = self._lib.ei_event_get_device(event)
            if not any(
                bool(self._lib.ei_device_has_capability(device, capability))
                for capability in (
                    _CAP_POINTER,
                    _CAP_POINTER_ABSOLUTE,
                    _CAP_SCROLL,
                    _CAP_BUTTON,
                )
            ):
                return
            device_id = int(device or 0)
            if device_id in self._devices:
                ref = device_id
            else:
                ref = int(self._lib.ei_device_ref(device))
                self._devices.append(ref)
            if ref not in self._started:
                self._lib.ei_device_start_emulating(ref, self._sequence)
                self._sequence = (self._sequence + 1) & 0xFFFFFFFF or 1
                self._started.add(ref)
            return
        if event_type == _EVENT_DEVICE_REMOVED:
            device = int(self._lib.ei_event_get_device(event) or 0)
            if device in self._devices:
                self._devices.remove(device)
                self._started.discard(device)
                self._lib.ei_device_unref(device)

    def _dispatch_events(self, timeout_s: float = 0.0) -> bool:
        assert self._ei
        fd = int(self._lib.ei_get_fd(self._ei))
        readable, _, _ = select.select([fd], [], [], max(0.0, timeout_s))
        if not readable:
            return False
        self._lib.ei_dispatch(self._ei)
        while True:
            event = self._lib.ei_get_event(self._ei)
            if not event:
                break
            try:
                self._handle_event(int(event))
            finally:
                self._lib.ei_event_unref(event)
        return True

    def _discover_devices(self, timeout_s: float) -> None:
        assert self._ei
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            wait_s = max(0.0, deadline - time.monotonic())
            self._dispatch_events(wait_s)
            if self._device_for(_CAP_POINTER_ABSOLUTE, optional=True, drain=False):
                return
        raise GuiUnavailableError("EIS did not provide an absolute pointer device")

    def _device_for(
        self,
        capability: int,
        *,
        optional: bool = False,
        drain: bool = True,
    ) -> int | None:
        if drain:
            self._dispatch_events(0.0)
        for device in self._devices:
            if self._lib.ei_device_has_capability(device, capability):
                return device
        if optional:
            return None
        raise GuiUnavailableError("EIS device does not support the requested pointer action")

    def _begin(self, device: int) -> None:
        if device not in self._started:
            self._lib.ei_device_start_emulating(device, self._sequence)
            self._sequence = (self._sequence + 1) & 0xFFFFFFFF or 1
            self._started.add(device)

    def _frame(self, device: int) -> None:
        assert self._ei
        self._lib.ei_device_frame(device, self._lib.ei_now(self._ei))

    def nudge(self, dx: float, dy: float) -> None:
        device = self._device_for(_CAP_POINTER)
        assert device is not None
        self._begin(device)
        self._lib.ei_device_pointer_motion(device, float(dx), float(dy))
        self._frame(device)
        time.sleep(0.03)
        self._lib.ei_device_pointer_motion(device, -float(dx), -float(dy))
        self._frame(device)

    def move(self, x: float, y: float) -> None:
        device = self._device_for(_CAP_POINTER_ABSOLUTE)
        assert device is not None
        self._begin(device)
        self._lib.ei_device_pointer_motion_absolute(device, float(x), float(y))
        self._frame(device)

    def button(self, button: int, pressed: bool) -> None:
        device = self._device_for(_CAP_BUTTON)
        assert device is not None
        codes = {1: _BTN_LEFT, 2: _BTN_MIDDLE, 3: _BTN_RIGHT}
        try:
            code = codes[int(button)]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Unsupported pointer button: {button}") from exc
        self._begin(device)
        self._lib.ei_device_button_button(device, code, bool(pressed))
        self._frame(device)

    def click(self, x: float, y: float, *, button: int, count: int) -> None:
        self.move(x, y)
        for _ in range(max(1, int(count))):
            self.button(button, True)
            time.sleep(0.015)
            self.button(button, False)
            time.sleep(0.035)

    def scroll(self, x: float, y: float, delta_x: float, delta_y: float) -> None:
        self.move(x, y)
        device = self._device_for(_CAP_SCROLL)
        assert device is not None
        self._begin(device)
        self._lib.ei_device_scroll_delta(device, float(delta_x), float(delta_y))
        self._frame(device)

    def drag(self, x: float, y: float, to_x: float, to_y: float) -> None:
        self.move(x, y)
        self.button(1, True)
        try:
            time.sleep(0.02)
            self.move(to_x, to_y)
            time.sleep(0.02)
        finally:
            self.button(1, False)

    def close(self) -> None:
        if self._ei is None:
            return
        for device in list(self._devices):
            if device in self._started:
                with contextlib.suppress(Exception):
                    self._lib.ei_device_stop_emulating(device)
            with contextlib.suppress(Exception):
                self._lib.ei_device_unref(device)
        self._devices.clear()
        self._started.clear()
        with contextlib.suppress(Exception):
            self._lib.ei_disconnect(self._ei)
        self._lib.ei_unref(self._ei)
        self._ei = None
