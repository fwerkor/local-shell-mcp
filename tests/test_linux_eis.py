from __future__ import annotations

from types import SimpleNamespace

import pytest

from local_shell_mcp.gui import linux_eis
from local_shell_mcp.gui.base import GuiUnavailableError


class _Fn:
    def __init__(self, result=None):
        self.result = result
        self.calls = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        self.calls.append(args)
        return self.result


def _signature_library():
    names = (
        "ei_new_sender",
        "ei_configure_name",
        "ei_setup_backend_fd",
        "ei_get_fd",
        "ei_dispatch",
        "ei_get_event",
        "ei_event_get_type",
        "ei_event_get_seat",
        "ei_event_get_device",
        "ei_seat_has_capability",
        "ei_event_unref",
        "ei_device_ref",
        "ei_device_unref",
        "ei_device_has_capability",
        "ei_device_start_emulating",
        "ei_device_stop_emulating",
        "ei_device_pointer_motion",
        "ei_device_pointer_motion_absolute",
        "ei_device_button_button",
        "ei_device_scroll_delta",
        "ei_device_frame",
        "ei_now",
        "ei_disconnect",
        "ei_unref",
        "ei_seat_bind_capabilities",
    )
    return SimpleNamespace(**{name: _Fn() for name in names})


def test_eis_configures_ctypes_api_signatures():
    sender = object.__new__(linux_eis.EisSender)
    sender._lib = _signature_library()

    sender._configure_api()

    assert sender._lib.ei_new_sender.argtypes is not None
    assert sender._lib.ei_setup_backend_fd.restype is not None
    assert sender._lib.ei_seat_bind_capabilities.argtypes is not None


def test_eis_init_available_and_backend_failure(monkeypatch):
    lib = _signature_library()
    lib.ei_new_sender.result = 101
    lib.ei_setup_backend_fd.result = 0

    monkeypatch.setattr(linux_eis.ctypes.util, "find_library", lambda _name: "libei.so")
    monkeypatch.setattr(linux_eis.ctypes, "CDLL", lambda _name: lib)
    monkeypatch.setattr(linux_eis.EisSender, "_configure_api", lambda self: None)
    monkeypatch.setattr(linux_eis.EisSender, "_discover_devices", lambda self, timeout: None)

    sender = linux_eis.EisSender(9)
    assert linux_eis.EisSender.available() is True
    assert sender._ei == 101
    assert sender._devices == []
    assert sender._sequence == 1

    closed = []
    monkeypatch.setattr(linux_eis.os, "close", closed.append)
    lib.ei_setup_backend_fd.result = -5
    with pytest.raises(GuiUnavailableError, match="Could not connect"):
        linux_eis.EisSender(10)
    assert closed == [10]

    monkeypatch.setattr(linux_eis.ctypes.util, "find_library", lambda _name: None)
    assert linux_eis.EisSender.available() is False
    with pytest.raises(GuiUnavailableError, match="requires libei"):
        linux_eis.EisSender(11)
    assert closed[-1] == 11


class _GestureLib:
    def __init__(self):
        self.calls = []

    def ei_device_has_capability(self, _device, _capability):
        return True

    def ei_device_start_emulating(self, device, sequence):
        self.calls.append(("start", device, sequence))

    def ei_device_stop_emulating(self, device):
        self.calls.append(("stop", device))

    def ei_device_pointer_motion(self, device, dx, dy):
        self.calls.append(("nudge", device, dx, dy))

    def ei_device_pointer_motion_absolute(self, device, x, y):
        self.calls.append(("move", device, x, y))

    def ei_device_button_button(self, device, code, pressed):
        self.calls.append(("button", device, code, pressed))

    def ei_device_scroll_delta(self, device, dx, dy):
        self.calls.append(("scroll", device, dx, dy))

    def ei_now(self, _ei):
        return 123

    def ei_device_frame(self, device, timestamp):
        self.calls.append(("frame", device, timestamp))

    def ei_device_unref(self, device):
        self.calls.append(("unref", device))

    def ei_disconnect(self, ei):
        self.calls.append(("disconnect", ei))

    def ei_unref(self, ei):
        self.calls.append(("ei_unref", ei))


