from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image

from .base import (
    GUI_MAX_CAPTURE_DIMENSION,
    GUI_MAX_CAPTURE_PIXELS,
    GUI_MAX_WINDOW_TEXT_BYTES,
    GUI_MAX_WINDOWS,
    GuiSnapshot,
    GuiStaleStateError,
    GuiUnavailableError,
    _assert_action_fresh,
    _bounds_tuple,
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
    if shutil.which("systemctl"):
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
            for key in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE"):
                env.pop(key, None)
            for line in result.stdout.splitlines():
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key in _DESKTOP_ENV_KEYS and value:
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


def _pressed_inputs_from_progress(raw: bytes) -> list[dict[str, Any]]:
    active: dict[tuple[str, int], dict[str, Any]] = {}
    for line in raw.splitlines()[:512]:
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(event, dict):
            continue
        kind = str(event.get("kind") or "")
        state = str(event.get("state") or "")
        try:
            if kind == "mouse":
                identity = ("mouse", int(event["button"]))
                record = {
                    "kind": "mouse",
                    "button": int(event["button"]),
                    "x": int(event["x"]),
                    "y": int(event["y"]),
                }
            elif kind == "key":
                identity = ("key", int(event["symbol"]))
                record = {"kind": "key", "symbol": int(event["symbol"])}
            else:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        if state in {"press", "move"}:
            active[identity] = record
        elif state == "release":
            active.pop(identity, None)
    return list(active.values())


def _run_helper(payload: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    argv = [_helper_python(env), str(_helper_path())]
    run_payload = dict(payload)
    progress_read = -1
    progress_write = -1
    run_kwargs: dict[str, Any] = {}
    if payload.get("command") == "raw":
        progress_read, progress_write = os.pipe()
        run_payload["_progress_fd"] = progress_write
        run_kwargs["pass_fds"] = (progress_write,)

    try:
        result = subprocess.run(
            argv,
            input=json.dumps(run_payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=env,
            **run_kwargs,
        )
    except subprocess.TimeoutExpired as exc:
        if progress_write >= 0:
            os.close(progress_write)
            progress_write = -1
        pressed: list[dict[str, Any]] = []
        if progress_read >= 0:
            with contextlib.suppress(OSError):
                pressed = _pressed_inputs_from_progress(os.read(progress_read, 64 * 1024))
        if pressed:
            cleanup = {
                "command": "release_inputs",
                "pressed": pressed,
            }
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run(
                    argv,
                    input=json.dumps(cleanup, ensure_ascii=False),
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                    env=env,
                )
        raise GuiUnavailableError("AT-SPI helper timed out") from exc
    finally:
        if progress_write >= 0:
            with contextlib.suppress(OSError):
                os.close(progress_write)
        if progress_read >= 0:
            with contextlib.suppress(OSError):
                os.close(progress_read)

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
            or "no preferred AT-SPI activation action" in message
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
        right = left + width
        bottom = top + height
        if 0 <= left < right <= image_size[0] and 0 <= top < bottom <= image_size[1]:
            return left, top, right, bottom
        raise GuiUnavailableError(
            "Captured desktop geometry does not match the monitor layout; "
            "cannot crop the target window safely"
        )

    if _monitor_for_window(bounds, monitors) is None:
        raise GuiUnavailableError("Could not map the target window to a captured monitor")

    # GDK exposes integer scale factors even when the compositor captures a
    # uniformly fractionally-scaled desktop (for example 1.5x). When all
    # outputs report the same scale and the captured desktop has a consistent
    # x/y ratio, prefer the observed capture ratio over the rounded metadata.
    reported_scales = {float(item.get("scale", 1) or 1) for item in monitors}
    ratio_x = image_size[0] / logical_size[0] if logical_size[0] > 0 else 0.0
    ratio_y = image_size[1] / logical_size[1] if logical_size[1] > 0 else 0.0
    if (
        len(reported_scales) == 1
        and ratio_x > 0
        and ratio_y > 0
        and abs(ratio_x - ratio_y) <= 0.02
    ):
        ratio = (ratio_x + ratio_y) / 2.0
        left = int(round((x - origin_x) * ratio))
        top = int(round((y - origin_y) * ratio))
        right = int(round((x + width - origin_x) * ratio))
        bottom = int(round((y + height - origin_y) * ratio))
        if 0 <= left < right <= image_size[0] and 0 <= top < bottom <= image_size[1]:
            return left, top, right, bottom

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
    _validate_capture_image_header(path)
    with Image.open(path) as image:
        image.load()
        if image.size == (int(bounds["width"]), int(bounds["height"])) and monitors:
            origin_x = min(int(item["x"]) for item in monitors)
            origin_y = min(int(item["y"]) for item in monitors)
            right = max(int(item["x"]) + int(item["width"]) for item in monitors)
            bottom = max(int(item["y"]) + int(item["height"]) for item in monitors)
            if (
                int(bounds["x"]) == origin_x
                and int(bounds["y"]) == origin_y
                and int(bounds["width"]) == right - origin_x
                and int(bounds["height"]) == bottom - origin_y
            ):
                return
        cropped = image.crop(_desktop_crop_box(bounds, monitors, image.size))
        cropped.save(path, format="PNG")


def _validate_capture_image_header(path: Path) -> None:
    try:
        with Image.open(path) as image:
            width, height = image.size
    except Exception as exc:
        raise GuiUnavailableError("Captured Wayland image is invalid") from exc
    if (
        width <= 0
        or height <= 0
        or width > GUI_MAX_CAPTURE_DIMENSION
        or height > GUI_MAX_CAPTURE_DIMENSION
        or width * height > GUI_MAX_CAPTURE_PIXELS
    ):
        raise GuiUnavailableError(
            "Captured Wayland image exceeds GUI screenshot safety limits"
        )


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
            await asyncio.to_thread(_validate_capture_image_header, path)
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
            umask=0o077,
        )
        if result.returncode == 0 and path.is_file():
            await asyncio.to_thread(_crop_desktop_capture, path, bounds, monitors)
            return name

    await portal_screenshot(path, env)
    if not path.is_file():
        raise GuiUnavailableError("Wayland screenshot portal did not return an image")
    await asyncio.to_thread(_crop_desktop_capture, path, bounds, monitors)
    return "xdg-desktop-portal"


def _x11_text_property(window: Any, connection: Any, name: str) -> str:
    try:
        atom = connection.intern_atom(name, only_if_exists=True)
        if not atom:
            return ""
        max_longs = max(1, (GUI_MAX_WINDOW_TEXT_BYTES + 3) // 4)
        prop = window.get_property(atom, 0, 0, max_longs, False)
        if prop is None:
            return ""
        value = prop.value
        if isinstance(value, bytes):
            raw = value[:GUI_MAX_WINDOW_TEXT_BYTES]
        else:
            try:
                raw = bytes(value)[:GUI_MAX_WINDOW_TEXT_BYTES]
            except (TypeError, ValueError):
                return str(value or "")[:GUI_MAX_WINDOW_TEXT_BYTES]
        return raw.decode("utf-8", errors="replace").rstrip("\0")
    except Exception:
        return ""


def _x11_window_geometry(window: Any, root: Any) -> dict[str, int]:
    geometry = window.get_geometry()
    translated = window.translate_coords(root, 0, 0)
    return {
        "x": int(translated.x),
        "y": int(translated.y),
        "width": int(geometry.width),
        "height": int(geometry.height),
    }


def _x11_match_window(connection: Any, record: dict[str, Any]) -> Any:
    from Xlib import Xatom

    root = connection.screen().root
    pid_atom = connection.intern_atom("_NET_WM_PID", only_if_exists=True)
    ids: list[int] = []
    for prop_name in ("_NET_CLIENT_LIST_STACKING", "_NET_CLIENT_LIST"):
        atom = connection.intern_atom(prop_name, only_if_exists=True)
        if not atom:
            continue
        prop = root.get_property(
            atom,
            Xatom.WINDOW,
            0,
            GUI_MAX_WINDOWS,
            False,
        )
        if prop is not None:
            ids = [int(value) for value in prop.value[:GUI_MAX_WINDOWS]]
            if ids:
                break
    if not ids:
        raise GuiUnavailableError("X11 window manager did not expose a client window list")

    expected_pid = int(record.get("pid") or 0)
    expected_title = str(record.get("title") or "")
    expected_bounds = record.get("bounds") if isinstance(record.get("bounds"), dict) else {}
    candidates: list[tuple[tuple[int, int], Any]] = []
    for xid in ids:
        try:
            window = connection.create_resource_object("window", xid)
            if pid_atom:
                pid_prop = window.get_property(
                    pid_atom,
                    Xatom.CARDINAL,
                    0,
                    1,
                    False,
                )
                pid = int(pid_prop.value[0]) if pid_prop is not None and len(pid_prop.value) else 0
            else:
                pid = 0
            if expected_pid and pid != expected_pid:
                continue
            geometry = _x11_window_geometry(window, root)
            title = _x11_text_property(
                window,
                connection,
                "_NET_WM_NAME",
            ) or _x11_text_property(window, connection, "WM_NAME")
            geometry_deltas = [
                abs(int(geometry.get(key, 0)) - int(expected_bounds.get(key, 0)))
                for key in ("x", "y", "width", "height")
            ]
            geometry_delta = sum(geometry_deltas)
            geometry_match = bool(expected_bounds) and all(
                delta <= 3 for delta in geometry_deltas
            )
            title_match = bool(expected_title) and title == expected_title
            if not geometry_match:
                continue
            candidates.append(
                (
                    (
                        0 if title_match else 1,
                        geometry_delta,
                    ),
                    window,
                )
            )
        except Exception:
            continue

    if not candidates:
        raise GuiUnavailableError("Could not map the AT-SPI target to an X11 client window")
    candidates.sort(key=lambda item: item[0])
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        raise GuiUnavailableError("X11 target window identity is ambiguous")
    return candidates[0][1]


def _x11_visual_masks(connection: Any, visual_id: int) -> tuple[int, int, int]:
    for screen in connection.display.info.roots:
        for depth in screen.allowed_depths:
            for visual in depth.visuals:
                if int(visual.visual_id) == int(visual_id):
                    return (
                        int(visual.red_mask),
                        int(visual.green_mask),
                        int(visual.blue_mask),
                    )
    raise GuiUnavailableError("X11 target visual metadata is unavailable")


def _x11_pixmap_to_image(
    connection: Any,
    image_reply: Any,
    *,
    width: int,
    height: int,
    visual_id: int,
) -> Image.Image:
    from Xlib import X

    format_info = next(
        (
            item
            for item in connection.display.info.pixmap_formats
            if int(item.depth) == int(image_reply.depth)
        ),
        None,
    )
    if format_info is None:
        raise GuiUnavailableError("X11 pixmap format is unavailable")
    bits_per_pixel = int(format_info.bits_per_pixel)
    if bits_per_pixel not in {24, 32}:
        raise GuiUnavailableError(
            f"Unsupported X11 pixmap depth layout: {bits_per_pixel} bits per pixel"
        )
    bytes_per_pixel = bits_per_pixel // 8
    masks = _x11_visual_masks(connection, visual_id)
    positions: list[int] = []
    for mask in masks:
        if mask <= 0:
            raise GuiUnavailableError("X11 target visual has invalid RGB masks")
        shift = (mask & -mask).bit_length() - 1
        if mask != 0xFF << shift or shift % 8:
            raise GuiUnavailableError("Unsupported X11 target visual RGB mask layout")
        byte_index = shift // 8
        if int(connection.display.info.image_byte_order) == int(X.MSBFirst):
            byte_index = bytes_per_pixel - 1 - byte_index
        if byte_index < 0 or byte_index >= bytes_per_pixel:
            raise GuiUnavailableError("X11 target visual RGB masks exceed pixel width")
        positions.append(byte_index)

    if len(set(positions)) != 3:
        raise GuiUnavailableError("X11 target visual RGB masks overlap")
    raw_layout = ["X"] * bytes_per_pixel
    for index, channel in zip(positions, "RGB", strict=True):
        raw_layout[index] = channel
    raw_mode = "".join(raw_layout)
    if raw_mode not in {"RGB", "BGR", "RGBX", "BGRX", "XRGB", "XBGR"}:
        raise GuiUnavailableError(f"Unsupported X11 pixel byte layout: {raw_mode}")
    pad = int(format_info.scanline_pad)
    stride = ((width * bits_per_pixel + pad - 1) // pad) * (pad // 8)
    return Image.frombytes(
        "RGB",
        (width, height),
        bytes(image_reply.data),
        "raw",
        raw_mode,
        stride,
        1,
    )


def _capture_x11_window_sync(
    path: Path,
    record: dict[str, Any],
    env: dict[str, str],
) -> None:
    try:
        from Xlib import X, display
    except ImportError as exc:  # pragma: no cover - Linux dependency guard
        raise GuiUnavailableError("X11 window capture requires python-xlib") from exc

    connection = display.Display(env.get("DISPLAY"))
    pixmap = None
    try:
        if not connection.has_extension("Composite"):
            raise GuiUnavailableError(
                "X11 Composite extension is required for safe per-window capture"
            )
        screen_number = int(connection.get_default_screen())
        compositor_atom = connection.intern_atom(
            f"_NET_WM_CM_S{screen_number}",
            only_if_exists=True,
        )
        compositor = (
            connection.get_selection_owner(compositor_atom)
            if compositor_atom
            else None
        )
        if compositor is None or not int(getattr(compositor, "id", 0) or 0):
            raise GuiUnavailableError(
                "An X11 compositing manager is required for safe per-window capture"
            )

        window = _x11_match_window(connection, record)
        geometry = window.get_geometry()
        width = int(geometry.width)
        height = int(geometry.height)
        if width <= 0 or height <= 0:
            raise GuiUnavailableError("X11 target window has invalid capture bounds")
        if (
            width > GUI_MAX_CAPTURE_DIMENSION
            or height > GUI_MAX_CAPTURE_DIMENSION
            or width * height > GUI_MAX_CAPTURE_PIXELS
        ):
            raise GuiUnavailableError(
                f"X11 capture dimensions exceed the safe budget: {width}x{height}"
            )
        visual_id = int(window.get_attributes().visual)
        pixmap = window.composite_name_window_pixmap()
        image_reply = pixmap.get_image(
            0,
            0,
            width,
            height,
            X.ZPixmap,
            0xFFFFFFFF,
        )
        image = _x11_pixmap_to_image(
            connection,
            image_reply,
            width=width,
            height=height,
            visual_id=visual_id,
        )
        current_window = _x11_match_window(connection, record)
        if int(getattr(current_window, "id", 0) or 0) != int(
            getattr(window, "id", 0) or 0
        ):
            raise GuiUnavailableError(
                "X11 target window identity changed during capture"
            )
        current_bounds = _x11_window_geometry(
            current_window,
            connection.screen().root,
        )
        expected_bounds = record.get("bounds")
        if (
            not isinstance(expected_bounds, dict)
            or any(
                abs(
                    int(current_bounds.get(key, 0))
                    - int(expected_bounds.get(key, 0))
                )
                > 3
                for key in ("x", "y", "width", "height")
            )
        ):
            raise GuiUnavailableError(
                "X11 target window moved or resized during capture"
            )
        image.save(path, "PNG")
    except GuiUnavailableError:
        raise
    except Exception as exc:
        raise GuiUnavailableError(
            f"XComposite window capture failed: {type(exc).__name__}: {exc}"
        ) from exc
    finally:
        if pixmap is not None:
            with contextlib.suppress(Exception):
                pixmap.free()
        connection.close()


async def _capture_x11(
    path: Path,
    record: dict[str, Any],
    env: dict[str, str],
) -> str:
    await asyncio.to_thread(_capture_x11_window_sync, path, record, env)
    return "x11-composite"



class LinuxGuiBackend:
    name = "linux-atspi"
    _ENV_REFRESH_S = 30.0

    def __init__(self) -> None:
        self._env: dict[str, str] | None = None
        self._env_refreshed_at = 0.0
        self._portal: PortalDesktop | None = None
        self._env_lock = asyncio.Lock()

    async def _ensure_env(self) -> dict[str, str]:
        now = time.monotonic()
        if self._env is not None and self._env_refreshed_at == 0.0:
            self._env_refreshed_at = now
            return self._env
        if self._env is not None and now - self._env_refreshed_at < self._ENV_REFRESH_S:
            return self._env
        async with self._env_lock:
            now = time.monotonic()
            if self._env is None or now - self._env_refreshed_at >= self._ENV_REFRESH_S:
                refreshed = await asyncio.to_thread(_desktop_environment)
                if self._env is not None and refreshed != self._env:
                    portal = self._portal
                    self._portal = None
                    if portal is not None:
                        await portal.close()
                self._env = refreshed
                self._env_refreshed_at = now
            return self._env

    def _helper(
        self,
        payload: dict[str, Any],
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        selected_env = env if env is not None else self._env
        if selected_env is None:
            raise GuiUnavailableError("Linux desktop environment has not been initialized")
        return _run_helper(payload, selected_env)

    def _list_data(self, env: dict[str, str] | None = None) -> dict[str, Any]:
        return self._helper({"command": "list"}, env)

    async def list_windows(self) -> dict[str, Any]:
        env = await self._ensure_env()
        session_type = _session_type(env)
        if session_type == "unknown":
            raise GuiUnavailableError(
                "No graphical Linux session was found; DISPLAY/WAYLAND_DISPLAY are unavailable"
            )
        data = await asyncio.to_thread(self._list_data, env)
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
                "capture_requires_focus": session_type == "wayland",
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
            env,
        )
        record = data["window"]
        locators: dict[str, Any] = {}
        paths = data.get("locators", {})
        for element in data.get("elements", []):
            element_id = str(element["id"])
            if element_id not in paths:
                continue
            raw_locator = paths[element_id]
            if isinstance(raw_locator, dict):
                semantic_locator = {
                    "path": list(raw_locator.get("path", [])),
                    "accessible_id": str(raw_locator.get("accessible_id") or ""),
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
            list_data = await asyncio.to_thread(self._list_data, env)
            monitors = list_data.get("monitors", [])
            if session_type == "wayland":
                await self._focus_window(record, env)
                refreshed = await asyncio.to_thread(
                    self._helper,
                    {
                        "command": "snapshot",
                        "window_id": window_id,
                        "include_elements": False,
                        "max_elements": 1,
                        "max_depth": 1,
                    },
                    env,
                )
                refreshed_record = refreshed.get("window")
                if (
                    not isinstance(refreshed_record, dict)
                    or _bounds_tuple(refreshed_record.get("bounds"))
                    != _bounds_tuple(record.get("bounds"))
                ):
                    raise GuiStaleStateError(
                        "Target window moved or resized while preparing the Wayland capture; "
                        "call gui_state again"
                    )
                capture_backend = await _capture_wayland(
                    screenshot_path,
                    record["bounds"],
                    monitors,
                    env,
                )
                post_capture = await asyncio.to_thread(
                    self._helper,
                    {
                        "command": "snapshot",
                        "window_id": window_id,
                        "include_elements": False,
                        "max_elements": 1,
                        "max_depth": 1,
                    },
                    env,
                )
                post_capture_record = post_capture.get("window")
                if (
                    not isinstance(post_capture_record, dict)
                    or _bounds_tuple(post_capture_record.get("bounds"))
                    != _bounds_tuple(record.get("bounds"))
                ):
                    raise GuiStaleStateError(
                        "Target window moved or resized during the Wayland capture; "
                        "call gui_state again"
                    )
            elif session_type == "x11":
                capture_backend = await _capture_x11(
                    screenshot_path,
                    record,
                    env,
                )
                post_capture = await asyncio.to_thread(
                    self._helper,
                    {
                        "command": "snapshot",
                        "window_id": window_id,
                        "include_elements": False,
                        "max_elements": 1,
                        "max_depth": 1,
                    },
                    env,
                )
                post_capture_record = post_capture.get("window")
                if (
                    not isinstance(post_capture_record, dict)
                    or str(post_capture_record.get("id") or "") != str(record.get("id") or "")
                    or _bounds_tuple(post_capture_record.get("bounds"))
                    != _bounds_tuple(record.get("bounds"))
                ):
                    raise GuiStaleStateError(
                        "Target window identity or geometry changed during the X11 capture; "
                        "call gui_state again"
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

    async def _focus_window(
        self,
        window: dict[str, Any],
        env: dict[str, str],
        *,
        deadline: Any | None = None,
    ) -> None:
        focus_action: dict[str, Any] = {"type": "focus"}
        if deadline is not None:
            focus_action["_observation_deadline"] = deadline
        await asyncio.to_thread(
            self._helper,
            {
                "command": "semantic_action",
                "window_id": window["id"],
                "locator": [],
                "action": focus_action,
            },
            env,
        )

    async def focus_window(self, window: dict[str, Any]) -> None:
        env = await self._ensure_env()
        await self._focus_window(window, env)

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

        env = await self._ensure_env()
        deadline = action.get("_observation_deadline")

        if kind == "focus":
            if locator is None:
                await self._focus_window(window, env, deadline=deadline)
                return {"semantic": True, "method": "window"}
            return await asyncio.to_thread(
                self._helper,
                {
                    "command": "semantic_action",
                    "window_id": window["id"],
                    "locator": locator["semantic"],
                    "action": action,
                },
                env,
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
                env,
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
                    env,
                )
            except _SemanticActionUnavailableError:
                pass

        if (
            locator is not None
            and kind in {"click", "double_click", "right_click", "move", "scroll", "drag"}
        ):
            resolved = await asyncio.to_thread(
                self._helper,
                {
                    "command": "resolve_locator",
                    "window_id": window["id"],
                    "locator": locator["semantic"],
                },
                env,
            )
            bounds = resolved.get("bounds")
            if not isinstance(bounds, dict):
                raise GuiStaleStateError(
                    "AT-SPI target element no longer has usable bounds"
                )
            locator = {**locator, "bounds": bounds}

        if kind in {"type", "key"}:
            if locator is not None:
                await asyncio.to_thread(
                    self._helper,
                    {
                        "command": "semantic_action",
                        "window_id": window["id"],
                        "locator": locator["semantic"],
                        "action": {
                            "type": "focus",
                            "_observation_deadline": deadline,
                        },
                    },
                    env,
                )
            else:
                await self._focus_window(window, env, deadline=deadline)

        if (
            kind in {"click", "double_click", "right_click", "move", "scroll", "drag"}
            and not action.get("_focus_prepared")
        ):
            await self._focus_window(window, env, deadline=deadline)

        _assert_action_fresh(action)
        session_type = _session_type(env)
        if session_type == "wayland":
            return await self._perform_wayland(window, locator, action, env)
        if session_type == "x11":
            return await self._perform_x11(window, locator, action, env)
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
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if env is None:
            env = await self._ensure_env()
        kind = action["type"]
        deadline = action.get("_observation_deadline")

        if kind == "type":
            text = str(action.get("text", ""))
            _assert_action_fresh(action)
            result = await asyncio.to_thread(
                self._helper,
                {
                    "command": "raw",
                    "kind": "text",
                    "window_id": window["id"],
                    "locator": locator["semantic"] if locator is not None else None,
                    "text": text,
                    "_observation_deadline": deadline,
                },
                env,
            )
            return {**result, "characters": len(text)}

        if kind == "key":
            _assert_action_fresh(action)
            return await asyncio.to_thread(
                self._helper,
                {
                    "command": "raw",
                    "kind": "key_chord",
                    "window_id": window["id"],
                    "locator": locator["semantic"] if locator is not None else None,
                    "keys": action.get("keys"),
                    "_observation_deadline": deadline,
                },
                env,
            )

        if kind in {"click", "double_click", "right_click", "move", "scroll"}:
            x, y = self._screen_point(window, action, locator)
            if kind == "move":
                events = [{"x": x, "y": y, "event": "abs"}]
            elif kind == "scroll":
                default_y = action.get("amount", -3) if "delta_x" not in action else 0
                amount_y = quantize_scroll_amount(action.get("delta_y", default_y))
                amount_x = quantize_scroll_amount(action.get("delta_x", 0))
                events: list[dict[str, Any]] = []
                for amount, negative_button, positive_button in (
                    (amount_y, 5, 4),
                    (amount_x, 7, 6),
                ):
                    if not amount:
                        continue
                    button = negative_button if amount < 0 else positive_button
                    events.extend(
                        {"x": x, "y": y, "event": f"b{button}c"}
                        for _ in range(abs(amount))
                    )
            else:
                button = 3 if kind == "right_click" else 1
                count = 2 if kind == "double_click" else 1
                events = [
                    {"x": x, "y": y, "event": f"b{button}c"}
                    for _ in range(count)
                ]
            if events:
                _assert_action_fresh(action)
                await asyncio.to_thread(
                    self._helper,
                    {
                        "command": "raw",
                        "kind": "bound_pointer",
                        "window_id": window["id"],
                        "window_bounds": window["bounds"],
                        "locator": locator["semantic"] if locator is not None else None,
                        "events": events,
                        "_observation_deadline": deadline,
                    },
                    env,
                )
            return {"screen_x": x, "screen_y": y}

        if kind == "drag":
            x, y = self._screen_point(
                window, {"x": action.get("x"), "y": action.get("y")}, locator
            )
            to_x, to_y = self._screen_point(
                window, {"x": action.get("to_x"), "y": action.get("to_y")}, None
            )
            _assert_action_fresh(action)
            await asyncio.to_thread(
                self._helper,
                {
                    "command": "raw",
                    "kind": "bound_pointer",
                    "window_id": window["id"],
                    "window_bounds": window["bounds"],
                    "locator": locator["semantic"] if locator is not None else None,
                    "events": [
                        {"x": x, "y": y, "event": "b1p"},
                        {"x": to_x, "y": to_y, "event": "abs"},
                        {"x": to_x, "y": to_y, "event": "b1r"},
                    ],
                    "_observation_deadline": deadline,
                },
                env,
            )
            return {"from": {"x": x, "y": y}, "to": {"x": to_x, "y": to_y}}

        raise ValueError(f"Unsupported GUI action type on X11: {kind}")

    async def _perform_wayland(
        self,
        window: dict[str, Any],
        locator: Any | None,
        action: dict[str, Any],
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if env is None:
            env = await self._ensure_env()
        if env != self._env:
            raise GuiStaleStateError(
                "Linux desktop session changed while preparing input; "
                "refresh the observation and try again"
            )
        if self._portal is None:
            self._portal = PortalDesktop(env)
        portal = self._portal
        kind = action["type"]
        deadline = action.get("_observation_deadline")
        session = await portal.ensure_session()

        def assert_observation_fresh() -> None:
            if env != self._env:
                raise GuiStaleStateError(
                    "Linux desktop session changed while preparing input; "
                    "refresh the observation and try again"
                )
            _assert_action_fresh(
                action,
                stale_hint="refresh the observation and try again",
            )

        assert_observation_fresh()

        if action.get("_focus_prepared"):
            await self._focus_window(window, env, deadline=deadline)
            refreshed = await asyncio.to_thread(
                self._helper,
                {
                    "command": "snapshot",
                    "window_id": window["id"],
                    "include_elements": False,
                    "max_elements": 1,
                    "max_depth": 1,
                },
                env,
            )
            refreshed_window = refreshed.get("window")
            if (
                not isinstance(refreshed_window, dict)
                or _bounds_tuple(refreshed_window.get("bounds"))
                != _bounds_tuple(window.get("bounds"))
            ):
                raise GuiStaleStateError(
                    "Target window moved or resized while preparing Wayland input; "
                    "refresh the displayed frame and try again"
                )
            assert_observation_fresh()

        if (
            locator is not None
            and kind in {"click", "double_click", "right_click", "move", "scroll", "drag"}
        ):
            resolved = await asyncio.to_thread(
                self._helper,
                {
                    "command": "resolve_locator",
                    "window_id": window["id"],
                    "locator": locator["semantic"],
                },
                env,
            )
            bounds = resolved.get("bounds") if isinstance(resolved, dict) else None
            if _bounds_tuple(bounds) is None:
                raise GuiStaleStateError(
                    "Target element is no longer available after preparing Wayland input; "
                    "refresh the observation and try again"
                )
            locator = {**locator, "bounds": dict(bounds)}
            assert_observation_fresh()

        if kind in {"type", "key"} and locator is not None:
            await asyncio.to_thread(
                self._helper,
                {
                    "command": "semantic_action",
                    "window_id": window["id"],
                    "locator": locator["semantic"],
                    "action": {
                        "type": "focus",
                        "_observation_deadline": deadline,
                    },
                },
                env,
            )
            assert_observation_fresh()
        elif not action.get("_focus_prepared"):
            await self._focus_window(window, env, deadline=deadline)
            assert_observation_fresh()

        if kind == "type":
            text = str(action.get("text", ""))
            assert_observation_fresh()
            await portal.type_text(text, session=session)
            return {"characters": len(text), "method": "xdg-desktop-portal"}

        if kind == "key":
            assert_observation_fresh()
            await portal.key_chord(action.get("keys"), session=session)
            return {"keys": action.get("keys"), "method": "xdg-desktop-portal"}

        if kind in {"click", "double_click", "right_click", "move", "scroll"}:
            x, y = self._screen_point(window, action, locator)
            assert_observation_fresh()
            if kind == "move":
                await portal.move(x, y, session=session)
            elif kind == "scroll":
                default_y = action.get("amount", -3) if "delta_x" not in action else 0
                amount_y = quantize_scroll_amount(action.get("delta_y", default_y))
                amount_x = quantize_scroll_amount(action.get("delta_x", 0))
                if amount_x or amount_y:
                    await portal.scroll(
                        x,
                        y,
                        float(amount_x),
                        float(amount_y),
                        session=session,
                    )
            else:
                await portal.click(
                    x,
                    y,
                    button=3 if kind == "right_click" else 1,
                    count=2 if kind == "double_click" else 1,
                    session=session,
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
            assert_observation_fresh()
            await portal.drag(x, y, to_x, to_y, session=session)
            return {
                "from": {"x": x, "y": y},
                "to": {"x": to_x, "y": to_y},
                "method": "xdg-desktop-portal",
            }

        raise ValueError(f"Unsupported GUI action type on Wayland: {kind}")
