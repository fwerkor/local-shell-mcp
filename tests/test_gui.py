from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PIL import Image, UnidentifiedImageError

from local_shell_mcp.gui.base import (
    GuiManager,
    GuiSnapshot,
    GuiStaleStateError,
    GuiUnavailableError,
)
from local_shell_mcp.gui.linux import _session_type
from local_shell_mcp.gui.linux_portal import _keysym
from local_shell_mcp.gui.macos import _cg_bounds
from local_shell_mcp.gui.macos import _key_parts as mac_key_parts
from local_shell_mcp.gui.windows import _key_sequence, _rect_dict


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
    assert [call[1] for call in calls] == ["gui_state", "delete_file_or_dir"]

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


def test_native_gui_dependencies_are_available_on_platform():
    import subprocess
    import sys

    if sys.platform == "win32":
        from local_shell_mcp.gui.windows import _automation

        assert _automation() is not None
        return

    if sys.platform == "darwin":
        from local_shell_mcp.gui.macos import _native

        ax, quartz = _native()
        assert ax is not None
        assert quartz is not None
        return

    if sys.platform.startswith("linux"):
        import dbus_next
        import Xlib

        assert dbus_next is not None
        assert Xlib is not None
        completed = subprocess.run(
            [
                "/usr/bin/python3",
                "-c",
                "import gi; gi.require_version('Atspi','2.0'); from gi.repository import Atspi",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            pytest.skip("system AT-SPI bindings are not installed in this dev runtime")


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
