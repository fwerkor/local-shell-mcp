from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

from .base import GuiSnapshot, GuiUnavailableError, display_screenshot_path


def _native():  # noqa: ANN202
    try:
        import ApplicationServices as AX
        import Quartz
    except ImportError as exc:  # pragma: no cover - macOS dependency guard
        raise GuiUnavailableError(
            "macOS GUI automation requires pyobjc-framework-ApplicationServices and "
            "pyobjc-framework-Quartz"
        ) from exc
    return AX, Quartz


def _cg_bounds(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {"x": 0, "y": 0, "width": 0, "height": 0}
    return {
        "x": int(round(float(value.get("X", value.get("x", 0))))),
        "y": int(round(float(value.get("Y", value.get("y", 0))))),
        "width": max(0, int(round(float(value.get("Width", value.get("width", 0)))))),
        "height": max(0, int(round(float(value.get("Height", value.get("height", 0)))))),
    }


def _ax_copy(AX: Any, element: Any, attribute: str, default: Any = None) -> Any:
    try:
        result = AX.AXUIElementCopyAttributeValue(element, attribute, None)
    except Exception:  # noqa: BLE001 - accessibility providers may reject attributes.
        return default
    if isinstance(result, tuple) and len(result) == 2:
        error, value = result
        return value if int(error) == 0 else default
    return result if result is not None else default


def _ax_value(AX: Any, value: Any, kind: int) -> Any:
    if value is None:
        return None
    try:
        result = AX.AXValueGetValue(value, kind, None)
    except Exception:  # noqa: BLE001 - malformed third-party AX values.
        return None
    if isinstance(result, tuple) and len(result) == 2:
        ok, unpacked = result
        return unpacked if ok else None
    return result


def _ax_bounds(AX: Any, element: Any) -> dict[str, int]:
    position = _ax_value(
        AX,
        _ax_copy(AX, element, AX.kAXPositionAttribute),
        AX.kAXValueCGPointType,
    )
    size = _ax_value(
        AX,
        _ax_copy(AX, element, AX.kAXSizeAttribute),
        AX.kAXValueCGSizeType,
    )
    if position is None or size is None:
        return {"x": 0, "y": 0, "width": 0, "height": 0}
    return {
        "x": int(round(float(position.x))),
        "y": int(round(float(position.y))),
        "width": max(0, int(round(float(size.width)))),
        "height": max(0, int(round(float(size.height)))),
    }


def _same_bounds(left: dict[str, int], right: dict[str, int], tolerance: int = 3) -> bool:
    return all(abs(int(left[key]) - int(right[key])) <= tolerance for key in left)


_MAC_KEY_CODES = {
    "A": 0, "S": 1, "D": 2, "F": 3, "H": 4, "G": 5, "Z": 6, "X": 7,
    "C": 8, "V": 9, "B": 11, "Q": 12, "W": 13, "E": 14, "R": 15, "Y": 16,
    "T": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23,
    "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29, "]": 30,
    "O": 31, "U": 32, "[": 33, "I": 34, "P": 35, "ENTER": 36, "RETURN": 36,
    "L": 37, "J": 38, "'": 39, "K": 40, ";": 41, "\\": 42, ",": 43,
    "/": 44, "N": 45, "M": 46, ".": 47, "TAB": 48, "SPACE": 49,
    "BACKSPACE": 51, "DELETE": 51, "ESC": 53, "ESCAPE": 53, "HOME": 115,
    "PAGEUP": 116, "END": 119, "PAGEDOWN": 121, "LEFT": 123, "RIGHT": 124,
    "DOWN": 125, "UP": 126,
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
    return [part.upper() for part in parts]


class MacOSGuiBackend:
    name = "macos-ax"

    def _windows(self) -> list[dict[str, Any]]:
        _AX, Quartz = _native()
        options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
        rows = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []
        windows = []
        for row in rows:
            layer = int(row.get(Quartz.kCGWindowLayer, 0) or 0)
            bounds = _cg_bounds(row.get(Quartz.kCGWindowBounds))
            window_id = int(row.get(Quartz.kCGWindowNumber, 0) or 0)
            if layer != 0 or not window_id or bounds["width"] <= 1 or bounds["height"] <= 1:
                continue
            windows.append(
                {
                    "id": f"cg:{window_id}",
                    "title": str(row.get(Quartz.kCGWindowName, "") or ""),
                    "app": str(row.get(Quartz.kCGWindowOwnerName, "") or ""),
                    "pid": int(row.get(Quartz.kCGWindowOwnerPID, 0) or 0),
                    "bounds": bounds,
                }
            )
        return windows

    def _find_record(self, window_id: str) -> dict[str, Any]:
        record = next((item for item in self._windows() if item["id"] == window_id), None)
        if record is None:
            raise LookupError(f"Window is no longer available: {window_id}")
        return record

    def _find_ax_window(self, record: dict[str, Any]) -> Any | None:
        AX, _Quartz = _native()
        if not bool(AX.AXIsProcessTrusted()):
            return None
        app = AX.AXUIElementCreateApplication(int(record["pid"]))
        windows = _ax_copy(AX, app, AX.kAXWindowsAttribute, []) or []
        title = str(record.get("title") or "")
        best = None
        for window in windows:
            candidate_title = str(_ax_copy(AX, window, AX.kAXTitleAttribute, "") or "")
            bounds = _ax_bounds(AX, window)
            if title and candidate_title == title and _same_bounds(bounds, record["bounds"]):
                return window
            if best is None and _same_bounds(bounds, record["bounds"]) or best is None and title and candidate_title == title:
                best = window
        return best or (windows[0] if len(windows) == 1 else None)

    async def list_windows(self) -> dict[str, Any]:
        AX, _Quartz = _native()
        trusted = bool(AX.AXIsProcessTrusted())
        return {
            "backend": self.name,
            "platform": "macos",
            "windows": self._windows(),
            "capabilities": {
                "accessibility": "AXUIElement" if trusted else False,
                "screen_recording_required": True,
                "accessibility_permission_required": not trusted,
                "window_capture": True,
                "coordinate_input": trusted,
                "semantic_actions": trusted,
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
        AX, _Quartz = _native()
        record = self._find_record(window_id)
        trusted = bool(AX.AXIsProcessTrusted())
        elements: list[dict[str, Any]] = []
        locators: dict[str, Any] = {}

        ax_window = self._find_ax_window(record) if include_elements and trusted else None
        if ax_window is not None:
            queue: list[tuple[Any, int]] = [(ax_window, 0)]
            while queue and len(elements) < max_elements:
                element, depth = queue.pop(0)
                element_id = f"e{len(elements) + 1}"
                elements.append(
                    {
                        "id": element_id,
                        "role": str(_ax_copy(AX, element, AX.kAXRoleAttribute, "") or ""),
                        "name": str(
                            _ax_copy(AX, element, AX.kAXTitleAttribute, "")
                            or _ax_copy(AX, element, AX.kAXDescriptionAttribute, "")
                            or ""
                        ),
                        "value": str(_ax_copy(AX, element, AX.kAXValueAttribute, "") or "")[:1000],
                        "bounds": _ax_bounds(AX, element),
                        "enabled": bool(_ax_copy(AX, element, AX.kAXEnabledAttribute, True)),
                        "depth": depth,
                    }
                )
                locators[element_id] = element
                if depth >= max_depth:
                    continue
                children = _ax_copy(AX, element, AX.kAXChildrenAttribute, []) or []
                queue.extend((child, depth + 1) for child in children)

        screenshot_display: str | None = None
        if screenshot_path is not None:
            window_number = str(window_id).split(":", 1)[1]
            result = await asyncio.to_thread(
                subprocess.run,
                ["/usr/sbin/screencapture", "-x", "-o", "-l", window_number, str(screenshot_path)],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if result.returncode != 0 or not screenshot_path.is_file():
                detail = (result.stderr or result.stdout or "").strip()
                raise GuiUnavailableError(
                    "macOS window capture failed; grant Screen Recording permission"
                    + (f": {detail}" if detail else "")
                )
            screenshot_display = display_screenshot_path(screenshot_path)

        return GuiSnapshot(
            window=record,
            elements=elements,
            locators=locators,
            screenshot_path=screenshot_display,
            capabilities={
                "accessibility": "AXUIElement" if trusted else False,
                "accessibility_permission_required": not trusted,
                "window_capture": screenshot_path is not None,
                "coordinate_space": "window-relative",
                "coordinate_input": trusted,
                "semantic_actions": trusted,
            },
        )

    async def perform_action(
        self,
        window: dict[str, Any],
        locator: Any | None,
        action: dict[str, Any],
    ) -> dict[str, Any]:
        AX, Quartz = _native()
        if not bool(AX.AXIsProcessTrusted()):
            raise GuiUnavailableError("Grant Accessibility permission to local-shell-mcp on macOS")

        kind = action["type"]
        if kind == "wait":
            seconds = max(0.0, min(float(action.get("seconds", 1.0)), 30.0))
            await asyncio.sleep(seconds)
            return {"waited_s": seconds}

        if kind == "focus":
            target = locator or self._find_ax_window(window)
            if target is None:
                raise RuntimeError("Could not resolve the target AX element")
            error = AX.AXUIElementSetAttributeValue(target, AX.kAXFocusedAttribute, True)
            if int(error) != 0 and locator is None:
                error = AX.AXUIElementPerformAction(target, AX.kAXRaiseAction)
            if int(error) != 0:
                raise RuntimeError(f"AX focus action failed with error {error}")
            return {"semantic": True}

        if kind == "set_value":
            if locator is None:
                raise ValueError("set_value requires element_id")
            error = AX.AXUIElementSetAttributeValue(
                locator, AX.kAXValueAttribute, str(action.get("text", ""))
            )
            if int(error) != 0:
                raise ValueError(f"Target element rejected AX value update: {error}")
            return {"semantic": True}

        if kind == "click" and locator is not None:
            error = AX.AXUIElementPerformAction(locator, AX.kAXPressAction)
            if int(error) == 0:
                return {"semantic": True, "method": "AXPress"}

        ax_window = self._find_ax_window(window)
        if ax_window is not None:
            AX.AXUIElementPerformAction(ax_window, AX.kAXRaiseAction)

        if kind == "type":
            text = str(action.get("text", ""))
            if locator is not None:
                AX.AXUIElementSetAttributeValue(locator, AX.kAXFocusedAttribute, True)
            event = Quartz.CGEventCreateKeyboardEvent(None, 0, True)
            Quartz.CGEventKeyboardSetUnicodeString(event, len(text), text)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
            up = Quartz.CGEventCreateKeyboardEvent(None, 0, False)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
            return {"characters": len(text)}

        if kind == "key":
            if locator is not None:
                AX.AXUIElementSetAttributeValue(locator, AX.kAXFocusedAttribute, True)
            self._send_key_chord(Quartz, action.get("keys"))
            return {"keys": action.get("keys")}

        if kind in {"click", "double_click", "right_click", "move", "scroll"}:
            x, y = self._screen_point(AX, window, action, locator)
            if kind == "move":
                self._mouse(Quartz, Quartz.kCGEventMouseMoved, x, y, Quartz.kCGMouseButtonLeft)
            elif kind == "scroll":
                self._mouse(Quartz, Quartz.kCGEventMouseMoved, x, y, Quartz.kCGMouseButtonLeft)
                amount = int(action.get("delta_y", action.get("amount", -3)))
                event = Quartz.CGEventCreateScrollWheelEvent(
                    None, Quartz.kCGScrollEventUnitLine, 1, amount
                )
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
            else:
                right = kind == "right_click"
                button = Quartz.kCGMouseButtonRight if right else Quartz.kCGMouseButtonLeft
                down = Quartz.kCGEventRightMouseDown if right else Quartz.kCGEventLeftMouseDown
                up = Quartz.kCGEventRightMouseUp if right else Quartz.kCGEventLeftMouseUp
                count = 2 if kind == "double_click" else 1
                for click_count in range(1, count + 1):
                    down_event = Quartz.CGEventCreateMouseEvent(None, down, (x, y), button)
                    up_event = Quartz.CGEventCreateMouseEvent(None, up, (x, y), button)
                    if count == 2:
                        Quartz.CGEventSetIntegerValueField(
                            down_event, Quartz.kCGMouseEventClickState, click_count
                        )
                        Quartz.CGEventSetIntegerValueField(
                            up_event, Quartz.kCGMouseEventClickState, click_count
                        )
                    Quartz.CGEventPost(Quartz.kCGHIDEventTap, down_event)
                    Quartz.CGEventPost(Quartz.kCGHIDEventTap, up_event)
            return {"screen_x": x, "screen_y": y}

        if kind == "drag":
            start_x, start_y = self._screen_point(
                AX, window, {"x": action.get("x"), "y": action.get("y")}, locator
            )
            end_x, end_y = self._screen_point(
                AX, window, {"x": action.get("to_x"), "y": action.get("to_y")}, None
            )
            self._mouse(
                Quartz, Quartz.kCGEventLeftMouseDown, start_x, start_y, Quartz.kCGMouseButtonLeft
            )
            self._mouse(
                Quartz, Quartz.kCGEventLeftMouseDragged, end_x, end_y, Quartz.kCGMouseButtonLeft
            )
            self._mouse(
                Quartz, Quartz.kCGEventLeftMouseUp, end_x, end_y, Quartz.kCGMouseButtonLeft
            )
            return {
                "from": {"x": start_x, "y": start_y},
                "to": {"x": end_x, "y": end_y},
            }

        raise ValueError(f"Unsupported GUI action type on macOS: {kind}")

    @staticmethod
    def _mouse(Quartz: Any, event_type: int, x: int, y: int, button: int) -> None:
        event = Quartz.CGEventCreateMouseEvent(None, event_type, (x, y), button)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)

    @staticmethod
    def _screen_point(
        AX: Any,
        window: dict[str, Any],
        action: dict[str, Any],
        locator: Any | None,
    ) -> tuple[int, int]:
        if locator is not None and action.get("x") is None and action.get("y") is None:
            bounds = _ax_bounds(AX, locator)
            return (
                bounds["x"] + bounds["width"] // 2,
                bounds["y"] + bounds["height"] // 2,
            )
        if action.get("x") is None or action.get("y") is None:
            raise ValueError("Coordinate action requires x and y, or an element_id")
        bounds = window["bounds"]
        return int(bounds["x"]) + int(action["x"]), int(bounds["y"]) + int(action["y"])

    @staticmethod
    def _send_key_chord(Quartz: Any, keys: Any) -> None:
        parts = _key_parts(keys)
        modifier_flags = {
            "SHIFT": Quartz.kCGEventFlagMaskShift,
            "CTRL": Quartz.kCGEventFlagMaskControl,
            "CONTROL": Quartz.kCGEventFlagMaskControl,
            "ALT": Quartz.kCGEventFlagMaskAlternate,
            "OPTION": Quartz.kCGEventFlagMaskAlternate,
            "CMD": Quartz.kCGEventFlagMaskCommand,
            "COMMAND": Quartz.kCGEventFlagMaskCommand,
            "META": Quartz.kCGEventFlagMaskCommand,
        }
        flags = 0
        ordinary = []
        for part in parts:
            if part in modifier_flags:
                flags |= modifier_flags[part]
            else:
                ordinary.append(part)
        if len(ordinary) != 1:
            raise ValueError("macOS key action requires exactly one non-modifier key")
        key = ordinary[0]
        code = _MAC_KEY_CODES.get(key)
        if code is None and len(key) == 1:
            code = _MAC_KEY_CODES.get(key.upper())
        if code is None:
            raise ValueError(f"Unsupported macOS key name: {key}")
        down = Quartz.CGEventCreateKeyboardEvent(None, code, True)
        up = Quartz.CGEventCreateKeyboardEvent(None, code, False)
        Quartz.CGEventSetFlags(down, flags)
        Quartz.CGEventSetFlags(up, flags)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
