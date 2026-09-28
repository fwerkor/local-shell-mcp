from __future__ import annotations

import contextlib
import hashlib
import json
import sys
from typing import Any

Atspi: Any | None = None

GUI_MAX_ELEMENTS = 1000
GUI_MAX_DEPTH = 20
GUI_MAX_WINDOWS = 256
GUI_MAX_WINDOW_TEXT_BYTES = 1024
GUI_MAX_WINDOWS_TOTAL_BYTES = 128 * 1024
GUI_MAX_ELEMENT_TEXT_BYTES = 1024
GUI_MAX_ELEMENTS_TOTAL_BYTES = 64 * 1024
GUI_MAX_ELEMENT_ACTIONS = 32
GUI_MAX_RESPONSE_BYTES = 256 * 1024

_KEYSYMS = {
    "BACKSPACE": 0xFF08,
    "TAB": 0xFF09,
    "ENTER": 0xFF0D,
    "RETURN": 0xFF0D,
    "ESC": 0xFF1B,
    "ESCAPE": 0xFF1B,
    "HOME": 0xFF50,
    "LEFT": 0xFF51,
    "UP": 0xFF52,
    "RIGHT": 0xFF53,
    "DOWN": 0xFF54,
    "PAGEUP": 0xFF55,
    "PAGEDOWN": 0xFF56,
    "END": 0xFF57,
    "DELETE": 0xFFFF,
    "SPACE": 0x20,
}

_MODIFIERS = {
    "SHIFT": 0xFFE1,
    "CTRL": 0xFFE3,
    "CONTROL": 0xFFE3,
    "ALT": 0xFFE9,
    "OPTION": 0xFFE9,
    "META": 0xFFEB,
    "SUPER": 0xFFEB,
    "WIN": 0xFFEB,
    "CMD": 0xFFEB,
    "COMMAND": 0xFFEB,
}


def _truncate_text(value: Any, limit: int) -> str:
    text = str(value or "")
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    suffix = "..."
    budget = max(0, limit - len(suffix))
    return encoded[:budget].decode("utf-8", errors="ignore") + suffix


def _json_size(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    )


def _keysym(text: str) -> int:
    upper = text.upper()
    if upper in _KEYSYMS:
        return _KEYSYMS[upper]
    if len(text) != 1:
        raise ValueError(f"Unsupported AT-SPI key name: {text}")
    codepoint = ord(text)
    if codepoint <= 0xFF:
        return codepoint
    return 0x01000000 | codepoint


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


def _atspi() -> Any:
    global Atspi
    if Atspi is not None:
        return Atspi
    try:
        import gi

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi as module
    except Exception as exc:
        raise RuntimeError(
            "AT-SPI Python bindings are unavailable. Install python3-gi and "
            f"gir1.2-atspi-2.0: {type(exc).__name__}: {exc}"
        ) from exc
    Atspi = module
    return module


def _bounds(obj: Any) -> dict[str, int]:
    try:
        component = obj.get_component_iface()
        if component is None:
            raise RuntimeError
        rect = component.get_extents(Atspi.CoordType.SCREEN)
        return {
            "x": int(rect.x),
            "y": int(rect.y),
            "width": max(0, int(rect.width)),
            "height": max(0, int(rect.height)),
        }
    except Exception:
        return {"x": 0, "y": 0, "width": 0, "height": 0}


def _state(obj: Any, state: Any) -> bool:
    try:
        return bool(obj.get_state_set().contains(state))
    except Exception:
        return False


def _apps() -> list[Any]:
    apps = []
    try:
        desktop_count = Atspi.get_desktop_count()
    except Exception:
        return apps
    for desktop_index in range(desktop_count):
        try:
            desktop = Atspi.get_desktop(desktop_index)
            child_count = desktop.get_child_count()
        except Exception:
            continue
        for index in range(child_count):
            try:
                app = desktop.get_child_at_index(index)
            except Exception:
                continue
            if app is not None:
                apps.append(app)
    return apps


