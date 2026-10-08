from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest
from PIL import Image

from local_shell_mcp.gui.base import (
    GuiSnapshot,
    GuiStaleStateError,
    GuiUnavailableError,
)
from local_shell_mcp.gui.macos import (
    MacOSGuiBackend,
)
from local_shell_mcp.gui.windows import WindowsGuiBackend


def test_windows_window_record_excludes_offscreen_windows(monkeypatch):
    import local_shell_mcp.gui.windows as windows

    class Rect:
        left = 10
        top = 20
        right = 210
        bottom = 120

    class Control:
        NativeWindowHandle = 123
        BoundingRectangle = Rect()
        IsOffscreen = True

    monkeypatch.setattr(windows, "_is_iconic_window", lambda _handle: False)
    assert windows._window_record(Control()) is None

def test_windows_window_record_excludes_minimized_windows(monkeypatch):
    import local_shell_mcp.gui.windows as windows

    class Rect:
        left = -32000
        top = -32000
        right = -31800
        bottom = -31900

    class Control:
        NativeWindowHandle = 456
        BoundingRectangle = Rect()
        IsOffscreen = False

    monkeypatch.setattr(windows, "_is_iconic_window", lambda handle: handle == 456)
    assert windows._window_record(Control()) is None

def test_windows_capture_rejects_oversized_rect_before_gdi_allocation(tmp_path, monkeypatch):
    import local_shell_mcp.gui.windows as windows

    class Fn:
        def __init__(self, callback):
            self.callback = callback
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            return self.callback(*args)

    def get_window_rect(_hwnd, rect_ptr):
        rect = windows.ctypes.cast(rect_ptr, windows.ctypes.POINTER(windows._WinRect)).contents
        rect.left = 0
        rect.top = 0
        rect.right = windows.GUI_MAX_CAPTURE_DIMENSION + 1
        rect.bottom = 10
        return 1

    class User32:
        GetWindowRect = Fn(get_window_rect)
        IsIconic = Fn(lambda _hwnd: 0)
        GetWindowDC = Fn(
            lambda _hwnd: pytest.fail("GetWindowDC must not run for oversized windows")
        )
        ReleaseDC = Fn(lambda *_args: 1)
        PrintWindow = Fn(lambda *_args: 1)

    class GDI32:
        CreateCompatibleDC = Fn(lambda *_args: 1)
        CreateCompatibleBitmap = Fn(lambda *_args: 1)
        SelectObject = Fn(lambda *_args: 1)
        GetDIBits = Fn(lambda *_args: 1)
        DeleteObject = Fn(lambda *_args: 1)
        DeleteDC = Fn(lambda *_args: 1)

    monkeypatch.setattr(
        windows.ctypes,
        "windll",
        SimpleNamespace(user32=User32(), gdi32=GDI32()),
        raising=False,
    )
    with pytest.raises(GuiUnavailableError, match="safe budget"):
        windows._capture_window_image_native(123, tmp_path / "oversized.png")

def test_windows_capture_unselects_bitmap_before_getdibits(tmp_path, monkeypatch):
    import local_shell_mcp.gui.windows as windows

    class Fn:
        def __init__(self, callback):
            self.callback = callback
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            return self.callback(*args)

    restored = False
    select_calls = 0

    def get_window_rect(_hwnd, rect_ptr):
        rect = windows.ctypes.cast(rect_ptr, windows.ctypes.POINTER(windows._WinRect)).contents
        rect.left = 0
        rect.top = 0
        rect.right = 2
        rect.bottom = 2
        return 1

    def select_object(_dc, obj):
        nonlocal restored, select_calls
        select_calls += 1
        if select_calls == 1:
            return 99
        assert obj == 99
        restored = True
        return 3

    def get_dibits(*_args):
        assert restored is True
        return 2

    class User32:
        GetWindowRect = Fn(get_window_rect)
        IsIconic = Fn(lambda _hwnd: 0)
        GetWindowDC = Fn(lambda _hwnd: 1)
        ReleaseDC = Fn(lambda *_args: 1)
        PrintWindow = Fn(lambda *_args: 1)

    class GDI32:
        CreateCompatibleDC = Fn(lambda *_args: 2)
        CreateCompatibleBitmap = Fn(lambda *_args: 3)
        SelectObject = Fn(select_object)
        GetDIBits = Fn(get_dibits)
        DeleteObject = Fn(lambda *_args: 1)
        DeleteDC = Fn(lambda *_args: 1)

    monkeypatch.setattr(
        windows.ctypes,
        "windll",
        SimpleNamespace(user32=User32(), gdi32=GDI32()),
        raising=False,
    )

    destination = tmp_path / "capture.png"
    windows._capture_window_image_native(123, destination)

    assert restored is True
    assert select_calls == 2
    assert destination.is_file()