def test_eis_gestures_drain_lifecycle_and_close(monkeypatch):
    sender = object.__new__(linux_eis.EisSender)
    sender._lib = _GestureLib()
    sender._ei = 77
    sender._devices = [55]
    sender._started = set()
    sender._sequence = 1
    monkeypatch.setattr(sender, "_dispatch_events", lambda _timeout=0.0: False)
    monkeypatch.setattr(linux_eis.time, "sleep", lambda _seconds: None)

    sender.nudge(1, -2)
    sender.move(10, 20)
    sender.button(1, True)
    sender.button(1, False)
    sender.click(1, 2, button=3, count=2)
    sender.scroll(3, 4, 5, -6)
    sender.drag(7, 8, 9, 10)

    with pytest.raises(ValueError, match="Unsupported pointer button"):
        sender.button(9, True)

    assert ("start", 55, 1) in sender._lib.calls
    assert ("nudge", 55, 1.0, -2.0) in sender._lib.calls
    assert ("nudge", 55, -1.0, 2.0) in sender._lib.calls
    assert ("move", 55, 10.0, 20.0) in sender._lib.calls
    assert any(call[0] == "scroll" for call in sender._lib.calls)

    sender.close()
    assert sender._ei is None
    assert sender._devices == []
    assert sender._started == set()
    assert ("disconnect", 77) in sender._lib.calls

    sender.close()


class _EventLib:
    def __init__(self):
        self.events = []
        self.types = {}
        self.device_for_event = {}
        self.calls = []

    def ei_get_fd(self, _ei):
        return 7

    def ei_dispatch(self, ei):
        self.calls.append(("dispatch", ei))

    def ei_get_event(self, _ei):
        return self.events.pop(0) if self.events else 0

    def ei_event_get_type(self, event):
        return self.types[event]

    def ei_event_get_seat(self, event):
        return 88 + event

    def ei_event_get_device(self, event):
        return self.device_for_event.get(event, 0)

    def ei_seat_has_capability(self, _seat, capability):
        return capability in {
            linux_eis._CAP_POINTER_ABSOLUTE,
            linux_eis._CAP_BUTTON,
        }

    def ei_seat_bind_capabilities(self, *args):
        self.calls.append(("bind", args))

    def ei_device_has_capability(self, _device, capability):
        return capability == linux_eis._CAP_POINTER_ABSOLUTE

    def ei_device_ref(self, device):
        self.calls.append(("ref", device))
        return device

    def ei_device_start_emulating(self, device, sequence):
        self.calls.append(("start", device, sequence))

    def ei_device_unref(self, device):
        self.calls.append(("unref", device))

    def ei_event_unref(self, event):
        self.calls.append(("event_unref", event))


def test_eis_dispatch_handles_device_lifecycle_and_disconnect(monkeypatch):
    sender = object.__new__(linux_eis.EisSender)
    sender._lib = _EventLib()
    sender._ei = 99
    sender._devices = []
    sender._started = set()
    sender._sequence = 1

    monkeypatch.setattr(
        linux_eis.select,
        "select",
        lambda *_args, **_kwargs: ([7], [], []),
    )

    sender._lib.events = [1, 2, 3]
    sender._lib.types = {
        1: linux_eis._EVENT_SEAT_ADDED,
        2: linux_eis._EVENT_DEVICE_RESUMED,
        3: linux_eis._EVENT_DEVICE_REMOVED,
    }
    sender._lib.device_for_event = {2: 55, 3: 55}

    assert sender._dispatch_events(0.25) is True
    assert sender._devices == []
    assert ("start", 55, 1) in sender._lib.calls
    assert ("unref", 55) in sender._lib.calls

    sender._lib.events = [4]
    sender._lib.types[4] = linux_eis._EVENT_DISCONNECT
    with pytest.raises(GuiUnavailableError, match="disconnected"):
        sender._dispatch_events()


