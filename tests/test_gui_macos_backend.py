from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from local_shell_mcp.gui.base import (
    GuiStaleStateError,
    GuiUnavailableError,
)
from local_shell_mcp.gui.macos import (
    MacOSGuiBackend,
    _unicode_chunks,
    _utf16_units,
)


@pytest.mark.asyncio
async def test_macos_native_traversal_is_offloaded(monkeypatch):
    backend = MacOSGuiBackend()
    calls = []

    async def fake_run_ax(func, *args, **kwargs):
        calls.append(func.__name__)
        return func(*args, **kwargs)

    monkeypatch.setattr(backend, "_run_ax", fake_run_ax)
    monkeypatch.setattr(backend, "_list_windows_sync", lambda: {"windows": []})
    monkeypatch.setattr(
        backend,
        "_snapshot_accessibility_sync",
        lambda *args, **kwargs: (
            {"id": "cg:1", "bounds": {}},
            False,
            [],
            {},
        ),
    )

    await backend.list_windows()
    await backend.snapshot(
        "cg:1",
        screenshot_path=None,
        include_elements=False,
        max_elements=1,
        max_depth=1,
    )
    monkeypatch.setattr(
        backend,
        "_perform_action_sync",
        lambda *_args, **_kwargs: {"performed": True},
    )
    result = await backend.perform_action(
        {"id": "cg:1", "bounds": {"x": 0, "y": 0, "width": 10, "height": 10}},
        None,
        {"type": "click", "x": 1, "y": 1},
    )
    assert result == {"performed": True}
    assert calls == ["<lambda>", "<lambda>", "<lambda>"]

@pytest.mark.asyncio
async def test_macos_element_focus_failure_aborts_keyboard_injection(monkeypatch):
    import local_shell_mcp.gui.macos as macos

    class AX:
        kAXFocusedAttribute = "focused"
        kAXRaiseAction = "raise"

        @staticmethod
        def AXIsProcessTrusted():
            return True

        @staticmethod
        def AXUIElementPerformAction(_target, _action):
            return 0

        @staticmethod
        def AXUIElementSetAttributeValue(target, _attribute, _value):
            return 7 if target == "element" else 0

    class Quartz:
        @staticmethod
        def CGEventCreateKeyboardEvent(*_args):
            raise AssertionError("keyboard event must not be created after focus failure")

    backend = MacOSGuiBackend()
    monkeypatch.setattr(macos, "_native", lambda: (AX, Quartz))
    monkeypatch.setattr(backend, "_current_record", lambda window: window)
    monkeypatch.setattr(backend, "_find_ax_window", lambda _window: "window")
    monkeypatch.setattr(
        backend,
        "_resolve_ax_locator",
        lambda _window, _locator: "element",
    )

    with pytest.raises(RuntimeError, match="could not be focused"):
        await backend.perform_action(
            {"id": "cg:1", "bounds": {"x": 0, "y": 0, "width": 10, "height": 10}},
            {"path": [0], "fingerprint": "observed"},
            {"type": "type", "text": "x"},
        )
    with pytest.raises(RuntimeError, match="could not be focused"):
        await backend.perform_action(
            {"id": "cg:1", "bounds": {"x": 0, "y": 0, "width": 10, "height": 10}},
            {"path": [0], "fingerprint": "observed"},
            {"type": "key", "keys": "A"},
        )

def test_macos_key_table_includes_physical_backquote():
    import local_shell_mcp.gui.macos as macos

    assert macos._MAC_KEY_CODES["`"] == 50

def test_macos_ax_copy_values_uses_bounded_native_range():
    import local_shell_mcp.gui.macos as macos

    calls = []

    class AX:
        @staticmethod
        def AXUIElementCopyAttributeValues(element, attribute, index, max_values, _out):
            calls.append((element, attribute, index, max_values))
            return 0, [f"value-{index + offset}" for offset in range(max_values)]

    result = macos._ax_copy_values(AX, "element", "children", 7, 2)

    assert result == ["value-7", "value-8"]
    assert calls == [("element", "children", 7, 2)]