def test_windows_capture_helper_times_out_and_removes_partial_output(tmp_path, monkeypatch):
    import local_shell_mcp.gui.windows as windows

    destination = tmp_path / "window.png"
    destination.write_bytes(b"partial")

    def run(argv, **kwargs):
        raise windows.subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(windows.subprocess, "run", run)

    with pytest.raises(GuiUnavailableError, match="exceeded"):
        windows._capture_window_image(123, destination)
    assert not destination.exists()

def test_windows_snapshot_uses_hwnd_capture_not_visible_rectangle(tmp_path, monkeypatch):
    import local_shell_mcp.gui.windows as windows

    class Window:
        NativeWindowHandle = 123

        def GetChildren(self):
            return []

        def CaptureToImage(self, *_args, **_kwargs):
            pytest.fail("UIA rectangle capture must not be used")

    backend = WindowsGuiBackend()
    window = Window()
    monkeypatch.setattr(
        backend,
        "_find_window",
        lambda _window_id, _observed_window=None: window,
    )
    monkeypatch.setattr(
        windows,
        "_window_record",
        lambda _control: {
            "id": "hwnd:123:fingerprint",
            "title": "Window",
            "app": "App",
            "pid": 1,
            "bounds": {"x": 10, "y": 20, "width": 100, "height": 80},
        },
    )
    captures = []

    def capture(hwnd, destination):
        captures.append((hwnd, destination))
        Image.new("RGB", (100, 80), (1, 2, 3)).save(destination, format="PNG")

    monkeypatch.setattr(windows, "_capture_window_image", capture)
    path = tmp_path / "window.png"
    snapshot = backend._snapshot_sync(
        "hwnd:123:fingerprint",
        screenshot_path=path,
        include_elements=False,
        max_elements=1,
        max_depth=1,
    )
    assert captures == [(123, path)]
    assert snapshot.screenshot_path is not None
    assert path.is_file()

def test_windows_snapshot_revalidates_native_identity_after_capture(tmp_path, monkeypatch):
    import local_shell_mcp.gui.windows as windows

    class Rect:
        left = 0
        top = 0
        right = 100
        bottom = 80

    class Control:
        NativeWindowHandle = 123
        ProcessId = 1
        ClassName = "Editor"
        AutomationId = "main"
        Name = "Window"
        BoundingRectangle = Rect()
        IsOffscreen = False

        def GetRuntimeId(self):
            return [1, 2, 3]

        def GetChildren(self):
            return []

        def GetNextSiblingControl(self):
            return None

    original = Control()
    replacement = Control()
    monkeypatch.setattr(windows, "_is_iconic_window", lambda _handle: False)

    class Root:
        def GetFirstChildControl(self):
            return replacement

        def GetChildren(self):
            raise AssertionError("window lookup must stay lazy")

    class Auto:
        @staticmethod
        def GetRootControl():
            return Root()

        @staticmethod
        def ControlsAreSame(left, right):
            return left is right

    monkeypatch.setattr(windows, "_automation", lambda: Auto())
    backend = WindowsGuiBackend()
    monkeypatch.setattr(
        backend,
        "_find_window",
        lambda _window_id, _observed_window=None: (
            original
            if _observed_window is None
            else WindowsGuiBackend._find_window(
                backend,
                _window_id,
                _observed_window,
            )
        ),
    )

    def capture(_hwnd, destination):
        Image.new("RGB", (100, 80)).save(destination, format="PNG")

    monkeypatch.setattr(windows, "_capture_window_image", capture)
    path = tmp_path / "reused-hwnd.png"
    with pytest.raises(LookupError, match="UIA identity changed"):
        backend._snapshot_sync(
            windows._window_record(original)["id"],
            screenshot_path=path,
            include_elements=False,
            max_elements=1,
            max_depth=1,
        )

