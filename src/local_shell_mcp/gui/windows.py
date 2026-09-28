from __future__ import annotations

import asyncio
import ctypes
import hashlib
import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any

from PIL import Image

from .base import (
    GUI_MAX_CAPTURE_DIMENSION,
    GUI_MAX_CAPTURE_PIXELS,
    GUI_MAX_ELEMENT_TEXT_BYTES,
    GUI_MAX_ELEMENTS_TOTAL_BYTES,
    GUI_MAX_WINDOW_TEXT_BYTES,
    GUI_MAX_WINDOWS,
    GUI_MAX_WINDOWS_TOTAL_BYTES,
    GuiSnapshot,
    GuiUnavailableError,
    _truncate_gui_text,
    display_screenshot_path,
    quantize_scroll_amount,
)


def _automation():  # noqa: ANN202
    try:
        import uiautomation as auto
    except ImportError as exc:  # pragma: no cover - Windows dependency guard
        raise GuiUnavailableError(
            "Windows GUI automation requires the uiautomation package"
        ) from exc
    return auto


_UIA_THREAD_STATE = threading.local()


def _initialize_uia_thread() -> None:
    auto = _automation()
    initializer_factory = getattr(auto, "UIAutomationInitializerInThread", None)
    if not callable(initializer_factory):
        return
    initializer = initializer_factory()
    initializer.__enter__()
    _UIA_THREAD_STATE.initializer = initializer


def _rect_dict(rect: Any) -> dict[str, int]:
    if rect is None:
        return {"x": 0, "y": 0, "width": 0, "height": 0}
    try:
        left = int(rect.left)
        top = int(rect.top)
        right = int(rect.right)
        bottom = int(rect.bottom)
    except (AttributeError, TypeError, ValueError):
        return {"x": 0, "y": 0, "width": 0, "height": 0}
    return {
        "x": left,
        "y": top,
        "width": max(0, right - left),
        "height": max(0, bottom - top),
    }


def _horizontal_wheel(amount: int) -> None:
    if not amount:
        return
    user32 = ctypes.windll.user32
    mouseeventf_hwheel = 0x1000
    wheel_delta = 120
    user32.mouse_event(
        mouseeventf_hwheel,
        0,
        0,
        ctypes.c_int(int(amount) * wheel_delta),
        0,
    )


class _WinRect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class _BitmapInfo(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", _BitmapInfoHeader),
        ("bmiColors", ctypes.c_uint32 * 1),
    ]


_WINDOW_CAPTURE_TIMEOUT_S = 15.0


