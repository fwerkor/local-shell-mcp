from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageGrab

from .base import (
    GuiSnapshot,
    GuiStaleStateError,
    GuiUnavailableError,
    display_screenshot_path,
    quantize_scroll_amount,
)
from .linux_portal import PortalDesktop, portal_screenshot

_DESKTOP_ENV_KEYS = {
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XDG_SESSION_TYPE",
    "XDG_CURRENT_DESKTOP",
    "XDG_RUNTIME_DIR",
    "DBUS_SESSION_BUS_ADDRESS",
}

_HELPER_PYTHON: str | None = None


def _desktop_environment() -> dict[str, str]:
    env = dict(os.environ)
    missing = [key for key in _DESKTOP_ENV_KEYS if not env.get(key)]
    if missing and shutil.which("systemctl"):
        try:
            result = subprocess.run(
                ["systemctl", "--user", "show-environment"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired):
            result = None
        if result is not None and result.returncode == 0:
            for line in result.stdout.splitlines():
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key in _DESKTOP_ENV_KEYS and value and not env.get(key):
                    env[key] = value
    return env


def _session_type(env: dict[str, str]) -> str:
    explicit = env.get("XDG_SESSION_TYPE", "").lower()
    if explicit in {"wayland", "x11"}:
        return explicit
    if env.get("WAYLAND_DISPLAY"):
        return "wayland"
    if env.get("DISPLAY"):
        return "x11"
    return "unknown"


def _helper_path() -> Path:
    return Path(__file__).with_name("linux_atspi_helper.py")


def _helper_python(env: dict[str, str]) -> str:
    global _HELPER_PYTHON
    if _HELPER_PYTHON is not None:
        return _HELPER_PYTHON

    candidates = [sys.executable, "/usr/bin/python3"]
    found = shutil.which("python3")
    if found:
        candidates.append(found)
    checked = set()
    for candidate in candidates:
        if not candidate or candidate in checked or not Path(candidate).exists():
            continue
        checked.add(candidate)
        result = subprocess.run(
            [
                candidate,
                "-c",
                (
                    "import gi; gi.require_version('Atspi','2.0'); "
                    "from gi.repository import Atspi; print(Atspi.get_desktop_count())"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env=env,
        )
        if result.returncode == 0:
            _HELPER_PYTHON = candidate
            return candidate
    raise GuiUnavailableError(
        "Linux GUI accessibility requires AT-SPI Python bindings. Install python3-gi "
        "and gir1.2-atspi-2.0 in the desktop session."
    )


class _SemanticActionUnavailableError(GuiUnavailableError):
    """Raised only when an AT-SPI element lacks a semantic click action."""


def _run_helper(payload: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    result = subprocess.run(
        [_helper_python(env), str(_helper_path())],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=env,
    )
    stdout = result.stdout.strip().splitlines()
    response = None
    if stdout:
        try:
            response = json.loads(stdout[-1])
        except json.JSONDecodeError:
            response = None
    if not isinstance(response, dict):
        detail = (result.stderr or result.stdout or "").strip()
        raise GuiUnavailableError(f"AT-SPI helper failed: {detail or result.returncode}")
    if not response.get("ok"):
        message = str(response.get("error") or "AT-SPI helper failed")
        error_type = str(response.get("error_type") or "")
        if error_type == "LookupError":
            raise GuiStaleStateError(message)
        if error_type == "ValueError" and (
            "no AT-SPI action interface" in message
            or "no AT-SPI actions" in message
        ):
            raise _SemanticActionUnavailableError(message)
        raise GuiUnavailableError(message)
    data = response.get("data")
    return data if isinstance(data, dict) else {}


def _window_center(bounds: dict[str, Any]) -> tuple[int, int]:
    return (
        int(bounds["x"]) + int(bounds["width"]) // 2,
        int(bounds["y"]) + int(bounds["height"]) // 2,
    )


def _monitor_for_window(
    bounds: dict[str, Any],
    monitors: list[dict[str, Any]],
) -> dict[str, Any] | None:
    cx, cy = _window_center(bounds)
    for monitor in monitors:
        if (
            int(monitor["x"]) <= cx < int(monitor["x"]) + int(monitor["width"])
            and int(monitor["y"]) <= cy < int(monitor["y"]) + int(monitor["height"])
        ):
            return monitor
    return None


def _scaled_axis_offset(
    coordinate: int,
    origin: int,
    *,
    axis: str,
    cross_coordinate: int,
    monitors: list[dict[str, Any]],
) -> int:
    size_key = "width" if axis == "x" else "height"
    cross_axis = "y" if axis == "x" else "x"
    cross_size = "height" if axis == "x" else "width"
    start, end = sorted((origin, coordinate))
    boundaries = {start, end}
    relevant = []
    for monitor in monitors:
        cross_start = int(monitor[cross_axis])
        cross_end = cross_start + int(monitor[cross_size])
        if not cross_start <= cross_coordinate < cross_end:
            continue
        axis_start = int(monitor[axis])
        axis_end = axis_start + int(monitor[size_key])
        if axis_end <= start or axis_start >= end:
            continue
        relevant.append(monitor)
        boundaries.add(max(start, axis_start))
        boundaries.add(min(end, axis_end))

    total = 0.0
    ordered = sorted(boundaries)
    for left, right in zip(ordered, ordered[1:], strict=False):
        midpoint = (left + right) / 2
        scale = 1.0
        for monitor in relevant:
            monitor_start = int(monitor[axis])
            monitor_end = monitor_start + int(monitor[size_key])
            if monitor_start <= midpoint < monitor_end:
                scale = float(monitor.get("scale", 1) or 1)
                break
        total += (right - left) * scale
    offset = int(round(total))
    return -offset if coordinate < origin else offset


def _desktop_crop_box(
    bounds: dict[str, Any],
    monitors: list[dict[str, Any]],
    image_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    x = int(bounds["x"])
    y = int(bounds["y"])
    width = max(1, int(bounds["width"]))
    height = max(1, int(bounds["height"]))
    if not monitors:
        raise GuiUnavailableError(
            "Monitor geometry is unavailable; cannot crop a full-desktop capture safely"
        )

    origin_x = min(int(item["x"]) for item in monitors)
    origin_y = min(int(item["y"]) for item in monitors)
    logical_right = max(int(item["x"]) + int(item["width"]) for item in monitors)
    logical_bottom = max(int(item["y"]) + int(item["height"]) for item in monitors)
    logical_size = (logical_right - origin_x, logical_bottom - origin_y)
    if image_size == logical_size:
        left = x - origin_x
        top = y - origin_y
        return left, top, left + width, top + height

    if _monitor_for_window(bounds, monitors) is None:
        raise GuiUnavailableError("Could not map the target window to a captured monitor")

    center_x, center_y = _window_center(bounds)
    left = _scaled_axis_offset(
        x,
        origin_x,
        axis="x",
        cross_coordinate=center_y,
        monitors=monitors,
    )
    top = _scaled_axis_offset(
        y,
        origin_y,
        axis="y",
        cross_coordinate=center_x,
        monitors=monitors,
    )
    right = _scaled_axis_offset(
        x + width,
        origin_x,
        axis="x",
        cross_coordinate=center_y,
        monitors=monitors,
    )
    bottom = _scaled_axis_offset(
        y + height,
        origin_y,
        axis="y",
        cross_coordinate=center_x,
        monitors=monitors,
    )
    if left < 0 or top < 0 or right > image_size[0] or bottom > image_size[1]:
        raise GuiUnavailableError(
            "Captured desktop geometry does not match the monitor layout; "
            "cannot crop the target window safely"
        )
    return left, top, right, bottom


def _crop_desktop_capture(
    path: Path,
    bounds: dict[str, Any],
    monitors: list[dict[str, Any]],
) -> None:
    with Image.open(path) as image:
        image.load()
        if image.size == (int(bounds["width"]), int(bounds["height"])):
            return
        cropped = image.crop(_desktop_crop_box(bounds, monitors, image.size))
        cropped.save(path, format="PNG")


async def _capture_wayland(
    path: Path,
    bounds: dict[str, Any],
    monitors: list[dict[str, Any]],
    env: dict[str, str],
) -> str:
    grim = shutil.which("grim")
    if grim:
        geometry = (
            f"{int(bounds['x'])},{int(bounds['y'])} "
            f"{int(bounds['width'])}x{int(bounds['height'])}"
        )
        result = await asyncio.to_thread(
            subprocess.run,
            [grim, "-g", geometry, str(path)],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            env=env,
        )
        if result.returncode == 0 and path.is_file():
            return "grim-region"

    full_capture_commands: list[tuple[str, list[str]]] = []
    spectacle = shutil.which("spectacle")
    if spectacle:
        full_capture_commands.append(
            ("spectacle", [spectacle, "-b", "-n", "-f", "-o", str(path)])
        )
    gnome_screenshot = shutil.which("gnome-screenshot")
    if gnome_screenshot:
        full_capture_commands.append(
            ("gnome-screenshot", [gnome_screenshot, "-f", str(path)])
        )

    for name, command in full_capture_commands:
        path.unlink(missing_ok=True)
        result = await asyncio.to_thread(
            subprocess.run,
            command,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            env=env,
        )
        if result.returncode == 0 and path.is_file():
            await asyncio.to_thread(_crop_desktop_capture, path, bounds, monitors)
            return name

    path.unlink(missing_ok=True)
    await portal_screenshot(path, env)
    if not path.is_file():
        raise GuiUnavailableError("Wayland screenshot portal did not return an image")
    await asyncio.to_thread(_crop_desktop_capture, path, bounds, monitors)
    return "xdg-desktop-portal"


async def _capture_x11(
    path: Path,
    bounds: dict[str, Any],
    env: dict[str, str],
) -> str:
    x = int(bounds["x"])
    y = int(bounds["y"])
    width = int(bounds["width"])
    height = int(bounds["height"])
    display = env.get("DISPLAY")
    image = await asyncio.to_thread(
        ImageGrab.grab,
        bbox=(x, y, x + width, y + height),
        xdisplay=display,
    )
    await asyncio.to_thread(image.save, path, "PNG")
    return "x11-xcb"


_X11_KEY_NAMES = {
    "CTRL": "Control_L",
    "CONTROL": "Control_L",
    "ALT": "Alt_L",
    "OPTION": "Alt_L",
    "SHIFT": "Shift_L",
    "META": "Super_L",
    "SUPER": "Super_L",
    "WIN": "Super_L",
    "CMD": "Super_L",
    "COMMAND": "Super_L",
    "ENTER": "Return",
    "RETURN": "Return",
    "TAB": "Tab",
    "ESC": "Escape",
    "ESCAPE": "Escape",
    "BACKSPACE": "BackSpace",
    "DELETE": "Delete",
    "SPACE": "space",
    "LEFT": "Left",
    "RIGHT": "Right",
    "UP": "Up",
    "DOWN": "Down",
    "HOME": "Home",
    "END": "End",
    "PAGEUP": "Page_Up",
    "PAGEDOWN": "Page_Down",
}


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


def _x11_key_chord(keys: Any, env: dict[str, str]) -> None:
    try:
        from Xlib import XK, X, display
        from Xlib.ext import xtest
    except ImportError as exc:  # pragma: no cover - Linux dependency guard
        raise GuiUnavailableError("X11 key chords require python-xlib") from exc

    parts = _key_parts(keys)
    connection = display.Display(env.get("DISPLAY"))
    pressed: list[int] = []
    try:
        keycodes: list[int] = []
        for part in parts:
            name = _X11_KEY_NAMES.get(part.upper(), part)
            if len(name) == 1 and name.isalpha():
                name = name.lower()
            keysym = XK.string_to_keysym(name)
            if not keysym:
                raise ValueError(f"Unsupported X11 key name: {part}")
            keycode = connection.keysym_to_keycode(keysym)
            if not keycode:
                raise ValueError(f"No X11 keycode for: {part}")
            keycodes.append(keycode)

        try:
            for keycode in keycodes:
                xtest.fake_input(connection, X.KeyPress, keycode)
                pressed.append(keycode)
        finally:
            for keycode in reversed(pressed):
                with contextlib.suppress(Exception):
                    xtest.fake_input(connection, X.KeyRelease, keycode)
            connection.sync()
    finally:
        connection.close()


class LinuxGuiBackend:
    name = "linux-atspi"

    def __init__(self) -> None:
        self._env: dict[str, str] | None = None
        self._portal: PortalDesktop | None = None
        self._env_lock = asyncio.Lock()

    async def _ensure_env(self) -> dict[str, str]:
        if self._env is not None:
            return self._env
        async with self._env_lock:
            if self._env is None:
                self._env = await asyncio.to_thread(_desktop_environment)
            return self._env

    def _helper(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._env is None:
            raise GuiUnavailableError("Linux desktop environment has not been initialized")
        return _run_helper(payload, self._env)

    def _list_data(self) -> dict[str, Any]:
        return self._helper({"command": "list"})

    async def list_windows(self) -> dict[str, Any]:
        env = await self._ensure_env()
        session_type = _session_type(env)
        if session_type == "unknown":
            raise GuiUnavailableError(
                "No graphical Linux session was found; DISPLAY/WAYLAND_DISPLAY are unavailable"
            )
        data = await asyncio.to_thread(self._list_data)
        return {
            "backend": self.name,
            "platform": "linux",
            "session_type": session_type,
            "windows": data.get("windows", []),
            "monitors": data.get("monitors", []),
            "capabilities": {
                "accessibility": "AT-SPI",
                "window_capture": True,
                "coordinate_input": True,
                "semantic_actions": True,
                "wayland_input": "xdg-desktop-portal" if session_type == "wayland" else None,
            },
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
        env = await self._ensure_env()
        data = await asyncio.to_thread(
            self._helper,
            {
                "command": "snapshot",
                "window_id": window_id,
                "include_elements": include_elements,
                "max_elements": max_elements,
                "max_depth": max_depth,
            },
        )
        record = data["window"]
        locators: dict[str, Any] = {}
        paths = data.get("locators", {})
        for element in data.get("elements", []):
            element_id = str(element["id"])
            raw_locator = paths.get(element_id, {})
            if isinstance(raw_locator, dict):
                semantic_locator = {
                    "path": list(raw_locator.get("path", [])),
                    "fingerprint": str(raw_locator.get("fingerprint") or ""),
                }
            else:
                semantic_locator = {"path": list(raw_locator), "fingerprint": ""}
            locators[element_id] = {
                "semantic": semantic_locator,
                "bounds": element.get("bounds", {}),
            }

        screenshot_display = None
        capture_backend = None
        session_type = _session_type(env)
        if screenshot_path is not None:
            list_data = await asyncio.to_thread(self._list_data)
            monitors = list_data.get("monitors", [])
            if session_type == "wayland":
                capture_backend = await _capture_wayland(
                    screenshot_path,
                    record["bounds"],
                    monitors,
                    env,
                )
            elif session_type == "x11":
                capture_backend = await _capture_x11(
                    screenshot_path,
                    record["bounds"],
                    env,
                )
            else:
                raise GuiUnavailableError(
                    "No graphical Linux session was found; DISPLAY/WAYLAND_DISPLAY are unavailable"
                )
            screenshot_display = display_screenshot_path(screenshot_path)

        return GuiSnapshot(
            window=record,
            elements=data.get("elements", []),
            locators=locators,
            screenshot_path=screenshot_display,
            capabilities={
                "accessibility": "AT-SPI",
                "window_capture": screenshot_path is not None,
                "capture_backend": capture_backend,
                "coordinate_space": "window-relative",
                "coordinate_input": True,
                "semantic_actions": True,
                "session_type": session_type,
            },
        )

    async def focus_window(self, window: dict[str, Any]) -> None:
        await self._ensure_env()
        await asyncio.to_thread(
            self._helper,
            {
                "command": "semantic_action",
                "window_id": window["id"],
                "locator": [],
                "action": {"type": "focus"},
            },
        )

    async def perform_action(
        self,
        window: dict[str, Any],
        locator: Any | None,
        action: dict[str, Any],
    ) -> dict[str, Any]:
        kind = action["type"]
        if kind == "wait":
            seconds = max(0.0, min(float(action.get("seconds", 1.0)), 30.0))
            await asyncio.sleep(seconds)
            return {"waited_s": seconds}

        if kind == "focus":
            if locator is None:
                await self.focus_window(window)
                return {"semantic": True, "method": "window"}
            return await asyncio.to_thread(
                self._helper,
                {
                    "command": "semantic_action",
                    "window_id": window["id"],
                    "locator": locator["semantic"],
                    "action": action,
                },
            )

        if kind == "set_value":
            if locator is None:
                raise ValueError("set_value requires element_id")
            return await asyncio.to_thread(
                self._helper,
                {
                    "command": "semantic_action",
                    "window_id": window["id"],
                    "locator": locator["semantic"],
                    "action": action,
                },
            )

        if kind == "click" and locator is not None:
            try:
                return await asyncio.to_thread(
                    self._helper,
                    {
                        "command": "semantic_action",
                        "window_id": window["id"],
                        "locator": locator["semantic"],
                        "action": action,
                    },
                )
            except _SemanticActionUnavailableError:
                pass

        if kind in {"type", "key"}:
            if locator is not None:
                await asyncio.to_thread(
                    self._helper,
                    {
                        "command": "semantic_action",
                        "window_id": window["id"],
                        "locator": locator["semantic"],
                        "action": {"type": "focus"},
                    },
                )
            else:
                await self.focus_window(window)

        if kind in {"click", "double_click", "right_click", "move", "scroll", "drag"}:
            await self.focus_window(window)

        env = await self._ensure_env()
        session_type = _session_type(env)
        if session_type == "wayland":
            return await self._perform_wayland(window, locator, action)
        if session_type == "x11":
            return await self._perform_x11(window, locator, action)
        raise GuiUnavailableError("No active X11 or Wayland desktop session is available")

    def _screen_point(
        self,
        window: dict[str, Any],
        action: dict[str, Any],
        locator: Any | None,
    ) -> tuple[int, int]:
        if locator is not None and action.get("x") is None and action.get("y") is None:
            bounds = locator["bounds"]
            width = int(bounds.get("width", 0))
            height = int(bounds.get("height", 0))
            if width <= 0 or height <= 0:
                raise ValueError("Target element has no usable screen bounds")
            x = int(bounds.get("x", 0)) + width // 2
            y = int(bounds.get("y", 0)) + height // 2
            window_bounds = window["bounds"]
            left = int(window_bounds["x"])
            top = int(window_bounds["y"])
            right = left + int(window_bounds["width"])
            bottom = top + int(window_bounds["height"])
            if not (left <= x < right and top <= y < bottom):
                raise ValueError("Target element center is outside the selected window")
            return x, y
        if action.get("x") is None or action.get("y") is None:
            raise ValueError("Coordinate action requires x and y, or an element_id")
        bounds = window["bounds"]
        return int(bounds["x"]) + int(action["x"]), int(bounds["y"]) + int(action["y"])

    async def _perform_x11(
        self,
        window: dict[str, Any],
        locator: Any | None,
        action: dict[str, Any],
    ) -> dict[str, Any]:
        kind = action["type"]
        if kind == "type":
            text = str(action.get("text", ""))
            result = await asyncio.to_thread(
                self._helper,
                {"command": "raw", "kind": "text", "text": text},
            )
            return {**result, "characters": len(text)}
        if kind == "key":
            env = await self._ensure_env()
            await asyncio.to_thread(_x11_key_chord, action.get("keys"), env)
            return {"keys": action.get("keys")}

        if kind in {"click", "double_click", "right_click", "move", "scroll"}:
            x, y = self._screen_point(window, action, locator)
            if kind == "move":
                event = "abs"
                await asyncio.to_thread(
                    self._helper,
                    {"command": "raw", "kind": "mouse", "x": x, "y": y, "event": event},
                )
            elif kind == "scroll":
                default_y = action.get("amount", -3) if "delta_x" not in action else 0
                amount_y = quantize_scroll_amount(action.get("delta_y", default_y))
                amount_x = quantize_scroll_amount(action.get("delta_x", 0))
                for amount, negative_button, positive_button in (
                    (amount_y, 5, 4),
                    (amount_x, 7, 6),
                ):
                    if not amount:
                        continue
                    button = negative_button if amount < 0 else positive_button
                    for _ in range(abs(amount)):
                        await asyncio.to_thread(
                            self._helper,
                            {
                                "command": "raw",
                                "kind": "mouse",
                                "x": x,
                                "y": y,
                                "event": f"b{button}c",
                            },
                        )
            else:
                button = 3 if kind == "right_click" else 1
                count = 2 if kind == "double_click" else 1
                for _ in range(count):
                    await asyncio.to_thread(
                        self._helper,
                        {
                            "command": "raw",
                            "kind": "mouse",
                            "x": x,
                            "y": y,
                            "event": f"b{button}c",
                        },
                    )
            return {"screen_x": x, "screen_y": y}

        if kind == "drag":
            x, y = self._screen_point(
                window, {"x": action.get("x"), "y": action.get("y")}, locator
            )
            to_x, to_y = self._screen_point(
                window, {"x": action.get("to_x"), "y": action.get("to_y")}, None
            )
            pressed = False
            pending_error: BaseException | None = None
            try:
                await asyncio.to_thread(
                    self._helper,
                    {"command": "raw", "kind": "mouse", "x": x, "y": y, "event": "b1p"},
                )
                pressed = True
                await asyncio.to_thread(
                    self._helper,
                    {
                        "command": "raw",
                        "kind": "mouse",
                        "x": to_x,
                        "y": to_y,
                        "event": "abs",
                    },
                )
            except BaseException as exc:
                pending_error = exc
            finally:
                if pressed:
                    try:
                        await asyncio.to_thread(
                            self._helper,
                            {
                                "command": "raw",
                                "kind": "mouse",
                                "x": to_x,
                                "y": to_y,
                                "event": "b1r",
                            },
                        )
                    except Exception:
                        if pending_error is None:
                            raise
            if pending_error is not None:
                raise pending_error
            return {"from": {"x": x, "y": y}, "to": {"x": to_x, "y": to_y}}

        raise ValueError(f"Unsupported GUI action type on X11: {kind}")

    async def _perform_wayland(
        self,
        window: dict[str, Any],
        locator: Any | None,
        action: dict[str, Any],
    ) -> dict[str, Any]:
        if self._portal is None:
            self._portal = PortalDesktop(await self._ensure_env())
        portal = self._portal
        kind = action["type"]
        if kind == "type":
            text = str(action.get("text", ""))
            await portal.type_text(text)
            return {"characters": len(text), "method": "xdg-desktop-portal"}
        if kind == "key":
            await portal.key_chord(action.get("keys"))
            return {"keys": action.get("keys"), "method": "xdg-desktop-portal"}

        if kind in {"click", "double_click", "right_click", "move", "scroll"}:
            x, y = self._screen_point(window, action, locator)
            if kind == "move":
                await portal.move(x, y)
            elif kind == "scroll":
                default_y = action.get("amount", -3) if "delta_x" not in action else 0
                amount_y = quantize_scroll_amount(action.get("delta_y", default_y))
                amount_x = quantize_scroll_amount(action.get("delta_x", 0))
                if amount_x or amount_y:
                    await portal.scroll(x, y, float(amount_x), float(amount_y))
            else:
                await portal.click(
                    x,
                    y,
                    button=3 if kind == "right_click" else 1,
                    count=2 if kind == "double_click" else 1,
                )
            return {
                "screen_x": x,
                "screen_y": y,
                "method": "xdg-desktop-portal",
            }

        if kind == "drag":
            x, y = self._screen_point(
                window, {"x": action.get("x"), "y": action.get("y")}, locator
            )
            to_x, to_y = self._screen_point(
                window, {"x": action.get("to_x"), "y": action.get("to_y")}, None
            )
            await portal.drag(x, y, to_x, to_y)
            return {
                "from": {"x": x, "y": y},
                "to": {"x": to_x, "y": to_y},
                "method": "xdg-desktop-portal",
            }

        raise ValueError(f"Unsupported GUI action type on Wayland: {kind}")