def test_macos_accessibility_traversal_does_not_fetch_children_after_budget(monkeypatch):
    import local_shell_mcp.gui.macos as macos

    child_queries = []

    class AX:
        kAXRoleAttribute = "role"
        kAXTitleAttribute = "title"
        kAXDescriptionAttribute = "description"
        kAXValueAttribute = "value"
        kAXEnabledAttribute = "enabled"
        kAXChildrenAttribute = "children"

        @staticmethod
        def AXIsProcessTrusted():
            return True

    root = object()
    backend = MacOSGuiBackend()
    monkeypatch.setattr(macos, "_native", lambda: (AX, object()))
    monkeypatch.setattr(
        backend,
        "_find_record",
        lambda _window_id: {
            "id": "cg:1",
            "pid": 1,
            "title": "Window",
            "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
        },
    )
    monkeypatch.setattr(backend, "_find_ax_window", lambda _record: root)
    monkeypatch.setattr(macos, "_ax_bounds", lambda _ax, _element: {})

    def ax_copy(_ax, _element, attr, default=None):
        if attr == AX.kAXChildrenAttribute:
            child_queries.append(True)
            return [object() for _ in range(10000)]
        return default

    monkeypatch.setattr(macos, "_ax_copy", ax_copy)
    monkeypatch.setattr(
        macos,
        "_ax_copy_values",
        lambda *_args, **_kwargs: child_queries.append(True) or [object()],
    )

    _record, _trusted, elements, _locators = backend._snapshot_accessibility_sync(
        "cg:1",
        include_elements=True,
        max_elements=1,
        max_depth=12,
    )
    assert len(elements) == 1
    assert child_queries == []

def test_macos_accessibility_traversal_bounds_provider_strings_and_total_bytes(monkeypatch):
    import local_shell_mcp.gui.macos as macos

    huge = "x" * (macos.GUI_MAX_ELEMENT_TEXT_BYTES * 8)

    class AX:
        kAXRoleAttribute = "role"
        kAXTitleAttribute = "title"
        kAXDescriptionAttribute = "description"
        kAXValueAttribute = "value"
        kAXEnabledAttribute = "enabled"
        kAXChildrenAttribute = "children"

        @staticmethod
        def AXIsProcessTrusted():
            return True

    children = [object() for _ in range(200)]
    root = object()
    backend = MacOSGuiBackend()
    monkeypatch.setattr(macos, "_native", lambda: (AX, object()))
    monkeypatch.setattr(
        backend,
        "_find_record",
        lambda _window_id: {
            "id": "cg:1",
            "pid": 1,
            "title": "Window",
            "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
        },
    )
    monkeypatch.setattr(backend, "_find_ax_window", lambda _record: root)
    monkeypatch.setattr(
        macos,
        "_ax_bounds",
        lambda _ax, _element: {"x": 0, "y": 0, "width": 10, "height": 10},
    )

    def ax_copy(_ax, element, attr, default=None):
        if attr == AX.kAXChildrenAttribute:
            return children if element is root else []
        if attr in {AX.kAXRoleAttribute, AX.kAXTitleAttribute, AX.kAXDescriptionAttribute}:
            return huge
        if attr == AX.kAXValueAttribute:
            return huge
        if attr == AX.kAXEnabledAttribute:
            return True
        return default

    monkeypatch.setattr(macos, "_ax_copy", ax_copy)
    monkeypatch.setattr(
        macos,
        "_ax_copy_values",
        lambda _ax, element, _attr, index, max_values: (
            children[index : index + max_values] if element is root else []
        ),
    )

    _record, _trusted, elements, locators = backend._snapshot_accessibility_sync(
        "cg:1",
        include_elements=True,
        max_elements=1000,
        max_depth=2,
    )

    assert elements
    assert len(json.dumps(elements, ensure_ascii=False).encode()) <= (
        macos.GUI_MAX_ELEMENTS_TOTAL_BYTES
    )
    assert len(locators) == len(elements)
    for element in elements:
        assert len(element["role"].encode()) <= macos.GUI_MAX_ELEMENT_TEXT_BYTES
        assert len(element["name"].encode()) <= macos.GUI_MAX_ELEMENT_TEXT_BYTES
        assert len(element["value"].encode()) <= macos.GUI_MAX_ELEMENT_VALUE_BYTES

