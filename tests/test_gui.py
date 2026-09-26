from __future__ import annotations

import asyncio
import tomllib
from pathlib import Path
from types import SimpleNamespace
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
    assert backend.actions[0][1] == "native-element"
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
    from local_shell_mcp.image_ops import ImageFile

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


@pytest.mark.asyncio
async def test_gui_state_result_local_screenshot(tmp_path, monkeypatch):
    import local_shell_mcp.tools as tools

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    get_settings = tools.get_settings
    get_settings.cache_clear()

    shot = tmp_path / "shot.png"
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


@pytest.mark.asyncio
async def test_gui_state_result_remote_screenshot_and_cleanup(tmp_path, monkeypatch):
    import local_shell_mcp.tools as tools
    from local_shell_mcp.image_ops import ImageFile

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

    async def remote_transfer(machine, tool, args, timeout_s=None):
        assert tool == "transfer_stat"
        return {"type": "file", "size": 7, "path": args["path"]}

    async def copy_remote(machine, source, destination, overwrite):
        Path(destination).write_bytes(b"fakepng")

    monkeypatch.setattr(tools, "_remote_worker_data", remote_worker)
    monkeypatch.setattr(tools, "_remote_transfer_data", remote_transfer)
    monkeypatch.setattr(tools, "_copy_remote_file_to_local", copy_remote)
    monkeypatch.setattr(
        tools,
        "transfer_alloc_temp_path",
        lambda suffix: {"path": str(tmp_path / f"temporary{suffix}")},
    )
    monkeypatch.setattr(
        tools,
        "read_image",
        lambda path: ImageFile(
            path=str(path),
            data=b"image",
            format="png",
            mime_type="image/png",
            size=5,
        ),
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
        "delete_file_or_dir",
        "gui_state_refresh",
    ]

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