def _monitors() -> list[dict[str, Any]]:
    try:
        import gi

        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk

        display = Gdk.Display.get_default()
        if display is None:
            return []
        monitors = []
        for index in range(display.get_n_monitors()):
            monitor = display.get_monitor(index)
            geometry = monitor.get_geometry()
            monitors.append(
                {
                    "index": index,
                    "x": int(geometry.x),
                    "y": int(geometry.y),
                    "width": int(geometry.width),
                    "height": int(geometry.height),
                    "scale": int(monitor.get_scale_factor()),
                    "primary": bool(monitor.is_primary()),
                }
            )
        return monitors
    except Exception:
        return []


def _windows() -> list[tuple[Any, Any, int]]:
    result = []
    for app in _apps():
        try:
            app.get_process_id()
            count = app.get_child_count()
        except Exception:
            continue
        for index in range(count):
            try:
                window = app.get_child_at_index(index)
                if window is None:
                    continue
                bounds = _bounds(window)
                role = str(window.get_role_name() or "")
            except Exception:
                continue
            if bounds["width"] <= 1 or bounds["height"] <= 1:
                continue
            if role not in {"frame", "dialog", "window", "application"} and index > 0:
                continue
            if not _window_is_visible(window):
                continue
            result.append((app, window, index))
            if len(result) >= GUI_MAX_WINDOWS:
                return result
    return result


def _window_is_visible(window: Any) -> bool:
    try:
        state_set = window.get_state_set()
    except Exception:
        return True
    state_type = getattr(Atspi, "StateType", None)
    if state_type is None:
        return True
    iconified = getattr(state_type, "ICONIFIED", None)
    if iconified is not None:
        with contextlib.suppress(Exception):
            if bool(state_set.contains(iconified)):
                return False
    showing = getattr(state_type, "SHOWING", None)
    if showing is not None:
        try:
            return bool(state_set.contains(showing))
        except Exception:
            return True
    return True


def _window_signature(window: Any) -> str | None:
    try:
        accessible_id = str(window.get_accessible_id() or "")
    except Exception:
        accessible_id = ""
    if not accessible_id:
        return None
    try:
        role = str(window.get_role_name() or "")
    except Exception:
        role = ""
    fingerprint = f"id\0{role}\0{accessible_id}"
    return hashlib.sha256(fingerprint.encode()).hexdigest()[:12]


def _accessible_id(obj: Any) -> str | None:
    try:
        accessible_id = _truncate_text(
            obj.get_accessible_id(),
            GUI_MAX_ELEMENT_TEXT_BYTES,
        )
    except Exception:
        accessible_id = ""
    return accessible_id or None


def _element_signature(obj: Any) -> str | None:
    accessible_id = _accessible_id(obj)
    if accessible_id is None:
        return None
    try:
        role = _truncate_text(
            obj.get_role_name(),
            GUI_MAX_ELEMENT_TEXT_BYTES,
        )
    except Exception:
        role = ""
    try:
        name = _truncate_text(
            obj.get_name(),
            GUI_MAX_ELEMENT_TEXT_BYTES,
        )
    except Exception:
        name = ""
    bounds = _bounds(obj)
    fingerprint = (
        f"{accessible_id}\0{role}\0{name}\0{bounds['x']}\0{bounds['y']}\0"
        f"{bounds['width']}\0{bounds['height']}"
    )
    return hashlib.sha256(fingerprint.encode()).hexdigest()[:16]


def _record(app: Any, window: Any, index: int) -> dict[str, Any]:
    del index
    pid = int(app.get_process_id())
    signature = _window_signature(window)
    if not signature:
        raise LookupError("AT-SPI window does not expose a stable accessible id")
    return {
        "id": f"atspi:{pid}:{signature}",
        "title": _truncate_text(window.get_name(), GUI_MAX_WINDOW_TEXT_BYTES),
        "app": _truncate_text(app.get_name(), GUI_MAX_WINDOW_TEXT_BYTES),
        "pid": pid,
        "bounds": _bounds(window),
    }


