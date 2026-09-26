from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from .base import GuiSnapshot, GuiUnavailableError, display_screenshot_path


def _automation():  # noqa: ANN202
    try:
        import uiautomation as auto
    except ImportError as exc:  # pragma: no cover - Windows dependency guard
        raise GuiUnavailableError(
            "Windows GUI automation requires the uiautomation package"
        ) from exc
    return auto


def _rect_dict(rect: Any) -> dict[str, int]:
    left = int(rect.left)
    top = int(rect.top)
    right = int(rect.right)
    bottom = int(rect.bottom)
    return {
        "x": left,
        "y": top,
        "width": max(0, right - left),
        "height": max(0, bottom - top),
    }


def _safe_property(control: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(control, name)
    except Exception:  # noqa: BLE001 - UIA providers can fail individual properties.
        return default


def _window_record(control: Any) -> dict[str, Any] | None:
    handle = int(_safe_property(control, "NativeWindowHandle", 0) or 0)
    bounds = _rect_dict(_safe_property(control, "BoundingRectangle"))
    if not handle or bounds["width"] <= 0 or bounds["height"] <= 0:
        return None
    return {
        "id": f"hwnd:{handle}",
        "title": str(_safe_property(control, "Name", "") or ""),
        "app": str(_safe_property(control, "ClassName", "") or ""),
        "pid": int(_safe_property(control, "ProcessId", 0) or 0),
        "bounds": bounds,
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

    def _find_window(self, window_id: str) -> Any:
        if not window_id.startswith("hwnd:"):
            raise ValueError(f"Invalid Windows window id: {window_id}")
        wanted = int(window_id.split(":", 1)[1])
        root = _automation().GetRootControl()
        for control in root.GetChildren():
            if int(_safe_property(control, "NativeWindowHandle", 0) or 0) == wanted:
                return control
        raise LookupError(f"Window is no longer available: {window_id}")

    async def list_windows(self) -> dict[str, Any]:
        auto = _automation()
        windows = []
        for control in auto.GetRootControl().GetChildren():
            try:
                record = _window_record(control)
            except Exception:  # noqa: BLE001 - skip broken third-party UIA providers.
                continue
            if record is not None:
                windows.append(record)
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

    async def snapshot(
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
            queue: list[tuple[Any, int]] = [(window, 0)]
            while queue and len(elements) < max_elements:
                control, depth = queue.pop(0)
                element_id = f"e{len(elements) + 1}"
                bounds = _rect_dict(_safe_property(control, "BoundingRectangle"))
                element = {
                    "id": element_id,
                    "role": str(_safe_property(control, "ControlTypeName", "") or ""),
                    "name": str(_safe_property(control, "Name", "") or ""),
                    "automation_id": str(_safe_property(control, "AutomationId", "") or ""),
                    "bounds": bounds,
                    "enabled": bool(_safe_property(control, "IsEnabled", True)),
                    "offscreen": bool(_safe_property(control, "IsOffscreen", False)),
                    "depth": depth,
                }
                elements.append(element)
                locators[element_id] = control
                if depth >= max_depth:
                    continue
                try:
                    children = control.GetChildren()
                except Exception:  # noqa: BLE001 - provider-specific tree failure.
                    children = []
                queue.extend((child, depth + 1) for child in children)

        screenshot_display: str | None = None
        if screenshot_path is not None:
            captured = bool(window.CaptureToImage(str(screenshot_path), captureCursor=False))
            if not captured or not screenshot_path.is_file():
                raise GuiUnavailableError(
                    "Windows Graphics/UIA capture failed; ensure the target window is on the active desktop"
                )
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

    async def perform_action(
        self,
        window: dict[str, Any],
        locator: Any | None,
        action: dict[str, Any],
    ) -> dict[str, Any]:
        auto = _automation()
        kind = action["type"]

        if kind == "wait":
            seconds = max(0.0, min(float(action.get("seconds", 1.0)), 30.0))
            await asyncio.sleep(seconds)
            return {"waited_s": seconds}

        if kind == "focus":
            target = locator or self._find_window(str(window["id"]))
            if not target.SetFocus():
                raise RuntimeError("UI Automation could not focus the target")
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
                locator.Click(waitTime=0)
            elif kind == "double_click":
                locator.DoubleClick(waitTime=0)
            else:
                locator.RightClick(waitTime=0)
            return {"semantic": True, "method": "control"}

        target_window = self._find_window(str(window["id"]))
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
            auto.SendKeys(sequence, interval=0.0, waitTime=0, charMode=True)
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
                amount = int(action.get("delta_y", action.get("amount", -3)))
                times = max(1, min(abs(amount), 100))
                if amount < 0:
                    auto.WheelDown(times, interval=0.0, waitTime=0)
                else:
                    auto.WheelUp(times, interval=0.0, waitTime=0)
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
            return (
                bounds["x"] + bounds["width"] // 2,
                bounds["y"] + bounds["height"] // 2,
            )
        if action.get("x") is None or action.get("y") is None:
            raise ValueError("Coordinate action requires x and y, or an element_id")
        bounds = window["bounds"]
        return int(bounds["x"]) + int(action["x"]), int(bounds["y"]) + int(action["y"])