def test_macos_semantic_action_rejects_recycled_ax_element(monkeypatch):
    import local_shell_mcp.gui.macos as macos

    class AX:
        kAXRoleAttribute = "role"
        kAXTitleAttribute = "title"
        kAXDescriptionAttribute = "description"
        kAXValueAttribute = "value"
        kAXEnabledAttribute = "enabled"
        kAXChildrenAttribute = "children"

        @staticmethod
        def AXIsProcessTrusted():
            return True

    root = object()
    child = object()
    titles = {root: "Window", child: "Save"}
    record = {
        "id": "cg:1",
        "pid": 1,
        "title": "Window",
        "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
    }
    backend = MacOSGuiBackend()
    monkeypatch.setattr(macos, "_native", lambda: (AX, object()))
    monkeypatch.setattr(backend, "_find_record", lambda _window_id: record)
    monkeypatch.setattr(backend, "_current_record", lambda _window: record)
    monkeypatch.setattr(backend, "_find_ax_window", lambda _record: root)
    monkeypatch.setattr(
        macos,
        "_ax_bounds",
        lambda _ax, element: (
            {"x": 10, "y": 10, "width": 20, "height": 20}
            if element is child
            else {"x": 0, "y": 0, "width": 100, "height": 100}
        ),
    )

    def ax_copy(_ax, element, attr, default=None):
        if attr == AX.kAXChildrenAttribute:
            return [child] if element is root else []
        if attr == AX.kAXRoleAttribute:
            return "button" if element is child else "window"
        if attr == AX.kAXTitleAttribute:
            return titles[element]
        if attr == AX.kAXDescriptionAttribute:
            return ""
        if attr == AX.kAXValueAttribute:
            return ""
        if attr == AX.kAXEnabledAttribute:
            return True
        return default

    monkeypatch.setattr(macos, "_ax_copy", ax_copy)
    monkeypatch.setattr(
        macos,
        "_ax_copy_values",
        lambda _ax, element, _attr, index, max_values: (
            ([child][index : index + max_values]) if element is root else []
        ),
    )

    _record, _trusted, elements, locators = backend._snapshot_accessibility_sync(
        "cg:1",
        include_elements=True,
        max_elements=10,
        max_depth=2,
    )
    child_id = next(item["id"] for item in elements if item["name"] == "Save")
    titles[child] = "Delete"

    with pytest.raises(LookupError, match="changed since observation"):
        backend._perform_action_sync(
            record,
            locators[child_id],
            {"type": "click"},
        )

def test_macos_locator_rejects_identical_replacement_ax_element(monkeypatch):
    import local_shell_mcp.gui.macos as macos

    class AX:
        kAXRoleAttribute = "role"
        kAXTitleAttribute = "title"
        kAXDescriptionAttribute = "description"
        kAXValueAttribute = "value"
        kAXEnabledAttribute = "enabled"
        kAXChildrenAttribute = "children"

    root = object()
    observed_child = object()
    replacement_child = object()
    current_child = {"value": observed_child}
    backend = MacOSGuiBackend()
    monkeypatch.setattr(macos, "_native", lambda: (AX, object()))
    monkeypatch.setattr(backend, "_find_ax_window", lambda _record: root)
    monkeypatch.setattr(
        macos,
        "_ax_bounds",
        lambda _ax, element: (
            {"x": 10, "y": 10, "width": 20, "height": 20}
            if element is not root
            else {"x": 0, "y": 0, "width": 100, "height": 100}
        ),
    )

    def ax_copy(_ax, element, attr, default=None):
        if attr == AX.kAXChildrenAttribute:
            return [current_child["value"]] if element is root else []
        if attr == AX.kAXRoleAttribute:
            return "button" if element is not root else "window"
        if attr == AX.kAXTitleAttribute:
            return "Save" if element is not root else "Window"
        if attr == AX.kAXDescriptionAttribute:
            return ""
        if attr == AX.kAXValueAttribute:
            return ""
        if attr == AX.kAXEnabledAttribute:
            return True
        return default

    monkeypatch.setattr(macos, "_ax_copy", ax_copy)
    monkeypatch.setattr(
        macos,
        "_ax_copy_values",
        lambda _ax, element, _attr, index, max_values: (
            [current_child["value"]][index : index + max_values] if element is root else []
        ),
    )
    locator = {
        "path": [0],
        "fingerprint": macos._ax_element_fingerprint(AX, observed_child),
        "_ax_element": observed_child,
    }
    current_child["value"] = replacement_child

    with pytest.raises(LookupError, match="identity changed since observation"):
        backend._resolve_ax_locator(
            {
                "id": "cg:1",
                "pid": 1,
                "title": "Window",
                "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
            },
            locator,
        )