def test_windows_traversal_stops_before_querying_children_at_budget(monkeypatch):
    import local_shell_mcp.gui.windows as windows

    class Root:
        def GetChildren(self):
            pytest.fail("GetChildren must not run after max_elements is reached")

    root = Root()
    backend = WindowsGuiBackend()
    monkeypatch.setattr(backend, "_find_window", lambda _window_id, _observed_window=None: root)
    monkeypatch.setattr(
        windows,
        "_window_record",
        lambda _control: {
            "id": "hwnd:1:fingerprint",
            "title": "Window",
            "app": "App",
            "pid": 1,
            "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
        },
    )

    snapshot = backend._snapshot_sync(
        "hwnd:1:fingerprint",
        screenshot_path=None,
        include_elements=True,
        max_elements=1,
        max_depth=12,
    )
    assert len(snapshot.elements) == 1

def test_windows_uia_traversal_bounds_provider_strings_and_total_bytes(monkeypatch):
    import local_shell_mcp.gui.windows as windows

    huge = "x" * (windows.GUI_MAX_ELEMENT_TEXT_BYTES * 8)

    class Rect:
        left = 0
        top = 0
        right = 100
        bottom = 20

    class Control:
        ControlTypeName = huge
        Name = huge
        AutomationId = huge
        BoundingRectangle = Rect()
        IsEnabled = True
        IsOffscreen = False
        ProcessId = 1
        ClassName = huge

        def __init__(self, children=None, runtime_id=1):
            self.children = list(children or [])
            self.runtime_id = runtime_id
            for left, right in zip(self.children, self.children[1:], strict=False):
                left.next = right
            if self.children:
                self.children[-1].next = None
            self.next = None

        def GetChildren(self):
            pytest.fail("descendant traversal must stay lazy")

        def GetFirstChildControl(self):
            return self.children[0] if self.children else None

        def GetNextSiblingControl(self):
            return self.next

        def GetRuntimeId(self):
            return [self.runtime_id]

    children = [Control(runtime_id=index + 2) for index in range(200)]
    root = Control(children=children)
    backend = WindowsGuiBackend()
    monkeypatch.setattr(backend, "_find_window", lambda _window_id, _observed_window=None: root)
    monkeypatch.setattr(
        windows,
        "_window_record",
        lambda _control: {
            "id": "hwnd:1:fingerprint",
            "title": "Window",
            "app": "App",
            "pid": 1,
            "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
        },
    )

    snapshot = backend._snapshot_sync(
        "hwnd:1:fingerprint",
        screenshot_path=None,
        include_elements=True,
        max_elements=1000,
        max_depth=2,
    )

    assert snapshot.elements
    assert len(json.dumps(snapshot.elements, ensure_ascii=False).encode()) <= (
        windows.GUI_MAX_ELEMENTS_TOTAL_BYTES
    )
    assert len(snapshot.locators) == len(snapshot.elements)
    for element in snapshot.elements:
        assert len(element["role"].encode()) <= windows.GUI_MAX_ELEMENT_TEXT_BYTES
        assert len(element["name"].encode()) <= windows.GUI_MAX_ELEMENT_TEXT_BYTES
        assert len(element["automation_id"].encode()) <= windows.GUI_MAX_ELEMENT_TEXT_BYTES

def test_windows_window_listing_bounds_provider_metadata_during_enumeration(
    monkeypatch,
):
    import local_shell_mcp.gui.windows as windows

    huge = "x" * (windows.GUI_MAX_WINDOW_TEXT_BYTES * 8)

    class Rect:
        left = 0
        top = 0
        right = 100
        bottom = 100

    class Control:
        BoundingRectangle = Rect()
        IsOffscreen = False
        ProcessId = 1
        AutomationId = "window"

        def __init__(self, handle):
            self.NativeWindowHandle = handle
            self.Name = huge
            self.ClassName = huge
            self.next = None

        def GetRuntimeId(self):
            return [self.NativeWindowHandle]

        def GetNextSiblingControl(self):
            return self.next

    controls = [Control(index + 1) for index in range(300)]
    for left, right in zip(controls, controls[1:], strict=False):
        left.next = right

    class Root:
        def GetFirstChildControl(self):
            return controls[0]

        def GetChildren(self):
            pytest.fail("window enumeration must stay lazy")

    class Auto:
        @staticmethod
        def GetRootControl():
            return Root()

    monkeypatch.setattr(windows, "_automation", lambda: Auto())
    monkeypatch.setattr(windows, "_is_iconic_window", lambda _handle: False)

    listed = WindowsGuiBackend()._list_windows_sync()["windows"]

    assert listed
    assert len(listed) <= windows.GUI_MAX_WINDOWS
    assert len(listed) < len(controls)
    public = [
        {key: value for key, value in item.items() if not key.startswith("_")} for item in listed
    ]
    assert len(json.dumps(public, ensure_ascii=False).encode()) <= (
        windows.GUI_MAX_WINDOWS_TOTAL_BYTES
    )
    assert all(
        len(item["title"].encode()) <= windows.GUI_MAX_WINDOW_TEXT_BYTES
        and len(item["app"].encode()) <= windows.GUI_MAX_WINDOW_TEXT_BYTES
        for item in listed
    )

