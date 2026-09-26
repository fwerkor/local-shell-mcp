from __future__ import annotations

import contextlib
import hashlib
import json
import sys
from typing import Any

Atspi: Any | None = None


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
    for desktop_index in range(Atspi.get_desktop_count()):
        desktop = Atspi.get_desktop(desktop_index)
        for index in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(index)
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
            result.append((app, window, index))
    return result


def _window_signature(window: Any) -> str:
    try:
        role = str(window.get_role_name() or "")
    except Exception:
        role = ""
    try:
        title = str(window.get_name() or "")
    except Exception:
        title = ""
    bounds = _bounds(window)
    fingerprint = (
        f"{role}\0{title}\0{bounds['x']}\0{bounds['y']}\0"
        f"{bounds['width']}\0{bounds['height']}"
    )
    return hashlib.sha256(fingerprint.encode()).hexdigest()[:12]


def _element_signature(obj: Any) -> str:
    try:
        role = str(obj.get_role_name() or "")
    except Exception:
        role = ""
    try:
        name = str(obj.get_name() or "")
    except Exception:
        name = ""
    bounds = _bounds(obj)
    fingerprint = (
        f"{role}\0{name}\0{bounds['x']}\0{bounds['y']}\0"
        f"{bounds['width']}\0{bounds['height']}"
    )
    return hashlib.sha256(fingerprint.encode()).hexdigest()[:16]


def _record(app: Any, window: Any, index: int) -> dict[str, Any]:
    pid = int(app.get_process_id())
    return {
        "id": f"atspi:{pid}:{index}:{_window_signature(window)}",
        "title": str(window.get_name() or ""),
        "app": str(app.get_name() or ""),
        "pid": pid,
        "bounds": _bounds(window),
    }


def _resolve_window(window_id: str) -> tuple[Any, Any, int]:
    parts = window_id.split(":")
    if len(parts) not in {3, 4} or parts[0] != "atspi":
        raise ValueError(f"Invalid AT-SPI window id: {window_id}")
    pid = int(parts[1])
    preferred_index = int(parts[2])
    signature = parts[3] if len(parts) == 4 else None
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
                if index == preferred_index:
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
    max_elements = max(1, int(payload.get("max_elements", 300)))
    max_depth = max(1, int(payload.get("max_depth", 12)))
    include_elements = bool(payload.get("include_elements", True))
    elements = []
    locators = {}
    if include_elements:
        queue: list[tuple[Any, list[int], int]] = [(window, [], 0)]
        while queue and len(elements) < max_elements:
            obj, path, depth = queue.pop(0)
            element_id = f"e{len(elements) + 1}"
            role = ""
            name = ""
            with contextlib.suppress(Exception):
                role = str(obj.get_role_name() or "")
            with contextlib.suppress(Exception):
                name = str(obj.get_name() or "")
            actions = []
            try:
                iface = obj.get_action_iface()
                if iface is not None:
                    actions = [
                        str(iface.get_action_name(i) or "")
                        for i in range(iface.get_n_actions())
                    ]
            except Exception:
                pass
            elements.append(
                {
                    "id": element_id,
                    "role": role,
                    "name": name,
                    "bounds": _bounds(obj),
                    "enabled": _state(obj, Atspi.StateType.ENABLED),
                    "focused": _state(obj, Atspi.StateType.FOCUSED),
                    "editable": _state(obj, Atspi.StateType.EDITABLE),
                    "actions": actions,
                    "depth": depth,
                }
            )
            locators[element_id] = {
                "path": path,
                "fingerprint": _element_signature(obj),
            }
            if depth >= max_depth:
                continue
            try:
                child_count = obj.get_child_count()
            except Exception:
                child_count = 0
            for child_index in range(child_count):
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


def _semantic_action(payload: dict[str, Any]) -> dict[str, Any]:
    _app, window, _window_index = _resolve_window(str(payload["window_id"]))
    raw_locator = payload.get("locator", {})
    if isinstance(raw_locator, dict):
        locator = [int(value) for value in raw_locator.get("path", [])]
        expected_fingerprint = str(raw_locator.get("fingerprint") or "")
    else:
        locator = [int(value) for value in raw_locator]
        expected_fingerprint = ""
    obj = _resolve_path(window, locator)
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
        chosen = 0
        for index in range(count):
            name = str(iface.get_action_name(index) or "").lower()
            if name in preferred:
                chosen = index
                break
        if not iface.do_action(chosen):
            raise RuntimeError("AT-SPI action failed")
        return {"semantic": True, "method": str(iface.get_action_name(chosen) or "action")}

    raise ValueError(f"Unsupported semantic AT-SPI action: {kind}")


def _raw(payload: dict[str, Any]) -> dict[str, Any]:
    kind = str(payload["kind"])
    if kind == "mouse":
        ok = Atspi.generate_mouse_event(
            int(payload["x"]),
            int(payload["y"]),
            str(payload["event"]),
        )
        if not ok:
            raise RuntimeError("AT-SPI mouse synthesis failed")
        return {"generated": True}
    if kind == "text":
        text = str(payload.get("text", ""))
        ok = Atspi.generate_keyboard_event(0, text, Atspi.KeySynthType.STRING)
        if not ok:
            raise RuntimeError("AT-SPI text synthesis failed")
        return {"generated": True, "characters": len(text)}
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
        for app, window, index in _windows():
            try:
                windows.append(_record(app, window, index))
            except Exception:
                continue
        return {"windows": windows, "monitors": _monitors()}
    if command == "snapshot":
        return _snapshot(payload)
    if command == "semantic_action":
        return _semantic_action(payload)
    if command == "raw":
        return _raw(payload)
    raise ValueError(f"Unknown helper command: {command}")


def main() -> int:
    try:
        request = json.loads(sys.stdin.read() or "{}")
        response = {"ok": True, "data": _main(request)}
        code = 0
    except Exception as exc:
        response = {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": f"{type(exc).__name__}: {exc}",
        }
        code = 2
    print(json.dumps(response, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
