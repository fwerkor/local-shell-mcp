from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from local_shell_mcp.gui.base import (
    GuiStaleStateError,
    GuiUnavailableError,
)
from local_shell_mcp.gui.linux import _session_type


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

@pytest.mark.asyncio
async def test_linux_raw_keyboard_focuses_selected_window(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    monkeypatch.setattr(linux, "_desktop_environment", lambda: {"XDG_SESSION_TYPE": "x11"})
    backend = linux.LinuxGuiBackend()
    calls = []

    async def focus(window, _env=None, **_kwargs):
        calls.append(("focus", window["id"]))

    async def raw(window, locator, action, _env=None):
        calls.append(("raw", action["type"]))
        return {"ok": True}

    monkeypatch.setattr(backend, "_focus_window", focus)
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

@pytest.mark.asyncio
async def test_linux_focus_falls_back_to_kwin_and_reverifies_active(monkeypatch):
    from unittest.mock import AsyncMock

    import local_shell_mcp.gui.linux as linux

    backend = linux.LinuxGuiBackend()
    env = {"XDG_CURRENT_DESKTOP": "KDE", "XDG_SESSION_TYPE": "wayland"}
    monkeypatch.setattr(backend, "_ensure_env", AsyncMock(return_value=env))
    helper_results = [
        {"semantic": True},
        {"semantic": True},
    ]
    calls = []

    def helper(payload, selected_env=None):
        calls.append((payload, selected_env))
        result = helper_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    activated = []
    monkeypatch.setattr(backend, "_helper", helper)
    monkeypatch.setattr(
        linux,
        "_focus_kde_wayland_window_sync",
        lambda window, selected_env: activated.append((window, selected_env)),
    )

    window = {
        "id": "atspi:42:sig",
        "pid": 42,
        "bounds": {"x": 10, "y": 20, "width": 300, "height": 200},
    }
    await backend._focus_window(window, env)

    assert activated == [(window, env)]
    assert len(calls) == 2
    assert calls[1][0]["command"] == "semantic_action"

@pytest.mark.asyncio
async def test_linux_focus_polls_until_kwin_activation_reaches_atspi(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    backend = linux.LinuxGuiBackend()
    env = {"XDG_CURRENT_DESKTOP": "KDE", "XDG_SESSION_TYPE": "wayland"}
    results = [
        {"semantic": True},
        GuiUnavailableError("AT-SPI target cannot be focused"),
        GuiUnavailableError("AT-SPI target cannot be focused"),
        {"semantic": True},
    ]
    calls = []

    def helper(payload, selected_env=None):
        calls.append((payload, selected_env))
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr(backend, "_helper", helper)
    monkeypatch.setattr(linux.asyncio, "sleep", no_wait)
    monkeypatch.setattr(
        linux,
        "_focus_kde_wayland_window_sync",
        lambda *_args, **_kwargs: None,
    )

    await backend._focus_window(
        {
            "id": "atspi:42:sig",
            "pid": 42,
            "bounds": {"x": 10, "y": 20, "width": 300, "height": 200},
        },
        env,
    )

    assert len(calls) == 4

@pytest.mark.asyncio
async def test_linux_focus_kwin_only_waits_until_target_is_active(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    backend = linux.LinuxGuiBackend()
    env = {"XDG_CURRENT_DESKTOP": "KDE", "XDG_SESSION_TYPE": "wayland"}
    active = iter((False, False, True))
    listed_calls = []

    monkeypatch.setattr(
        linux,
        "_focus_kde_wayland_window_sync",
        lambda *_args, **_kwargs: None,
    )

    def listed(window_id, selected_env):
        listed_calls.append((window_id, selected_env))
        return {"id": window_id, "active": next(active)}

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr(backend, "_listed_window", listed)
    monkeypatch.setattr(linux.asyncio, "sleep", no_wait)

    window = {
        "id": "kwin:22222222-2222-2222-2222-222222222222",
        "pid": 42,
        "bounds": {"x": 10, "y": 20, "width": 300, "height": 200},
    }
    await backend._focus_window(window, env)

    assert len(listed_calls) == 3

@pytest.mark.asyncio
async def test_linux_focus_verifies_with_kwin_even_when_atspi_reports_active(monkeypatch):
    from unittest.mock import AsyncMock

    import local_shell_mcp.gui.linux as linux

    backend = linux.LinuxGuiBackend()
    env = {"XDG_CURRENT_DESKTOP": "KDE", "XDG_SESSION_TYPE": "wayland"}
    monkeypatch.setattr(backend, "_ensure_env", AsyncMock(return_value=env))
    helper_calls = []

    def helper(payload, _env=None):
        helper_calls.append(payload)
        return {"semantic": True, "already_active": True}

    monkeypatch.setattr(backend, "_helper", helper)
    activated = []
    monkeypatch.setattr(
        linux,
        "_focus_kde_wayland_window_sync",
        lambda window, selected_env: activated.append((window, selected_env)),
    )

    window = {
        "id": "atspi:42:sig",
        "pid": 42,
        "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
    }
    await backend._focus_window(window, env)

    assert activated == [(window, env)]
    assert len(helper_calls) == 2

@pytest.mark.asyncio
async def test_linux_snapshot_preserves_accessible_id_in_semantic_locator(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    backend = linux.LinuxGuiBackend()
    backend._env = {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}

    def helper(payload, _env=None):
        assert payload["command"] == "snapshot"
        return {
            "window": {
                "id": "atspi:1:window",
                "title": "Window",
                "app": "App",
                "pid": 1,
                "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
            },
            "elements": [
                {
                    "id": "e1",
                    "role": "button",
                    "name": "Save",
                    "bounds": {"x": 10, "y": 10, "width": 20, "height": 20},
                },
                {
                    "id": "e2",
                    "role": "label",
                    "name": "Unstable",
                    "bounds": {"x": 40, "y": 10, "width": 20, "height": 20},
                },
            ],
            "locators": {
                "e1": {
                    "path": [0],
                    "accessible_id": "save-button",
                    "fingerprint": "save-fp",
                }
            },
        }

    monkeypatch.setattr(backend, "_helper", helper)
    snapshot = await backend.snapshot(
        "atspi:1:window",
        screenshot_path=None,
        include_elements=True,
        max_elements=10,
        max_depth=2,
    )

    assert snapshot.locators["e1"]["semantic"] == {
        "path": [0],
        "accessible_id": "save-button",
        "fingerprint": "save-fp",
    }
    assert "e2" not in snapshot.locators

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

def test_linux_environment_discovery_clears_missing_stale_display_selectors(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    monkeypatch.setenv("DISPLAY", ":stale")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-stale")
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/keep")
    monkeypatch.setattr(linux.shutil, "which", lambda _name: "/usr/bin/systemctl")
    monkeypatch.setattr(
        linux.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="WAYLAND_DISPLAY=wayland-3\nXDG_SESSION_TYPE=wayland\n",
        ),
    )

    env = linux._desktop_environment()

    assert "DISPLAY" not in env
    assert env["WAYLAND_DISPLAY"] == "wayland-3"
    assert env["XDG_SESSION_TYPE"] == "wayland"
    assert env["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/keep"

@pytest.mark.asyncio
async def test_linux_desktop_environment_refreshes_and_resets_portal(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    backend = linux.LinuxGuiBackend()
    times = iter([100.0, 100.0, 131.0, 131.0])
    environments = iter(
        [
            {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"},
            {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-1"},
        ]
    )
    monkeypatch.setattr(
        linux,
        "time",
        SimpleNamespace(monotonic=lambda: next(times)),
    )
    monkeypatch.setattr(linux, "_desktop_environment", lambda: next(environments))

    first = await backend._ensure_env()
    closed = []

    class Portal:
        async def close(self):
            closed.append(True)

    backend._portal = Portal()
    second = await backend._ensure_env()
    assert first["DISPLAY"] == ":0"
    assert second["WAYLAND_DISPLAY"] == "wayland-1"
    assert backend._portal is None
    assert closed == [True]

@pytest.mark.asyncio
async def test_linux_raw_element_action_reresolves_locator_bounds(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    backend = linux.LinuxGuiBackend()
    backend._env = {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}
    helper_calls = []
    received = []

    def helper(payload, _env=None):
        helper_calls.append(payload)
        assert payload["command"] == "resolve_locator"
        return {"bounds": {"x": 40, "y": 50, "width": 20, "height": 10}}

    async def focus(_window, _env=None, **_kwargs):
        return None

    async def raw(_window, locator, _action, _env=None):
        received.append(locator)
        return {"performed": True}

    monkeypatch.setattr(backend, "_helper", helper)
    monkeypatch.setattr(backend, "_focus_window", focus)
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
async def test_linux_raw_pointer_focuses_target_before_injection(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    backend = linux.LinuxGuiBackend()
    backend._env = {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}
    calls = []

    async def focus(_window, _env=None, **_kwargs):
        calls.append("focus")

    async def raw(_window, _locator, _action, _env=None):
        calls.append("raw")
        return {"performed": True}

    monkeypatch.setattr(backend, "_focus_window", focus)
    monkeypatch.setattr(backend, "_perform_x11", raw)
    result = await backend.perform_action(
        {"id": "w", "bounds": {"x": 0, "y": 0, "width": 100, "height": 100}},
        None,
        {"type": "click", "x": 10, "y": 10},
    )
    assert result == {"performed": True}
    assert calls == ["focus", "raw"]

@pytest.mark.asyncio
async def test_linux_stale_semantic_click_never_falls_back(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    monkeypatch.setattr(linux, "_desktop_environment", lambda: {"XDG_SESSION_TYPE": "x11"})
    backend = linux.LinuxGuiBackend()
    calls = []

    def stale(_payload, _env=None):
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

def test_linux_helper_timeout_before_synthesis_does_not_release_inputs(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    payloads = []

    monkeypatch.setattr(linux, "_helper_python", lambda _env: "/usr/bin/python3")
    monkeypatch.setattr(linux, "_helper_path", lambda: Path("/tmp/helper.py"))

    def run(_argv, **kwargs):
        payloads.append(json.loads(kwargs["input"]))
        raise linux.subprocess.TimeoutExpired(cmd="helper", timeout=30)

    monkeypatch.setattr(linux.subprocess, "run", run)

    raw = {
        "command": "raw",
        "kind": "key_chord",
        "keys": ["CTRL", "A"],
    }
    with pytest.raises(GuiUnavailableError, match="helper timed out"):
        linux._run_helper(raw, {})

    assert len(payloads) == 1
    assert payloads[0]["command"] == "raw"
    assert payloads[0]["keys"] == ["CTRL", "A"]
    assert isinstance(payloads[0]["_progress_fd"], int)

def test_linux_helper_timeout_releases_only_confirmed_held_inputs(monkeypatch):
    import local_shell_mcp.gui.linux as linux

    payloads = []

    monkeypatch.setattr(linux, "_helper_python", lambda _env: "/usr/bin/python3")
    monkeypatch.setattr(linux, "_helper_path", lambda: Path("/tmp/helper.py"))

    def run(_argv, **kwargs):
        payload = json.loads(kwargs["input"])
        payloads.append(payload)
        if len(payloads) == 1:
            progress_fd = kwargs["pass_fds"][0]
            linux.os.write(
                progress_fd,
                (
                    b'{"kind":"key","symbol":1001,"state":"press"}\n'
                    b'{"kind":"key","symbol":1002,"state":"press"}\n'
                    b'{"kind":"key","symbol":1002,"state":"release"}\n'
                ),
            )
            raise linux.subprocess.TimeoutExpired(cmd="helper", timeout=30)
        return SimpleNamespace(stdout='{"ok": true}\n', stderr="", returncode=0)

    monkeypatch.setattr(linux.subprocess, "run", run)

    raw = {
        "command": "raw",
        "kind": "key_chord",
        "keys": ["CTRL", "A"],
    }
    with pytest.raises(GuiUnavailableError, match="helper timed out"):
        linux._run_helper(raw, {})

    assert payloads[1] == {
        "command": "release_inputs",
        "pressed": [{"kind": "key", "symbol": 1001}],
    }

@pytest.mark.asyncio
async def test_linux_snapshot_keeps_discovered_environment_for_all_helper_calls(
    tmp_path, monkeypatch
):
    import local_shell_mcp.gui.linux as linux
    from local_shell_mcp.settings import get_settings

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()

    old_env = {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":1"}
    replacement_env = {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-1"}
    backend = linux.LinuxGuiBackend()
    backend._env = old_env
    backend._env_refreshed_at = time.monotonic()
    seen_envs = []
    snapshot_calls = 0

    def helper(payload, env=None):
        nonlocal snapshot_calls
        seen_envs.append(env)
        if payload["command"] == "list":
            return {"windows": [], "monitors": []}
        if payload["command"] == "snapshot":
            snapshot_calls += 1
            if snapshot_calls == 1:
                backend._env = replacement_env
            return {
                "window": {
                    "id": "atspi:1:stable",
                    "title": "Target",
                    "app": "App",
                    "pid": 1,
                    "bounds": {"x": 0, "y": 0, "width": 20, "height": 10},
                },
                "elements": [],
                "locators": {},
            }
        raise AssertionError(payload)

    async def capture(path, _record, env):
        seen_envs.append(env)
        Image.new("RGB", (20, 10)).save(path, format="PNG")
        return "xcomposite"

    monkeypatch.setattr(backend, "_helper", helper)
    monkeypatch.setattr(linux, "_capture_x11", capture)

    result = await backend.snapshot(
        "atspi:1:stable",
        screenshot_path=tmp_path / "bound-env.png",
        include_elements=False,
        max_elements=1,
        max_depth=1,
    )

    assert result.capabilities["session_type"] == "x11"
    assert snapshot_calls == 2
    assert seen_envs
    assert all(env is old_env for env in seen_envs)
    assert backend._env is replacement_env
    get_settings.cache_clear()