def test_windows_semantic_action_rejects_recycled_uia_element(monkeypatch):
    import local_shell_mcp.gui.windows as windows

    class Rect:
        left = 10
        top = 10
        right = 40
        bottom = 30

    class Child:
        ControlTypeName = "Button"
        AutomationId = "save"
        BoundingRectangle = Rect()
        IsEnabled = True
        IsOffscreen = False
        ProcessId = 1
        ClassName = "Button"

        def __init__(self):
            self.Name = "Save"

        def GetRuntimeId(self):
            return [7, 8, 9]

        def GetChildren(self):
            pytest.fail("descendant traversal must stay lazy")

        def GetFirstChildControl(self):
            return None

        def GetNextSiblingControl(self):
            return None

        def GetInvokePattern(self):
            pytest.fail("recycled UIA element must be rejected before Invoke")

    class Root(Child):
        NativeWindowHandle = 1
        AutomationId = "root"
        ClassName = "Window"

        def __init__(self, child):
            super().__init__()
            self.Name = "Window"
            self.child = child

        def GetRuntimeId(self):
            return [1]

        def GetChildren(self):
            pytest.fail("descendant traversal must stay lazy")

        def GetFirstChildControl(self):
            return self.child

    child = Child()
    root = Root(child)
    backend = WindowsGuiBackend()
    record = {
        "id": "hwnd:1:fingerprint",
        "title": "Window",
        "app": "App",
        "pid": 1,
        "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
    }
    monkeypatch.setattr(backend, "_find_window", lambda _window_id, _observed_window=None: root)
    monkeypatch.setattr(windows, "_window_record", lambda _control: record)
    monkeypatch.setattr(windows, "_automation", lambda: SimpleNamespace())

    snapshot = backend._snapshot_sync(
        record["id"],
        screenshot_path=None,
        include_elements=True,
        max_elements=10,
        max_depth=2,
    )
    child_id = next(item["id"] for item in snapshot.elements if item["automation_id"] == "save")
    locator = snapshot.locators[child_id]
    child.Name = "Delete"

    with pytest.raises(LookupError, match="changed since observation"):
        backend._perform_action_sync(
            record,
            locator,
            {"type": "click"},
        )

def test_windows_semantic_action_rejects_identical_replacement_uia_element(monkeypatch):
    import local_shell_mcp.gui.windows as windows

    class Rect:
        left = 10
        top = 10
        right = 40
        bottom = 30

    class Child:
        ControlTypeName = "Button"
        AutomationId = "save"
        BoundingRectangle = Rect()
        IsEnabled = True
        IsOffscreen = False
        ProcessId = 1
        ClassName = "Button"
        Name = "Save"

        def GetRuntimeId(self):
            return [7, 8, 9]

        def GetChildren(self):
            pytest.fail("descendant traversal must stay lazy")

        def GetFirstChildControl(self):
            return None

        def GetNextSiblingControl(self):
            return None

        def GetInvokePattern(self):
            pytest.fail("replacement UIA element must be rejected before Invoke")

    class Root(Child):
        NativeWindowHandle = 1
        AutomationId = "root"
        ClassName = "Window"
        Name = "Window"

        def __init__(self, child):
            self.child = child

        def GetRuntimeId(self):
            return [1]

        def GetChildren(self):
            pytest.fail("descendant traversal must stay lazy")

        def GetFirstChildControl(self):
            return self.child

    observed_child = Child()
    replacement_child = Child()
    root = Root(observed_child)
    backend = WindowsGuiBackend()
    record = {
        "id": "hwnd:1:fingerprint",
        "title": "Window",
        "app": "App",
        "pid": 1,
        "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
    }
    monkeypatch.setattr(backend, "_find_window", lambda _window_id, _observed_window=None: root)
    monkeypatch.setattr(windows, "_window_record", lambda _control: record)

    class Auto:
        @staticmethod
        def ControlsAreSame(left, right):
            return left is right

    monkeypatch.setattr(windows, "_automation", lambda: Auto())

    snapshot = backend._snapshot_sync(
        record["id"],
        screenshot_path=None,
        include_elements=True,
        max_elements=10,
        max_depth=2,
    )
    child_id = next(item["id"] for item in snapshot.elements if item["automation_id"] == "save")
    locator = snapshot.locators[child_id]
    root.child = replacement_child

    with pytest.raises(LookupError, match="identity changed since observation"):
        backend._perform_action_sync(
            record,
            locator,
            {"type": "click"},
        )