def _capture_window_image_native(hwnd: int, destination: Path) -> None:
    windll = getattr(ctypes, "windll", None)
    if windll is None:  # pragma: no cover - Windows-only runtime guard.
        raise GuiUnavailableError("Win32 window capture is unavailable on this platform")
    user32 = windll.user32
    gdi32 = windll.gdi32

    user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_WinRect)]
    user32.GetWindowRect.restype = ctypes.c_int
    user32.IsIconic.argtypes = [ctypes.c_void_p]
    user32.IsIconic.restype = ctypes.c_int
    user32.GetWindowDC.argtypes = [ctypes.c_void_p]
    user32.GetWindowDC.restype = ctypes.c_void_p
    user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    user32.PrintWindow.restype = ctypes.c_int
    gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi32.CreateCompatibleBitmap.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
    ]
    gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
    gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.SelectObject.restype = ctypes.c_void_p
    gdi32.GetDIBits.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.POINTER(_BitmapInfo),
        ctypes.c_uint,
    ]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi32.DeleteObject.restype = ctypes.c_int
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
    gdi32.DeleteDC.restype = ctypes.c_int

    rect = _WinRect()
    if not user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rect)):
        raise GuiUnavailableError("Win32 could not read the target window bounds")
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width <= 0 or height <= 0:
        raise GuiUnavailableError("Win32 target window has invalid capture bounds")
    if (
        width > GUI_MAX_CAPTURE_DIMENSION
        or height > GUI_MAX_CAPTURE_DIMENSION
        or width * height > GUI_MAX_CAPTURE_PIXELS
    ):
        raise GuiUnavailableError(
            f"Windows capture dimensions exceed the safe budget: {width}x{height}"
        )
    if user32.IsIconic(ctypes.c_void_p(hwnd)):
        raise GuiUnavailableError("Cannot capture a minimized Windows window safely")

    window_dc = user32.GetWindowDC(ctypes.c_void_p(hwnd))
    if not window_dc:
        raise GuiUnavailableError("Win32 could not acquire the target window DC")
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height) if memory_dc else None
    old_object = gdi32.SelectObject(memory_dc, bitmap) if bitmap else None
    bitmap_selected = bool(old_object)
    try:
        if not memory_dc or not bitmap or not old_object:
            raise GuiUnavailableError("Win32 could not allocate an off-screen window capture")
        rendered = bool(user32.PrintWindow(ctypes.c_void_p(hwnd), memory_dc, 0x00000002))
        if not rendered:
            rendered = bool(user32.PrintWindow(ctypes.c_void_p(hwnd), memory_dc, 0))
        if not rendered:
            raise GuiUnavailableError(
                "Win32 PrintWindow could not capture the selected window independently"
            )

        byte_count = width * height * 4
        pixels = ctypes.create_string_buffer(byte_count)
        info = _BitmapInfo()
        info.bmiHeader.biSize = ctypes.sizeof(_BitmapInfoHeader)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0
        info.bmiHeader.biSizeImage = byte_count
        restored = gdi32.SelectObject(memory_dc, old_object)
        if not restored:
            raise GuiUnavailableError(
                "Win32 could not unselect the capture bitmap before reading pixels"
            )
        bitmap_selected = False
        copied = gdi32.GetDIBits(
            memory_dc,
            bitmap,
            0,
            height,
            pixels,
            ctypes.byref(info),
            0,
        )
        if copied != height:
            raise GuiUnavailableError("Win32 could not read the captured window bitmap")
        image = Image.frombytes(
            "RGB",
            (width, height),
            bytes(pixels),
            "raw",
            "BGRX",
            width * 4,
            1,
        )
        image.save(destination, format="PNG")
    finally:
        if old_object and bitmap_selected:
            gdi32.SelectObject(memory_dc, old_object)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if memory_dc:
            gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(ctypes.c_void_p(hwnd), window_dc)


def _capture_window_image(hwnd: int, destination: Path) -> None:
    if getattr(sys, "frozen", False):
        argv = [
            sys.executable,
            "_gui-capture-window",
            str(int(hwnd)),
            str(destination),
        ]
    else:
        argv = [
            sys.executable,
            "-m",
            "local_shell_mcp.main",
            "_gui-capture-window",
            str(int(hwnd)),
            str(destination),
        ]
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=_WINDOW_CAPTURE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        destination.unlink(missing_ok=True)
        raise GuiUnavailableError(
            f"Win32 window capture exceeded {_WINDOW_CAPTURE_TIMEOUT_S:g}s and was terminated"
        ) from exc
    if completed.returncode != 0:
        destination.unlink(missing_ok=True)
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise GuiUnavailableError(
            f"Win32 window capture helper failed: {detail or completed.returncode}"
        )