def _resolve_window(window_id: str) -> tuple[Any, Any, int]:
    parts = window_id.split(":")
    if len(parts) not in {3, 4} or parts[0] != "atspi":
        raise ValueError(f"Invalid AT-SPI window id: {window_id}")
    pid = int(parts[1])
    preferred_index: int | None
    signature: str | None
    if len(parts) == 4:
        preferred_index = int(parts[2])
        signature = parts[3]
    elif parts[2].isdigit():
        preferred_index = int(parts[2])
        signature = None
    else:
        preferred_index = None
        signature = parts[2]
    for app in _apps():
        try:
            if int(app.get_process_id()) != pid:
                continue
            count = app.get_child_count()
        except Exception:
            continue

        candidates = []
        for index in range(count):
            try:
                window = app.get_child_at_index(index)
            except Exception:
                continue
            if window is None:
                continue
            if signature is None:
                if preferred_index is not None and index == preferred_index:
                    return app, window, index
                continue
            if _window_signature(window) == signature:
                candidates.append((window, index))

        if signature is not None:
            if len(candidates) == 1:
                window, index = candidates[0]
                return app, window, index
            if len(candidates) > 1:
                raise LookupError(f"Window identity is ambiguous after reordering: {window_id}")
    raise LookupError(f"Window is no longer available: {window_id}")


def _resolve_path(window: Any, path: list[int]) -> Any:
    current = window
    for index in path:
        current = current.get_child_at_index(int(index))
        if current is None:
            raise LookupError("AT-SPI element path is no longer valid")
    return current


def _snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    app, window, window_index = _resolve_window(str(payload["window_id"]))
    max_elements = max(1, min(int(payload.get("max_elements", 300)), GUI_MAX_ELEMENTS))
    max_depth = max(1, min(int(payload.get("max_depth", 12)), GUI_MAX_DEPTH))
    include_elements = bool(payload.get("include_elements", True))
    elements = []
    locators = {}
    elements_bytes = 2
    if include_elements:
        queue: list[tuple[Any, list[int], int]] = [(window, [], 0)]
        while queue and len(elements) < max_elements:
            obj, path, depth = queue.pop(0)
            element_id = f"e{len(elements) + 1}"
            role = ""
            name = ""
            with contextlib.suppress(Exception):
                role = _truncate_text(obj.get_role_name(), GUI_MAX_ELEMENT_TEXT_BYTES)
            with contextlib.suppress(Exception):
                name = _truncate_text(obj.get_name(), GUI_MAX_ELEMENT_TEXT_BYTES)
            actions = []
            try:
                iface = obj.get_action_iface()
                if iface is not None:
                    action_count = max(0, min(int(iface.get_n_actions()), GUI_MAX_ELEMENT_ACTIONS))
                    actions = [
                        _truncate_text(
                            iface.get_action_name(i),
                            GUI_MAX_ELEMENT_TEXT_BYTES,
                        )
                        for i in range(action_count)
                    ]
            except Exception:
                pass
            signature = _element_signature(obj)
            element = {
                "id": element_id,
                "role": role,
                "name": name,
                "bounds": _bounds(obj),
                "enabled": _state(obj, Atspi.StateType.ENABLED),
                "focused": _state(obj, Atspi.StateType.FOCUSED),
                "editable": _state(obj, Atspi.StateType.EDITABLE),
                "actions": actions if signature is not None else [],
                "depth": depth,
            }
            extra = _json_size(element) + (1 if elements else 0)
            if elements_bytes + extra > GUI_MAX_ELEMENTS_TOTAL_BYTES:
                break
            elements.append(element)
            elements_bytes += extra
            if signature is not None:
                locators[element_id] = {
                    "path": path,
                    "accessible_id": _accessible_id(obj),
                    "fingerprint": signature,
                }
            if depth >= max_depth:
                continue
            try:
                child_count = obj.get_child_count()
            except Exception:
                child_count = 0
            remaining = max(0, max_elements - len(elements) - len(queue))
            for child_index in range(min(child_count, remaining)):
                try:
                    child = obj.get_child_at_index(child_index)
                except Exception:
                    child = None
                if child is not None:
                    queue.append((child, [*path, child_index], depth + 1))
    return {
        "window": _record(app, window, window_index),
        "elements": elements,
        "locators": locators,
    }