def test_windows_control_mouse_fallback_focuses_verified_window(monkeypatch):
    import local_shell_mcp.gui.windows as windows

    calls = []

    class Rect:
        left = 2
        top = 2
        right = 8
        bottom = 8

    class Locator:
        BoundingRectangle = Rect()

        def GetInvokePattern(self):
            return None

        def Click(self, waitTime=0):
            calls.append(("click", waitTime))

    class Target:
        def SetFocus(self):
            calls.append(("focus",))

    backend = WindowsGuiBackend()
    monkeypatch.setattr(windows, "_automation", lambda: SimpleNamespace())
    monkeypatch.setattr(
        windows,
        "_native_window_bounds",
        lambda _hwnd: {"x": 0, "y": 0, "width": 10, "height": 10},
    )
    monkeypatch.setattr(backend, "_find_window", lambda _window_id, _observed_window=None: Target())
    locator = Locator()
    monkeypatch.setattr(
        backend,
        "_resolve_element_locator",
        lambda _window_id, _locator, _observed_window=None: locator,
    )
    result = backend._perform_action_sync(
        {"id": "hwnd:1:fingerprint", "bounds": {"x": 0, "y": 0, "width": 10, "height": 10}},
        {"path": [0], "fingerprint": "observed"},
        {"type": "click", "_focus_prepared": True},
    )
    assert result == {"semantic": True, "method": "control"}
    assert calls == [("focus",), ("click", 0)]

@pytest.mark.parametrize("kind", ["click", "double_click", "right_click"])
def test_windows_control_mouse_fallback_rejects_element_outside_window(
    monkeypatch,
    kind,
):
    import local_shell_mcp.gui.windows as windows

    class Rect:
        left = 100
        top = 100
        right = 120
        bottom = 120

    class Locator:
        BoundingRectangle = Rect()

        def GetInvokePattern(self):
            return None

        def Click(self, **_kwargs):
            pytest.fail("out-of-window control click must not be synthesized")

        def DoubleClick(self, **_kwargs):
            pytest.fail("out-of-window control double-click must not be synthesized")

        def RightClick(self, **_kwargs):
            pytest.fail("out-of-window control right-click must not be synthesized")

    class Target:
        def SetFocus(self):
            return None

    backend = WindowsGuiBackend()
    monkeypatch.setattr(windows, "_automation", lambda: SimpleNamespace())
    monkeypatch.setattr(
        windows,
        "_native_window_bounds",
        lambda _hwnd: {"x": 0, "y": 0, "width": 50, "height": 50},
    )
    monkeypatch.setattr(
        backend,
        "_find_window",
        lambda _window_id, _observed_window=None: Target(),
    )
    locator = Locator()
    monkeypatch.setattr(
        backend,
        "_resolve_element_locator",
        lambda _window_id, _locator, _observed_window=None: locator,
    )

    with pytest.raises(ValueError, match="outside the selected window"):
        backend._perform_action_sync(
            {
                "id": "hwnd:1:fingerprint",
                "bounds": {"x": 0, "y": 0, "width": 50, "height": 50},
            },
            {"path": [0], "fingerprint": "observed"},
            {"type": kind},
        )

