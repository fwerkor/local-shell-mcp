from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from local_shell_mcp.gui.base import (
    GuiStaleStateError,
    GuiUnavailableError,
)
from local_shell_mcp.gui.linux import _desktop_crop_box


def test_wayland_full_desktop_crop_requires_monitor_geometry():
    with pytest.raises(GuiUnavailableError, match="Monitor geometry is unavailable"):
        _desktop_crop_box(
            {"x": -100, "y": 0, "width": 200, "height": 100},
            [],
            (1920, 1080),
        )

def test_wayland_desktop_crop_rejects_oversized_header_before_decode(tmp_path, monkeypatch):
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

    def helper(payload, _env=None):
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

    async def focus(_window, _env=None, **_kwargs):
        calls.append("focus")

    async def capture(path, bounds, monitors, env, *, portal=None):
        del bounds, monitors, env, portal
        calls.append("capture")
        Image.new("RGB", (10, 10)).save(path)
        return "test-wayland"

    monkeypatch.setattr(backend, "_helper", helper)
    monkeypatch.setattr(backend, "_focus_window", focus)
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

    def helper(payload, _env=None):
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

    async def focus(_window, _env=None, **_kwargs):
        return None

    async def capture(*_args, **_kwargs):
        pytest.fail("capture must not run with stale Wayland bounds")

    monkeypatch.setattr(backend, "_helper", helper)
    monkeypatch.setattr(backend, "_focus_window", focus)
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
async def test_wayland_snapshot_rejects_bounds_change_during_capture(tmp_path, monkeypatch):
    import local_shell_mcp.gui.linux as linux

    backend = linux.LinuxGuiBackend()
    backend._env = {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"}
    snapshot_calls = 0

    def helper(payload, _env=None):
        nonlocal snapshot_calls
        if payload["command"] == "snapshot":
            snapshot_calls += 1
            x = 50 if snapshot_calls == 3 else 0
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

    async def focus(_window, _env=None, **_kwargs):
        return None

    async def capture(path, *_args, **_kwargs):
        Image.new("RGB", (10, 10)).save(path, format="PNG")
        return "grim-region"

    monkeypatch.setattr(backend, "_helper", helper)
    monkeypatch.setattr(backend, "_focus_window", focus)
    monkeypatch.setattr(linux, "_capture_wayland", capture)

    with pytest.raises(GuiStaleStateError, match="during the Wayland capture"):
        await backend.snapshot(
            "atspi:1:sig",
            screenshot_path=tmp_path / "wayland.png",
            include_elements=False,
            max_elements=10,
            max_depth=2,
        )
    assert snapshot_calls == 3

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
async def test_wayland_full_capture_fallback_uses_private_creation_mask(
    tmp_path,
    monkeypatch,
):
    import local_shell_mcp.gui.linux as linux

    path = tmp_path / "spectacle.png"
    path.write_bytes(b"precreated")
    path.chmod(0o600)
    calls = []

    monkeypatch.setattr(
        linux.shutil,
        "which",
        lambda name: "/usr/bin/spectacle" if name == "spectacle" else None,
    )

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        assert kwargs["umask"] == 0o077
        Image.new("RGB", (10, 10)).save(path, format="PNG")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(linux.subprocess, "run", run)
    monkeypatch.setattr(linux, "_crop_desktop_capture", lambda *_args: None)

    method = await linux._capture_wayland(
        path,
        {"x": 0, "y": 0, "width": 10, "height": 10},
        [],
        {},
    )

    assert method == "spectacle"
    assert len(calls) == 1

@pytest.mark.asyncio
async def test_wayland_portal_fallback_keeps_precreated_private_destination(
    tmp_path,
    monkeypatch,
):
    import local_shell_mcp.gui.linux as linux

    path = tmp_path / "portal.png"
    path.write_bytes(b"precreated")
    path.chmod(0o600)
    monkeypatch.setattr(linux.shutil, "which", lambda _name: None)

    async def screenshot(destination, _env):
        assert destination == path
        assert destination.exists()
        if linux.os.name == "posix":
            assert destination.stat().st_mode & 0o777 == 0o600
        Image.new("RGB", (10, 10)).save(destination, format="PNG")

    monkeypatch.setattr(linux, "portal_screenshot", screenshot)
    monkeypatch.setattr(linux, "_crop_desktop_capture", lambda *_args: None)

    method = await linux._capture_wayland(
        path,
        {"x": 0, "y": 0, "width": 10, "height": 10},
        [],
        {},
    )

    assert method == "xdg-desktop-portal"
    if linux.os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600

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

    async def focus(_window, _env=None, **_kwargs):
        calls.append("focus")

    monkeypatch.setattr(backend, "_focus_window", focus)
    result = await backend._perform_wayland(
        {"id": "atspi:1:sig", "bounds": {"x": 0, "y": 0, "width": 100, "height": 100}},
        None,
        {"type": "click", "x": 5, "y": 6},
    )
    assert result["method"] == "xdg-desktop-portal"
    assert calls == ["bootstrap", "focus", "click"]

@pytest.mark.asyncio
async def test_wayland_rejects_observation_expired_during_portal_bootstrap(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    backend = linux.LinuxGuiBackend()
    backend._env = {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"}

    class Portal:
        async def ensure_session(self):
            return "session-1"

        async def click(self, *_args, **_kwargs):
            pytest.fail("expired observation must not inject pointer input")

    backend._portal = Portal()
    monkeypatch.setattr(linux.time, "monotonic", lambda: 20.0)

    with pytest.raises(GuiStaleStateError, match="expired while preparing input"):
        await backend._perform_wayland(
            {
                "id": "atspi:1:sig",
                "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
            },
            None,
            {
                "type": "click",
                "x": 5,
                "y": 6,
                "_observation_deadline": 10.0,
            },
        )

@pytest.mark.asyncio
async def test_wayland_reresolves_element_bounds_after_portal_bootstrap(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    backend = linux.LinuxGuiBackend()
    backend._env = {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"}
    clicks = []

    class Portal:
        async def ensure_session(self):
            return "session-1"

        async def click(self, x, y, **_kwargs):
            clicks.append((x, y))

    backend._portal = Portal()

    async def focus(_window, _env=None, **_kwargs):
        return None

    def helper(payload, _env=None):
        assert payload["command"] == "resolve_locator"
        return {"bounds": {"x": 40, "y": 50, "width": 20, "height": 10}}

    monkeypatch.setattr(backend, "_focus_window", focus)
    monkeypatch.setattr(backend, "_helper", helper)
    monkeypatch.setattr(linux.time, "monotonic", lambda: 5.0)

    result = await backend._perform_wayland(
        {
            "id": "atspi:1:sig",
            "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
        },
        {
            "semantic": {
                "path": [0],
                "accessible_id": "button",
                "fingerprint": "fp",
            },
            "bounds": {"x": 10, "y": 10, "width": 10, "height": 10},
        },
        {"type": "click", "_observation_deadline": 10.0},
    )

    assert clicks == [(50, 55)]
    assert result["screen_x"] == 50
    assert result["screen_y"] == 55

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

    async def focus(_window, _env=None, **_kwargs):
        calls.append("focus")

    def helper(payload, _env=None):
        assert payload["command"] == "snapshot"
        calls.append("snapshot")
        return {
            "window": {
                "id": "atspi:1:sig",
                "bounds": {"x": 10, "y": 0, "width": 100, "height": 100},
            }
        }

    monkeypatch.setattr(backend, "_focus_window", focus)
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

def test_wayland_equal_size_full_desktop_does_not_bypass_geometry_validation(
    tmp_path,
):
    import local_shell_mcp.gui.linux as linux

    path = tmp_path / "desktop.png"
    Image.new("RGB", (100, 100)).save(path, format="PNG")
    monitors = [{"x": 0, "y": 0, "width": 100, "height": 100, "scale": 1}]
    bounds = {"x": 10, "y": 0, "width": 100, "height": 100}

    with pytest.raises(GuiUnavailableError, match="does not match the monitor layout"):
        linux._crop_desktop_capture(path, bounds, monitors)