def _resolve_locator(payload: dict[str, Any]) -> dict[str, Any]:
    _app, window, _window_index = _resolve_window(str(payload["window_id"]))
    raw_locator = payload.get("locator", {})
    if isinstance(raw_locator, dict):
        locator = [int(value) for value in raw_locator.get("path", [])]
        expected_accessible_id = str(raw_locator.get("accessible_id") or "")
        expected_fingerprint = str(raw_locator.get("fingerprint") or "")
    else:
        locator = [int(value) for value in raw_locator]
        expected_accessible_id = ""
        expected_fingerprint = ""
    obj = _resolve_path(window, locator)
    if isinstance(raw_locator, dict):
        current_accessible_id = _accessible_id(obj)
        if (
            not expected_accessible_id
            or current_accessible_id != expected_accessible_id
        ):
            raise LookupError("AT-SPI target element changed since observation")
    if expected_fingerprint and _element_signature(obj) != expected_fingerprint:
        raise LookupError("AT-SPI target element changed since observation")
    return {"bounds": _bounds(obj)}


def _semantic_action(payload: dict[str, Any]) -> dict[str, Any]:
    _app, window, _window_index = _resolve_window(str(payload["window_id"]))
    raw_locator = payload.get("locator", {})
    if isinstance(raw_locator, dict):
        locator = [int(value) for value in raw_locator.get("path", [])]
        expected_accessible_id = str(raw_locator.get("accessible_id") or "")
        expected_fingerprint = str(raw_locator.get("fingerprint") or "")
    else:
        locator = [int(value) for value in raw_locator]
        expected_accessible_id = ""
        expected_fingerprint = ""
    obj = _resolve_path(window, locator)
    if isinstance(raw_locator, dict):
        current_accessible_id = _accessible_id(obj)
        if (
            not expected_accessible_id
            or current_accessible_id != expected_accessible_id
        ):
            raise LookupError("AT-SPI target element changed since observation")
    if expected_fingerprint and _element_signature(obj) != expected_fingerprint:
        raise LookupError("AT-SPI target element changed since observation")
    action = payload["action"]
    kind = str(action["type"])

    if kind == "focus":
        component = obj.get_component_iface()
        if component is None or not component.grab_focus():
            raise RuntimeError("AT-SPI target cannot be focused")
        return {"semantic": True}

    if kind == "set_value":
        editable = obj.get_editable_text_iface()
        if editable is None:
            raise ValueError("Target element does not support AT-SPI EditableText")
        if not editable.set_text_contents(str(action.get("text", ""))):
            raise RuntimeError("AT-SPI EditableText rejected the new value")
        return {"semantic": True}

    if kind == "click":
        iface = obj.get_action_iface()
        if iface is None:
            raise ValueError("Target element has no AT-SPI action interface")
        count = iface.get_n_actions()
        if count <= 0:
            raise ValueError("Target element has no AT-SPI actions")
        preferred = {"click", "press", "activate", "jump", "open"}
        chosen: int | None = None
        for index in range(count):
            name = str(iface.get_action_name(index) or "").lower()
            if name in preferred:
                chosen = index
                break
        if chosen is None:
            raise ValueError("Target element has no preferred AT-SPI activation action")
        if not iface.do_action(chosen):
            raise RuntimeError("AT-SPI action failed")
        return {"semantic": True, "method": str(iface.get_action_name(chosen) or "action")}

    raise ValueError(f"Unsupported semantic AT-SPI action: {kind}")


def _focus_keyboard_target(payload: dict[str, Any]) -> None:
    window_id = str(payload.get("window_id") or "")
    if not window_id:
        raise ValueError("keyboard synthesis requires window_id")
    raw_locator = payload.get("locator")
    _semantic_action(
        {
            "window_id": window_id,
            "locator": raw_locator if raw_locator is not None else [],
            "action": {"type": "focus"},
        }
    )

    _app, window, _window_index = _resolve_window(window_id)
    if raw_locator is None:
        obj = window
    elif isinstance(raw_locator, dict):
        locator = [int(value) for value in raw_locator.get("path", [])]
        obj = _resolve_path(window, locator)
        expected_accessible_id = str(raw_locator.get("accessible_id") or "")
        expected_fingerprint = str(raw_locator.get("fingerprint") or "")
        if (
            not expected_accessible_id
            or _accessible_id(obj) != expected_accessible_id
            or (
                expected_fingerprint
                and _element_signature(obj) != expected_fingerprint
            )
        ):
            raise LookupError("AT-SPI target element changed since observation")
    else:
        obj = _resolve_path(window, [int(value) for value in raw_locator])

    if not _state(obj, Atspi.StateType.FOCUSED):
        raise RuntimeError("AT-SPI keyboard target did not remain focused")


