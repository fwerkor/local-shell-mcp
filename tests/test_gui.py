from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
import tomllib
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from PIL import Image, UnidentifiedImageError

from local_shell_mcp.gui.base import (
    GuiManager,
    GuiSnapshot,
    GuiStaleStateError,
    GuiUnavailableError,
    quantize_scroll_amount,
)
from local_shell_mcp.gui.linux import _desktop_crop_box, _session_type
from local_shell_mcp.gui.linux_portal import (
    PortalDesktop,
    _keysym,
    _portal_request,
    _portal_request_path,
)
from local_shell_mcp.gui.macos import (
    _MAC_KEY_CODES,
    MacOSGuiBackend,
    _cg_bounds,
    _unicode_chunks,
    _utf16_units,
)
from local_shell_mcp.gui.macos import _key_parts as mac_key_parts
from local_shell_mcp.gui.windows import WindowsGuiBackend, _key_sequence, _rect_dict
from local_shell_mcp.image_ops import ImageFile


def test_native_gui_adapters_are_optional_dependencies():
    project = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    mandatory = "\n".join(project["dependencies"]).lower()
    for package in (
        "uiautomation",
        "pyobjc-framework-applicationservices",
        "pyobjc-framework-quartz",
        "dbus-next",
        "python-xlib",
    ):
        assert package not in mandatory

    optional = "\n".join(project["optional-dependencies"]["gui"]).lower()
    for package in (
        "uiautomation",
        "pyobjc-framework-applicationservices",
        "pyobjc-framework-quartz",
        "dbus-next",
        "python-xlib",
    ):
        assert package in optional