def test_windows_pointer_rejects_native_bounds_change_after_focus(monkeypatch):
    import local_shell_mcp.gui.windows as windows

    pointer_calls = []

    class Target:
        def SetFocus(self):
            return None

    class Auto:
        @staticmethod
        def Click(*_args, **_kwargs):
            pointer_calls.append("click")

    backend = WindowsGuiBackend()
    monkeypatch.setattr(windows, "_automation", lambda: Auto())
    monkeypatch.setattr(
        backend,
        "_find_window",
        lambda _window_id, _observed_window=None: Target(),
    )
    monkeypatch.setattr(
        windows,
        "_native_window_bounds",
        lambda _hwnd: {"x": 10, "y": 0, "width": 100, "height": 100},
    )

    with pytest.raises(LookupError, match="moved or resized immediately before pointer"):
        backend._perform_action_sync(
            {
                "id": "hwnd:1:fingerprint",
                "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
            },
            None,
            {"type": "click", "x": 5, "y": 6, "_focus_prepared": True},
        )
    assert pointer_calls == []

@pytest.mark.asyncio
async def test_windows_native_traversal_uses_one_initialized_uia_thread(monkeypatch):
    import local_shell_mcp.gui.windows as windows

    calls = []
    main_thread = threading.get_ident()

    class Initializer:
        def __enter__(self):
            calls.append(("init", threading.get_ident()))
            return self

        def __exit__(self, *_args):
            calls.append(("exit", threading.get_ident()))

    class Auto:
        UIAutomationInitializerInThread = Initializer

    monkeypatch.setattr(windows, "_automation", lambda: Auto())
    backend = WindowsGuiBackend()

    def list_sync():
        calls.append(("list", threading.get_ident()))
        return {"windows": []}

    def snapshot_sync(*_args, **_kwargs):
        calls.append(("snapshot", threading.get_ident()))
        return GuiSnapshot(window={"id": "w", "bounds": {}}, elements=[])

    def action_sync(*_args, **_kwargs):
        calls.append(("action", threading.get_ident()))
        return {"performed": True}

    monkeypatch.setattr(backend, "_list_windows_sync", list_sync)
    monkeypatch.setattr(backend, "_snapshot_sync", snapshot_sync)
    monkeypatch.setattr(backend, "_perform_action_sync", action_sync)

    try:
        await backend.list_windows()
        await backend.snapshot(
            "w",
            screenshot_path=None,
            include_elements=False,
            max_elements=1,
            max_depth=1,
        )
        result = await backend.perform_action(
            {"id": "hwnd:1", "bounds": {"x": 0, "y": 0, "width": 10, "height": 10}},
            None,
            {"type": "click", "x": 1, "y": 1},
        )
    finally:
        backend._executor.shutdown(wait=True)

    assert result == {"performed": True}
    init_threads = [thread_id for kind, thread_id in calls if kind == "init"]
    operation_threads = [
        thread_id for kind, thread_id in calls if kind in {"list", "snapshot", "action"}
    ]
    assert len(init_threads) == 1
    assert len(set(operation_threads)) == 1
    assert operation_threads[0] == init_threads[0]
    assert operation_threads[0] != main_thread

def test_windows_and_macos_locator_centers_must_stay_inside_window(monkeypatch):
    import local_shell_mcp.gui.macos as macos

    window = {"bounds": {"x": 100, "y": 100, "width": 200, "height": 100}}

    class Rect:
        left = 120
        top = 130
        right = 140
        bottom = 150

    class Locator:
        BoundingRectangle = Rect()

    assert WindowsGuiBackend._screen_point(
        window,
        {"type": "move"},
        Locator(),
    ) == (130, 140)

    class EmptyLocator:
        BoundingRectangle = None

    with pytest.raises(ValueError, match="no usable"):
        WindowsGuiBackend._screen_point(window, {"type": "scroll"}, EmptyLocator())

    class OutsideRect:
        left = 400
        top = 130
        right = 420
        bottom = 150

    class OutsideLocator:
        BoundingRectangle = OutsideRect()

    with pytest.raises(ValueError, match="outside"):
        WindowsGuiBackend._screen_point(window, {"type": "drag"}, OutsideLocator())

    monkeypatch.setattr(
        macos,
        "_ax_bounds",
        lambda _ax, locator: locator,
    )
    assert MacOSGuiBackend._screen_point(
        object(),
        window,
        {"type": "move"},
        {"x": 120, "y": 130, "width": 20, "height": 20},
    ) == (130, 140)
    with pytest.raises(ValueError, match="no usable"):
        MacOSGuiBackend._screen_point(
            object(),
            window,
            {"type": "scroll"},
            {"x": 0, "y": 0, "width": 0, "height": 0},
        )
    with pytest.raises(ValueError, match="outside"):
        MacOSGuiBackend._screen_point(
            object(),
            window,
            {"type": "drag"},
            {"x": 400, "y": 130, "width": 20, "height": 20},
        )