def _bounds_tuple(bounds: Any) -> tuple[int, int, int, int]:
    if not isinstance(bounds, dict):
        return (0, 0, 0, 0)
    return tuple(
        int(bounds.get(key, 0) or 0)
        for key in ("x", "y", "width", "height")
    )


def _prepare_pointer_target(payload: dict[str, Any]) -> dict[str, int]:
    window_id = str(payload.get("window_id") or "")
    if not window_id:
        raise ValueError("pointer synthesis requires window_id")
    expected_bounds = payload.get("window_bounds")
    if not isinstance(expected_bounds, dict):
        raise ValueError("pointer synthesis requires window_bounds")

    _app, window, _window_index = _resolve_window(window_id)
    if _bounds_tuple(_bounds(window)) != _bounds_tuple(expected_bounds):
        raise LookupError("AT-SPI target window changed since observation")
    component = window.get_component_iface()
    if component is None or not component.grab_focus():
        raise RuntimeError("AT-SPI target window cannot be focused")

    _app, window, _window_index = _resolve_window(window_id)
    current_bounds = _bounds(window)
    if _bounds_tuple(current_bounds) != _bounds_tuple(expected_bounds):
        raise LookupError("AT-SPI target window changed while focusing")

    raw_locator = payload.get("locator")
    if raw_locator is not None:
        if not isinstance(raw_locator, dict):
            raise LookupError("AT-SPI target locator is invalid")
        locator = [int(value) for value in raw_locator.get("path", [])]
        obj = _resolve_path(window, locator)
        expected_accessible_id = str(raw_locator.get("accessible_id") or "")
        expected_fingerprint = str(raw_locator.get("fingerprint") or "")
        if (
            not expected_accessible_id
            or _accessible_id(obj) != expected_accessible_id
            or (
                expected_fingerprint
                and _element_signature(obj) != expected_fingerprint
            )
        ):
            raise LookupError("AT-SPI target element changed since observation")
    return current_bounds