def test_core_imports_without_optional_gui_adapters():
    import os
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root / "src")
    code = r"""
import builtins
blocked = {
    "uiautomation",
    "ApplicationServices",
    "Quartz",
    "dbus_next",
    "Xlib",
}
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split(".", 1)[0] in blocked:
        raise ModuleNotFoundError(name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
import local_shell_mcp.remote
import local_shell_mcp.tools
print("ok")
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok"


class FakeBackend:
    name = "fake-native"

    def __init__(self) -> None:
        self.bounds = {"x": 10, "y": 20, "width": 300, "height": 200}
        self.actions: list[tuple[dict[str, Any], Any, dict[str, Any]]] = []

    async def list_windows(self) -> dict[str, Any]:
        return {
            "windows": [
                {
                    "id": "window:1",
                    "title": "Demo",
                    "app": "demo",
                    "pid": 1,
                    "bounds": dict(self.bounds),
                }
            ]
        }

    async def snapshot(
        self,
        window_id: str,
        *,
        screenshot_path: Path | None,
        include_elements: bool,
        max_elements: int,
        max_depth: int,
    ) -> GuiSnapshot:
        assert window_id == "window:1"
        assert max_elements <= 1000
        assert max_depth <= 20
        if screenshot_path is not None:
            Image.new("RGB", (600, 400)).save(screenshot_path, format="PNG")
        elements = [
            {
                "id": "e1",
                "role": "button",
                "name": "Apply",
                "bounds": {"x": 20, "y": 30, "width": 80, "height": 30},
            }
        ]
        return GuiSnapshot(
            window={
                "id": "window:1",
                "title": "Demo",
                "app": "demo",
                "pid": 1,
                "bounds": dict(self.bounds),
            },
            elements=elements if include_elements else [],
            locators={"e1": "native-element"} if include_elements else {},
            screenshot_path=str(screenshot_path) if screenshot_path is not None else None,
            capabilities={"semantic_actions": True},
        )

    async def focus_window(self, window: dict[str, Any]) -> None:
        self.actions.append((window, None, {"type": "focus_window"}))

    async def perform_action(
        self,
        window: dict[str, Any],
        locator: Any | None,
        action: dict[str, Any],
    ) -> dict[str, Any]:
        self.actions.append((window, locator, action))
        return {"performed": True}


def _install_frame_observation(
    manager: GuiManager,
    backend: FakeBackend,
    *,
    observation_id: str = "frame-observation",
    window_id: str = "window:1",
) -> str:
    manager._frame_observations[observation_id] = SimpleNamespace(
        state_id=observation_id,
        window={
            "id": window_id,
            "title": "Demo",
            "app": "demo",
            "pid": 1,
            "bounds": dict(backend.bounds),
        },
        locators={},
        created_at=time.monotonic(),
    )
    return observation_id


@pytest.mark.asyncio
async def test_gui_manager_state_is_single_use_and_resolves_element(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    backend = FakeBackend()
    manager = GuiManager(backend)

    state = await manager.snapshot("window:1", screenshot=False)

    result = await manager.act(
        "window:1",
        state["state_id"],
        [{"type": "click", "element_id": "e1"}],
    )

    assert state["elements"][0]["bounds"] == {
        "x": 10,
        "y": 10,
        "width": 80,
        "height": 30,
    }
    assert result["state_consumed"] is True
    assert [item[2]["type"] for item in backend.actions] == [
        "focus_window",
        "click",
    ]
    assert backend.actions[1][1] == "native-element"
    with pytest.raises(GuiStaleStateError, match="stale"):
        await manager.act(
            "window:1",
            state["state_id"],
            [{"type": "click", "element_id": "e1"}],
        )


@pytest.mark.asyncio
async def test_gui_manager_rejects_coordinate_action_after_window_moves(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    backend = FakeBackend()
    manager = GuiManager(backend)
    state = await manager.snapshot("window:1", screenshot=False)
    backend.bounds["x"] += 20

    with pytest.raises(GuiStaleStateError, match="moved or resized"):
        await manager.act(
            "window:1",
            state["state_id"],
            [{"type": "click", "x": 10, "y": 10}],
        )
    assert backend.actions == []


@pytest.mark.asyncio
async def test_gui_manager_rechecks_geometry_after_coordinate_focus(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))

    class FocusMovesBackend(FakeBackend):
        async def focus_window(self, window):
            await super().focus_window(window)
            self.bounds["x"] += 20

    backend = FocusMovesBackend()
    manager = GuiManager(backend)
    state = await manager.snapshot("window:1", screenshot=False)

    with pytest.raises(GuiStaleStateError, match="moved or resized"):
        await manager.act(
            "window:1",
            state["state_id"],
            [{"type": "click", "x": 10, "y": 10}],
        )

    assert [item[2]["type"] for item in backend.actions] == ["focus_window"]


@pytest.mark.asyncio
async def test_gui_manager_normalizes_screenshot_to_logical_window_pixels(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    backend = FakeBackend()
    manager = GuiManager(backend)

    state = await manager.snapshot("window:1", screenshot=True)
    screenshot_path = Path(state["screenshot_path"])
    try:
        with Image.open(screenshot_path) as image:
            assert image.size == (300, 200)
    finally:
        screenshot_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_gui_manager_clamps_observation_limits(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    backend = FakeBackend()
    manager = GuiManager(backend)

    state = await manager.snapshot(
        "window:1",
        screenshot=False,
        max_elements=100_000,
        max_depth=100_000,
    )

    assert state["backend"] == "fake-native"
    assert state["elements"][0]["id"] == "e1"


def test_cross_platform_coordinate_and_key_helpers():
    class Rect:
        left = 4
        top = 5
        right = 14
        bottom = 25

    assert _rect_dict(Rect()) == {"x": 4, "y": 5, "width": 10, "height": 20}
    assert _key_sequence(["CTRL", "A"]) == "{Ctrl}A"
    assert _cg_bounds({"X": 1.2, "Y": 2.6, "Width": 10.4, "Height": 20.6}) == {
        "x": 1,
        "y": 3,
        "width": 10,
        "height": 21,
    }
    assert mac_key_parts("cmd+shift+p") == ["CMD", "SHIFT", "P"]
    assert _keysym("ENTER") == 0xFF0D
    assert _keysym("你") == 0x01000000 | ord("你")
    from local_shell_mcp.gui import linux_portal

    assert linux_portal._MODIFIERS["META"] == 0xFFEB
    assert linux_portal._MODIFIERS["META"] == linux_portal._MODIFIERS["SUPER"]


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"XDG_SESSION_TYPE": "wayland"}, "wayland"),
        ({"XDG_SESSION_TYPE": "x11"}, "x11"),
        ({"WAYLAND_DISPLAY": "wayland-0"}, "wayland"),
        ({"DISPLAY": ":0"}, "x11"),
        ({}, "unknown"),
    ],
)
def test_linux_session_detection(env, expected):
    assert _session_type(env) == expected


def test_base_helpers_and_platform_selection(monkeypatch, tmp_path):
    import local_shell_mcp.gui.base as base

    assert base._bounds_tuple(None) is None
    assert base._bounds_tuple({"x": "1", "y": 2, "width": 3, "height": 4}) == (1, 2, 3, 4)
    assert base._bounds_tuple({"x": "bad"}) is None

    image = tmp_path / "same.png"
    Image.new("RGB", (5, 6)).save(image)
    base._normalize_screenshot_coordinates(image, {})
    base._normalize_screenshot_coordinates(image, {"bounds": "bad"})
    base._normalize_screenshot_coordinates(image, {"bounds": {"width": "bad", "height": 6}})
    base._normalize_screenshot_coordinates(image, {"bounds": {"width": 0, "height": 6}})
    base._normalize_screenshot_coordinates(image, {"bounds": {"width": 5, "height": 6}})
    with Image.open(image) as opened:
        assert opened.size == (5, 6)

    monkeypatch.setattr(base.platform, "system", lambda: "Windows")
    assert base._backend_for_platform().name == "windows-uia"
    monkeypatch.setattr(base.platform, "system", lambda: "Darwin")
    assert base._backend_for_platform().name == "macos-ax"

    import local_shell_mcp.gui.linux as linux

    monkeypatch.setattr(linux, "_desktop_environment", lambda: {})
    monkeypatch.setattr(base.platform, "system", lambda: "Linux")
    assert base._backend_for_platform().name == "linux-atspi"

    monkeypatch.setattr(base.platform, "system", lambda: "Plan9")
    with pytest.raises(base.GuiUnavailableError, match="unsupported"):
        base._backend_for_platform()


@pytest.mark.asyncio
async def test_gui_manager_list_snapshot_errors_and_cache(tmp_path, monkeypatch):
    import local_shell_mcp.gui.base as base

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))

    backend = FakeBackend()
    manager = GuiManager(backend)
    assert manager.backend_name == "fake-native"
    listed = await manager.list_windows()
    assert listed["backend"] == "fake-native"

    class BrokenBackend(FakeBackend):
        async def snapshot(self, window_id, **kwargs):
            path = kwargs["screenshot_path"]
            if path:
                path.write_text("partial")
            raise RuntimeError("capture failed")

    with pytest.raises(RuntimeError, match="capture failed"):
        await GuiManager(BrokenBackend()).snapshot("window:1", screenshot=True)
    assert not list((tmp_path / ".state").rglob("gui-*.png"))

    monkeypatch.setattr(base, "GUI_STATE_CACHE_LIMIT", 2)
    for _ in range(4):
        await manager.snapshot("window:1", screenshot=False)
    assert len(manager._states) == 2


@pytest.mark.asyncio
async def test_gui_manager_bounds_window_list_metadata(monkeypatch):
    import local_shell_mcp.gui.base as base

    class ManyWindows(FakeBackend):
        async def list_windows(self):
            windows = [
                {
                    "id": f"window:{index}",
                    "title": "T" * 5000,
                    "app": "A" * 5000,
                    "pid": index,
                    "bounds": {"x": 0, "y": 0, "width": 100, "height": 100, "extra": "x"},
                    "unknown": "Z" * 10000,
                }
                for index in range(base.GUI_MAX_WINDOWS + 20)
            ]
            windows.insert(
                0,
                {
                    "id": "x" * (base.GUI_MAX_WINDOW_ID_BYTES + 1),
                    "title": "bad",
                    "bounds": {},
                },
            )
            return {"windows": windows}

    listed = await GuiManager(ManyWindows()).list_windows()
    windows = listed["windows"]
    assert len(windows) <= base.GUI_MAX_WINDOWS
    assert all(
        len(item["title"].encode("utf-8")) <= base.GUI_MAX_WINDOW_TEXT_BYTES
        for item in windows
    )
    assert all(
        len(item["app"].encode("utf-8")) <= base.GUI_MAX_WINDOW_TEXT_BYTES
        for item in windows
    )
    assert all(len(item["id"].encode("utf-8")) <= base.GUI_MAX_WINDOW_ID_BYTES for item in windows)
    assert all("unknown" not in item for item in windows)
    assert all("extra" not in item.get("bounds", {}) for item in windows)
    encoded = json.dumps(windows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert len(encoded) <= base.GUI_MAX_WINDOWS_TOTAL_BYTES


@pytest.mark.asyncio
async def test_gui_snapshot_bounds_element_metadata_before_return(tmp_path, monkeypatch):
    import local_shell_mcp.gui.base as base

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))

    class LargeMetadataBackend(FakeBackend):
        async def snapshot(
            self,
            window_id,
            *,
            screenshot_path,
            include_elements,
            max_elements,
            max_depth,
        ):
            del screenshot_path, include_elements, max_elements, max_depth
            elements = [
                {
                    "id": f"e{index}",
                    "role": "R" * 5000,
                    "name": "N" * 5000,
                    "automation_id": "I" * 5000,
                    "value": "V" * 5000,
                    "description": "D" * 5000,
                    "enabled": True,
                    "focused": index == 0,
                    "offscreen": False,
                    "depth": 3,
                    "actions": ["A" * 5000] * 40,
                    "bounds": {"x": 10, "y": 20, "width": 20, "height": 10},
                }
                for index in range(100)
            ]
            return GuiSnapshot(
                window={
                    "id": window_id,
                    "title": "Demo",
                    "bounds": dict(self.bounds),
                },
                elements=elements,
                locators={item["id"]: object() for item in elements},
            )

    manager = GuiManager(LargeMetadataBackend())
    state = await manager.snapshot("window:1", screenshot=False)
    encoded = json.dumps(
        state["elements"], ensure_ascii=False, separators=(",", ":")
    ).encode()
    assert len(encoded) <= base.GUI_MAX_ELEMENTS_TOTAL_BYTES
    assert state["elements"]
    assert all(
        len(item["name"].encode()) <= base.GUI_MAX_ELEMENT_TEXT_BYTES
        for item in state["elements"]
    )
    assert all(
        len(item["automation_id"].encode()) <= base.GUI_MAX_ELEMENT_TEXT_BYTES
        for item in state["elements"]
    )
    assert all(
        len(item["description"].encode()) <= base.GUI_MAX_ELEMENT_VALUE_BYTES
        for item in state["elements"]
    )
    assert state["elements"][0]["enabled"] is True
    assert state["elements"][0]["focused"] is True
    assert state["elements"][0]["offscreen"] is False
    assert state["elements"][0]["depth"] == 3
    assert len(state["elements"][0]["actions"]) == 32
    record = manager._states[state["state_id"]]
    assert set(record.locators) == {item["id"] for item in state["elements"]}


@pytest.mark.asyncio
async def test_gui_manager_action_validation_and_staleness(tmp_path, monkeypatch):
    import local_shell_mcp.gui.base as base

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    backend = FakeBackend()
    manager = GuiManager(backend)

    with pytest.raises(ValueError, match="at least one"):
        await manager.act("window:1", "missing", [])

    state = await manager.snapshot("window:1", screenshot=False)
    with pytest.raises(GuiStaleStateError, match="different window"):
        await manager.act("window:2", state["state_id"], [{"type": "wait"}])

    state = await manager.snapshot("window:1", screenshot=False)
    with pytest.raises(ValueError, match=r"actions\[0\]\.type"):
        await manager.act("window:1", state["state_id"], [{}])

    state = await manager.snapshot("window:1", screenshot=False)
    with pytest.raises(ValueError, match="Unknown element_id"):
        await manager.act(
            "window:1",
            state["state_id"],
            [{"type": "click", "element_id": "missing"}],
        )

    state = await manager.snapshot("window:1", screenshot=False)
    backend.bounds["x"] += 1
    with pytest.raises(GuiStaleStateError, match="moved or resized"):
        await manager.act(
            "window:1",
            state["state_id"],
            [{"type": "click", "x": 1, "y": 2}],
        )
    backend.bounds["x"] -= 1

    state = await manager.snapshot("window:1", screenshot=False)
    original_list = backend.list_windows

    async def missing_window():
        return {"windows": []}

    backend.list_windows = missing_window
    with pytest.raises(GuiStaleStateError, match="no longer available"):
        await manager.act(
            "window:1",
            state["state_id"],
            [{"type": "move", "x": 1, "y": 2}],
        )
    backend.list_windows = original_list

    state = await manager.snapshot("window:1", screenshot=False)
    backend.bounds.pop("width")
    result = await manager.act(
        "window:1",
        state["state_id"],
        [{"type": "scroll", "x": 1, "y": 2}],
    )
    assert result["actions"][0]["performed"] is True
    backend.bounds["width"] = 300

    class NoneBackend(FakeBackend):
        async def perform_action(self, window, locator, action):
            return None

    none_manager = GuiManager(NoneBackend())
    state = await none_manager.snapshot("window:1", screenshot=False)
    result = await none_manager.act("window:1", state["state_id"], [{"type": "wait"}])
    assert result["actions"] == [{"index": 0, "type": "wait"}]

    expired = await manager.snapshot("window:1", screenshot=False)
    record = manager._states[expired["state_id"]]
    record.created_at -= base.GUI_STATE_TTL_S + 1
    with pytest.raises(GuiStaleStateError, match="stale"):
        await manager.act("window:1", expired["state_id"], [{"type": "wait"}])


def test_gui_manager_singleton_helpers(monkeypatch):
    import local_shell_mcp.gui.base as base

    sentinel = object()
    monkeypatch.setattr(base, "_manager", sentinel)
    assert base.get_gui_manager() is sentinel
    base.reset_gui_manager()
    assert base._manager is None

    monkeypatch.setattr(base, "_backend_for_platform", lambda: FakeBackend())
    first = base.get_gui_manager()
    assert isinstance(first, GuiManager)
    assert base.get_gui_manager() is first
    base.reset_gui_manager()


def test_gui_tool_result_rendering_and_errors():
    import local_shell_mcp.tools as tools

    data = {
        "backend": "fake",
        "state_id": "state-1",
        "state_ttl_s": 30,
        "window": {
            "id": "w",
            "app": "Demo",
            "title": "Window",
            "bounds": {"x": 1, "y": 2, "width": 300, "height": 200},
        },
        "elements": [
            {
                "id": "e1",
                "role": "button",
                "name": "line 1\n" + ("x" * 200),
                "bounds": {"x": 4, "y": 5, "width": 6, "height": 7},
            }
        ],
        "capabilities": {"semantic_actions": True},
    }
    image = ImageFile(
        path="shot.png",
        data=b"png-bytes",
        format="png",
        mime_type="image/png",
        size=9,
    )
    result = tools._gui_state_call_result(data, "node", image)
    assert result.structuredContent["ok"] is True
    assert result.structuredContent["screenshot"] is True
    assert result.structuredContent["bytes"] == 9
    assert result.content[0].type == "image"
    assert "GUI state state-1" in result.content[1].text
    assert "Accessibility elements:" in result.content[1].text
    assert "..." in result.content[1].text

    no_image = tools._gui_state_call_result(
        {"backend": "fake", "elements": "bad", "capabilities": "bad"},
        None,
        None,
    )
    assert no_image.structuredContent["screenshot"] is False
    assert len(no_image.content) == 1

    error = tools._gui_state_error_result("node", RuntimeError("boom"))
    assert error.isError is True
    assert error.structuredContent["error_type"] == "RuntimeError"
    metadata = tools.GuiStateResult(ok=False, message="bad")
    assert tools._format_gui_state_text(metadata) == "Unable to observe GUI state: bad"


def test_gui_state_result_bounds_accessibility_metadata():
    import local_shell_mcp.tools as tools

    elements = [
        {
            "id": f"e{index}",
            "role": "R" * 5000,
            "name": "N" * 5000,
            "automation_id": "A" * 5000,
            "value": "V" * 10000,
            "bounds": {"x": 1, "y": 2, "width": 3, "height": 4, "extra": "ignored"},
            "enabled": True,
            "actions": ["X" * 1000] * 100,
            "depth": 1,
            "unknown": "Z" * 100000,
        }
        for index in range(100)
    ]
    result = tools._gui_state_call_result(
        {
            "backend": "fake",
            "state_id": "s",
            "state_ttl_s": 30,
            "window": {
                "id": "w" * 5000,
                "title": "T" * 5000,
                "app": "A" * 5000,
                "pid": "42",
                "bounds": {"x": 0, "y": 0, "width": 10, "height": 10, "extra": "ignored"},
                "unknown": "Z" * 100000,
            },
            "elements": elements,
            "capabilities": {},
        },
        None,
        None,
    )

    window = result.structuredContent["window"]
    assert window is not None
    assert len(window["id"].encode("utf-8")) <= tools.GUI_WINDOW_TEXT_FIELD_MAX_BYTES
    assert len(window["title"].encode("utf-8")) <= tools.GUI_WINDOW_TEXT_FIELD_MAX_BYTES
    assert len(window["app"].encode("utf-8")) <= tools.GUI_WINDOW_TEXT_FIELD_MAX_BYTES
    assert window["pid"] == 42
    assert "unknown" not in window
    assert "extra" not in window["bounds"]

    bounded = result.structuredContent["elements"]
    assert bounded
    first = bounded[0]
    assert len(first["role"].encode("utf-8")) <= tools.GUI_ELEMENT_TEXT_FIELD_MAX_BYTES
    assert len(first["name"].encode("utf-8")) <= tools.GUI_ELEMENT_TEXT_FIELD_MAX_BYTES
    assert len(first["automation_id"].encode("utf-8")) <= tools.GUI_ELEMENT_TEXT_FIELD_MAX_BYTES
    assert len(first["value"].encode("utf-8")) <= tools.GUI_ELEMENT_VALUE_FIELD_MAX_BYTES
    assert len(first["actions"]) == tools.GUI_ELEMENT_ACTION_MAX_ITEMS
    assert all(
        len(action.encode("utf-8")) <= tools.GUI_ELEMENT_ACTION_MAX_BYTES
        for action in first["actions"]
    )
    assert "unknown" not in first
    encoded = json.dumps(bounded, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert len(encoded) <= tools.GUI_ELEMENTS_TOTAL_BYTES


@pytest.mark.asyncio
async def test_gui_state_result_local_screenshot(tmp_path, monkeypatch):
    import local_shell_mcp.tools as tools

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    get_settings = tools.get_settings
    get_settings.cache_clear()

    shot = tmp_path / ".state" / "tmp" / "shot.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 6)).save(shot)

    class Manager:
        async def snapshot(self, **kwargs):
            assert kwargs["window_id"] == "w"
            return {
                "backend": "fake",
                "state_id": "s",
                "state_ttl_s": 30,
                "window": {
                    "id": "w",
                    "bounds": {"x": 0, "y": 0, "width": 8, "height": 6},
                },
                "elements": [],
                "capabilities": {},
                "screenshot_path": str(shot),
            }

    monkeypatch.setattr(tools, "get_gui_manager", lambda: Manager())
    result = await tools._gui_state_result(
        "w",
        screenshot=True,
        include_elements=True,
        max_elements=10,
        max_depth=3,
        machine=None,
    )
    assert result.isError is False
    assert result.structuredContent["screenshot"] is True
    assert not shot.exists()

    class Broken:
        async def snapshot(self, **kwargs):
            raise RuntimeError("no desktop")

    monkeypatch.setattr(tools, "get_gui_manager", lambda: Broken())
    failed = await tools._gui_state_result(
        "w",
        screenshot=False,
        include_elements=False,
        max_elements=1,
        max_depth=1,
        machine=None,
    )
    assert failed.isError is True
    assert "no desktop" in failed.structuredContent["message"]


def test_gui_temp_reader_accepts_workspace_relative_internal_path(tmp_path, monkeypatch):
    import local_shell_mcp.tools as tools

    workspace = tmp_path / "workspace"
    state = workspace / ".state"
    workspace.mkdir()
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(state))
    tools.get_settings.cache_clear()

    shot = tools.temp_dir() / "relative.png"
    Image.new("RGB", (4, 4)).save(shot, format="PNG")
    display = str(shot.relative_to(workspace))

    image = tools._read_gui_temp_image(display)
    assert image.format == "png"
    tools._delete_gui_temp_file(display)
    assert not shot.exists()


@pytest.mark.asyncio
async def test_gui_screenshot_temp_can_live_outside_workspace(tmp_path, monkeypatch):
    import local_shell_mcp.tools as tools

    workspace = tmp_path / "workspace"
    state = tmp_path / "state"
    workspace.mkdir()
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(state))
    tools.get_settings.cache_clear()

    shot = tools.temp_dir() / "outside-workspace.png"
    Image.new("RGB", (4, 4)).save(shot, format="PNG")

    class Manager:
        async def frame(self, _window_id):
            return {
                "backend": "fake",
                "window": {"id": "w", "bounds": {"x": 0, "y": 0, "width": 4, "height": 4}},
                "capabilities": {},
                "screenshot_path": str(shot),
            }

    monkeypatch.setattr(tools, "get_gui_manager", lambda: Manager())
    data, image = await tools._gui_frame_data("w", None)
    assert data["backend"] == "fake"
    assert image.format == "png"
    assert not shot.exists()


@pytest.mark.asyncio
async def test_gui_state_result_remote_screenshot_and_cleanup(tmp_path, monkeypatch):
    import local_shell_mcp.tools as tools

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "true")
    tools.get_settings.cache_clear()
    calls = []

    async def remote_worker(machine, tool, args, timeout_s=None):
        calls.append((machine, tool, args, timeout_s))
        if tool == "gui_state":
            return {
                "backend": "remote",
                "state_id": "s",
                "state_ttl_s": 30,
                "window": {"id": "w", "bounds": {"x": 0, "y": 0, "width": 4, "height": 4}},
                "elements": [],
                "capabilities": {},
                "screenshot_path": ".local-shell-mcp/tmp/remote.png",
            }
        if tool == "gui_state_refresh":
            return {"state_id": "s", "state_ttl_s": 30}
        return {"deleted": True}

    transfer_calls = []

    async def remote_transfer(machine, tool, args, timeout_s=None):
        transfer_calls.append((machine, tool, args, timeout_s))
        return {"deleted": True}

    async def copy_remote_gui_temp(machine, source, destination):
        del machine, source
        Image.new("RGB", (4, 4)).save(destination, format="PNG")
        return {"bytes": 7}

    monkeypatch.setattr(tools, "_remote_worker_data", remote_worker)
    monkeypatch.setattr(tools, "_remote_transfer_data", remote_transfer)
    monkeypatch.setattr(tools, "_copy_remote_gui_temp_to_local", copy_remote_gui_temp)
    monkeypatch.setattr(
        tools,
        "transfer_alloc_temp_path",
        lambda suffix: {
            "path": str(tools.temp_dir() / f"temporary{suffix}")
        },
    )

    result = await tools._gui_state_result(
        "w",
        screenshot=True,
        include_elements=True,
        max_elements=10,
        max_depth=3,
        machine="node",
    )
    assert result.isError is False
    assert result.structuredContent["machine"] == "node"
    assert result.structuredContent["screenshot"] is True
    assert [call[1] for call in calls] == [
        "gui_state",
        "gui_state_refresh",
        "gui_state_refresh",
    ]
    assert [call[1] for call in transfer_calls] == ["transfer_gui_temp_delete"]

    calls.clear()
    monkeypatch.setattr(tools, "_REMOTE_GUI_STATE_REFRESH_INTERVAL_S", 0.001)

    async def slow_copy(machine, source, destination):
        del machine, source
        await asyncio.sleep(0.01)
        Image.new("RGB", (4, 4)).save(destination, format="PNG")
        return {"bytes": 7}

    monkeypatch.setattr(tools, "_copy_remote_gui_temp_to_local", slow_copy)
    kept_alive = await tools._gui_state_result(
        "w",
        screenshot=True,
        include_elements=False,
        max_elements=1,
        max_depth=1,
        machine="node",
    )
    assert kept_alive.isError is False
    refresh_calls = [call for call in calls if call[1] == "gui_state_refresh"]
    assert len(refresh_calls) >= 3

    async def invalid_refresh(*_args, **_kwargs):
        return "bad"

    monkeypatch.setattr(tools, "_remote_worker_data", invalid_refresh)
    with pytest.raises(RuntimeError, match="invalid data"):
        await tools._refresh_remote_gui_state_once("node", "w", "s")
    with pytest.raises(RuntimeError, match="invalid data"):
        await tools._refresh_remote_gui_frame_once("node", "w", "obs")
    monkeypatch.setattr(tools, "_REMOTE_GUI_STATE_REFRESH_INTERVAL_S", 0)
    with pytest.raises(RuntimeError, match="invalid data"):
        await tools._refresh_remote_gui_state_lease("node", "w", "s")
    with pytest.raises(RuntimeError, match="invalid data"):
        await tools._refresh_remote_gui_frame_lease("node", "w", "obs")

    async def invalid_remote(*args, **kwargs):
        return "bad"

    monkeypatch.setattr(tools, "_remote_worker_data", invalid_remote)
    failed = await tools._gui_state_result(
        "w",
        screenshot=False,
        include_elements=False,
        max_elements=1,
        max_depth=1,
        machine="node",
    )
    assert failed.isError is True
    assert "invalid data" in failed.structuredContent["message"]

def test_controller_gui_staging_stays_inside_workspace_with_external_state_dir(
    tmp_path, monkeypatch
):
    import local_shell_mcp.tools as tools

    workspace = tmp_path / "workspace"
    state = tmp_path / "state"
    workspace.mkdir()
    state.mkdir()
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(state))
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER_ACCESS", "false")
    tools.get_settings.cache_clear()

    staging = Path(tools._controller_gui_staging_path())
    staging.relative_to(workspace)
    assert staging.parent == workspace / ".local-shell-mcp" / "gui-relay"
    assert not staging.is_relative_to(state)


def test_controller_gui_staging_rejects_symlink(tmp_path, monkeypatch):
    import local_shell_mcp.tools as tools

    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    parent = workspace / ".local-shell-mcp"
    parent.mkdir()
    (parent / "gui-relay").symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(workspace))
    tools.get_settings.cache_clear()

    with pytest.raises(ValueError, match="must not be a symlink"):
        tools._controller_gui_staging_path()


@pytest.mark.asyncio
async def test_copy_remote_gui_temp_rejects_oversized_source_before_transfer(monkeypatch):
    import local_shell_mcp.tools as tools

    async def remote_transfer(_machine, tool, _args, timeout_s=None):
        del timeout_s
        assert tool == "transfer_gui_temp_stat"
        return {
            "type": "file",
            "size": tools.MAX_VIEW_IMAGE_BYTES + 1,
            "path": "gui.png",
        }

    monkeypatch.setattr(tools, "_remote_transfer_data", remote_transfer)
    monkeypatch.setattr(
        tools,
        "create_upload_ticket",
        lambda *_args, **_kwargs: pytest.fail(
            "oversized screenshot must be rejected before staging"
        ),
    )
    with pytest.raises(ValueError, match="Refusing image"):
        await tools._copy_remote_gui_temp_to_local("node", "gui.png", "unused.png")


@pytest.mark.asyncio
async def test_copy_remote_gui_temp_to_local_uses_internal_transfer_tools(tmp_path, monkeypatch):
    import local_shell_mcp.tools as tools

    calls = []
    ticket = {"token": "t", "url": "https://controller/remote/transfer/t"}

    async def remote_transfer(machine, tool, args, timeout_s=None):
        calls.append((machine, tool, args, timeout_s))
        assert tool == "transfer_gui_temp_stat"
        return {"type": "file", "size": 7, "path": args["path"]}

    async def stream(
        src_machine,
        src_path,
        total_bytes,
        expected_sha256,
        actual_ticket,
        progress=None,
        *,
        put_tool="transfer_put_url",
        stat_tool="transfer_stat",
    ):
        del progress
        calls.append(
            (
                "stream",
                src_machine,
                src_path,
                total_bytes,
                expected_sha256,
                actual_ticket,
                put_tool,
                stat_tool,
            )
        )
        return {"path": str(tmp_path / "out.png"), "sha256": "digest"}

    revoked = []
    monkeypatch.setattr(tools, "_remote_transfer_data", remote_transfer)
    monkeypatch.setattr(tools, "create_upload_ticket", lambda *_args, **_kwargs: ticket)
    monkeypatch.setattr(tools, "_stream_remote_file_to_upload_ticket", stream)
    monkeypatch.setattr(tools, "revoke_transfer_ticket", revoked.append)

    result = await tools._copy_remote_gui_temp_to_local(
        "node",
        "/outside/workspace/gui-" + "a" * 32 + ".png",
        str(tmp_path / "out.png"),
    )
    assert result["bytes"] == 7
    assert result["transport"] == "http-stream"
    assert calls[0][1] == "transfer_gui_temp_stat"
    assert calls[1][-2:] == ("transfer_gui_temp_put_url", "transfer_gui_temp_stat")
    assert revoked == ["t"]


@pytest.mark.asyncio
async def test_gui_frame_data_local_and_remote_paths(tmp_path, monkeypatch):
    import local_shell_mcp.tools as tools
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "true")
    tools.get_settings.cache_clear()

    local_shot = tools.temp_dir() / "local-frame.png"
    Image.new("RGB", (4, 4)).save(local_shot, format="PNG")

    class Manager:
        async def frame(self, window_id):
            assert window_id == "w"
            return {
                "backend": "local",
                "window": {"id": "w", "bounds": {"x": 0, "y": 0, "width": 4, "height": 4}},
                "capabilities": {},
                "screenshot_path": str(local_shot),
            }

    monkeypatch.setattr(tools, "get_gui_manager", lambda: Manager())

    local_data, local_image = await tools._gui_frame_data("w", None)
    assert local_data["backend"] == "local"
    assert "screenshot_path" not in local_data
    assert local_image.format == "png"
    assert not local_shot.exists()

    calls = []

    async def remote_worker(machine, tool, args, timeout_s=None):
        calls.append((machine, tool, args, timeout_s))
        if tool == "gui_frame":
            return {
                "backend": "remote",
                "observation_id": "obs-remote",
                "window": {"id": "w", "bounds": {"x": 0, "y": 0, "width": 4, "height": 4}},
                "capabilities": {},
                "screenshot_path": ".local-shell-mcp/tmp/frame.png",
            }
        if tool == "gui_frame_refresh":
            return {"observation_id": "obs-remote", "observation_ttl_s": 30}
        raise AssertionError(f"unexpected worker tool: {tool}")

    transfer_calls = []

    async def remote_transfer(machine, tool, args, timeout_s=None):
        transfer_calls.append((machine, tool, args, timeout_s))
        return {"deleted": True}

    async def copy_remote_gui_temp(machine, source, destination):
        assert machine == "node"
        del source
        Image.new("RGB", (4, 4)).save(destination, format="PNG")
        return {"bytes": 5}

    monkeypatch.setattr(tools, "_remote_worker_data", remote_worker)
    monkeypatch.setattr(tools, "_remote_transfer_data", remote_transfer)
    monkeypatch.setattr(tools, "_copy_remote_gui_temp_to_local", copy_remote_gui_temp)
    monkeypatch.setattr(
        tools,
        "transfer_alloc_temp_path",
        lambda suffix: {"path": str(tools.temp_dir() / f"relay{suffix}")},
    )

    remote_data, remote_image = await tools._gui_frame_data("w", "node")
    assert remote_data["backend"] == "remote"
    assert remote_data["observation_id"] == "obs-remote"
    assert remote_data["observation_ttl_s"] == 30
    assert "screenshot_path" not in remote_data
    assert remote_image.format == "png"
    assert [call[1] for call in calls] == ["gui_frame", "gui_frame_refresh"]
    assert [call[1] for call in transfer_calls] == ["transfer_gui_temp_delete"]
    assert not (tools.temp_dir() / "relay.png").exists()


@pytest.mark.asyncio
async def test_gui_frame_data_renews_remote_observation_during_slow_transfer(
    tmp_path,
    monkeypatch,
):
    import local_shell_mcp.tools as tools

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "true")
    monkeypatch.setattr(tools, "_REMOTE_GUI_STATE_REFRESH_INTERVAL_S", 0.01)
    tools.get_settings.cache_clear()
    calls = []

    async def remote_worker(machine, tool, args, timeout_s=None):
        calls.append((machine, tool, args, timeout_s))
        if tool == "gui_frame":
            return {
                "backend": "remote",
                "observation_id": "obs-slow",
                "window": {
                    "id": "w",
                    "bounds": {"x": 0, "y": 0, "width": 4, "height": 4},
                },
                "capabilities": {},
                "screenshot_path": ".local-shell-mcp/tmp/slow-frame.png",
            }
        if tool == "gui_frame_refresh":
            return {"observation_id": "obs-slow", "observation_ttl_s": 30}
        raise AssertionError(f"unexpected worker tool: {tool}")

    async def remote_transfer(*_args, **_kwargs):
        return {"deleted": True}

    async def slow_copy(_machine, _source, destination):
        await asyncio.sleep(0.035)
        Image.new("RGB", (4, 4)).save(destination, format="PNG")
        return {"bytes": 5}

    monkeypatch.setattr(tools, "_remote_worker_data", remote_worker)
    monkeypatch.setattr(tools, "_remote_transfer_data", remote_transfer)
    monkeypatch.setattr(tools, "_copy_remote_gui_temp_to_local", slow_copy)
    monkeypatch.setattr(
        tools,
        "transfer_alloc_temp_path",
        lambda suffix: {"path": str(tools.temp_dir() / f"slow-relay{suffix}")},
    )

    data, image = await tools._gui_frame_data("w", "node")

    assert data["observation_id"] == "obs-slow"
    assert image.format == "png"
    refreshes = [call for call in calls if call[1] == "gui_frame_refresh"]
    assert len(refreshes) >= 2


@pytest.mark.asyncio
async def test_gui_frame_data_rejects_invalid_sources(tmp_path, monkeypatch):
    import local_shell_mcp.tools as tools

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))

    class MissingLocal:
        async def frame(self, _window_id):
            return {"window": {"id": "w"}}

    monkeypatch.setattr(tools, "get_gui_manager", lambda: MissingLocal())
    with pytest.raises(RuntimeError, match="no screenshot"):
        await tools._gui_frame_data("w", None)

    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    tools.get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="disabled"):
        await tools._gui_frame_data("w", "node")

    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "true")
    tools.get_settings.cache_clear()

    async def invalid_remote(*_args, **_kwargs):
        return "bad"

    monkeypatch.setattr(tools, "_remote_worker_data", invalid_remote)
    with pytest.raises(RuntimeError, match="invalid data"):
        await tools._gui_frame_data("w", "node")

    async def no_screenshot(*_args, **_kwargs):
        return {"window": {"id": "w"}}

    monkeypatch.setattr(tools, "_remote_worker_data", no_screenshot)
    with pytest.raises(RuntimeError, match="no screenshot"):
        await tools._gui_frame_data("w", "node")

    async def no_observation(*_args, **_kwargs):
        return {"window": {"id": "w"}, "screenshot_path": "remote.png"}

    monkeypatch.setattr(tools, "_remote_worker_data", no_observation)
    with pytest.raises(RuntimeError, match="no observation_id"):
        await tools._gui_frame_data("w", "node")

    async def remote_frame(*_args, **_kwargs):
        return {"window": {"id": "w"}, "screenshot_path": "remote.png"}

    cleanup_calls = []

    async def remote_frame_with_cleanup(machine, tool, args, timeout_s=None):
        if tool == "gui_frame":
            return {
                "window": {"id": "w"},
                "observation_id": "obs-cleanup",
                "screenshot_path": "remote.png",
            }
        if tool == "gui_frame_refresh":
            return {"observation_id": "obs-cleanup", "observation_ttl_s": 30}
        raise AssertionError(f"unexpected worker tool: {tool}")

    async def remote_transfer(machine, tool, args, timeout_s=None):
        cleanup_calls.append((machine, tool, args, timeout_s))
        return {"deleted": True}

    async def bad_copy(*_args, **_kwargs):
        raise RuntimeError("Remote GUI temp source is not a file")

    monkeypatch.setattr(tools, "_remote_worker_data", remote_frame_with_cleanup)
    monkeypatch.setattr(tools, "_remote_transfer_data", remote_transfer)
    monkeypatch.setattr(tools, "_copy_remote_gui_temp_to_local", bad_copy)
    with pytest.raises(RuntimeError, match="not a file"):
        await tools._gui_frame_data("w", "node")
    assert cleanup_calls == [
        (
            "node",
            "transfer_gui_temp_delete",
            {"path": "remote.png"},
            30,
        )
    ]


def test_native_gui_optional_dependency_guards_are_platform_safe():
    import sys

    if sys.platform == "win32":
        from local_shell_mcp.gui.windows import _automation

        try:
            auto = _automation()
        except GuiUnavailableError:
            return
        assert auto is not None
        return

    if sys.platform == "darwin":
        from local_shell_mcp.gui.macos import _native

        try:
            ax, quartz = _native()
        except GuiUnavailableError:
            return
        assert ax is not None
        assert quartz is not None
        return

    if sys.platform.startswith("linux"):
        from local_shell_mcp.gui.linux_portal import _portal_modules

        try:
            message_bus, variant = _portal_modules()
        except GuiUnavailableError:
            return
        assert message_bus is not None
        assert variant is not None


@pytest.mark.asyncio
async def test_gui_manager_cleans_missing_or_invalid_backend_screenshots(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))

    class NoScreenshotBackend(FakeBackend):
        async def snapshot(self, window_id, **kwargs):
            return GuiSnapshot(
                window={
                    "id": "window:1",
                    "title": "Demo",
                    "app": "demo",
                    "pid": 1,
                    "bounds": dict(self.bounds),
                },
                elements=[],
                screenshot_path=None,
            )

    state = await GuiManager(NoScreenshotBackend()).snapshot("window:1", screenshot=True)
    assert state["screenshot_path"] is None
    assert not list((tmp_path / ".state").rglob("gui-*.png"))

    class MissingFileBackend(FakeBackend):
        async def snapshot(self, window_id, **kwargs):
            return GuiSnapshot(
                window={
                    "id": "window:1",
                    "title": "Demo",
                    "app": "demo",
                    "pid": 1,
                    "bounds": dict(self.bounds),
                },
                elements=[],
                screenshot_path="claimed.png",
            )

    with pytest.raises(GuiUnavailableError, match="did not produce"):
        await GuiManager(MissingFileBackend()).snapshot("window:1", screenshot=True)

    class InvalidImageBackend(FakeBackend):
        async def snapshot(self, window_id, **kwargs):
            path = kwargs["screenshot_path"]
            path.write_bytes(b"not-an-image")
            return GuiSnapshot(
                window={
                    "id": "window:1",
                    "title": "Demo",
                    "app": "demo",
                    "pid": 1,
                    "bounds": dict(self.bounds),
                },
                elements=[],
                screenshot_path=str(path),
            )

    with pytest.raises(UnidentifiedImageError):
        await GuiManager(InvalidImageBackend()).snapshot("window:1", screenshot=True)
    assert not list((tmp_path / ".state").rglob("gui-*.png"))


@pytest.mark.asyncio
async def test_gui_manager_rechecks_geometry_before_each_coordinate_action(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))

    class MovingBackend(FakeBackend):
        async def perform_action(self, window, locator, action):
            result = await super().perform_action(window, locator, action)
            if action["type"] == "wait":
                self.bounds["x"] += 5
            return result

    backend = MovingBackend()
    manager = GuiManager(backend)
    state = await manager.snapshot("window:1", screenshot=False)

    with pytest.raises(GuiStaleStateError, match="moved or resized"):
        await manager.act(
            "window:1",
            state["state_id"],
            [
                {"type": "wait", "seconds": 0},
                {"type": "click", "x": 10, "y": 10},
            ],
        )
    assert [action[2]["type"] for action in backend.actions] == ["wait"]


@pytest.mark.asyncio
async def test_gui_manager_checks_element_actions_that_can_fall_back_to_coordinates(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    backend = FakeBackend()
    manager = GuiManager(backend)
    state = await manager.snapshot("window:1", screenshot=False)
    backend.bounds["y"] += 7

    with pytest.raises(GuiStaleStateError, match="moved or resized"):
        await manager.act(
            "window:1",
            state["state_id"],
            [{"type": "click", "element_id": "e1"}],
        )
    assert backend.actions == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action",
    [
        {"type": "click", "x": -1, "y": 0},
        {"type": "move", "x": 300, "y": 0},
        {"type": "scroll", "x": 0, "y": 200, "delta_y": -1},
        {"type": "drag", "x": 1, "y": 1, "to_x": 300, "to_y": 10},
    ],
)
async def test_gui_manager_rejects_points_outside_selected_window(
    tmp_path, monkeypatch, action
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    backend = FakeBackend()
    manager = GuiManager(backend)
    state = await manager.snapshot("window:1", screenshot=False)

    with pytest.raises(ValueError, match="outside the selected window"):
        await manager.act("window:1", state["state_id"], [action])
    assert backend.actions == []


@pytest.mark.asyncio
async def test_gui_manager_refreshes_remote_state_ttl(tmp_path, monkeypatch):
    import local_shell_mcp.gui.base as base

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    manager = GuiManager(FakeBackend())
    state = await manager.snapshot("window:1", screenshot=False)
    record = manager._states[state["state_id"]]
    record.created_at -= base.GUI_STATE_TTL_S - 1

    refreshed = await manager.refresh_state("window:1", state["state_id"])
    assert refreshed["state_ttl_s"] == base.GUI_STATE_TTL_S
    assert record.created_at > 0
    result = await manager.act(
        "window:1",
        state["state_id"],
        [{"type": "wait", "seconds": 0}],
    )
    assert result["state_consumed"] is True


def test_scroll_quantization_and_platform_key_edge_cases():
    assert quantize_scroll_amount(0) == 0
    assert quantize_scroll_amount(-0.5) == -1
    assert quantize_scroll_amount(0.5) == 1
    assert quantize_scroll_amount(-101) == -100
    assert _MAC_KEY_CODES["BACKSPACE"] == 51
    assert _MAC_KEY_CODES["DELETE"] == 117
    assert _rect_dict(None) == {"x": 0, "y": 0, "width": 0, "height": 0}


def test_mixed_dpi_desktop_crop_uses_each_monitor_scale():
    monitors = [
        {"x": 0, "y": 0, "width": 1920, "height": 1080, "scale": 1},
        {"x": 1920, "y": 0, "width": 1280, "height": 720, "scale": 2},
    ]
    bounds = {"x": 2020, "y": 100, "width": 200, "height": 100}

    assert _desktop_crop_box(bounds, monitors, (4480, 1440)) == (
        2120,
        200,
        2520,
        400,
    )
    assert _desktop_crop_box(bounds, monitors, (3200, 1080)) == (
        2020,
        100,
        2220,
        200,
    )


def test_fractional_wayland_desktop_crop_infers_capture_ratio():
    monitors = [
        {"x": 0, "y": 0, "width": 1920, "height": 1080, "scale": 1},
    ]
    bounds = {"x": 100, "y": 50, "width": 200, "height": 100}
    assert _desktop_crop_box(bounds, monitors, (2880, 1620)) == (
        150,
        75,
        450,
        225,
    )


def test_atspi_window_identity_survives_child_reordering(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    class Window:
        def __init__(self, title, stable_id):
            self.title = title
            self.stable_id = stable_id

        def get_name(self):
            return self.title

        def get_role_name(self):
            return "frame"

        def get_accessible_id(self):
            return self.stable_id

    class App:
        def __init__(self, children):
            self.children = children

        def get_process_id(self):
            return 42

        def get_child_count(self):
            return len(self.children)

        def get_child_at_index(self, index):
            return self.children[index]

    target = Window("Target", "target-window")
    other = Window("Other", "other-window")
    monkeypatch.setattr(
        helper,
        "_bounds",
        lambda window: {
            "x": 100 if window is target else 400,
            "y": 50,
            "width": 300,
            "height": 200,
        },
    )
    signature = helper._window_signature(target)
    target.title = "Target — changed"
    assert helper._window_signature(target) == signature
    app = App([other, target])
    monkeypatch.setattr(helper, "_apps", lambda: [app])

    _app, resolved, index = helper._resolve_window(f"atspi:42:0:{signature}")
    assert resolved is target
    assert index == 1

    monkeypatch.setattr(
        helper,
        "_bounds",
        lambda _window: {"x": 0, "y": 0, "width": 300, "height": 200},
    )
    replacement_signature = helper._window_signature(target)
    replacement = Window("Replacement", "replacement-window")
    app.children = [replacement]
    with pytest.raises(LookupError, match="no longer available"):
        helper._resolve_window(f"atspi:42:0:{replacement_signature}")

    duplicate = Window("Target copy", "target-window")
    app.children = [target, duplicate]
    ambiguous_signature = helper._window_signature(target)
    with pytest.raises(LookupError, match="ambiguous"):
        helper._resolve_window(f"atspi:42:0:{ambiguous_signature}")


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
        rect = windows.ctypes.cast(
            rect_ptr, windows.ctypes.POINTER(windows._WinRect)
        ).contents
        rect.left = 0
        rect.top = 0
        rect.right = windows.GUI_MAX_CAPTURE_DIMENSION + 1
        rect.bottom = 10
        return 1

    class User32:
        GetWindowRect = Fn(get_window_rect)
        IsIconic = Fn(lambda _hwnd: 0)
        GetWindowDC = Fn(
            lambda _hwnd: pytest.fail(
                "GetWindowDC must not run for oversized windows"
            )
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
        rect = windows.ctypes.cast(
            rect_ptr, windows.ctypes.POINTER(windows._WinRect)
        ).contents
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
    monkeypatch.setattr(backend, "_find_window", lambda _window_id: window)
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

        def GetChildren(self):
            return self.children

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
            return []

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
            return [self.child]

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
    child_id = next(
        item["id"] for item in snapshot.elements if item["automation_id"] == "save"
    )
    locator = snapshot.locators[child_id]
    child.Name = "Delete"

    with pytest.raises(LookupError, match="changed since observation"):
        backend._perform_action_sync(
            record,
            locator,
            {"type": "click"},
        )


def test_atspi_window_without_stable_accessible_id_is_not_exposed():
    import local_shell_mcp.gui.linux_atspi_helper as helper

    class Window:
        def get_accessible_id(self):
            return ""

        def get_role_name(self):
            return "frame"

        def get_name(self):
            return "Mutable"

    class App:
        def get_process_id(self):
            return 42

        def get_name(self):
            return "App"

    window = Window()
    assert helper._window_signature(window) is None
    with pytest.raises(LookupError, match="stable accessible id"):
        helper._record(App(), window, 0)


def test_atspi_public_window_id_ignores_sibling_index(monkeypatch):
    import local_shell_mcp.gui.linux_atspi_helper as helper

    class Window:
        def get_accessible_id(self):
            return "stable-window"

        def get_role_name(self):
            return "frame"

        def get_name(self):
            return "Target"

    class App:
        def __init__(self, children):
            self.children = children

        def get_process_id(self):
            return 42

        def get_name(self):
            return "App"

        def get_child_count(self):
            return len(self.children)

        def get_child_at_index(self, index):
            return self.children[index]

    target = Window()
    other = Window()
    other.get_accessible_id = lambda: "other-window"
    app = App([target, other])
    monkeypatch.setattr(helper, "_apps", lambda: [app])
    monkeypatch.setattr(
        helper,
        "_bounds",
        lambda _window: {"x": 0, "y": 0, "width": 100, "height": 100},
    )

    first_id = helper._record(app, target, 0)["id"]
    app.children = [other, target]
    second_id = helper._record(app, target, 1)["id"]
    assert first_id == second_id
    assert first_id.count(":") == 2
    _resolved_app, resolved, index = helper._resolve_window(first_id)
    assert resolved is target
    assert index == 1


def test_windows_control_mouse_fallback_focuses_verified_window(monkeypatch):
    import local_shell_mcp.gui.windows as windows

    calls = []

    class Locator:
        def GetInvokePattern(self):
            return None

        def Click(self, waitTime=0):
            calls.append(("click", waitTime))

    class Target:
        def SetFocus(self):
            calls.append(("focus",))

    backend = WindowsGuiBackend()
    monkeypatch.setattr(windows, "_automation", lambda: SimpleNamespace())
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
        {"type": "click"},
    )
    assert result == {"semantic": True, "method": "control"}
    assert calls == [("focus",), ("click", 0)]


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
        thread_id
        for kind, thread_id in calls
        if kind in {"list", "snapshot", "action"}
    ]
    assert len(init_threads) == 1
    assert len(set(operation_threads)) == 1
    assert operation_threads[0] == init_threads[0]
    assert operation_threads[0] != main_thread


@pytest.mark.asyncio
async def test_macos_native_traversal_is_offloaded(monkeypatch):
    import local_shell_mcp.gui.macos as macos

    backend = MacOSGuiBackend()
    calls = []

    async def fake_to_thread(func, *args, **kwargs):
        calls.append(func.__name__)
        return func(*args, **kwargs)

    monkeypatch.setattr(macos.asyncio, "to_thread", fake_to_thread)
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
async def test_gui_state_cancellation_cleans_late_capture(tmp_path, monkeypatch):
    import local_shell_mcp.gui.base as base

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(base, "temp_dir", lambda: tmp_path)
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowBackend(FakeBackend):
        async def snapshot(self, window_id, **kwargs):
            path = kwargs["screenshot_path"]
            started.set()
            await release.wait()
            Image.new("RGB", (300, 200)).save(path)
            return GuiSnapshot(
                window={"id": window_id, "bounds": dict(self.bounds)},
                elements=[],
                screenshot_path=str(path),
            )

    manager = GuiManager(SlowBackend())
    task = asyncio.create_task(manager.snapshot("window:1", screenshot=True))
    await started.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert list(tmp_path.glob("gui-*.png")) == []
    assert manager._states == {}


def test_screenshot_normalization_rejects_oversized_provider_dimensions(tmp_path):
    import local_shell_mcp.gui.base as base

    path = tmp_path / "small.png"
    Image.new("RGB", (4, 4)).save(path)
    with pytest.raises(GuiUnavailableError, match="safe screenshot budget"):
        base._normalize_screenshot_coordinates(
            path,
            {
                "bounds": {
                    "width": base.GUI_MAX_CAPTURE_DIMENSION + 1,
                    "height": 4,
                }
            },
        )
    assert Image.open(path).size == (4, 4)


def test_screenshot_normalization_rejects_oversized_actual_image_before_decode(
    tmp_path,
    monkeypatch,
):
    import local_shell_mcp.gui.base as base

    class OversizedImage:
        size = (base.GUI_MAX_CAPTURE_DIMENSION + 1, 1)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def load(self):
            pytest.fail("oversized screenshot must be rejected before pixel decode")

    monkeypatch.setattr(base.Image, "open", lambda _path: OversizedImage())
    with pytest.raises(GuiUnavailableError, match="safe screenshot budget"):
        base._normalize_screenshot_coordinates(
            tmp_path / "oversized.png",
            {"bounds": {"width": 10, "height": 10}},
        )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits are not enforced on Windows")
@pytest.mark.asyncio
async def test_gui_screenshots_use_private_permissions(tmp_path, monkeypatch):
    import local_shell_mcp.gui.base as base

    monkeypatch.setattr(base, "temp_dir", lambda: tmp_path)
    manager = GuiManager(FakeBackend())

    state = await manager.snapshot("window:1", screenshot=True)
    screenshot = Path(state["screenshot_path"])
    try:
        assert tmp_path.stat().st_mode & 0o777 == 0o700
        assert screenshot.stat().st_mode & 0o777 == 0o600
    finally:
        screenshot.unlink(missing_ok=True)

    frame = await manager.frame("window:1")
    frame_path = Path(frame["screenshot_path"])
    try:
        assert frame_path.stat().st_mode & 0o777 == 0o600
    finally:
        frame_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_gui_frame_holds_temp_lease_until_consumer_cleanup(tmp_path, monkeypatch):
    import local_shell_mcp.gui.base as base
    import local_shell_mcp.tools as tools

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(base, "temp_dir", lambda: tmp_path)
    acquired = []
    released = []
    monkeypatch.setattr(base, "acquire_temp_file_lease", lambda path: acquired.append(path) or True)
    monkeypatch.setattr(base, "release_temp_file_lease", lambda path: released.append(path))
    monkeypatch.setattr(tools, "temp_dir", lambda: tmp_path)
    monkeypatch.setattr(tools, "release_temp_file_lease", lambda path: released.append(path))

    manager = GuiManager(FakeBackend())
    frame = await manager.frame("window:1")
    path = Path(frame["screenshot_path"])
    assert acquired == [path]
    assert released == []
    tools._delete_gui_temp_file(str(path))
    assert released == [path]


@pytest.mark.asyncio
async def test_gui_frame_cancellation_waits_for_normalization_before_cleanup(tmp_path, monkeypatch):
    import local_shell_mcp.gui.base as base

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(base, "temp_dir", lambda: tmp_path)
    backend = FakeBackend()
    manager = GuiManager(backend)
    started = threading.Event()
    release = threading.Event()
    original = base._normalize_screenshot_coordinates

    def slow_normalize(path, window):
        started.set()
        release.wait(timeout=2)
        original(path, window)

    monkeypatch.setattr(base, "_normalize_screenshot_coordinates", slow_normalize)
    task = asyncio.create_task(manager.frame("window:1"))
    assert await asyncio.to_thread(started.wait, 1)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert list(tmp_path.glob("gui-frame-*.png")) == []


@pytest.mark.asyncio
async def test_gui_action_rechecks_state_ttl_after_execution_queue(tmp_path, monkeypatch):
    import local_shell_mcp.gui.base as base

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(base, "GUI_STATE_TTL_S", 0.02)
    backend = FakeBackend()
    manager = GuiManager(backend)
    state = await manager.snapshot("window:1", screenshot=False)

    await manager._execution_lock.acquire()
    task = asyncio.create_task(
        manager.act(
            "window:1",
            state["state_id"],
            [{"type": "click", "x": 1, "y": 1}],
        )
    )
    await asyncio.sleep(0.04)
    manager._execution_lock.release()

    with pytest.raises(GuiStaleStateError, match="stale"):
        await task
    assert backend.actions == []


@pytest.mark.asyncio
async def test_gui_action_rechecks_state_ttl_between_batch_actions(tmp_path, monkeypatch):
    import local_shell_mcp.gui.base as base

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(base, "GUI_STATE_TTL_S", 0.02)

    class WaitBackend(FakeBackend):
        async def perform_action(self, window, locator, action):
            self.actions.append((window, locator, action))
            if action["type"] == "wait":
                await asyncio.sleep(float(action["seconds"]))
            return {"performed": True}

    backend = WaitBackend()
    manager = GuiManager(backend)
    state = await manager.snapshot("window:1", screenshot=False)
    with pytest.raises(GuiStaleStateError, match="expired during action batch"):
        await manager.act(
            "window:1",
            state["state_id"],
            [
                {"type": "wait", "seconds": 0.03},
                {"type": "click", "x": 1, "y": 1},
            ],
        )
    assert [action[2]["type"] for action in backend.actions] == ["wait"]


@pytest.mark.asyncio
async def test_gui_frame_cancellation_cleans_late_capture(tmp_path, monkeypatch):
    import local_shell_mcp.gui.base as base

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(base, "temp_dir", lambda: tmp_path)
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowBackend(FakeBackend):
        async def snapshot(self, window_id, **kwargs):
            path = kwargs["screenshot_path"]
            started.set()
            await release.wait()
            Image.new("RGB", (300, 200)).save(path)
            return GuiSnapshot(
                window={"id": window_id, "bounds": dict(self.bounds)},
                elements=[],
                screenshot_path=str(path),
            )

    manager = GuiManager(SlowBackend())
    task = asyncio.create_task(manager.frame("window:1"))
    await started.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert list(tmp_path.glob("gui-frame-*.png")) == []


@pytest.mark.asyncio
async def test_gui_manager_validation_and_refresh_error_paths(tmp_path, monkeypatch):
    import local_shell_mcp.gui.base as base

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    manager = GuiManager(FakeBackend())

    for action, message in [
        ({"type": "click", "x": 1}, "both x and y"),
        ({"type": "click"}, "requires x and y"),
        ({"type": "drag", "x": 1, "y": 1}, "requires to_x and to_y"),
    ]:
        state = await manager.snapshot("window:1", screenshot=False)
        with pytest.raises(ValueError, match=message):
            await manager.act("window:1", state["state_id"], [action])

    with pytest.raises(GuiStaleStateError, match="stale"):
        await manager.refresh_state("window:1", "missing")

    state = await manager.snapshot("window:1", screenshot=False)
    with pytest.raises(GuiStaleStateError, match="different window"):
        await manager.refresh_state("window:2", state["state_id"])

    with pytest.raises(ValueError, match="invalid bounds"):
        base._validate_window_relative_point({}, 0, 0, label="point")
    with pytest.raises(ValueError, match="integer x and y"):
        base._validate_window_relative_point(
            {"bounds": {"x": 0, "y": 0, "width": 10, "height": 10}},
            "bad",
            0,
            label="point",
        )

    elements = [{"id": "e1", "bounds": {"x": 3, "y": 4, "width": 5, "height": 6}}]
    assert base._window_relative_elements(elements, {}) == elements


@pytest.mark.asyncio
async def test_gui_manager_human_actions_validate_observed_geometry(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    backend = FakeBackend()
    manager = GuiManager(backend)
    observed = dict(backend.bounds)
    observation_id = _install_frame_observation(manager, backend)

    result = await manager.human_act(
        "window:1",
        observation_id,
        observed,
        [
            {"type": "click", "x": 10, "y": 12},
            {"type": "type", "text": "hello"},
        ],
    )

    assert result["human_control"] is True
    assert [item["type"] for item in result["actions"]] == ["click", "type"]
    assert [item[2]["type"] for item in backend.actions] == [
        "focus_window",
        "click",
        "focus_window",
        "type",
    ]

    backend.bounds["x"] += 1
    with pytest.raises(GuiStaleStateError, match="displayed frame"):
        await manager.human_act(
            "window:1",
            observation_id,
            observed,
            [{"type": "click", "x": 10, "y": 12}],
        )


@pytest.mark.asyncio
async def test_gui_manager_human_actions_reject_unscoped_targets(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    backend = FakeBackend()
    manager = GuiManager(backend)
    observed = dict(backend.bounds)
    observation_id = _install_frame_observation(manager, backend)

    with pytest.raises(ValueError, match="outside the selected window"):
        await manager.human_act(
            "window:1",
            observation_id,
            observed,
            [{"type": "click", "x": 999, "y": 1}],
        )
    with pytest.raises(ValueError, match="do not accept element_id"):
        await manager.human_act(
            "window:1",
            observation_id,
            observed,
            [{"type": "click", "element_id": "e1"}],
        )
    with pytest.raises(ValueError, match="Unsupported human GUI action"):
        await manager.human_act(
            "window:1",
            observation_id,
            observed,
            [{"type": "wait", "seconds": 1}],
        )
    with pytest.raises(ValueError, match="Observed window bounds"):
        await manager.human_act(
            "window:1", observation_id, {}, [{"type": "type", "text": "x"}]
        )
    missing_observation = _install_frame_observation(
        manager, backend, observation_id="missing-frame", window_id="missing"
    )
    with pytest.raises(GuiStaleStateError, match="no longer available"):
        await manager.human_act(
            "missing",
            missing_observation,
            observed,
            [{"type": "type", "text": "x"}],
        )


@pytest.mark.asyncio
async def test_gui_frame_does_not_allocate_model_state(tmp_path, monkeypatch):
    import local_shell_mcp.gui.base as base

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    manager = GuiManager(FakeBackend())

    frame = await manager.frame("window:1")

    assert frame["window"]["id"] == "window:1"
    assert "state_id" not in frame
    assert frame["observation_id"] in manager._frame_observations
    assert manager._states == {}
    refreshed = await manager.refresh_frame_observation(
        "window:1",
        frame["observation_id"],
    )
    assert refreshed == {
        "observation_id": frame["observation_id"],
        "observation_ttl_s": base.GUI_STATE_TTL_S,
    }
    with pytest.raises(GuiStaleStateError, match="different window"):
        await manager.refresh_frame_observation(
            "window:2",
            frame["observation_id"],
        )
    manager._frame_observations[frame["observation_id"]].created_at -= (
        base.GUI_STATE_TTL_S + 1
    )
    with pytest.raises(GuiStaleStateError, match="stale or unknown"):
        await manager.refresh_frame_observation(
            "window:1",
            frame["observation_id"],
        )
    screenshot = Path(frame["screenshot_path"])
    assert screenshot.is_file()
    screenshot.unlink()


@pytest.mark.asyncio
async def test_gui_human_action_uses_native_identity_from_displayed_frame(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    native_identity = object()

    class IdentityBackend(FakeBackend):
        async def snapshot(self, window_id, **kwargs):
            snapshot = await super().snapshot(window_id, **kwargs)
            snapshot.window["_native_identity"] = native_identity
            return snapshot

        async def focus_window(self, window):
            assert window.get("_native_identity") is native_identity
            await super().focus_window(window)

        async def perform_action(self, window, locator, action):
            assert window.get("_native_identity") is native_identity
            return await super().perform_action(window, locator, action)

    backend = IdentityBackend()
    manager = GuiManager(backend)
    frame = await manager.frame("window:1")
    screenshot = Path(frame["screenshot_path"])
    try:
        assert "_native_identity" not in frame["window"]
        result = await manager.human_act(
            "window:1",
            frame["observation_id"],
            frame["window"]["bounds"],
            [{"type": "click", "x": 1, "y": 1}],
        )
    finally:
        screenshot.unlink(missing_ok=True)

    assert result["human_control"] is True


@pytest.mark.asyncio
async def test_gui_manager_bounds_window_metadata_before_return(tmp_path, monkeypatch):
    import local_shell_mcp.gui.base as base

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    oversized = "x" * (base.GUI_MAX_WINDOW_TEXT_BYTES * 2)

    class OversizedWindowBackend(FakeBackend):
        async def snapshot(self, window_id, **kwargs):
            snapshot = await super().snapshot(window_id, **kwargs)
            snapshot.window["title"] = oversized
            snapshot.window["app"] = oversized
            return snapshot

    manager = GuiManager(OversizedWindowBackend())
    state = await manager.snapshot("window:1", screenshot=False)
    frame = await manager.frame("window:1")

    assert len(state["window"]["title"].encode("utf-8")) <= base.GUI_MAX_WINDOW_TEXT_BYTES
    assert len(state["window"]["app"].encode("utf-8")) <= base.GUI_MAX_WINDOW_TEXT_BYTES
    assert len(frame["window"]["title"].encode("utf-8")) <= base.GUI_MAX_WINDOW_TEXT_BYTES
    assert len(frame["window"]["app"].encode("utf-8")) <= base.GUI_MAX_WINDOW_TEXT_BYTES
    assert manager._states[state["state_id"]].window["title"] == oversized
    Path(frame["screenshot_path"]).unlink()


@pytest.mark.asyncio
async def test_gui_action_batch_limits_do_not_consume_state(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    manager = GuiManager(FakeBackend())
    state = await manager.snapshot("window:1", screenshot=False)

    with pytest.raises(ValueError, match="at most"):
        await manager.act(
            "window:1",
            state["state_id"],
            [{"type": "wait", "seconds": 0}] * 33,
        )
    assert state["state_id"] in manager._states

    with pytest.raises(ValueError, match="Total GUI wait time"):
        await manager.act(
            "window:1",
            state["state_id"],
            [
                {"type": "wait", "seconds": 20},
                {"type": "wait", "seconds": 11},
            ],
        )
    assert state["state_id"] in manager._states


@pytest.mark.asyncio
async def test_gui_action_specific_validation_precedes_state_consumption(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    backend = FakeBackend()
    manager = GuiManager(backend)
    state = await manager.snapshot("window:1", screenshot=False)
    state_id = state["state_id"]

    for invalid in (
        {"type": "key"},
        {"type": "set_value", "text": "secret"},
        {"type": "type"},
        {"type": "focus", "element_id": " "},
        {"type": "unknown"},
    ):
        with pytest.raises(ValueError):
            await manager.act(
                "window:1",
                state_id,
                [
                    {"type": "click", "x": 1, "y": 1},
                    invalid,
                ],
            )
        assert state_id in manager._states
        assert backend.actions == []


@pytest.mark.asyncio
async def test_cancelled_native_action_keeps_execution_lock_until_backend_settles(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))

    class BlockingBackend(FakeBackend):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.calls = 0
            self.active = 0
            self.max_active = 0

        async def perform_action(self, window, locator, action):
            del window, locator, action
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            if self.calls == 1:
                self.started.set()
                await self.release.wait()
            self.active -= 1
            return {"performed": True}

    backend = BlockingBackend()
    manager = GuiManager(backend)
    bounds = dict(backend.bounds)
    observation_id = _install_frame_observation(manager, backend)
    first = asyncio.create_task(
        manager.human_act(
            "window:1",
            observation_id,
            bounds,
            [{"type": "click", "x": 1, "y": 1}],
        )
    )
    await backend.started.wait()
    first.cancel()
    second = asyncio.create_task(
        manager.human_act(
            "window:1",
            observation_id,
            bounds,
            [{"type": "click", "x": 2, "y": 2}],
        )
    )
    await asyncio.sleep(0.01)
    assert backend.calls == 1
    assert backend.max_active == 1

    backend.release.set()
    with pytest.raises(asyncio.CancelledError):
        await first
    await second
    assert backend.calls == 2
    assert backend.max_active == 1


@pytest.mark.asyncio
async def test_cancelled_gui_capture_holds_execution_lock_until_backend_settles(
    tmp_path, monkeypatch
):
    import local_shell_mcp.gui.base as base

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(base, "temp_dir", lambda: tmp_path)

    class BlockingCaptureBackend(FakeBackend):
        def __init__(self):
            super().__init__()
            self.capture_started = asyncio.Event()
            self.release_capture = asyncio.Event()
            self.action_started = asyncio.Event()

        async def snapshot(
            self,
            window_id,
            *,
            screenshot_path,
            include_elements,
            max_elements,
            max_depth,
        ):
            del include_elements, max_elements, max_depth
            self.capture_started.set()
            await self.release_capture.wait()
            if screenshot_path is not None:
                Image.new("RGB", (300, 200), (1, 2, 3)).save(
                    screenshot_path, format="PNG"
                )
            return GuiSnapshot(
                window={
                    "id": window_id,
                    "title": "Demo",
                    "app": "demo",
                    "pid": 1,
                    "bounds": dict(self.bounds),
                },
                elements=[],
                screenshot_path=str(screenshot_path) if screenshot_path else None,
            )

        async def perform_action(self, window, locator, action):
            del window, locator, action
            self.action_started.set()
            return {"performed": True}

    backend = BlockingCaptureBackend()
    manager = GuiManager(backend)
    observation_id = _install_frame_observation(manager, backend)
    frame = asyncio.create_task(manager.frame("window:1"))
    await backend.capture_started.wait()
    frame.cancel()

    action = asyncio.create_task(
        manager.human_act(
            "window:1",
            observation_id,
            dict(backend.bounds),
            [{"type": "click", "x": 1, "y": 1}],
        )
    )
    await asyncio.sleep(0.01)
    assert not backend.action_started.is_set()

    backend.release_capture.set()
    with pytest.raises(asyncio.CancelledError):
        await frame
    await action
    assert backend.action_started.is_set()


@pytest.mark.asyncio
async def test_gui_input_batches_are_serialized(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))

    class SlowBackend(FakeBackend):
        def __init__(self):
            super().__init__()
            self.active = 0
            self.max_active = 0

        async def perform_action(self, window, locator, action):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.02)
            self.active -= 1
            return {"performed": True}

    backend = SlowBackend()
    manager = GuiManager(backend)
    bounds = dict(backend.bounds)
    observation_id = _install_frame_observation(manager, backend)
    await asyncio.gather(
        manager.human_act("window:1", observation_id, bounds, [{"type": "click", "x": 1, "y": 1}]),
        manager.human_act("window:1", observation_id, bounds, [{"type": "click", "x": 2, "y": 2}]),
    )
    assert backend.max_active == 1


def test_x11_window_matching_and_pixmap_decode(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    xlib = ModuleType("Xlib")
    xlib.X = SimpleNamespace(LSBFirst=0, MSBFirst=1)
    xlib.Xatom = SimpleNamespace(WINDOW=1, CARDINAL=2)
    monkeypatch.setitem(sys.modules, "Xlib", xlib)
    X = xlib.X

    class Window:
        def __init__(self, xid, pid, title, bounds):
            self.xid = xid
            self.pid = pid
            self.title = title
            self.bounds = bounds

        def get_full_property(self, atom, _kind):
            if atom == "_NET_WM_PID":
                return SimpleNamespace(value=[self.pid])
            if atom == "_NET_WM_NAME":
                return SimpleNamespace(value=self.title.encode())
            return None

        def get_wm_name(self):
            return self.title

        def get_geometry(self):
            return SimpleNamespace(
                width=self.bounds["width"],
                height=self.bounds["height"],
            )

        def translate_coords(self, root, _x, _y):
            assert isinstance(root, Root)
            return SimpleNamespace(x=self.bounds["x"], y=self.bounds["y"])

    first = Window(1, 42, "Other", {"x": 0, "y": 0, "width": 100, "height": 100})
    target = Window(2, 42, "Target", {"x": 10, "y": 20, "width": 300, "height": 200})

    class Root:
        def get_full_property(self, atom, _kind):
            if atom == "_NET_CLIENT_LIST_STACKING":
                return SimpleNamespace(value=[1, 2])
            return None

    visual = SimpleNamespace(
        visual_id=7,
        red_mask=0x00FF0000,
        green_mask=0x0000FF00,
        blue_mask=0x000000FF,
    )
    info = SimpleNamespace(
        pixmap_formats=[
            SimpleNamespace(depth=24, bits_per_pixel=32, scanline_pad=32)
        ],
        image_byte_order=X.LSBFirst,
        roots=[SimpleNamespace(allowed_depths=[SimpleNamespace(visuals=[visual])])],
    )

    class Connection:
        display = SimpleNamespace(info=info)

        def screen(self):
            return SimpleNamespace(root=Root())

        def intern_atom(self, name, only_if_exists=True):
            del only_if_exists
            return name

        def create_resource_object(self, _kind, xid):
            return {1: first, 2: target}[xid]

    connection = Connection()
    matched = linux._x11_match_window(
        connection,
        {
            "pid": 42,
            "title": "Target",
            "bounds": {"x": 10, "y": 20, "width": 300, "height": 200},
        },
    )
    assert matched is target

    image = linux._x11_pixmap_to_image(
        connection,
        SimpleNamespace(depth=24, data=bytes([3, 2, 1, 0])),
        width=1,
        height=1,
        visual_id=7,
    )
    assert image.getpixel((0, 0)) == (1, 2, 3)


def test_x11_match_rejects_sole_same_process_window_without_title_or_geometry_match(
    monkeypatch,
):
    import local_shell_mcp.gui.linux as linux

    xlib = ModuleType("Xlib")
    xlib.Xatom = SimpleNamespace(WINDOW=1, CARDINAL=2)
    monkeypatch.setitem(sys.modules, "Xlib", xlib)

    class Window:
        def get_full_property(self, _atom, _kind):
            return SimpleNamespace(value=[42])

        def get_wm_name(self):
            return "Other"

        def get_geometry(self):
            return SimpleNamespace(width=50, height=40)

        def translate_coords(self, _root, _x, _y):
            return SimpleNamespace(x=500, y=600)

    window = Window()

    class Root:
        def get_full_property(self, atom, _kind):
            if atom == "_NET_CLIENT_LIST_STACKING":
                return SimpleNamespace(value=[1])
            return None

    class Connection:
        def screen(self):
            return SimpleNamespace(root=Root())

        def intern_atom(self, name, only_if_exists=True):
            del only_if_exists
            return name

        def create_resource_object(self, _kind, _xid):
            return window

    with pytest.raises(GuiUnavailableError, match="Could not map"):
        linux._x11_match_window(
            Connection(),
            {
                "pid": 42,
                "title": "Target",
                "bounds": {"x": 10, "y": 20, "width": 300, "height": 200},
            },
        )


def test_x11_match_rejects_same_title_with_different_geometry(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    xlib = ModuleType("Xlib")
    xlib.Xatom = SimpleNamespace(WINDOW=1, CARDINAL=2)
    monkeypatch.setitem(sys.modules, "Xlib", xlib)

    class Window:
        def get_full_property(self, _atom, _kind):
            return SimpleNamespace(value=[42])

        def get_wm_name(self):
            return "Untitled"

        def get_geometry(self):
            return SimpleNamespace(width=80, height=60)

        def translate_coords(self, _root, _x, _y):
            return SimpleNamespace(x=500, y=600)

    window = Window()

    class Root:
        def get_full_property(self, atom, _kind):
            if atom == "_NET_CLIENT_LIST_STACKING":
                return SimpleNamespace(value=[1])
            return None

    class Connection:
        def screen(self):
            return SimpleNamespace(root=Root())

        def intern_atom(self, name, only_if_exists=True):
            del only_if_exists
            return name

        def create_resource_object(self, _kind, _xid):
            return window

    with pytest.raises(GuiUnavailableError, match="Could not map"):
        linux._x11_match_window(
            Connection(),
            {
                "pid": 42,
                "title": "Untitled",
                "bounds": {"x": 10, "y": 20, "width": 300, "height": 200},
            },
        )


def test_x11_capture_rejects_oversized_window_before_pixmap_read(tmp_path, monkeypatch):
    import local_shell_mcp.gui.linux as linux

    class Window:
        def get_geometry(self):
            return SimpleNamespace(
                width=linux.GUI_MAX_CAPTURE_DIMENSION + 1,
                height=10,
            )

        def composite_name_window_pixmap(self):
            pytest.fail("oversized X11 window must be rejected before pixmap allocation")

    class Connection:
        def has_extension(self, name):
            assert name == "Composite"
            return True

        def get_default_screen(self):
            return 0

        def intern_atom(self, _name, only_if_exists=True):
            del only_if_exists
            return 99

        def get_selection_owner(self, _atom):
            return SimpleNamespace(id=123)

        def close(self):
            pass

    xlib = ModuleType("Xlib")
    xlib.X = SimpleNamespace(ZPixmap=2)
    xlib.display = SimpleNamespace(Display=lambda _display: Connection())
    monkeypatch.setitem(sys.modules, "Xlib", xlib)
    monkeypatch.setattr(linux, "_x11_match_window", lambda *_args: Window())

    with pytest.raises(GuiUnavailableError, match="safe budget"):
        linux._capture_x11_window_sync(
            tmp_path / "oversized.png",
            {"id": "w"},
            {"DISPLAY": ":0"},
        )


def test_x11_capture_uses_composite_window_pixmap(tmp_path, monkeypatch):
    import local_shell_mcp.gui.linux as linux

    calls = []

    class Pixmap:
        def get_image(self, *args):
            calls.append(("get_image", args))
            return object()

        def free(self):
            calls.append(("free",))

    class Window:
        def get_geometry(self):
            return SimpleNamespace(width=4, height=3)

        def get_attributes(self):
            return SimpleNamespace(visual=7)

        def composite_name_window_pixmap(self):
            calls.append(("name_pixmap",))
            return Pixmap()

    class Connection:
        def has_extension(self, name):
            assert name == "Composite"
            return True

        def get_default_screen(self):
            return 0

        def intern_atom(self, name, only_if_exists=True):
            del only_if_exists
            assert name == "_NET_WM_CM_S0"
            return 99

        def get_selection_owner(self, atom):
            assert atom == 99
            return SimpleNamespace(id=123)

        def close(self):
            calls.append(("close",))

    connection = Connection()
    xlib = ModuleType("Xlib")
    xlib.X = SimpleNamespace(ZPixmap=2)
    xlib.display = SimpleNamespace(Display=lambda _display: connection)
    monkeypatch.setitem(sys.modules, "Xlib", xlib)
    monkeypatch.setattr(linux, "_x11_match_window", lambda _connection, _record: Window())
    monkeypatch.setattr(
        linux,
        "_x11_pixmap_to_image",
        lambda *_args, **_kwargs: Image.new("RGB", (4, 3), (1, 2, 3)),
    )

    path = tmp_path / "window.png"
    linux._capture_x11_window_sync(
        path,
        {"id": "atspi:1:0:sig", "pid": 1, "title": "Window", "bounds": {}},
        {"DISPLAY": ":0"},
    )
    assert path.is_file()
    assert ("name_pixmap",) in calls
    assert any(call[0] == "get_image" for call in calls)
    assert ("free",) in calls
    assert calls[-1] == ("close",)


def test_x11_capture_fails_closed_without_compositor(tmp_path, monkeypatch):
    import local_shell_mcp.gui.linux as linux

    class Connection:
        def has_extension(self, _name):
            return True

        def get_default_screen(self):
            return 0

        def intern_atom(self, _name, only_if_exists=True):
            del only_if_exists
            return 99

        def get_selection_owner(self, _atom):
            return None

        def close(self):
            pass

    xlib = ModuleType("Xlib")
    xlib.X = SimpleNamespace(ZPixmap=2)
    xlib.display = SimpleNamespace(Display=lambda _display: Connection())
    monkeypatch.setitem(sys.modules, "Xlib", xlib)
    with pytest.raises(GuiUnavailableError, match="compositing manager"):
        linux._capture_x11_window_sync(
            tmp_path / "window.png",
            {"id": "w"},
            {"DISPLAY": ":0"},
        )


@pytest.mark.asyncio
async def test_linux_raw_keyboard_focuses_selected_window(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    monkeypatch.setattr(linux, "_desktop_environment", lambda: {"XDG_SESSION_TYPE": "x11"})
    backend = linux.LinuxGuiBackend()
    calls = []

    async def focus(window):
        calls.append(("focus", window["id"]))

    async def raw(window, locator, action):
        calls.append(("raw", action["type"]))
        return {"ok": True}

    monkeypatch.setattr(backend, "focus_window", focus)
    monkeypatch.setattr(backend, "_perform_x11", raw)

    window = {"id": "window:1", "bounds": {"x": 0, "y": 0, "width": 10, "height": 10}}
    await backend.perform_action(
        window,
        None,
        {"type": "key", "keys": "CTRL+A"},
    )
    assert calls == [("focus", "window:1"), ("raw", "key")]

    calls.clear()
    result = await backend.perform_action(window, None, {"type": "focus"})
    assert result == {"semantic": True, "method": "window"}
    assert calls == [("focus", "window:1")]


def test_linux_locator_center_must_be_usable_and_inside_window(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    monkeypatch.setattr(linux, "_desktop_environment", lambda: {"XDG_SESSION_TYPE": "x11"})
    backend = linux.LinuxGuiBackend()
    window = {"id": "w", "bounds": {"x": 100, "y": 100, "width": 200, "height": 100}}

    assert backend._screen_point(
        window,
        {"type": "right_click"},
        {"bounds": {"x": 120, "y": 130, "width": 20, "height": 10}},
    ) == (130, 135)

    with pytest.raises(ValueError, match="no usable"):
        backend._screen_point(
            window,
            {"type": "scroll"},
            {"bounds": {"x": 0, "y": 0, "width": 0, "height": 0}},
        )

    with pytest.raises(ValueError, match="outside"):
        backend._screen_point(
            window,
            {"type": "drag"},
            {"bounds": {"x": 400, "y": 130, "width": 20, "height": 10}},
        )


def test_x11_key_chord_validates_before_pressing(monkeypatch):
    import sys
    from types import ModuleType

    import local_shell_mcp.gui.linux as linux

    events = []
    closed = []

    class Connection:
        def keysym_to_keycode(self, keysym):
            return 10 if keysym == 1 else 0

        def sync(self):
            events.append(("sync",))

        def close(self):
            closed.append(True)

    connection = Connection()
    xlib = ModuleType("Xlib")
    xlib.XK = SimpleNamespace(
        string_to_keysym=lambda name: 1 if name == "Control_L" else 0
    )
    xlib.X = SimpleNamespace(KeyPress=2, KeyRelease=3)
    xlib.display = SimpleNamespace(Display=lambda _name: connection)
    ext = ModuleType("Xlib.ext")
    ext.xtest = SimpleNamespace(
        fake_input=lambda _connection, event_type, keycode: events.append(
            (event_type, keycode)
        )
    )
    xlib.ext = ext
    monkeypatch.setitem(sys.modules, "Xlib", xlib)
    monkeypatch.setitem(sys.modules, "Xlib.ext", ext)

    with pytest.raises(ValueError, match="Unsupported X11 key name"):
        linux._x11_key_chord("CTRL+NOT_A_KEY", {"DISPLAY": ":0"})

    assert events == []
    assert closed == [True]


def test_wayland_full_desktop_crop_requires_monitor_geometry():
    with pytest.raises(GuiUnavailableError, match="Monitor geometry is unavailable"):
        _desktop_crop_box(
            {"x": -100, "y": 0, "width": 200, "height": 100},
            [],
            (1920, 1080),
        )


@pytest.mark.asyncio
async def test_linux_environment_discovery_is_lazy_and_off_event_loop(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    calls = []

    def discover():
        calls.append("discover")
        return {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}

    original_to_thread = asyncio.to_thread

    async def tracked_to_thread(func, *args, **kwargs):
        if func is discover:
            calls.append("to_thread")
        return await original_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(linux, "_desktop_environment", discover)
    monkeypatch.setattr(asyncio, "to_thread", tracked_to_thread)
    backend = linux.LinuxGuiBackend()
    assert calls == []
    env = await backend._ensure_env()
    assert env["DISPLAY"] == ":0"
    assert calls == ["to_thread", "discover"]


def test_linux_environment_discovery_timeout_is_nonfatal(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    monkeypatch.setattr(linux.shutil, "which", lambda _name: "/usr/bin/systemctl")
    monkeypatch.setattr(
        linux.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            linux.subprocess.TimeoutExpired("systemctl", 5)
        ),
    )
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    env = linux._desktop_environment()
    assert linux._session_type(env) == "unknown"


def test_linux_environment_discovery_replaces_stale_inherited_values(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    for key in linux._DESKTOP_ENV_KEYS:
        monkeypatch.setenv(key, f"stale-{key.lower()}")
    monkeypatch.setattr(linux.shutil, "which", lambda _name: "/usr/bin/systemctl")
    calls = []

    def run(*_args, **_kwargs):
        calls.append(True)
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "DISPLAY=:9\n"
                "WAYLAND_DISPLAY=wayland-9\n"
                "XDG_SESSION_TYPE=wayland\n"
                "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus\n"
            ),
        )

    monkeypatch.setattr(linux.subprocess, "run", run)
    env = linux._desktop_environment()

    assert calls == [True]
    assert env["DISPLAY"] == ":9"
    assert env["WAYLAND_DISPLAY"] == "wayland-9"
    assert env["XDG_SESSION_TYPE"] == "wayland"
    assert env["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/1000/bus"


@pytest.mark.asyncio
async def test_linux_desktop_environment_refreshes_and_resets_portal(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    backend = linux.LinuxGuiBackend()
    times = iter([100.0, 100.0, 131.0, 131.0])
    environments = iter([
        {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"},
        {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-1"},
    ])
    monkeypatch.setattr(
        linux,
        "time",
        SimpleNamespace(monotonic=lambda: next(times)),
    )
    monkeypatch.setattr(linux, "_desktop_environment", lambda: next(environments))

    first = await backend._ensure_env()
    backend._portal = object()
    second = await backend._ensure_env()
    assert first["DISPLAY"] == ":0"
    assert second["WAYLAND_DISPLAY"] == "wayland-1"
    assert backend._portal is None


def test_wayland_desktop_crop_rejects_oversized_header_before_decode(
    tmp_path, monkeypatch
):
    import local_shell_mcp.gui.linux as linux

    class OversizedImage:
        size = (linux.GUI_MAX_CAPTURE_DIMENSION + 1, 1)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def load(self):
            pytest.fail("oversized capture must be rejected before decoding pixels")

    monkeypatch.setattr(linux.Image, "open", lambda _path: OversizedImage())

    with pytest.raises(GuiUnavailableError, match="screenshot safety limits"):
        linux._crop_desktop_capture(
            tmp_path / "desktop.png",
            {"x": 0, "y": 0, "width": 10, "height": 10},
            [],
        )


@pytest.mark.asyncio
async def test_wayland_snapshot_focuses_target_before_visible_region_capture(tmp_path, monkeypatch):
    import local_shell_mcp.gui.linux as linux

    backend = linux.LinuxGuiBackend()
    backend._env = {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"}
    calls = []

    def helper(payload):
        if payload["command"] == "snapshot":
            return {
                "window": {
                    "id": "atspi:1:sig",
                    "title": "Target",
                    "app": "App",
                    "pid": 1,
                    "bounds": {"x": 0, "y": 0, "width": 10, "height": 10},
                },
                "elements": [],
                "locators": {},
            }
        if payload["command"] == "list":
            return {"windows": [], "monitors": []}
        raise AssertionError(payload)

    async def focus(_window):
        calls.append("focus")

    async def capture(path, bounds, monitors, env):
        del bounds, monitors, env
        calls.append("capture")
        Image.new("RGB", (10, 10)).save(path)
        return "test-wayland"

    monkeypatch.setattr(backend, "_helper", helper)
    monkeypatch.setattr(backend, "focus_window", focus)
    monkeypatch.setattr(linux, "_capture_wayland", capture)

    result = await backend.snapshot(
        "atspi:1:sig",
        screenshot_path=tmp_path / "wayland.png",
        include_elements=False,
        max_elements=10,
        max_depth=2,
    )
    assert result.capabilities["capture_backend"] == "test-wayland"
    assert calls == ["focus", "capture"]


@pytest.mark.asyncio
async def test_wayland_snapshot_rejects_bounds_change_after_focus(tmp_path, monkeypatch):
    import local_shell_mcp.gui.linux as linux

    backend = linux.LinuxGuiBackend()
    backend._env = {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"}
    snapshot_calls = 0

    def helper(payload):
        nonlocal snapshot_calls
        if payload["command"] == "snapshot":
            snapshot_calls += 1
            x = 0 if snapshot_calls == 1 else 50
            return {
                "window": {
                    "id": "atspi:1:sig",
                    "title": "Target",
                    "app": "App",
                    "pid": 1,
                    "bounds": {"x": x, "y": 0, "width": 10, "height": 10},
                },
                "elements": [],
                "locators": {},
            }
        if payload["command"] == "list":
            return {"windows": [], "monitors": []}
        raise AssertionError(payload)

    async def focus(_window):
        return None

    async def capture(*_args, **_kwargs):
        pytest.fail("capture must not run with stale Wayland bounds")

    monkeypatch.setattr(backend, "_helper", helper)
    monkeypatch.setattr(backend, "focus_window", focus)
    monkeypatch.setattr(linux, "_capture_wayland", capture)

    with pytest.raises(GuiStaleStateError, match="moved or resized"):
        await backend.snapshot(
            "atspi:1:sig",
            screenshot_path=tmp_path / "wayland.png",
            include_elements=False,
            max_elements=10,
            max_depth=2,
        )
    assert snapshot_calls == 2


@pytest.mark.asyncio
async def test_wayland_grim_rejects_oversized_output_before_decode(tmp_path, monkeypatch):
    import local_shell_mcp.gui.linux as linux

    path = tmp_path / "grim.png"

    class OversizedImage:
        size = (linux.GUI_MAX_CAPTURE_DIMENSION + 1, 1)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def load(self):
            pytest.fail("oversized grim output must be rejected before decoding")

    def run(argv, **_kwargs):
        Path(argv[-1]).write_bytes(b"png")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        linux.shutil,
        "which",
        lambda name: "/usr/bin/grim" if name == "grim" else None,
    )
    monkeypatch.setattr(linux.subprocess, "run", run)
    monkeypatch.setattr(linux.Image, "open", lambda _path: OversizedImage())

    with pytest.raises(GuiUnavailableError, match="screenshot safety limits"):
        await linux._capture_wayland(
            path,
            {"x": 0, "y": 0, "width": 10, "height": 10},
            [],
            {},
        )


@pytest.mark.asyncio
async def test_linux_raw_element_action_reresolves_locator_bounds(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    backend = linux.LinuxGuiBackend()
    backend._env = {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}
    helper_calls = []
    received = []

    def helper(payload):
        helper_calls.append(payload)
        assert payload["command"] == "resolve_locator"
        return {"bounds": {"x": 40, "y": 50, "width": 20, "height": 10}}

    async def focus(_window):
        return None

    async def raw(_window, locator, _action):
        received.append(locator)
        return {"performed": True}

    monkeypatch.setattr(backend, "_helper", helper)
    monkeypatch.setattr(backend, "focus_window", focus)
    monkeypatch.setattr(backend, "_perform_x11", raw)

    locator = {
        "semantic": {"path": [1], "fingerprint": "fp"},
        "bounds": {"x": 1, "y": 2, "width": 3, "height": 4},
    }
    await backend.perform_action(
        {"id": "atspi:1:sig", "bounds": {"x": 0, "y": 0, "width": 100, "height": 100}},
        locator,
        {"type": "right_click"},
    )
    assert helper_calls[0]["locator"]["fingerprint"] == "fp"
    assert received[0]["bounds"] == {"x": 40, "y": 50, "width": 20, "height": 10}


@pytest.mark.asyncio
async def test_wayland_refocuses_target_after_portal_bootstrap(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    backend = linux.LinuxGuiBackend()
    backend._env = {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"}
    calls = []

    class Portal:
        async def ensure_session(self):
            calls.append("bootstrap")
            return "session-1"

        async def click(self, *_args, **kwargs):
            assert kwargs["session"] == "session-1"
            calls.append("click")

    backend._portal = Portal()

    async def focus(_window):
        calls.append("focus")

    monkeypatch.setattr(backend, "focus_window", focus)
    result = await backend._perform_wayland(
        {"id": "atspi:1:sig", "bounds": {"x": 0, "y": 0, "width": 100, "height": 100}},
        None,
        {"type": "click", "x": 5, "y": 6},
    )
    assert result["method"] == "xdg-desktop-portal"
    assert calls == ["bootstrap", "focus", "click"]


@pytest.mark.asyncio
async def test_wayland_prepared_pointer_revalidates_after_portal_bootstrap(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    backend = linux.LinuxGuiBackend()
    backend._env = {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"}
    calls = []

    class Portal:
        async def ensure_session(self):
            calls.append("bootstrap")
            return "session-1"

        async def click(self, *_args, **_kwargs):
            pytest.fail("stale Wayland coordinates must not be injected")

    backend._portal = Portal()

    async def focus(_window):
        calls.append("focus")

    def helper(payload):
        assert payload["command"] == "snapshot"
        calls.append("snapshot")
        return {
            "window": {
                "id": "atspi:1:sig",
                "bounds": {"x": 10, "y": 0, "width": 100, "height": 100},
            }
        }

    monkeypatch.setattr(backend, "focus_window", focus)
    monkeypatch.setattr(backend, "_helper", helper)

    with pytest.raises(GuiStaleStateError, match="preparing Wayland input"):
        await backend._perform_wayland(
            {
                "id": "atspi:1:sig",
                "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
            },
            None,
            {"type": "click", "x": 5, "y": 6, "_focus_prepared": True},
        )

    assert calls == ["bootstrap", "focus", "snapshot"]


@pytest.mark.asyncio
async def test_linux_raw_pointer_focuses_target_before_injection(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    backend = linux.LinuxGuiBackend()
    backend._env = {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}
    calls = []

    async def focus(_window):
        calls.append("focus")

    async def raw(_window, _locator, _action):
        calls.append("raw")
        return {"performed": True}

    monkeypatch.setattr(backend, "focus_window", focus)
    monkeypatch.setattr(backend, "_perform_x11", raw)
    result = await backend.perform_action(
        {"id": "w", "bounds": {"x": 0, "y": 0, "width": 100, "height": 100}},
        None,
        {"type": "click", "x": 10, "y": 10},
    )
    assert result == {"performed": True}
    assert calls == ["focus", "raw"]


@pytest.mark.asyncio
async def test_x11_compound_pointer_actions_use_one_helper_invocation(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    backend = linux.LinuxGuiBackend()
    calls = []

    def helper(payload):
        calls.append(payload)
        return {"generated": True}

    monkeypatch.setattr(backend, "_helper", helper)
    window = {"id": "w", "bounds": {"x": 0, "y": 0, "width": 100, "height": 100}}

    await backend._perform_x11(
        window,
        None,
        {"type": "double_click", "x": 10, "y": 20},
    )
    await backend._perform_x11(
        window,
        None,
        {"type": "scroll", "x": 10, "y": 20, "delta_y": -3},
    )

    assert len(calls) == 2
    assert calls[0]["kind"] == "mouse_sequence"
    assert [item["event"] for item in calls[0]["events"]] == ["b1c", "b1c"]
    assert calls[1]["kind"] == "mouse_sequence"
    assert [item["event"] for item in calls[1]["events"]] == ["b5c"] * 3


def test_atspi_mouse_sequence_runs_in_one_helper_process(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    generated = []

    class Atspi:
        @staticmethod
        def generate_mouse_event(x, y, event):
            generated.append((x, y, event))
            return True

    monkeypatch.setattr(helper, "Atspi", Atspi)
    result = helper._raw(
        {
            "kind": "mouse_sequence",
            "events": [
                {"x": 1, "y": 2, "event": "b1c"},
                {"x": 1, "y": 2, "event": "b1c"},
            ],
        }
    )
    assert result == {"generated": True, "events": 2}
    assert generated == [(1, 2, "b1c"), (1, 2, "b1c")]


@pytest.mark.asyncio
async def test_x11_drag_releases_button_after_motion_failure(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    monkeypatch.setattr(linux, "_desktop_environment", lambda: {"XDG_SESSION_TYPE": "x11"})
    backend = linux.LinuxGuiBackend()
    events = []

    def helper(payload):
        event = payload.get("event")
        events.append(dict(payload))
        if event == "abs":
            raise RuntimeError("motion failed")
        return {"generated": True}

    monkeypatch.setattr(backend, "_helper", helper)
    window = {"id": "w", "bounds": {"x": 0, "y": 0, "width": 100, "height": 100}}
    with pytest.raises(RuntimeError, match="motion failed"):
        await backend._perform_x11(
            window,
            None,
            {"type": "drag", "x": 1, "y": 1, "to_x": 10, "to_y": 10},
        )
    assert [item["event"] for item in events] == ["b1p", "abs", "b1r"]
    assert events[-1]["x"] == 1
    assert events[-1]["y"] == 1


def test_atspi_snapshot_bounds_direct_child_provider_calls(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    child_calls = []

    class Node:
        def __init__(self, child_count=0):
            self.child_count = child_count

        def get_role_name(self):
            return "node"

        def get_name(self):
            return "n"

        def get_action_iface(self):
            return None

        def get_child_count(self):
            return self.child_count

        def get_child_at_index(self, index):
            child_calls.append(index)
            return Node()

    root = Node(child_count=100000)
    app = object()
    monkeypatch.setattr(helper, "_resolve_window", lambda _id: (app, root, 0))
    monkeypatch.setattr(helper, "_record", lambda *_args: {"id": "w"})
    monkeypatch.setattr(helper, "_bounds", lambda _obj: {})
    monkeypatch.setattr(helper, "_state", lambda *_args: False)
    monkeypatch.setattr(helper, "_element_signature", lambda _obj: "sig")
    monkeypatch.setattr(
        helper,
        "Atspi",
        SimpleNamespace(
            StateType=SimpleNamespace(ENABLED=1, FOCUSED=2, EDITABLE=3)
        ),
    )

    result = helper._snapshot(
        {
            "window_id": "w",
            "include_elements": True,
            "max_elements": 3,
            "max_depth": 5,
        }
    )
    assert len(result["elements"]) == 3
    assert child_calls == [0, 1]


def test_atspi_element_locator_rejects_reordered_replacement(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    replacement = object()
    monkeypatch.setattr(helper, "_resolve_window", lambda _window_id: (None, object(), 0))
    monkeypatch.setattr(helper, "_resolve_path", lambda _window, _path: replacement)
    monkeypatch.setattr(helper, "_element_signature", lambda _obj: "replacement")

    with pytest.raises(LookupError, match="changed since observation"):
        helper._semantic_action(
            {
                "window_id": "atspi:1:0:sig",
                "locator": {"path": [2], "fingerprint": "observed"},
                "action": {"type": "focus"},
            }
        )


@pytest.mark.asyncio
async def test_portal_request_subscribes_before_immediate_response(monkeypatch):
    import sys
    from types import ModuleType

    signal_type = object()
    dbus_next = ModuleType("dbus_next")
    dbus_next.MessageType = SimpleNamespace(SIGNAL=signal_type)
    monkeypatch.setitem(sys.modules, "dbus_next", dbus_next)

    class Bus:
        unique_name = ":1.42"

        def __init__(self):
            self.handler = None
            self.match_rules = []

        def _add_match_rule(self, rule):
            self.match_rules.append(rule)

        def _remove_match_rule(self, rule):
            self.match_rules.remove(rule)

        def add_message_handler(self, handler):
            assert self.match_rules
            self.handler = handler

        def remove_message_handler(self, handler):
            assert handler is self.handler
            self.handler = None

    bus = Bus()
    token = "lsm_req_test"
    path = _portal_request_path(bus, token)

    async def immediate():
        assert bus.handler is not None
        bus.handler(
            SimpleNamespace(
                message_type=signal_type,
                path=path,
                interface="org.freedesktop.portal.Request",
                member="Response",
                body=[0, {"answer": "ok"}],
            )
        )
        return path

    assert await _portal_request(bus, immediate(), handle_token=token) == {"answer": "ok"}
    assert bus.handler is None
    assert bus.match_rules == []


@pytest.mark.asyncio
async def test_portal_connect_failure_does_not_poison_cached_connection(monkeypatch):
    import local_shell_mcp.gui.linux_portal as linux_portal

    attempts = []

    class InterfaceObject:
        def get_interface(self, name):
            return name

    class Connected:
        def __init__(self, fail):
            self.fail = fail
            self.disconnected = False

        async def introspect(self, *_args):
            if self.fail:
                raise RuntimeError("transient introspection failure")
            return object()

        def get_proxy_object(self, *_args):
            return InterfaceObject()

        def disconnect(self):
            self.disconnected = True

    class MessageBus:
        def __init__(self, **_kwargs):
            self.connected = Connected(fail=not attempts)
            attempts.append(self.connected)

        async def connect(self):
            return self.connected

    monkeypatch.setattr(linux_portal, "_portal_modules", lambda: (MessageBus, object))
    portal = PortalDesktop({})

    with pytest.raises(RuntimeError, match="transient"):
        await portal._connect()
    assert portal._bus is None
    assert portal._remote is None
    assert portal._screen is None
    assert attempts[0].disconnected is True

    await portal._connect()
    assert portal._bus is attempts[1]
    assert portal._remote == "org.freedesktop.portal.RemoteDesktop"
    assert portal._screen == "org.freedesktop.portal.ScreenCast"


@pytest.mark.asyncio
async def test_portal_closed_signal_clears_cached_session(monkeypatch):
    portal = PortalDesktop({})
    portal._session = "/session/1"
    portal._streams = [{"node_id": 1, "properties": {}}]
    callbacks = []

    class SessionIface:
        def on_closed(self, callback):
            callbacks.append(callback)

    class Obj:
        def get_interface(self, name):
            assert name == "org.freedesktop.portal.Session"
            return SessionIface()

    class Bus:
        async def introspect(self, *_args):
            return object()
        def get_proxy_object(self, *_args):
            return Obj()

    portal._bus = Bus()
    await portal._observe_session_closed("/session/1")
    assert len(callbacks) == 1
    assert portal._session_iface is not None
    callbacks[0]()
    assert portal._session is None
    assert portal._session_iface is None
    assert portal._streams == []


@pytest.mark.asyncio
async def test_portal_transport_failure_invalidates_cached_connection():
    portal = PortalDesktop({})
    portal._session = "/session/1"
    portal._streams = [
        {
            "node_id": 7,
            "properties": {"position": [0, 0], "size": [100, 100]},
        }
    ]
    disconnected = []

    class Bus:
        def disconnect(self):
            disconnected.append(True)

    class Remote:
        async def call_notify_pointer_motion_absolute(self, *_args):
            raise RuntimeError("portal transport failed")

    portal._bus = Bus()
    portal._remote = Remote()
    portal._screen = object()
    portal._session_iface = object()

    with pytest.raises(RuntimeError, match="transport failed"):
        await portal.move(10, 20, session="/session/1")

    assert disconnected == [True]
    assert portal._bus is None
    assert portal._remote is None
    assert portal._screen is None
    assert portal._session is None
    assert portal._session_iface is None
    assert portal._streams == []


@pytest.mark.asyncio
async def test_portal_screenshot_deletes_portal_source_after_copy(tmp_path, monkeypatch):
    import local_shell_mcp.gui.linux_portal as portal_module

    source = tmp_path / "portal-source.png"
    source.write_bytes(b"png")
    destination = tmp_path / "copy.png"

    class Screenshot:
        def call_screenshot(self, *_args):
            return object()

    class Obj:
        def get_interface(self, _name):
            return Screenshot()

    class Bus:
        async def connect(self):
            return self

        async def introspect(self, *_args):
            return object()

        def get_proxy_object(self, *_args):
            return Obj()

        def disconnect(self):
            pass

    class Variant:
        def __init__(self, *_args):
            pass

    monkeypatch.setattr(portal_module, "_portal_modules", lambda: (Bus, Variant))

    async def request(*_args, **_kwargs):
        return {"uri": source.as_uri()}

    monkeypatch.setattr(portal_module, "_portal_request", request)
    await portal_module.portal_screenshot(destination, {})
    assert destination.read_bytes() == b"png"
    assert not source.exists()


@pytest.mark.asyncio
async def test_portal_session_setup_resets_when_closed_observation_fails(monkeypatch):
    import local_shell_mcp.gui.linux_portal as portal_module

    portal = PortalDesktop({})
    closed = []

    class Remote:
        def call_create_session(self, _options):
            return "create"

        def call_select_devices(self, *_args):
            return "devices"

        def call_start(self, *_args):
            return "start"

    class Screen:
        def call_select_sources(self, *_args):
            return "sources"

    async def connect():
        portal._remote = Remote()
        portal._screen = Screen()

    responses = iter(
        [
            {"session_handle": "/session/1"},
            {},
            {},
            {"streams": []},
        ]
    )

    async def request(_awaitable, **_kwargs):
        return next(responses)

    async def observe(_session):
        raise RuntimeError("cannot subscribe")

    async def close(session):
        closed.append(session)

    class Variant:
        def __init__(self, *_args):
            pass

    monkeypatch.setattr(portal, "_connect", connect)
    monkeypatch.setattr(portal, "_request", request)
    monkeypatch.setattr(portal, "_observe_session_closed", observe)
    monkeypatch.setattr(portal, "_close_session", close)
    monkeypatch.setattr(portal_module, "_portal_modules", lambda: (object, Variant))

    with pytest.raises(GuiUnavailableError, match="closure observation"):
        await portal.ensure_session()
    assert closed == ["/session/1"]
    assert portal._session is None
    assert portal._session_iface is None
    assert portal._streams == []


@pytest.mark.asyncio
async def test_portal_click_releases_pressed_button_after_release_failure(monkeypatch):
    portal = PortalDesktop({})
    calls = []
    release_failures = {"remaining": 1}

    async def ready():
        return "session"

    async def move(_x, _y, *, session=None):
        assert session == "session"

    async def button(_button, pressed, *, session=None):
        assert session == "session"
        calls.append(pressed)
        if not pressed and release_failures["remaining"]:
            release_failures["remaining"] -= 1
            raise RuntimeError("release failed")

    portal._session = "session"
    portal._remote = object()
    monkeypatch.setattr(portal, "ensure_session", ready)
    monkeypatch.setattr(portal, "move", move)
    monkeypatch.setattr(portal, "button", button)
    with pytest.raises(RuntimeError, match="release failed"):
        await portal.click(1, 2)
    assert calls == [True, False, False]


@pytest.mark.asyncio
async def test_portal_scroll_translates_to_positive_down_axis():
    portal = PortalDesktop({})
    portal._session = "session"
    portal._streams = [
        {
            "node_id": 7,
            "properties": {"position": [0, 0], "size": [100, 100]},
        }
    ]
    axes = []

    class Remote:
        async def call_notify_pointer_motion_absolute(self, *_args):
            pass

        async def call_notify_pointer_axis(
            self, session, _options, delta_x, delta_y
        ):
            axes.append((session, delta_x, delta_y))

    portal._remote = Remote()
    await portal.scroll(10, 20, 2.0, -3.0, session="session")
    assert axes == [("session", -2.0, 3.0)]


@pytest.mark.asyncio
async def test_portal_type_text_maps_tabs_and_line_endings_to_keysyms():
    portal = PortalDesktop({})
    portal._session = "session"
    events = []

    class Remote:
        async def call_notify_keyboard_keysym(
            self, session, _options, keysym, pressed
        ):
            events.append((session, keysym, pressed))

    portal._remote = Remote()
    await portal.type_text("a\tb\r\nc\rd", session="session")

    pressed = [keysym for _session, keysym, state in events if state == 1]
    assert pressed == [
        ord("a"),
        0xFF09,
        ord("b"),
        0xFF0D,
        ord("c"),
        0xFF0D,
        ord("d"),
    ]


@pytest.mark.asyncio
async def test_portal_click_does_not_reopen_session_mid_gesture(monkeypatch):
    portal = PortalDesktop({})
    portal._session = "session-1"
    portal._streams = [
        {
            "node_id": 7,
            "properties": {"position": [0, 0], "size": [100, 100]},
        }
    ]
    ensure_calls = []

    async def ensure():
        ensure_calls.append(True)
        return "session-2"

    class Remote:
        async def call_notify_pointer_motion_absolute(
            self, session, _options, _stream, _x, _y
        ):
            assert session == "session-1"
            portal._on_session_closed()

        async def call_notify_pointer_button(self, *_args):
            pytest.fail("button must not be sent after the bound session closes")

    portal._remote = Remote()
    monkeypatch.setattr(portal, "ensure_session", ensure)

    with pytest.raises(GuiUnavailableError, match="closed during the current gesture"):
        await portal.click(10, 10, session="session-1")
    assert ensure_calls == []


@pytest.mark.asyncio
async def test_portal_drag_retries_release_after_release_failure(monkeypatch):
    portal = PortalDesktop({})
    button_calls = []
    moves = []
    release_failures = {"remaining": 1}

    async def ready():
        return "session"

    async def move(x, y, *, session=None):
        assert session == "session"
        moves.append((x, y))

    async def button(_button, pressed, *, session=None):
        assert session == "session"
        button_calls.append(pressed)
        if not pressed and release_failures["remaining"]:
            release_failures["remaining"] -= 1
            raise RuntimeError("release failed")

    portal._session = "session"
    portal._remote = object()
    monkeypatch.setattr(portal, "ensure_session", ready)
    monkeypatch.setattr(portal, "move", move)
    monkeypatch.setattr(portal, "button", button)

    with pytest.raises(RuntimeError, match="release failed"):
        await portal.drag(1, 2, 10, 20)

    assert moves == [(1, 2), (10, 20)]
    assert button_calls == [True, False, False]


@pytest.mark.asyncio
async def test_portal_key_chord_releases_every_successfully_pressed_key(monkeypatch):
    portal = PortalDesktop({})
    events = []
    fail_once = {"value": True}

    async def ready():
        return "session"

    async def key_event(symbol, pressed, *, session=None):
        assert session == "session"
        events.append((symbol, pressed))
        if symbol == 0x41 and pressed and fail_once["value"]:
            fail_once["value"] = False
            raise RuntimeError("key down failed")

    portal._session = "session"
    portal._remote = object()
    monkeypatch.setattr(portal, "ensure_session", ready)
    monkeypatch.setattr(portal, "_key_event", key_event)
    with pytest.raises(RuntimeError, match="key down failed"):
        await portal.key_chord("CTRL+SHIFT+A")

    assert (0xFFE3, False) in events
    assert (0xFFE1, False) in events


@pytest.mark.asyncio
async def test_portal_setup_failure_closes_created_session(monkeypatch):
    portal = PortalDesktop({})
    portal._bus = object()
    portal._remote = SimpleNamespace()
    portal._screen = SimpleNamespace()
    closed = []

    async def connect():
        return None

    class Variant:
        def __init__(self, _signature, value):
            self.value = value

    async def request(awaitable, *, handle_token, timeout_s=120.0):
        del awaitable, handle_token, timeout_s
        if not hasattr(request, "created"):
            request.created = True
            return {"session_handle": "/session/1"}
        raise RuntimeError("selection failed")

    async def close(session):
        closed.append(session)

    portal._remote.call_create_session = lambda _opts: object()
    portal._screen.call_select_sources = lambda *_args: object()
    monkeypatch.setattr(portal, "_connect", connect)
    monkeypatch.setattr(portal, "_request", request)
    monkeypatch.setattr(portal, "_close_session", close)

    import local_shell_mcp.gui.linux_portal as linux_portal

    monkeypatch.setattr(linux_portal, "_portal_modules", lambda: (object, Variant))

    with pytest.raises(RuntimeError, match="selection failed"):
        await portal.ensure_session()
    assert closed == ["/session/1"]
    assert portal._session is None
    assert portal._streams == []


@pytest.mark.asyncio
async def test_portal_pointer_mapping_is_fail_closed_and_right_click_is_right_button(monkeypatch):
    portal = PortalDesktop({})
    portal._streams = [
        {
            "node_id": 7,
            "properties": {"position": [100, 100], "size": [200, 100]},
        }
    ]
    assert portal._stream_point(120, 130) == (7, 20.0, 30.0)
    with pytest.raises(GuiUnavailableError, match="outside"):
        portal._stream_point(10, 10)

    calls = []

    class Remote:
        async def call_notify_pointer_button(self, session, options, code, state):
            calls.append((session, code, state))

    async def ready():
        return "session"

    portal._remote = Remote()
    portal._session = "session"
    monkeypatch.setattr(portal, "ensure_session", ready)
    await portal.button(3, True)
    await portal.button(3, False)
    assert calls == [("session", 0x111, 1), ("session", 0x111, 0)]


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


@pytest.mark.asyncio
async def test_human_batch_prevalidates_all_coordinates(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    backend = FakeBackend()
    manager = GuiManager(backend)
    observed = dict(backend.bounds)
    observation_id = _install_frame_observation(manager, backend)

    with pytest.raises(ValueError, match="outside the selected window"):
        await manager.human_act(
            "window:1",
            observation_id,
            observed,
            [
                {"type": "click", "x": 1, "y": 1},
                {"type": "drag", "x": 2, "y": 2, "to_x": 999, "to_y": 2},
            ],
        )
    assert backend.actions == []


@pytest.mark.asyncio
async def test_gui_payload_limits_precede_state_consumption(tmp_path, monkeypatch):
    import local_shell_mcp.tools as tools

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    manager = GuiManager(FakeBackend())
    state = await manager.snapshot("window:1", screenshot=False)

    with pytest.raises(ValueError, match="text may not exceed"):
        await manager.act(
            "window:1",
            state["state_id"],
            [{"type": "type", "text": "x" * 4097}],
        )
    assert state["state_id"] in manager._states

    with pytest.raises(ValueError, match="keys may contain at most"):
        await manager.act(
            "window:1",
            state["state_id"],
            [{"type": "key", "keys": ["A"] * 17}],
        )
    assert state["state_id"] in manager._states

    with pytest.raises(ValueError, match="text may not exceed"):
        tools.GuiAction.model_validate({"type": "type", "text": "x" * 4097})
    assert tools.GuiAction.model_validate(
        {"type": "key", "keys": "CTRL+A"}
    ).keys == "CTRL+A"
    assert tools.GuiAction.model_validate(
        {"type": "key", "keys": ["CTRL", "A"]}
    ).keys == ["CTRL", "A"]
    with pytest.raises(ValueError, match="keys may not exceed"):
        tools.GuiAction.model_validate({"type": "key", "keys": "X" * 257})
    with pytest.raises(ValueError, match="keys may contain at most"):
        tools.GuiAction.model_validate(
            {"type": "key", "keys": [str(index) for index in range(17)]}
        )
    with pytest.raises(ValueError, match="key requires keys"):
        tools.GuiAction.model_validate({"type": "key"})
    with pytest.raises(ValueError, match="set_value requires element_id"):
        tools.GuiAction.model_validate({"type": "set_value", "text": "secret"})
    with pytest.raises(ValueError, match="element_id must not be empty"):
        tools.GuiAction.model_validate({"type": "focus", "element_id": " "})
    with pytest.raises(ValueError, match="requires x and y"):
        tools.GuiAction.model_validate({"type": "click"})
    with pytest.raises(ValueError, match="drag requires to_x and to_y"):
        tools.GuiAction.model_validate({"type": "drag", "x": 1, "y": 1})
    with pytest.raises(ValueError, match="type requires text"):
        tools.GuiAction.model_validate({"type": "type"})
    with pytest.raises(ValueError, match="at least one key"):
        tools.GuiAction.model_validate({"type": "key", "keys": []})


@pytest.mark.asyncio
async def test_linux_stale_semantic_click_never_falls_back(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    monkeypatch.setattr(linux, "_desktop_environment", lambda: {"XDG_SESSION_TYPE": "x11"})
    backend = linux.LinuxGuiBackend()
    calls = []

    def stale(_payload):
        raise GuiStaleStateError("AT-SPI target element changed since observation")

    async def raw(*_args, **_kwargs):
        calls.append("raw")
        return {"performed": True}

    monkeypatch.setattr(backend, "_helper", stale)
    monkeypatch.setattr(backend, "_perform_x11", raw)

    with pytest.raises(GuiStaleStateError):
        await backend.perform_action(
            {"id": "w", "bounds": {"x": 0, "y": 0, "width": 100, "height": 100}},
            {
                "semantic": {"path": [0], "fingerprint": "old"},
                "bounds": {"x": 10, "y": 10, "width": 20, "height": 20},
            },
            {"type": "click"},
        )
    assert calls == []


def test_atspi_apps_skip_defunct_desktop_children(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    good = object()

    class Desktop:
        def get_child_count(self):
            return 3

        def get_child_at_index(self, index):
            if index == 1:
                raise RuntimeError("defunct app")
            return good if index == 2 else None

    monkeypatch.setattr(
        helper,
        "Atspi",
        SimpleNamespace(
            get_desktop_count=lambda: 1,
            get_desktop=lambda _index: Desktop(),
        ),
    )
    assert helper._apps() == [good]


def test_atspi_listing_skips_defunct_children(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    class GoodWindow:
        def get_role_name(self):
            return "frame"

    good = GoodWindow()

    class App:
        def get_process_id(self):
            return 42

        def get_child_count(self):
            return 2

        def get_child_at_index(self, index):
            if index == 0:
                raise RuntimeError("defunct")
            return good

    monkeypatch.setattr(helper, "_apps", lambda: [App()])
    monkeypatch.setattr(
        helper,
        "_bounds",
        lambda _window: {"x": 0, "y": 0, "width": 100, "height": 100},
    )
    windows = helper._windows()
    assert len(windows) == 1
    assert windows[0][1] is good


def test_atspi_listing_skips_iconified_and_nonshowing_windows(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    class StateSet:
        def __init__(self, states):
            self.states = set(states)

        def contains(self, state):
            return state in self.states

    class Window:
        def __init__(self, states):
            self.states = states

        def get_role_name(self):
            return "frame"

        def get_state_set(self):
            return StateSet(self.states)

    visible = Window({"showing"})
    minimized = Window({"showing", "iconified"})
    hidden = Window(set())

    class App:
        def get_process_id(self):
            return 42

        def get_child_count(self):
            return 3

        def get_child_at_index(self, index):
            return [visible, minimized, hidden][index]

    monkeypatch.setattr(
        helper,
        "Atspi",
        SimpleNamespace(
            StateType=SimpleNamespace(ICONIFIED="iconified", SHOWING="showing")
        ),
    )
    monkeypatch.setattr(helper, "_apps", lambda: [App()])
    monkeypatch.setattr(
        helper,
        "_bounds",
        lambda _window: {"x": 0, "y": 0, "width": 100, "height": 100},
    )

    windows = helper._windows()
    assert [item[1] for item in windows] == [visible]


def test_atspi_helper_bounds_provider_controlled_snapshot_fields(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    huge = "x" * (helper.GUI_MAX_ELEMENT_TEXT_BYTES * 4)

    class StateSet:
        def contains(self, _state):
            return False

    class ActionIface:
        def get_n_actions(self):
            return helper.GUI_MAX_ELEMENT_ACTIONS * 4

        def get_action_name(self, _index):
            return huge

    class Element:
        def __init__(self, index=0):
            self.index = index

        def get_accessible_id(self):
            return f"element-{self.index}"

        def get_role_name(self):
            return huge

        def get_name(self):
            return huge

        def get_action_iface(self):
            return ActionIface()

        def get_state_set(self):
            return StateSet()

        def get_child_count(self):
            return 100 if self.index == 0 else 0

        def get_child_at_index(self, index):
            return Element(index + 1)

    class App:
        def get_process_id(self):
            return 42

        def get_name(self):
            return huge

    root = Element()
    monkeypatch.setattr(
        helper,
        "Atspi",
        SimpleNamespace(
            StateType=SimpleNamespace(
                ENABLED="enabled",
                FOCUSED="focused",
                EDITABLE="editable",
            )
        ),
    )
    monkeypatch.setattr(helper, "_resolve_window", lambda _id: (App(), root, 0))
    monkeypatch.setattr(
        helper,
        "_bounds",
        lambda _obj: {"x": 0, "y": 0, "width": 100, "height": 100},
    )

    result = helper._snapshot(
        {
            "window_id": "atspi:42:sig",
            "include_elements": True,
            "max_elements": helper.GUI_MAX_ELEMENTS,
            "max_depth": helper.GUI_MAX_DEPTH,
        }
    )

    assert len(result["window"]["title"].encode()) <= helper.GUI_MAX_WINDOW_TEXT_BYTES
    assert len(result["window"]["app"].encode()) <= helper.GUI_MAX_WINDOW_TEXT_BYTES
    assert len(json.dumps(result["elements"], ensure_ascii=False).encode()) <= (
        helper.GUI_MAX_ELEMENTS_TOTAL_BYTES
    )
    assert result["elements"]
    for element in result["elements"]:
        assert len(element["role"].encode()) <= helper.GUI_MAX_ELEMENT_TEXT_BYTES
        assert len(element["name"].encode()) <= helper.GUI_MAX_ELEMENT_TEXT_BYTES
        assert len(element["actions"]) <= helper.GUI_MAX_ELEMENT_ACTIONS
        assert all(
            len(action.encode()) <= helper.GUI_MAX_ELEMENT_TEXT_BYTES
            for action in element["actions"]
        )


def test_macos_key_table_includes_physical_backquote():
    import local_shell_mcp.gui.macos as macos

    assert macos._MAC_KEY_CODES["`"] == 50


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
    backend = MacOSGuiBackend()
    record = {
        "id": "cg:7",
        "pid": 42,
        "title": "Ambiguous",
        "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
        "_ax_identity_required": True,
    }
    monkeypatch.setattr(
        backend,
        "_snapshot_accessibility_sync",
        lambda *_args, **_kwargs: (record, True, [], {}),
    )

    snapshot = await backend.snapshot(
        "cg:7",
        screenshot_path=None,
        include_elements=False,
        max_elements=1,
        max_depth=1,
    )

    assert snapshot.capabilities["accessibility"] is False
    assert snapshot.capabilities["coordinate_input"] is False
    assert snapshot.capabilities["semantic_actions"] is False
    assert snapshot.capabilities["accessibility_permission_required"] is False


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
        def AXUIElementSetAttributeValue(*_args):
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
            {"type": "drag", "x": 1, "y": 2, "to_x": 30, "to_y": 40},
        )
    assert calls == [
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
    first_record = windows._window_record(first)
    second_record = windows._window_record(second)
    assert first_record is not None
    assert second_record is not None
    assert first_record["id"] == second_record["id"]

    class Root:
        def GetChildren(self):
            return [second]

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
    replacement.ProcessId = 202
    replacement.Name = "Document B"
    replacement.GetRuntimeId = lambda: [9, 9, 9]

    class Root:
        def GetChildren(self):
            return [replacement]

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
    monkeypatch.setattr(windows, "_is_iconic_window", lambda _handle: False)
    record = windows._window_record(original)
    assert record is not None

    class Root:
        def GetChildren(self):
            return [replacement]

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
        "_horizontal_wheel",
        lambda amount: calls.append(("horizontal", amount)),
    )

    await backend.perform_action(
        {"id": "hwnd:1", "bounds": {"x": 0, "y": 0, "width": 100, "height": 100}},
        None,
        {"type": "scroll", "x": 10, "y": 10, "delta_x": 2},
    )

    assert ("horizontal", -2) in calls
    assert not any(item[0] in {"up", "down"} for item in calls)