@pytest.mark.asyncio
async def test_gui_frame_data_local_and_remote_paths(tmp_path, monkeypatch):
    import local_shell_mcp.tools as tools
    from local_shell_mcp.image_ops import ImageFile

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "true")
    tools.get_settings.cache_clear()

    local_shot = tmp_path / "local-frame.png"
    local_shot.write_bytes(b"local")

    class Manager:
        async def frame(self, window_id):
            assert window_id == "w"
            return {
                "backend": "local",
                "window": {"id": "w", "bounds": {"x": 0, "y": 0, "width": 4, "height": 4}},
                "capabilities": {},
                "screenshot_path": str(local_shot),
            }

    image = ImageFile(
        path="frame.png",
        data=b"image",
        format="png",
        mime_type="image/png",
        size=5,
    )
    monkeypatch.setattr(tools, "get_gui_manager", lambda: Manager())
    monkeypatch.setattr(tools, "read_image", lambda _path: image)

    local_data, local_image = await tools._gui_frame_data("w", None)
    assert local_data["backend"] == "local"
    assert "screenshot_path" not in local_data
    assert local_image is image
    assert not local_shot.exists()

    calls = []

    async def remote_worker(machine, tool, args, timeout_s=None):
        calls.append((machine, tool, args, timeout_s))
        if tool == "gui_frame":
            return {
                "backend": "remote",
                "window": {"id": "w", "bounds": {"x": 0, "y": 0, "width": 4, "height": 4}},
                "capabilities": {},
                "screenshot_path": ".local-shell-mcp/tmp/frame.png",
            }
        assert tool == "delete_file_or_dir"
        return {"deleted": True}

    async def remote_transfer(machine, tool, args, timeout_s=None):
        assert machine == "node"
        assert tool == "transfer_stat"
        return {"type": "file", "path": args["path"], "size": 5}

    async def copy_remote(machine, source, destination, overwrite):
        assert (machine, overwrite) == ("node", True)
        Path(destination).write_bytes(b"remote")

    monkeypatch.setattr(tools, "_remote_worker_data", remote_worker)
    monkeypatch.setattr(tools, "_remote_transfer_data", remote_transfer)
    monkeypatch.setattr(tools, "_copy_remote_file_to_local", copy_remote)
    monkeypatch.setattr(
        tools,
        "transfer_alloc_temp_path",
        lambda suffix: {"path": str(tmp_path / f"relay{suffix}")},
    )

    remote_data, remote_image = await tools._gui_frame_data("w", "node")
    assert remote_data["backend"] == "remote"
    assert "screenshot_path" not in remote_data
    assert remote_image is image
    assert [call[1] for call in calls] == ["gui_frame", "delete_file_or_dir"]
    assert not (tmp_path / "relay.png").exists()


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

    async def remote_frame(*_args, **_kwargs):
        return {"window": {"id": "w"}, "screenshot_path": "remote.png"}

    async def bad_stat(*_args, **_kwargs):
        return {"type": "directory"}

    cleanup_calls = []

    async def remote_frame_with_cleanup(machine, tool, args, timeout_s=None):
        if tool == "gui_frame":
            return {"window": {"id": "w"}, "screenshot_path": "remote.png"}
        cleanup_calls.append((machine, tool, args, timeout_s))
        return {"deleted": True}

    monkeypatch.setattr(tools, "_remote_worker_data", remote_frame_with_cleanup)
    monkeypatch.setattr(tools, "_remote_transfer_data", bad_stat)
    with pytest.raises(RuntimeError, match="not a file"):
        await tools._gui_frame_data("w", "node")
    assert cleanup_calls == [
        (
            "node",
            "delete_file_or_dir",
            {"path": "remote.png", "recursive": False},
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


def test_atspi_window_identity_survives_child_reordering(monkeypatch):
    from local_shell_mcp.gui import linux_atspi_helper as helper

    class Window:
        def __init__(self, title):
            self.title = title

        def get_name(self):
            return self.title

        def get_role_name(self):
            return "frame"

    class App:
        def __init__(self, children):
            self.children = children

        def get_process_id(self):
            return 42

        def get_child_count(self):
            return len(self.children)

        def get_child_at_index(self, index):
            return self.children[index]

    target = Window("Target")
    other = Window("Other")
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
    replacement = Window("Replacement")
    app.children = [replacement]
    with pytest.raises(LookupError, match="no longer available"):
        helper._resolve_window(f"atspi:42:0:{replacement_signature}")

    duplicate = Window("Target")
    app.children = [target, duplicate]
    ambiguous_signature = helper._window_signature(target)
    with pytest.raises(LookupError, match="ambiguous"):
        helper._resolve_window(f"atspi:42:0:{ambiguous_signature}")


@pytest.mark.asyncio
async def test_windows_native_traversal_is_offloaded(monkeypatch):
    import local_shell_mcp.gui.windows as windows

    backend = WindowsGuiBackend()
    calls = []

    async def fake_to_thread(func, *args, **kwargs):
        calls.append(func.__name__)
        return func(*args, **kwargs)

    monkeypatch.setattr(windows.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(backend, "_list_windows_sync", lambda: {"windows": []})
    monkeypatch.setattr(
        backend,
        "_snapshot_sync",
        lambda *args, **kwargs: GuiSnapshot(window={"id": "w", "bounds": {}}, elements=[]),
    )

    await backend.list_windows()
    await backend.snapshot(
        "w",
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
        {"id": "hwnd:1", "bounds": {"x": 0, "y": 0, "width": 10, "height": 10}},
        None,
        {"type": "click", "x": 1, "y": 1},
    )
    assert result == {"performed": True}
    assert calls == ["<lambda>", "<lambda>", "<lambda>"]


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

    result = await manager.human_act(
        "window:1",
        observed,
        [
            {"type": "click", "x": 10, "y": 12},
            {"type": "type", "text": "hello"},
        ],
    )

    assert result["human_control"] is True
    assert [item["type"] for item in result["actions"]] == ["click", "type"]
    assert [item[2]["type"] for item in backend.actions] == [
        "click",
        "focus_window",
        "type",
    ]

    backend.bounds["x"] += 1
    with pytest.raises(GuiStaleStateError, match="displayed frame"):
        await manager.human_act(
            "window:1",
            observed,
            [{"type": "click", "x": 10, "y": 12}],
        )


@pytest.mark.asyncio
async def test_gui_manager_human_actions_reject_unscoped_targets(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    backend = FakeBackend()
    manager = GuiManager(backend)
    observed = dict(backend.bounds)

    with pytest.raises(ValueError, match="outside the selected window"):
        await manager.human_act(
            "window:1",
            observed,
            [{"type": "click", "x": 999, "y": 1}],
        )
    with pytest.raises(ValueError, match="do not accept element_id"):
        await manager.human_act(
            "window:1",
            observed,
            [{"type": "click", "element_id": "e1"}],
        )
    with pytest.raises(ValueError, match="Unsupported human GUI action"):
        await manager.human_act(
            "window:1",
            observed,
            [{"type": "wait", "seconds": 1}],
        )
    with pytest.raises(ValueError, match="Observed window bounds"):
        await manager.human_act("window:1", {}, [{"type": "type", "text": "x"}])
    with pytest.raises(GuiStaleStateError, match="no longer available"):
        await manager.human_act(
            "missing",
            observed,
            [{"type": "type", "text": "x"}],
        )


@pytest.mark.asyncio
async def test_gui_frame_does_not_allocate_model_state(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    manager = GuiManager(FakeBackend())

    frame = await manager.frame("window:1")

    assert frame["window"]["id"] == "window:1"
    assert "state_id" not in frame
    assert manager._states == {}
    screenshot = Path(frame["screenshot_path"])
    assert screenshot.is_file()
    screenshot.unlink()


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
    await asyncio.gather(
        manager.human_act("window:1", bounds, [{"type": "click", "x": 1, "y": 1}]),
        manager.human_act("window:1", bounds, [{"type": "click", "x": 2, "y": 2}]),
    )
    assert backend.max_active == 1


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
async def test_x11_drag_releases_button_after_motion_failure(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    monkeypatch.setattr(linux, "_desktop_environment", lambda: {"XDG_SESSION_TYPE": "x11"})
    backend = linux.LinuxGuiBackend()
    events = []

    def helper(payload):
        event = payload.get("event")
        events.append(event)
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
    assert events == ["b1p", "abs", "b1r"]


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
async def test_portal_key_chord_releases_every_successfully_pressed_key(monkeypatch):
    portal = PortalDesktop({})
    events = []
    fail_once = {"value": True}

    async def key_event(symbol, pressed):
        events.append((symbol, pressed))
        if symbol == 0x41 and pressed and fail_once["value"]:
            fail_once["value"] = False
            raise RuntimeError("key down failed")

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
        return None

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
    monkeypatch.setattr(backend, "_find_ax_window", lambda _window: "window")

    with pytest.raises(RuntimeError, match="could not be focused"):
        await backend.perform_action(
            {"id": "cg:1", "bounds": {"x": 0, "y": 0, "width": 10, "height": 10}},
            "element",
            {"type": "type", "text": "x"},
        )
    with pytest.raises(RuntimeError, match="could not be focused"):
        await backend.perform_action(
            {"id": "cg:1", "bounds": {"x": 0, "y": 0, "width": 10, "height": 10}},
            "element",
            {"type": "key", "keys": "A"},
        )


@pytest.mark.asyncio
async def test_human_batch_prevalidates_all_coordinates(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    backend = FakeBackend()
    manager = GuiManager(backend)
    observed = dict(backend.bounds)

    with pytest.raises(ValueError, match="outside the selected window"):
        await manager.human_act(
            "window:1",
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


def test_macos_utf16_text_units_and_chunks():
    assert _utf16_units("A") == 1
    assert _utf16_units("😀") == 2
    assert _utf16_units("A😀") == 3
    assert _unicode_chunks("A😀B", max_units=2) == ["A", "😀", "B"]


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
    monkeypatch.setattr(backend, "_find_window", lambda _window_id: target)

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
    monkeypatch.setattr(backend, "_find_window", lambda _window_id: Target())
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

    assert ("horizontal", 2) in calls
    assert not any(item[0] in {"up", "down"} for item in calls)