def _raw(payload: dict[str, Any]) -> dict[str, Any]:
    kind = str(payload["kind"])
    if kind == "bound_pointer":
        window_bounds = _prepare_pointer_target(payload)
        events = payload.get("events")
        if not isinstance(events, list) or not events or len(events) > 200:
            raise ValueError("bound_pointer requires 1..200 events")
        left = int(window_bounds["x"])
        top = int(window_bounds["y"])
        right = left + int(window_bounds["width"])
        bottom = top + int(window_bounds["height"])
        pressed_buttons: list[int] = []
        last_x, last_y = left, top
        generated = 0
        try:
            for event in events:
                if not isinstance(event, dict):
                    raise ValueError("bound_pointer events must be objects")
                x = int(event["x"])
                y = int(event["y"])
                name = str(event["event"])
                if not (left <= x < right and top <= y < bottom):
                    raise LookupError(
                        "Pointer target moved outside the selected window"
                    )
                if not Atspi.generate_mouse_event(x, y, name):
                    raise RuntimeError("AT-SPI mouse synthesis failed")
                generated += 1
                last_x, last_y = x, y
                if len(name) >= 3 and name[0] == "b" and name[-1] in {"p", "r"}:
                    try:
                        button = int(name[1:-1])
                    except ValueError:
                        button = 0
                    if button > 0:
                        if name[-1] == "p":
                            pressed_buttons.append(button)
                        elif button in pressed_buttons:
                            pressed_buttons.remove(button)
        finally:
            for button in reversed(pressed_buttons):
                with contextlib.suppress(Exception):
                    Atspi.generate_mouse_event(
                        last_x,
                        last_y,
                        f"b{button}r",
                    )
        return {"generated": True, "events": generated}
    if kind == "mouse":
        ok = Atspi.generate_mouse_event(
            int(payload["x"]),
            int(payload["y"]),
            str(payload["event"]),
        )
        if not ok:
            raise RuntimeError("AT-SPI mouse synthesis failed")
        return {"generated": True}
    if kind == "mouse_sequence":
        events = payload.get("events")
        if not isinstance(events, list) or not events or len(events) > 200:
            raise ValueError("mouse_sequence requires 1..200 events")
        for event in events:
            if not isinstance(event, dict):
                raise ValueError("mouse_sequence events must be objects")
            ok = Atspi.generate_mouse_event(
                int(event["x"]),
                int(event["y"]),
                str(event["event"]),
            )
            if not ok:
                raise RuntimeError("AT-SPI mouse synthesis failed")
        return {"generated": True, "events": len(events)}
    if kind == "text":
        _focus_keyboard_target(payload)
        text = str(payload.get("text", ""))
        ok = Atspi.generate_keyboard_event(0, text, Atspi.KeySynthType.STRING)
        if not ok:
            raise RuntimeError("AT-SPI text synthesis failed")
        return {"generated": True, "characters": len(text)}
    if kind == "key_chord":
        _focus_keyboard_target(payload)
        parts = _key_parts(payload.get("keys"))
        modifiers: list[int] = []
        ordinary: list[int] = []
        for part in parts:
            symbol = _MODIFIERS.get(part.upper())
            if symbol is not None:
                modifiers.append(symbol)
                continue
            key = part.lower() if len(part) == 1 and part.isalpha() else part
            ordinary.append(_keysym(key))
        if len(ordinary) != 1:
            raise ValueError("key action requires exactly one non-modifier key")

        pressed: list[int] = []
        try:
            for symbol in modifiers:
                if not Atspi.generate_keyboard_event(
                    symbol,
                    None,
                    Atspi.KeySynthType.PRESS,
                ):
                    raise RuntimeError("AT-SPI key press synthesis failed")
                pressed.append(symbol)
            ordinary_symbol = ordinary[0]
            if not Atspi.generate_keyboard_event(
                ordinary_symbol,
                None,
                Atspi.KeySynthType.PRESS,
            ):
                raise RuntimeError("AT-SPI key press synthesis failed")
            pressed.append(ordinary_symbol)
            if not Atspi.generate_keyboard_event(
                ordinary_symbol,
                None,
                Atspi.KeySynthType.RELEASE,
            ):
                raise RuntimeError("AT-SPI key release synthesis failed")
            pressed.pop()
        finally:
            for symbol in reversed(pressed):
                with contextlib.suppress(Exception):
                    Atspi.generate_keyboard_event(
                        symbol,
                        None,
                        Atspi.KeySynthType.RELEASE,
                    )
        return {"generated": True, "keys": parts}
    if kind == "keysym":
        ok = Atspi.generate_keyboard_event(
            int(payload["keysym"]),
            None,
            Atspi.KeySynthType.SYM,
        )
        if not ok:
            raise RuntimeError("AT-SPI key synthesis failed")
        return {"generated": True}
    raise ValueError(f"Unsupported raw AT-SPI action: {kind}")


def _main(payload: dict[str, Any]) -> dict[str, Any]:
    _atspi()
    command = str(payload.get("command") or "")
    if command == "list":
        windows = []
        windows_bytes = 2
        for app, window, index in _windows():
            try:
                record = _record(app, window, index)
            except Exception:
                continue
            extra = _json_size(record) + (1 if windows else 0)
            if windows_bytes + extra > GUI_MAX_WINDOWS_TOTAL_BYTES:
                break
            windows.append(record)
            windows_bytes += extra
            if len(windows) >= GUI_MAX_WINDOWS:
                break
        return {"windows": windows, "monitors": _monitors()}
    if command == "snapshot":
        return _snapshot(payload)
    if command == "semantic_action":
        return _semantic_action(payload)
    if command == "resolve_locator":
        return _resolve_locator(payload)
    if command == "raw":
        return _raw(payload)
    raise ValueError(f"Unknown helper command: {command}")


def main() -> int:
    try:
        request = json.loads(sys.stdin.read() or "{}")
        response = {"ok": True, "data": _main(request)}
        code = 0
    except Exception as exc:
        detail = _truncate_text(
            f"{type(exc).__name__}: {exc}",
            GUI_MAX_ELEMENT_TEXT_BYTES * 4,
        )
        response = {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": detail,
        }
        code = 2
    encoded = json.dumps(response, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > GUI_MAX_RESPONSE_BYTES:
        response = {
            "ok": False,
            "error_type": "ValueError",
            "error": "ValueError: AT-SPI helper response exceeds the safe size budget",
        }
        code = 2
        encoded = json.dumps(response, ensure_ascii=False)
    print(encoded)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