def _safe_property(control: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(control, name)
    except Exception:  # noqa: BLE001 - UIA providers can fail individual properties.
        return default


def _control_runtime_id(control: Any) -> str:
    try:
        value = control.GetRuntimeId()
    except Exception:  # noqa: BLE001 - third-party UIA providers can reject runtime IDs.
        value = None
    if isinstance(value, (list, tuple)):
        return ",".join(str(int(part)) for part in value)
    return str(value or "")


def _window_fingerprint(control: Any) -> str:
    fields = [
        str(int(_safe_property(control, "NativeWindowHandle", 0) or 0)),
        str(int(_safe_property(control, "ProcessId", 0) or 0)),
        _truncate_gui_text(
            _safe_property(control, "ClassName", ""),
            GUI_MAX_ELEMENT_TEXT_BYTES,
        ),
        _truncate_gui_text(
            _safe_property(control, "AutomationId", ""),
            GUI_MAX_ELEMENT_TEXT_BYTES,
        ),
        _truncate_gui_text(_control_runtime_id(control), GUI_MAX_ELEMENT_TEXT_BYTES),
    ]
    return hashlib.sha256("\0".join(fields).encode("utf-8")).hexdigest()[:16]


def _same_uia_control(observed: Any, current: Any) -> bool:
    if observed is None or current is None:
        return False
    auto = _automation()
    compare = getattr(auto, "ControlsAreSame", None)
    if not callable(compare):
        return False
    try:
        return bool(compare(observed, current))
    except Exception:  # noqa: BLE001 - fail closed if UIA identity comparison is unavailable.
        return False


def _element_fingerprint(control: Any) -> str:
    bounds = _rect_dict(_safe_property(control, "BoundingRectangle"))
    fields = [
        _truncate_gui_text(_control_runtime_id(control), GUI_MAX_ELEMENT_TEXT_BYTES),
        str(int(_safe_property(control, "ProcessId", 0) or 0)),
        _truncate_gui_text(
            _safe_property(control, "ControlTypeName", ""),
            GUI_MAX_ELEMENT_TEXT_BYTES,
        ),
        _truncate_gui_text(
            _safe_property(control, "Name", ""),
            GUI_MAX_ELEMENT_TEXT_BYTES,
        ),
        _truncate_gui_text(
            _safe_property(control, "AutomationId", ""),
            GUI_MAX_ELEMENT_TEXT_BYTES,
        ),
        _truncate_gui_text(
            _safe_property(control, "ClassName", ""),
            GUI_MAX_ELEMENT_TEXT_BYTES,
        ),
        str(bounds["x"]),
        str(bounds["y"]),
        str(bounds["width"]),
        str(bounds["height"]),
    ]
    return hashlib.sha256("\0".join(fields).encode("utf-8")).hexdigest()[:16]


def _is_iconic_window(handle: int) -> bool:
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return False
    user32 = windll.user32
    user32.IsIconic.argtypes = [ctypes.c_void_p]
    user32.IsIconic.restype = ctypes.c_int
    return bool(user32.IsIconic(ctypes.c_void_p(handle)))


def _window_record(control: Any) -> dict[str, Any] | None:
    handle = int(_safe_property(control, "NativeWindowHandle", 0) or 0)
    bounds = _rect_dict(_safe_property(control, "BoundingRectangle"))
    if (
        not handle
        or bool(_safe_property(control, "IsOffscreen", False))
        or _is_iconic_window(handle)
        or bounds["width"] <= 0
        or bounds["height"] <= 0
    ):
        return None
    return {
        "id": f"hwnd:{handle}:{_window_fingerprint(control)}",
        "title": _truncate_gui_text(
            _safe_property(control, "Name", ""),
            GUI_MAX_WINDOW_TEXT_BYTES,
        ),
        "app": _truncate_gui_text(
            _safe_property(control, "ClassName", ""),
            GUI_MAX_WINDOW_TEXT_BYTES,
        ),
        "pid": int(_safe_property(control, "ProcessId", 0) or 0),
        "bounds": bounds,
        "_uia_control": control,
    }


def _key_sequence(keys: Any) -> str:
    if isinstance(keys, str):
        parts = [part.strip() for part in keys.replace("+", " ").split() if part.strip()]
    elif isinstance(keys, list):
        parts = [str(part).strip() for part in keys if str(part).strip()]
    else:
        raise ValueError("key action requires keys as a string or list")
    if not parts:
        raise ValueError("key action requires at least one key")

    names = {
        "CONTROL": "Ctrl",
        "CTRL": "Ctrl",
        "ALT": "Alt",
        "OPTION": "Alt",
        "SHIFT": "Shift",
        "WIN": "Win",
        "META": "Win",
        "CMD": "Win",
        "COMMAND": "Win",
        "ENTER": "Enter",
        "RETURN": "Enter",
        "TAB": "Tab",
        "ESC": "Esc",
        "ESCAPE": "Esc",
        "BACKSPACE": "Back",
        "DELETE": "Delete",
        "SPACE": "Space",
        "UP": "Up",
        "DOWN": "Down",
        "LEFT": "Left",
        "RIGHT": "Right",
        "HOME": "Home",
        "END": "End",
        "PAGEUP": "PageUp",
        "PAGEDOWN": "PageDown",
    }
    rendered: list[str] = []
    for part in parts:
        upper = part.upper()
        special = names.get(upper)
        if special:
            rendered.append(f"{{{special}}}")
        elif len(part) == 1:
            rendered.append(part)
        elif upper.startswith("F") and upper[1:].isdigit():
            rendered.append(f"{{{upper}}}")
        else:
            raise ValueError(f"Unsupported Windows key name: {part}")
    return "".join(rendered)


class WindowsGuiBackend:
    name = "windows-uia"

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="lsm-windows-uia",
            initializer=_initialize_uia_thread,
        )

    async def _run_uia(self, func: Any, /, *args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            partial(func, *args, **kwargs),
        )

    def _find_window(
        self,
        window_id: str,
        observed_window: dict[str, Any] | None = None,
    ) -> Any:
        parts = window_id.split(":")
        if len(parts) != 3 or parts[0] != "hwnd" or not parts[2]:
            raise ValueError(f"Invalid Windows window id: {window_id}")
        wanted = int(parts[1])
        expected_fingerprint = parts[2]
        root = _automation().GetRootControl()
        for control in root.GetChildren():
            if int(_safe_property(control, "NativeWindowHandle", 0) or 0) != wanted:
                continue
            if _window_fingerprint(control) != expected_fingerprint:
                raise LookupError(f"Window identity changed since observation: {window_id}")
            if observed_window is not None and "_uia_control" in observed_window:
                observed_control = observed_window.get("_uia_control")
                if not _same_uia_control(observed_control, control):
                    raise LookupError(
                        f"Window UIA identity changed since observation: {window_id}"
                    )
            return control
        raise LookupError(f"Window is no longer available: {window_id}")

    def _resolve_element_locator(
        self,
        window_id: str,
        locator: dict[str, Any],
        observed_window: dict[str, Any] | None = None,
    ) -> Any:
        path = locator.get("path")
        expected_fingerprint = str(locator.get("fingerprint") or "")
        observed_control = locator.get("_uia_control")
        if (
            not isinstance(path, list)
            or not expected_fingerprint
            or observed_control is None
        ):
            raise LookupError("Windows UIA locator is invalid or incomplete")
        control = self._find_window(window_id, observed_window)
        for raw_index in path:
            try:
                index = int(raw_index)
                children = control.GetChildren()
                control = children[index]
            except (IndexError, TypeError, ValueError) as exc:
                raise LookupError(
                    "Target UIA element is no longer available; call gui_state again"
                ) from exc
            except Exception as exc:  # noqa: BLE001 - provider-specific tree failure.
                raise LookupError(
                    "Target UIA element could not be re-resolved; call gui_state again"
                ) from exc
        if _element_fingerprint(control) != expected_fingerprint:
            raise LookupError(
                "Target UIA element changed since observation; call gui_state again"
            )
        if not _same_uia_control(observed_control, control):
            raise LookupError(
                "Target UIA element identity changed since observation; call gui_state again"
            )
        return control

    def _list_windows_sync(self) -> dict[str, Any]:
        auto = _automation()
        windows = []
        used_bytes = 2
        root = auto.GetRootControl()
        control = root.GetFirstChildControl()
        scanned = 0
        while control is not None and scanned < GUI_MAX_WINDOWS * 4:
            scanned += 1
            try:
                record = _window_record(control)
            except Exception:  # noqa: BLE001 - skip broken third-party UIA providers.
                record = None
            if record is not None:
                public_record = {
                    key: record[key]
                    for key in ("id", "title", "app", "pid", "bounds")
                    if key in record
                }
                extra = len(
                    json.dumps(
                        public_record,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        default=str,
                    ).encode("utf-8")
                ) + (1 if windows else 0)
                if used_bytes + extra > GUI_MAX_WINDOWS_TOTAL_BYTES:
                    break
                windows.append(record)
                used_bytes += extra
                if len(windows) >= GUI_MAX_WINDOWS:
                    break
            try:
                control = control.GetNextSiblingControl()
            except Exception:  # noqa: BLE001 - broken provider sibling traversal.
                break
        return {
            "backend": self.name,
            "platform": "windows",
            "windows": windows,
            "capabilities": {
                "accessibility": "UI Automation",
                "window_capture": True,
                "coordinate_input": True,
                "semantic_actions": True,
            },
        }

    async def list_windows(self) -> dict[str, Any]:
        return await self._run_uia(self._list_windows_sync)

    def _snapshot_sync(
        self,
        window_id: str,
        *,
        screenshot_path: Path | None,
        include_elements: bool,
        max_elements: int,
        max_depth: int,
    ) -> GuiSnapshot:
        window = self._find_window(window_id)
        record = _window_record(window)
        if record is None:
            raise LookupError(f"Window has no usable screen bounds: {window_id}")

        elements: list[dict[str, Any]] = []
        locators: dict[str, Any] = {}
        if include_elements:
            queue: list[tuple[Any, int, list[int]]] = [(window, 0, [])]
            used_bytes = 2
            while queue and len(elements) < max_elements:
                control, depth, path = queue.pop(0)
                element_id = f"e{len(elements) + 1}"
                bounds = _rect_dict(_safe_property(control, "BoundingRectangle"))
                element = {
                    "id": element_id,
                    "role": _truncate_gui_text(
                        _safe_property(control, "ControlTypeName", ""),
                        GUI_MAX_ELEMENT_TEXT_BYTES,
                    ),
                    "name": _truncate_gui_text(
                        _safe_property(control, "Name", ""),
                        GUI_MAX_ELEMENT_TEXT_BYTES,
                    ),
                    "automation_id": _truncate_gui_text(
                        _safe_property(control, "AutomationId", ""),
                        GUI_MAX_ELEMENT_TEXT_BYTES,
                    ),
                    "bounds": bounds,
                    "enabled": bool(_safe_property(control, "IsEnabled", True)),
                    "offscreen": bool(_safe_property(control, "IsOffscreen", False)),
                    "depth": depth,
                }
                encoded = json.dumps(
                    element,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
                extra = len(encoded) + (1 if elements else 0)
                if used_bytes + extra > GUI_MAX_ELEMENTS_TOTAL_BYTES:
                    break
                elements.append(element)
                used_bytes += extra
                locators[element_id] = {
                    "path": list(path),
                    "fingerprint": _element_fingerprint(control),
                    "_uia_control": control,
                }
                remaining = max_elements - len(elements) - len(queue)
                if depth >= max_depth or remaining <= 0:
                    continue
                try:
                    children = control.GetChildren()
                except Exception:  # noqa: BLE001 - provider-specific tree failure.
                    children = []
                queue.extend(
                    (child, depth + 1, [*path, index])
                    for index, child in enumerate(children[:remaining])
                )

        screenshot_display: str | None = None
        if screenshot_path is not None:
            handle = int(_safe_property(window, "NativeWindowHandle", 0) or 0)
            if not handle:
                raise GuiUnavailableError("Windows target has no native HWND for safe capture")
            _capture_window_image(handle, screenshot_path)
            current = self._find_window(window_id, record)
            current_record = _window_record(current)
            if current_record is None:
                raise LookupError(
                    f"Window is no longer safely capturable after capture: {window_id}"
                )
            if current_record.get("bounds") != record.get("bounds"):
                raise LookupError(
                    f"Window moved or resized during capture: {window_id}"
                )
            if not screenshot_path.is_file():
                raise GuiUnavailableError("Win32 window capture did not produce an image")
            screenshot_display = display_screenshot_path(screenshot_path)

        return GuiSnapshot(
            window=record,
            elements=elements,
            locators=locators,
            screenshot_path=screenshot_display,
            capabilities={
                "accessibility": "UI Automation",
                "window_capture": screenshot_path is not None,
                "coordinate_space": "window-relative",
                "coordinate_input": True,
                "semantic_actions": True,
            },
        )

    async def snapshot(
        self,
        window_id: str,
        *,
        screenshot_path: Path | None,
        include_elements: bool,
        max_elements: int,
        max_depth: int,
    ) -> GuiSnapshot:
        return await self._run_uia(
            self._snapshot_sync,
            window_id,
            screenshot_path=screenshot_path,
            include_elements=include_elements,
            max_elements=max_elements,
            max_depth=max_depth,
        )

    async def focus_window(self, window: dict[str, Any]) -> None:
        def focus() -> None:
            target = self._find_window(str(window["id"]), window)
            target.SetFocus()

        await self._run_uia(focus)

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
        return await self._run_uia(self._perform_action_sync, window, locator, action)

    def _perform_action_sync(
        self,
        window: dict[str, Any],
        locator: Any | None,
        action: dict[str, Any],
    ) -> dict[str, Any]:
        auto = _automation()
        kind = action["type"]
        if locator is not None:
            if not isinstance(locator, dict):
                raise LookupError("Windows UIA locator is invalid; call gui_state again")
            locator = self._resolve_element_locator(str(window["id"]), locator, window)

        if kind == "focus":
            target = locator or self._find_window(str(window["id"]), window)
            target.SetFocus()
            return {"semantic": True}

        if kind == "set_value":
            if locator is None:
                raise ValueError("set_value requires element_id")
            value = str(action.get("text", ""))
            pattern = locator.GetValuePattern()
            if pattern is None:
                raise ValueError("Target element does not support the UIA Value pattern")
            pattern.SetValue(value)
            return {"semantic": True}

        if kind in {"click", "double_click", "right_click"} and locator is not None:
            if kind == "click":
                pattern = locator.GetInvokePattern()
                if pattern is not None:
                    pattern.Invoke()
                    return {"semantic": True, "method": "invoke"}
            target_window = self._find_window(str(window["id"]), window)
            if not action.get("_focus_prepared"):
                target_window.SetFocus()
            self._screen_point(window, {}, locator)
            if kind == "click":
                locator.Click(waitTime=0)
            elif kind == "double_click":
                locator.DoubleClick(waitTime=0)
            else:
                locator.RightClick(waitTime=0)
            return {"semantic": True, "method": "control"}

        target_window = self._find_window(str(window["id"]), window)
        if not action.get("_focus_prepared"):
            target_window.SetFocus()

        if kind == "type":
            text = str(action.get("text", ""))
            if locator is not None:
                locator.SetFocus()
            auto.SendKeys(text, interval=0.0, waitTime=0, charMode=True)
            return {"characters": len(text)}

        if kind == "key":
            if locator is not None:
                locator.SetFocus()
            sequence = _key_sequence(action.get("keys"))
            auto.SendKeys(sequence, interval=0.0, waitTime=0, charMode=False)
            return {"keys": action.get("keys")}

        if kind in {"click", "double_click", "right_click", "move", "scroll"}:
            x, y = self._screen_point(window, action, locator)
            if kind == "click":
                auto.Click(x, y, waitTime=0)
            elif kind == "double_click":
                auto.Click(x, y, waitTime=0)
                auto.Click(x, y, waitTime=0)
            elif kind == "right_click":
                auto.RightClick(x, y, waitTime=0)
            elif kind == "move":
                auto.MoveTo(x, y, moveSpeed=0, waitTime=0)
            else:
                auto.MoveTo(x, y, moveSpeed=0, waitTime=0)
                default_y = action.get("amount", -3) if "delta_x" not in action else 0
                amount_y = quantize_scroll_amount(action.get("delta_y", default_y))
                amount_x = quantize_scroll_amount(action.get("delta_x", 0))
                if amount_y < 0:
                    auto.WheelDown(abs(amount_y), interval=0.0, waitTime=0)
                elif amount_y > 0:
                    auto.WheelUp(amount_y, interval=0.0, waitTime=0)
                if amount_x:
                    _horizontal_wheel(-amount_x)
            return {"screen_x": x, "screen_y": y}

        if kind == "drag":
            start_x, start_y = self._screen_point(
                window,
                {"x": action.get("x"), "y": action.get("y")},
                locator,
            )
            end_x, end_y = self._screen_point(
                window,
                {"x": action.get("to_x"), "y": action.get("to_y")},
                None,
            )
            auto.DragDrop(start_x, start_y, end_x, end_y, moveSpeed=0, waitTime=0)
            return {
                "from": {"x": start_x, "y": start_y},
                "to": {"x": end_x, "y": end_y},
            }

        raise ValueError(f"Unsupported GUI action type on Windows: {kind}")

    @staticmethod
    def _screen_point(
        window: dict[str, Any],
        action: dict[str, Any],
        locator: Any | None,
    ) -> tuple[int, int]:
        if locator is not None and action.get("x") is None and action.get("y") is None:
            bounds = _rect_dict(_safe_property(locator, "BoundingRectangle"))
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