def test_macos_current_record_rejects_reused_cg_id_with_new_ax_window(monkeypatch):
    import local_shell_mcp.gui.macos as macos

    original_ax = object()
    replacement_ax = object()
    observed = {
        "id": "cg:7",
        "pid": 42,
        "title": "Document",
        "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
        "_ax_identity_required": True,
        "_ax_window": original_ax,
    }
    current = {
        "id": "cg:7",
        "pid": 42,
        "title": "Document",
        "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
    }

    class AX:
        @staticmethod
        def CFEqual(left, right):
            return left is right

    backend = MacOSGuiBackend()
    monkeypatch.setattr(macos, "_native", lambda: (AX, object()))
    monkeypatch.setattr(backend, "_find_record", lambda _window_id: dict(current))
    monkeypatch.setattr(backend, "_find_ax_window", lambda _record: replacement_ax)

    with pytest.raises(LookupError, match="AX identity changed"):
        backend._current_record(observed)

@pytest.mark.asyncio
async def test_macos_snapshot_marks_unresolved_ax_window_non_interactive(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    import local_shell_mcp.gui.macos as macos

    backend = MacOSGuiBackend()
    record = {
        "id": "cg:7",
        "pid": 42,
        "title": "Ambiguous",
        "app": "Editor",
        "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
    }

    class AX:
        @staticmethod
        def AXIsProcessTrusted():
            return True

    monkeypatch.setattr(macos, "_native", lambda: (AX, object()))
    monkeypatch.setattr(backend, "_find_record", lambda _window_id: dict(record))
    monkeypatch.setattr(backend, "_find_ax_window", lambda _record: None)
    observed, trusted, elements, locators = backend._snapshot_accessibility_sync(
        "cg:7",
        include_elements=False,
        max_elements=1,
        max_depth=1,
    )
    assert trusted is True
    assert observed["_ax_identity_required"] is False
    monkeypatch.setattr(
        backend,
        "_snapshot_accessibility_sync",
        lambda *_args, **_kwargs: (observed, trusted, elements, locators),
    )

    def capture(argv, **_kwargs):
        Image.new("RGB", (100, 100)).save(Path(argv[-1]), format="PNG")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(macos.subprocess, "run", capture)
    screenshot_path = tmp_path / "view-only.png"
    snapshot = await backend.snapshot(
        "cg:7",
        screenshot_path=screenshot_path,
        include_elements=False,
        max_elements=1,
        max_depth=1,
    )

    assert snapshot.capabilities["accessibility"] is False
    assert snapshot.capabilities["coordinate_input"] is False
    assert snapshot.capabilities["semantic_actions"] is False
    assert snapshot.capabilities["accessibility_permission_required"] is False
    assert screenshot_path.is_file()

@pytest.mark.asyncio
async def test_macos_snapshot_revalidates_window_after_capture(tmp_path, monkeypatch):
    import local_shell_mcp.gui.macos as macos

    backend = MacOSGuiBackend()
    record = {
        "id": "cg:7",
        "pid": 42,
        "title": "Document",
        "app": "Editor",
        "bounds": {"x": 0, "y": 0, "width": 100, "height": 80},
    }
    monkeypatch.setattr(
        backend,
        "_snapshot_accessibility_sync",
        lambda *_args, **_kwargs: (record, True, [], {}),
    )

    def capture(argv, **_kwargs):
        Image.new("RGB", (100, 80)).save(Path(argv[-1]), format="PNG")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(macos.subprocess, "run", capture)
    monkeypatch.setattr(
        backend,
        "_current_record",
        lambda _observed: {
            **record,
            "bounds": {"x": 10, "y": 0, "width": 100, "height": 80},
        },
    )

    with pytest.raises(LookupError, match="moved or resized during capture"):
        await backend.snapshot(
            "cg:7",
            screenshot_path=tmp_path / "capture.png",
            include_elements=False,
            max_elements=1,
            max_depth=1,
        )

def test_macos_ax_window_matching_rejects_ambiguous_weaker_matches(monkeypatch):
    import local_shell_mcp.gui.macos as macos

    first = object()
    second = object()

    class AX:
        kAXWindowsAttribute = "windows"
        kAXTitleAttribute = "title"

        @staticmethod
        def AXIsProcessTrusted():
            return True

        @staticmethod
        def AXUIElementCreateApplication(_pid):
            return "app"

    monkeypatch.setattr(macos, "_native", lambda: (AX, object()))
    monkeypatch.setattr(
        macos,
        "_ax_copy_values",
        lambda _ax, _element, _attr, index, max_values: [first, second][index : index + max_values],
    )
    monkeypatch.setattr(
        macos,
        "_ax_copy",
        lambda _ax, obj, attr, default=None: (
            [first, second]
            if attr == AX.kAXWindowsAttribute
            else ("Shared" if obj in {first, second} else default)
        ),
    )
    monkeypatch.setattr(
        macos,
        "_ax_bounds",
        lambda _ax, _window: {"x": 0, "y": 0, "width": 100, "height": 100},
    )

    backend = MacOSGuiBackend()
    assert (
        backend._find_ax_window(
            {
                "pid": 1,
                "title": "Shared",
                "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
            }
        )
        is None
    )

def test_macos_ax_window_matching_rejects_sole_unrelated_window(monkeypatch):
    import local_shell_mcp.gui.macos as macos

    remaining = object()

    class AX:
        kAXWindowsAttribute = "windows"
        kAXTitleAttribute = "title"

        @staticmethod
        def AXIsProcessTrusted():
            return True

        @staticmethod
        def AXUIElementCreateApplication(_pid):
            return "app"

    monkeypatch.setattr(macos, "_native", lambda: (AX, object()))
    monkeypatch.setattr(
        macos,
        "_ax_copy_values",
        lambda _ax, _element, _attr, index, max_values: [remaining][index : index + max_values],
    )
    monkeypatch.setattr(
        macos,
        "_ax_copy",
        lambda _ax, obj, attr, default=None: (
            [remaining]
            if attr == AX.kAXWindowsAttribute
            else ("Other document" if obj is remaining else default)
        ),
    )
    monkeypatch.setattr(
        macos,
        "_ax_bounds",
        lambda _ax, _window: {"x": 500, "y": 500, "width": 80, "height": 80},
    )

    backend = MacOSGuiBackend()
    assert (
        backend._find_ax_window(
            {
                "pid": 1,
                "title": "Closed document",
                "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
            }
        )
        is None
    )

def test_macos_ax_window_matching_rejects_title_only_match(monkeypatch):
    import local_shell_mcp.gui.macos as macos

    remaining = object()

    class AX:
        kAXWindowsAttribute = "windows"
        kAXTitleAttribute = "title"

        @staticmethod
        def AXIsProcessTrusted():
            return True

        @staticmethod
        def AXUIElementCreateApplication(_pid):
            return "app"

    monkeypatch.setattr(macos, "_native", lambda: (AX, object()))
    monkeypatch.setattr(
        macos,
        "_ax_copy_values",
        lambda _ax, _element, _attr, index, max_values: [remaining][index : index + max_values],
    )
    monkeypatch.setattr(
        macos,
        "_ax_copy",
        lambda _ax, obj, attr, default=None: (
            [remaining]
            if attr == AX.kAXWindowsAttribute
            else ("Document" if obj is remaining else default)
        ),
    )
    monkeypatch.setattr(
        macos,
        "_ax_bounds",
        lambda _ax, _window: {"x": 500, "y": 500, "width": 80, "height": 80},
    )

    backend = MacOSGuiBackend()
    assert (
        backend._find_ax_window(
            {
                "pid": 1,
                "title": "Document",
                "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
            }
        )
        is None
    )

def test_macos_raw_input_rejects_closed_cg_window_before_ax_title_fallback(monkeypatch):
    import local_shell_mcp.gui.macos as macos

    class AX:
        @staticmethod
        def AXIsProcessTrusted():
            return True

    backend = MacOSGuiBackend()
    monkeypatch.setattr(macos, "_native", lambda: (AX, object()))
    monkeypatch.setattr(
        backend,
        "_find_record",
        lambda _window_id: (_ for _ in ()).throw(LookupError("closed")),
    )
    monkeypatch.setattr(backend, "_find_ax_window", lambda _record: object())

    with pytest.raises(LookupError, match="closed"):
        backend._perform_action_sync(
            {
                "id": "cg:1",
                "pid": 42,
                "title": "Untitled",
                "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
            },
            None,
            {"type": "type", "text": "x"},
        )

@pytest.mark.asyncio
async def test_macos_rejects_oversized_capture_before_screencapture(tmp_path, monkeypatch):
    import local_shell_mcp.gui.macos as macos

    backend = MacOSGuiBackend()
    record = {
        "id": "cg:1",
        "pid": 42,
        "title": "Huge",
        "bounds": {
            "x": 0,
            "y": 0,
            "width": macos.GUI_MAX_CAPTURE_DIMENSION + 1,
            "height": 100,
        },
    }
    monkeypatch.setattr(
        backend,
        "_snapshot_accessibility_sync",
        lambda *_args, **_kwargs: (record, True, [], {}),
    )
    called = []
    monkeypatch.setattr(
        macos.subprocess,
        "run",
        lambda *_args, **_kwargs: called.append(True),
    )

    with pytest.raises(GuiUnavailableError, match="safe budget"):
        await backend.snapshot(
            "cg:1",
            screenshot_path=tmp_path / "capture.png",
            include_elements=False,
            max_elements=1,
            max_depth=1,
        )
    assert called == []

def test_macos_click_failure_releases_pressed_mouse_button(monkeypatch):
    import local_shell_mcp.gui.macos as macos

    posted = []
    up_attempts = 0

    class AX:
        kAXFocusedAttribute = "focused"
        kAXRaiseAction = "raise"

        @staticmethod
        def AXIsProcessTrusted():
            return True

        @staticmethod
        def AXUIElementSetAttributeValue(*_args):
            return 0

        @staticmethod
        def AXUIElementPerformAction(*_args):
            return 0

    class Quartz:
        kCGHIDEventTap = 1
        kCGMouseButtonLeft = 0
        kCGMouseButtonRight = 1
        kCGEventLeftMouseDown = 10
        kCGEventLeftMouseUp = 11
        kCGEventRightMouseDown = 12
        kCGEventRightMouseUp = 13
        kCGMouseEventClickState = 20

        @staticmethod
        def CGEventCreateMouseEvent(_source, event_type, _point, _button):
            return {"type": event_type}

        @staticmethod
        def CGEventPost(_tap, event):
            nonlocal up_attempts
            posted.append(event["type"])
            if event["type"] == Quartz.kCGEventLeftMouseUp and up_attempts == 0:
                up_attempts += 1
                raise RuntimeError("up failed")

    backend = MacOSGuiBackend()
    window = {
        "id": "cg:1",
        "pid": 42,
        "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
    }
    monkeypatch.setattr(macos, "_native", lambda: (AX, Quartz))
    monkeypatch.setattr(backend, "_current_record", lambda _window: window)
    monkeypatch.setattr(backend, "_find_ax_window", lambda _window: "ax-window")

    with pytest.raises(RuntimeError, match="up failed"):
        backend._perform_action_sync(
            window,
            None,
            {"type": "click", "x": 5, "y": 6},
        )
    assert posted == [
        Quartz.kCGEventLeftMouseDown,
        Quartz.kCGEventLeftMouseUp,
        Quartz.kCGEventLeftMouseUp,
    ]

def test_macos_drag_failure_releases_pressed_mouse_button(monkeypatch):
    import local_shell_mcp.gui.macos as macos

    calls = []

    class AX:
        kAXFocusedAttribute = "focused"
        kAXRaiseAction = "raise"

        @staticmethod
        def AXIsProcessTrusted():
            return True

        @staticmethod
        def AXUIElementSetAttributeValue(target, attribute, value):
            calls.append(("focus", target, attribute, value))
            return 0

        @staticmethod
        def AXUIElementPerformAction(*_args):
            return 0

    class Quartz:
        kCGMouseButtonLeft = 0
        kCGEventLeftMouseDown = 10
        kCGEventLeftMouseDragged = 11
        kCGEventLeftMouseUp = 12

    backend = MacOSGuiBackend()
    window = {
        "id": "cg:1",
        "pid": 42,
        "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
    }
    monkeypatch.setattr(macos, "_native", lambda: (AX, Quartz))
    monkeypatch.setattr(backend, "_current_record", lambda _window: window)
    monkeypatch.setattr(backend, "_find_ax_window", lambda _window: "ax-window")

    def mouse(_quartz, event_type, x, y, _button):
        calls.append((event_type, x, y))
        if event_type == Quartz.kCGEventLeftMouseDragged:
            raise RuntimeError("drag failed")

    monkeypatch.setattr(backend, "_mouse", mouse)

    with pytest.raises(RuntimeError, match="drag failed"):
        backend._perform_action_sync(
            window,
            None,
            {
                "type": "drag",
                "x": 1,
                "y": 2,
                "to_x": 30,
                "to_y": 40,
                "_focus_prepared": True,
            },
        )
    assert calls[0] == ("focus", "ax-window", "focused", True)
    assert calls[1:] == [
        (Quartz.kCGEventLeftMouseDown, 1, 2),
        (Quartz.kCGEventLeftMouseDragged, 30, 40),
        (Quartz.kCGEventLeftMouseUp, 1, 2),
    ]

def test_macos_raw_input_requires_unambiguous_focusable_window(monkeypatch):
    import local_shell_mcp.gui.macos as macos

    posted = []

    class AX:
        kAXFocusedAttribute = "focused"
        kAXRaiseAction = "raise"

        @staticmethod
        def AXIsProcessTrusted():
            return True

        @staticmethod
        def AXUIElementSetAttributeValue(*_args):
            return 0

        @staticmethod
        def AXUIElementPerformAction(*_args):
            return 0

    class Quartz:
        kCGHIDEventTap = 1
        kCGEventMouseMoved = 2
        kCGMouseButtonLeft = 0

        @staticmethod
        def CGEventCreateMouseEvent(*_args):
            return object()

        @staticmethod
        def CGEventPost(*args):
            posted.append(args)

    backend = MacOSGuiBackend()
    monkeypatch.setattr(macos, "_native", lambda: (AX, Quartz))
    monkeypatch.setattr(backend, "_current_record", lambda window: window)
    monkeypatch.setattr(backend, "_find_ax_window", lambda _window: None)

    with pytest.raises(RuntimeError, match="unambiguously"):
        backend._perform_action_sync(
            {"id": "cg:1", "pid": 1, "bounds": {"x": 0, "y": 0, "width": 20, "height": 20}},
            None,
            {"type": "move", "x": 1, "y": 1},
        )
    assert posted == []

def test_macos_utf16_text_units_and_chunks():
    assert _utf16_units("A") == 1
    assert _utf16_units("😀") == 2
    assert _utf16_units("A😀") == 3
    assert _unicode_chunks("A😀B", max_units=2) == ["A", "😀", "B"]

def test_macos_window_enumeration_bounds_provider_metadata(monkeypatch):
    import local_shell_mcp.gui.macos as macos

    huge = "x" * (macos.GUI_MAX_WINDOW_TEXT_BYTES * 4)

    class Quartz:
        kCGWindowListOptionOnScreenOnly = 1
        kCGWindowListExcludeDesktopElements = 2
        kCGNullWindowID = 0
        kCGWindowLayer = "layer"
        kCGWindowBounds = "bounds"
        kCGWindowNumber = "number"
        kCGWindowName = "name"
        kCGWindowOwnerName = "owner"
        kCGWindowOwnerPID = "pid"

        @staticmethod
        def CGWindowListCopyWindowInfo(_options, _window_id):
            return [
                {
                    "layer": 0,
                    "bounds": {"X": 0, "Y": 0, "Width": 100, "Height": 100},
                    "number": index + 1,
                    "name": huge,
                    "owner": huge,
                    "pid": 42,
                }
                for index in range(macos.GUI_MAX_WINDOWS * 4)
            ]

    monkeypatch.setattr(macos, "_native", lambda: (object(), Quartz))
    windows = MacOSGuiBackend()._windows()

    assert 0 < len(windows) <= macos.GUI_MAX_WINDOWS
    assert len(
        json.dumps(
            windows,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ) <= (macos.GUI_MAX_WINDOWS_TOTAL_BYTES)
    for record in windows:
        assert len(record["title"].encode()) <= macos.GUI_MAX_WINDOW_TEXT_BYTES
        assert len(record["app"].encode()) <= macos.GUI_MAX_WINDOW_TEXT_BYTES

def test_macos_pointer_rejects_bounds_change_after_focus(monkeypatch):
    import local_shell_mcp.gui.macos as macos

    class AX:
        kAXFocusedAttribute = "focused"
        kAXRaiseAction = "raise"

        @staticmethod
        def AXIsProcessTrusted():
            return True

        @staticmethod
        def AXUIElementSetAttributeValue(*_args):
            return 0

        @staticmethod
        def AXUIElementPerformAction(*_args):
            return 0

    class Quartz:
        pass

    observed = {
        "id": "cg:1",
        "pid": 1,
        "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
    }
    moved = {
        **observed,
        "bounds": {"x": 10, "y": 0, "width": 100, "height": 100},
    }
    current_calls = 0
    backend = MacOSGuiBackend()

    def current(_window):
        nonlocal current_calls
        current_calls += 1
        return observed if current_calls == 1 else moved

    monkeypatch.setattr(macos, "_native", lambda: (AX, Quartz))
    monkeypatch.setattr(backend, "_current_record", current)
    monkeypatch.setattr(backend, "_find_ax_window", lambda _record: object())
    monkeypatch.setattr(
        backend,
        "_mouse",
        lambda *_args: pytest.fail("stale macOS pointer input must not be injected"),
    )

    with pytest.raises(LookupError, match="moved or resized immediately before pointer"):
        backend._perform_action_sync(
            observed,
            None,
            {"type": "move", "x": 1, "y": 2, "_focus_prepared": True},
        )
    assert current_calls == 2

def test_macos_rejects_expiry_after_final_native_preparation(monkeypatch):
    import local_shell_mcp.gui.base as base
    import local_shell_mcp.gui.macos as macos

    clock = iter((5.0, 20.0))

    class AX:
        kAXFocusedAttribute = "focused"
        kAXRaiseAction = "raise"

        @staticmethod
        def AXIsProcessTrusted():
            return True

        @staticmethod
        def AXUIElementSetAttributeValue(*_args):
            return 0

        @staticmethod
        def AXUIElementPerformAction(*_args):
            return 0

    class Quartz:
        pass

    observed = {
        "id": "cg:1",
        "pid": 1,
        "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
    }
    backend = MacOSGuiBackend()
    monkeypatch.setattr(base.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(macos, "_native", lambda: (AX, Quartz))
    monkeypatch.setattr(backend, "_current_record", lambda _window: observed)
    monkeypatch.setattr(backend, "_find_ax_window", lambda _record: object())
    monkeypatch.setattr(
        backend,
        "_mouse",
        lambda *_args: pytest.fail("expired macOS pointer input must not be injected"),
    )

    with pytest.raises(GuiStaleStateError, match="expired while preparing input"):
        backend._perform_action_sync(
            observed,
            None,
            {
                "type": "move",
                "x": 1,
                "y": 2,
                "_focus_prepared": True,
                "_observation_deadline": 10.0,
            },
        )

@pytest.mark.asyncio
async def test_macos_ax_timeout_resets_worker_and_allows_followup(monkeypatch):
    import local_shell_mcp.gui.macos as macos

    backend = MacOSGuiBackend()
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(macos, "_AX_OPERATION_TIMEOUT_S", 0.01)

    def blocked_provider():
        started.set()
        release.wait(1)
        return "late"

    try:
        with pytest.raises(GuiUnavailableError, match="Accessibility provider timed out"):
            await backend._run_ax(blocked_provider)
        assert started.is_set()
        assert await backend._run_ax(lambda: "ok") == "ok"
    finally:
        release.set()
        backend._executor.shutdown(wait=False, cancel_futures=True)