def test_windows_window_id_ignores_mutable_title(monkeypatch):
    import local_shell_mcp.gui.windows as windows

    class Rect:
        left = 0
        top = 0
        right = 100
        bottom = 100

    class Control:
        NativeWindowHandle = 7
        ProcessId = 101
        ClassName = "Editor"
        AutomationId = "main"
        BoundingRectangle = Rect()

        def __init__(self, name):
            self.Name = name

        def GetRuntimeId(self):
            return [1, 2, 3]

    first = Control("Document A")
    second = Control("Document A *")
    second.GetNextSiblingControl = lambda: None
    first_record = windows._window_record(first)
    second_record = windows._window_record(second)
    assert first_record is not None
    assert second_record is not None
    assert first_record["id"] == second_record["id"]

    class Root:
        def GetFirstChildControl(self):
            return second

        def GetChildren(self):
            raise AssertionError("window lookup must stay lazy")

    class Auto:
        def GetRootControl(self):
            return Root()

    monkeypatch.setattr(windows, "_automation", lambda: Auto())
    backend = WindowsGuiBackend()
    assert backend._find_window(first_record["id"]) is second

def test_windows_window_id_rejects_reused_hwnd(monkeypatch):
    import local_shell_mcp.gui.windows as windows

    class Rect:
        left = 0
        top = 0
        right = 100
        bottom = 100

    class Control:
        NativeWindowHandle = 7
        ProcessId = 101
        ClassName = "Editor"
        AutomationId = "main"
        Name = "Document A"
        BoundingRectangle = Rect()

        def GetRuntimeId(self):
            return [1, 2, 3]

    original = Control()
    record = windows._window_record(original)
    assert record is not None

    replacement = Control()
    replacement.GetNextSiblingControl = lambda: None
    replacement.ProcessId = 202
    replacement.Name = "Document B"
    replacement.GetRuntimeId = lambda: [9, 9, 9]

    class Root:
        def GetFirstChildControl(self):
            return replacement

        def GetChildren(self):
            raise AssertionError("window lookup must stay lazy")

    class Auto:
        def GetRootControl(self):
            return Root()

    monkeypatch.setattr(windows, "_automation", lambda: Auto())
    backend = WindowsGuiBackend()
    with pytest.raises(LookupError, match="identity changed"):
        backend._find_window(record["id"])

def test_windows_window_id_rejects_same_fingerprint_reused_hwnd(monkeypatch):
    import local_shell_mcp.gui.windows as windows

    class Rect:
        left = 0
        top = 0
        right = 100
        bottom = 100

    class Control:
        NativeWindowHandle = 7
        ProcessId = 101
        ClassName = "Editor"
        AutomationId = "main"
        Name = "Document"
        BoundingRectangle = Rect()
        IsOffscreen = False

        def GetRuntimeId(self):
            return [7]

    original = Control()
    replacement = Control()
    replacement.GetNextSiblingControl = lambda: None
    monkeypatch.setattr(windows, "_is_iconic_window", lambda _handle: False)
    record = windows._window_record(original)
    assert record is not None

    class Root:
        def GetFirstChildControl(self):
            return replacement

        def GetChildren(self):
            raise AssertionError("window lookup must stay lazy")

    class Auto:
        @staticmethod
        def GetRootControl():
            return Root()

        @staticmethod
        def ControlsAreSame(left, right):
            return left is right

    monkeypatch.setattr(windows, "_automation", lambda: Auto())
    backend = WindowsGuiBackend()

    with pytest.raises(LookupError, match="UIA identity changed"):
        backend._find_window(record["id"], record)

@pytest.mark.asyncio
async def test_windows_focus_and_shortcuts_use_uiautomation_semantics(monkeypatch):
    import local_shell_mcp.gui.windows as windows

    calls = []

    class Target:
        def SetFocus(self):
            calls.append(("focus",))
            return None

    class Auto:
        def SendKeys(self, sequence, **kwargs):
            calls.append(("keys", sequence, kwargs["charMode"]))

    target = Target()
    backend = WindowsGuiBackend()
    monkeypatch.setattr(windows, "_automation", lambda: Auto())
    monkeypatch.setattr(backend, "_find_window", lambda _window_id, _observed_window=None: target)

    await backend.focus_window({"id": "hwnd:1"})
    await backend.perform_action(
        {"id": "hwnd:1", "bounds": {"x": 0, "y": 0, "width": 10, "height": 10}},
        None,
        {"type": "key", "keys": "CTRL+A"},
    )

    assert ("keys", "{Ctrl}A", False) in calls