def test_eis_discovery_success_timeout_and_missing_capability(monkeypatch):
    sender = object.__new__(linux_eis.EisSender)
    sender._lib = _EventLib()
    sender._ei = 1
    sender._devices = []
    sender._started = set()
    sender._sequence = 1

    def dispatch(_timeout=0.0):
        sender._devices[:] = [22]
        return True

    monkeypatch.setattr(sender, "_dispatch_events", dispatch)
    sender._discover_devices(0.1)

    sender._devices = []
    monkeypatch.setattr(sender, "_dispatch_events", lambda _timeout=0.0: False)
    with pytest.raises(GuiUnavailableError, match="absolute pointer"):
        sender._discover_devices(0.0)

    with pytest.raises(GuiUnavailableError, match="requested pointer action"):
        sender._device_for(linux_eis._CAP_SCROLL, drain=False)
    assert sender._device_for(linux_eis._CAP_SCROLL, optional=True, drain=False) is None


def test_eis_init_library_sender_and_discovery_failures_cleanup(monkeypatch):
    closed = []
    monkeypatch.setattr(linux_eis.os, "close", closed.append)
    monkeypatch.setattr(linux_eis.ctypes.util, "find_library", lambda _name: "libei.so")

    def broken_cdll(_name):
        raise OSError("load failed")

    monkeypatch.setattr(linux_eis.ctypes, "CDLL", broken_cdll)
    with pytest.raises(GuiUnavailableError, match="requires libei"):
        linux_eis.EisSender(21)
    assert closed == [21]

    lib = _signature_library()
    monkeypatch.setattr(linux_eis.ctypes, "CDLL", lambda _name: lib)
    monkeypatch.setattr(linux_eis.EisSender, "_configure_api", lambda self: None)
    lib.ei_new_sender.result = 0
    with pytest.raises(GuiUnavailableError, match="Could not create"):
        linux_eis.EisSender(22)
    assert closed[-1] == 22

    lib.ei_new_sender.result = 101
    lib.ei_setup_backend_fd.result = 0

    def fail_discovery(_self, _timeout):
        raise GuiUnavailableError("discovery failed")

    monkeypatch.setattr(linux_eis.EisSender, "_discover_devices", fail_discovery)
    with pytest.raises(GuiUnavailableError, match="discovery failed"):
        linux_eis.EisSender(23)
    assert lib.ei_disconnect.calls[-1] == (101,)
    assert lib.ei_unref.calls[-1] == (101,)


def test_eis_lifecycle_ignores_unsupported_duplicate_and_unknown_events(monkeypatch):
    sender = object.__new__(linux_eis.EisSender)
    sender._lib = _EventLib()
    sender._ei = 99
    sender._devices = []
    sender._started = set()
    sender._sequence = 1

    sender._lib.types = {
        1: linux_eis._EVENT_DEVICE_RESUMED,
        2: linux_eis._EVENT_DEVICE_RESUMED,
        3: linux_eis._EVENT_DEVICE_REMOVED,
    }
    sender._lib.device_for_event = {1: 55, 2: 55, 3: 999}

    sender._lib.ei_device_has_capability = lambda _device, _capability: False
    sender._handle_event(1)
    assert sender._devices == []

    sender._lib.ei_device_has_capability = (
        lambda _device, capability: capability == linux_eis._CAP_POINTER_ABSOLUTE
    )
    sender._handle_event(2)
    sender._handle_event(2)
    assert sender._devices == [55]
    assert sender._started == {55}
    assert sender._lib.calls.count(("ref", 55)) == 1
    assert sender._lib.calls.count(("start", 55, 1)) == 1

    sender._handle_event(3)
    assert sender._devices == [55]

    monkeypatch.setattr(
        linux_eis.select,
        "select",
        lambda *_args, **_kwargs: ([], [], []),
    )
    assert sender._dispatch_events(0.0) is False


def test_eis_close_handles_started_and_unstarted_devices():
    sender = object.__new__(linux_eis.EisSender)
    sender._lib = _GestureLib()
    sender._ei = 77
    sender._devices = [55, 66]
    sender._started = {55}
    sender._sequence = 1

    sender.close()

    assert ("stop", 55) in sender._lib.calls
    assert ("stop", 66) not in sender._lib.calls
    assert ("unref", 55) in sender._lib.calls
    assert ("unref", 66) in sender._lib.calls
    assert sender._devices == []
    assert sender._started == set()
    assert sender._ei is None