@pytest.mark.asyncio
async def test_windows_horizontal_only_scroll_does_not_inject_vertical_scroll(monkeypatch):
    import local_shell_mcp.gui.windows as windows

    calls = []

    class Target:
        def SetFocus(self):
            return None

    class Auto:
        def MoveTo(self, *args, **kwargs):
            calls.append(("move", args[:2]))

        def WheelDown(self, *args, **kwargs):
            calls.append(("down", args[0]))

        def WheelUp(self, *args, **kwargs):
            calls.append(("up", args[0]))

    backend = WindowsGuiBackend()
    monkeypatch.setattr(windows, "_automation", lambda: Auto())
    monkeypatch.setattr(backend, "_find_window", lambda _window_id, _observed_window=None: Target())
    monkeypatch.setattr(
        windows,
        "_native_window_bounds",
        lambda _hwnd: {"x": 0, "y": 0, "width": 100, "height": 100},
    )
    monkeypatch.setattr(
        windows,
        "_horizontal_wheel",
        lambda amount: calls.append(("horizontal", amount)),
    )

    await backend.perform_action(
        {
            "id": "hwnd:1:fingerprint",
            "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
        },
        None,
        {"type": "scroll", "x": 10, "y": 10, "delta_x": 2},
    )

    assert ("horizontal", -2) in calls
    assert not any(item[0] in {"up", "down"} for item in calls)

def test_windows_rejects_expiry_after_final_native_preparation(monkeypatch):
    import local_shell_mcp.gui.base as base
    import local_shell_mcp.gui.windows as windows

    pointer_calls = []
    clock = iter((5.0, 20.0))

    class Target:
        def SetFocus(self):
            return None

    class Auto:
        @staticmethod
        def Click(*_args, **_kwargs):
            pointer_calls.append("click")

    observed = {
        "id": "hwnd:1:fingerprint",
        "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
    }
    backend = WindowsGuiBackend()
    monkeypatch.setattr(base.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(windows, "_automation", lambda: Auto())
    monkeypatch.setattr(
        backend,
        "_find_window",
        lambda _window_id, _observed_window=None: Target(),
    )
    monkeypatch.setattr(
        windows,
        "_native_window_bounds",
        lambda _hwnd: dict(observed["bounds"]),
    )

    with pytest.raises(GuiStaleStateError, match="expired while preparing input"):
        backend._perform_action_sync(
            observed,
            None,
            {
                "type": "click",
                "x": 5,
                "y": 6,
                "_focus_prepared": True,
                "_observation_deadline": 10.0,
            },
        )
    assert pointer_calls == []

def test_windows_runtime_id_rejects_oversized_component_array_before_rendering():
    import local_shell_mcp.gui.windows as windows

    class Bomb:
        def __int__(self):
            raise AssertionError("oversized runtime ID must be rejected before components are read")

    class Control:
        def GetRuntimeId(self):
            return [Bomb()] * (windows.GUI_MAX_ELEMENT_TEXT_BYTES // 2 + 1)

    with pytest.raises(ValueError, match="runtime ID exceeds"):
        windows._control_runtime_id(Control())

@pytest.mark.asyncio
async def test_windows_uia_timeout_rotates_worker_and_allows_followup(monkeypatch):
    import local_shell_mcp.gui.windows as windows

    monkeypatch.setattr(windows, "_initialize_uia_thread", lambda: None)
    monkeypatch.setattr(windows, "_UIA_OPERATION_TIMEOUT_S", 0.02)
    backend = WindowsGuiBackend()
    release = threading.Event()
    started = threading.Event()
    original_executor = backend._executor

    def blocked():
        started.set()
        release.wait(1.0)
        return "late"

    try:
        with pytest.raises(GuiUnavailableError, match="provider timed out"):
            await backend._run_uia(blocked)
        assert started.is_set()
        assert backend._executor is not original_executor
        assert await backend._run_uia(lambda: "ok") == "ok"
    finally:
        release.set()
        backend._executor.shutdown(wait=True)
