from __future__ import annotations

import asyncio
import contextlib
import json
import math
import platform
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

from ..fs_ops import (
    acquire_temp_file_lease,
    relative_display,
    release_temp_file_lease,
    temp_dir,
)

GUI_STATE_TTL_S = 30.0
GUI_STATE_CACHE_LIMIT = 32
GUI_MAX_ELEMENTS = 1000
GUI_MAX_DEPTH = 20
GUI_MAX_ACTIONS = 32
GUI_MAX_TOTAL_WAIT_S = 30.0
GUI_MAX_TEXT_BYTES = 4096
GUI_MAX_KEY_PARTS = 16
GUI_MAX_KEYS_BYTES = 256
GUI_MAX_WINDOWS = 256
GUI_MAX_WINDOW_ID_BYTES = 1024
GUI_MAX_WINDOW_TEXT_BYTES = 1024
GUI_MAX_WINDOWS_TOTAL_BYTES = 128 * 1024
GUI_MAX_CAPTURE_DIMENSION = 16_384
GUI_MAX_CAPTURE_PIXELS = 64_000_000
GUI_MAX_ELEMENT_TEXT_BYTES = 1024
GUI_MAX_ELEMENT_VALUE_BYTES = 2048
GUI_MAX_ELEMENTS_TOTAL_BYTES = 64 * 1024

_COORDINATE_ACTIONS = {
    "click",
    "double_click",
    "right_click",
    "move",
    "scroll",
    "drag",
}
_HUMAN_ACTIONS = _COORDINATE_ACTIONS | {"type", "key"}
_GUI_ACTIONS = _HUMAN_ACTIONS | {"set_value", "focus", "wait"}


class GuiUnavailableError(RuntimeError):
    """Raised when desktop automation is unavailable in the current session."""


class GuiStaleStateError(RuntimeError):
    """Raised when an action references an expired or changed GUI state."""


@dataclass(slots=True)
class GuiSnapshot:
    window: dict[str, Any]
    elements: list[dict[str, Any]]
    locators: dict[str, Any] = field(default_factory=dict)
    screenshot_path: str | None = None
    capabilities: dict[str, Any] = field(default_factory=dict)


class GuiBackend(Protocol):
    name: str

    async def list_windows(self) -> dict[str, Any]: ...

    async def snapshot(
        self,
        window_id: str,
        *,
        screenshot_path: Path | None,
        include_elements: bool,
        max_elements: int,
        max_depth: int,
    ) -> GuiSnapshot: ...

    async def perform_action(
        self,
        window: dict[str, Any],
        locator: Any | None,
        action: dict[str, Any],
    ) -> dict[str, Any]: ...

    async def focus_window(self, window: dict[str, Any]) -> None: ...


@dataclass(slots=True)
class _StateRecord:
    state_id: str
    window: dict[str, Any]
    locators: dict[str, Any]
    created_at: float


def _backend_for_platform() -> GuiBackend:
    system = platform.system()
    if system == "Windows":
        from .windows import WindowsGuiBackend

        return WindowsGuiBackend()
    if system == "Darwin":
        from .macos import MacOSGuiBackend

        return MacOSGuiBackend()
    if system == "Linux":
        from .linux import LinuxGuiBackend

        return LinuxGuiBackend()
    raise GuiUnavailableError(f"GUI automation is unsupported on {system or platform.platform()}")


def _truncate_gui_text(value: Any, limit: int) -> str:
    text = str(value or "")
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    suffix = "..."
    budget = max(0, limit - len(suffix))
    return encoded[:budget].decode("utf-8", errors="ignore") + suffix


def _bounded_element_record(element: dict[str, Any]) -> dict[str, Any]:
    bounded: dict[str, Any] = {}
    for key in ("id", "role", "name", "automation_id"):
        if key in element:
            bounded[key] = _truncate_gui_text(element.get(key), GUI_MAX_ELEMENT_TEXT_BYTES)
    for key in ("value", "description"):
        if key in element:
            bounded[key] = _truncate_gui_text(element.get(key), GUI_MAX_ELEMENT_VALUE_BYTES)
    for key in ("enabled", "focused", "offscreen", "depth"):
        if key in element:
            bounded[key] = element.get(key)
    bounds = element.get("bounds")
    if isinstance(bounds, dict):
        bounded["bounds"] = {
            key: bounds.get(key)
            for key in ("x", "y", "width", "height")
            if key in bounds
        }
    actions = element.get("actions")
    if isinstance(actions, list):
        bounded["actions"] = [
            _truncate_gui_text(item, GUI_MAX_ELEMENT_TEXT_BYTES)
            for item in actions[:32]
        ]
    return bounded


def _bounded_elements(
    elements: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[str]]:
    bounded: list[dict[str, Any]] = []
    kept_ids: set[str] = set()
    used = 2
    for raw in elements[:GUI_MAX_ELEMENTS]:
        if not isinstance(raw, dict):
            continue
        record = _bounded_element_record(raw)
        encoded = json.dumps(
            record,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        extra = len(encoded) + (1 if bounded else 0)
        if used + extra > GUI_MAX_ELEMENTS_TOTAL_BYTES:
            break
        bounded.append(record)
        used += extra
        element_id = record.get("id")
        if isinstance(element_id, str):
            kept_ids.add(element_id)
    return bounded, kept_ids


def _bounded_window_record(window: dict[str, Any]) -> dict[str, Any] | None:
    bounded: dict[str, Any] = {}
    if "id" in window:
        window_id = str(window.get("id") or "")
        if len(window_id.encode("utf-8")) > GUI_MAX_WINDOW_ID_BYTES:
            return None
        bounded["id"] = window_id
    for key in ("title", "app"):
        if key in window:
            bounded[key] = _truncate_gui_text(window.get(key), GUI_MAX_WINDOW_TEXT_BYTES)
    if "pid" in window:
        try:
            bounded["pid"] = int(window.get("pid"))
        except (TypeError, ValueError):
            bounded["pid"] = 0
    bounds = window.get("bounds")
    if isinstance(bounds, dict):
        bounded["bounds"] = {
            key: bounds.get(key)
            for key in ("x", "y", "width", "height")
            if key in bounds
        }
    return bounded


def _bounded_window_records(windows: Any) -> list[dict[str, Any]]:
    if not isinstance(windows, list):
        return []
    bounded: list[dict[str, Any]] = []
    used = 2
    for raw in windows[:GUI_MAX_WINDOWS]:
        if not isinstance(raw, dict):
            continue
        record = _bounded_window_record(raw)
        if record is None:
            continue
        encoded = json.dumps(
            record,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        extra = len(encoded) + (1 if bounded else 0)
        if used + extra > GUI_MAX_WINDOWS_TOTAL_BYTES:
            break
        bounded.append(record)
        used += extra
    return bounded


def _normalize_screenshot_coordinates(path: Path, window: dict[str, Any]) -> None:
    bounds = window.get("bounds")
    if not isinstance(bounds, dict):
        return
    try:
        width = int(bounds["width"])
        height = int(bounds["height"])
    except (KeyError, TypeError, ValueError):
        return
    if width <= 0 or height <= 0:
        return
    if (
        width > GUI_MAX_CAPTURE_DIMENSION
        or height > GUI_MAX_CAPTURE_DIMENSION
        or width * height > GUI_MAX_CAPTURE_PIXELS
    ):
        raise GuiUnavailableError(
            f"GUI window dimensions exceed the safe screenshot budget: {width}x{height}"
        )
    with Image.open(path) as image:
        image.load()
        if image.size == (width, height):
            return
        normalized = image.resize((width, height), Image.Resampling.LANCZOS)
        normalized.save(path, format="PNG")


def _bounds_tuple(value: Any) -> tuple[int, int, int, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        return (
            int(value["x"]),
            int(value["y"]),
            int(value["width"]),
            int(value["height"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _window_relative_elements(
    elements: list[dict[str, Any]],
    window: dict[str, Any],
) -> list[dict[str, Any]]:
    window_bounds = _bounds_tuple(window.get("bounds"))
    if window_bounds is None:
        return [dict(element) for element in elements]
    window_x, window_y, _width, _height = window_bounds
    normalized = []
    for element in elements:
        item = dict(element)
        bounds = _bounds_tuple(element.get("bounds"))
        if bounds is not None:
            x, y, width, height = bounds
            item["bounds"] = {
                "x": x - window_x,
                "y": y - window_y,
                "width": width,
                "height": height,
            }
        normalized.append(item)
    return normalized


def _validate_window_relative_point(
    window: dict[str, Any],
    x: Any,
    y: Any,
    *,
    label: str,
) -> None:
    bounds = _bounds_tuple(window.get("bounds"))
    if bounds is None:
        raise ValueError("Target window has invalid bounds")
    _window_x, _window_y, width, height = bounds
    try:
        px = int(x)
        py = int(y)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} requires integer x and y coordinates") from exc
    if px < 0 or py < 0 or px >= width or py >= height:
        raise ValueError(
            f"{label} ({px}, {py}) is outside the selected window "
            f"({width}x{height})"
        )


def _validate_coordinate_action(
    window: dict[str, Any],
    action: dict[str, Any],
    *,
    has_locator: bool,
) -> None:
    kind = str(action["type"])
    has_x = action.get("x") is not None
    has_y = action.get("y") is not None
    if has_x != has_y:
        raise ValueError(f"{kind} requires both x and y when either coordinate is provided")
    if has_x:
        _validate_window_relative_point(
            window,
            action["x"],
            action["y"],
            label=f"{kind} point",
        )
    elif not has_locator:
        raise ValueError(f"{kind} requires x and y, or an element_id")

    if kind == "drag":
        if action.get("to_x") is None or action.get("to_y") is None:
            raise ValueError("drag requires to_x and to_y")
        _validate_window_relative_point(
            window,
            action["to_x"],
            action["to_y"],
            label="drag destination",
        )


def quantize_scroll_amount(value: Any, *, limit: int = 100) -> int:
    amount = float(value)
    if amount == 0:
        return 0
    magnitude = max(1, min(math.ceil(abs(amount)), limit))
    return -magnitude if amount < 0 else magnitude


async def _await_native_operation(awaitable: Any) -> Any:
    task = asyncio.create_task(awaitable)
    try:
        return await asyncio.shield(task)
    except BaseException:
        with contextlib.suppress(BaseException):
            await asyncio.shield(task)
        raise


def _cleanup_gui_screenshot(path: Path) -> None:
    path.unlink(missing_ok=True)
    release_temp_file_lease(path)


class GuiManager:
    """Own short-lived observed states and dispatch actions to the native backend."""

    def __init__(self, backend: GuiBackend | None = None) -> None:
        self._backend = backend or _backend_for_platform()
        self._states: dict[str, _StateRecord] = {}
        self._lock = asyncio.Lock()
        self._execution_lock = asyncio.Lock()

    @property
    def backend_name(self) -> str:
        return self._backend.name

    async def list_windows(self) -> dict[str, Any]:
        result = await self._backend.list_windows()
        result.setdefault("backend", self._backend.name)
        result["windows"] = _bounded_window_records(result.get("windows"))
        return result

    async def snapshot(
        self,
        window_id: str,
        *,
        screenshot: bool = True,
        include_elements: bool = True,
        max_elements: int = 300,
        max_depth: int = 12,
    ) -> dict[str, Any]:
        max_elements = max(1, min(int(max_elements), GUI_MAX_ELEMENTS))
        max_depth = max(1, min(int(max_depth), GUI_MAX_DEPTH))
        screenshot_path: Path | None = None
        if screenshot:
            screenshot_path = temp_dir() / f"gui-{uuid.uuid4().hex}.png"
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            acquire_temp_file_lease(screenshot_path)

        async def capture_snapshot() -> GuiSnapshot:
            return await _await_native_operation(
                self._backend.snapshot(
                    str(window_id),
                    screenshot_path=screenshot_path,
                    include_elements=include_elements,
                    max_elements=max_elements,
                    max_depth=max_depth,
                )
            )

        try:
            if screenshot_path is not None:
                async with self._execution_lock:
                    snapshot = await capture_snapshot()
            else:
                snapshot = await capture_snapshot()

            if screenshot_path is not None:
                if snapshot.screenshot_path is None:
                    _cleanup_gui_screenshot(screenshot_path)
                elif not screenshot_path.is_file():
                    raise GuiUnavailableError(
                        "GUI backend did not produce the requested screenshot"
                    )
                else:
                    normalize = asyncio.create_task(
                        asyncio.to_thread(
                            _normalize_screenshot_coordinates,
                            screenshot_path,
                            snapshot.window,
                        )
                    )
                    try:
                        await asyncio.shield(normalize)
                    except BaseException:
                        with contextlib.suppress(BaseException):
                            await asyncio.shield(normalize)
                        raise
        except BaseException:
            if screenshot_path is not None:
                _cleanup_gui_screenshot(screenshot_path)
            raise

        bounded_elements, kept_ids = _bounded_elements(snapshot.elements)
        bounded_locators = {
            element_id: locator
            for element_id, locator in snapshot.locators.items()
            if element_id in kept_ids
        }

        state_id = uuid.uuid4().hex
        now = time.monotonic()
        async with self._lock:
            self._prune_locked(now)
            self._states[state_id] = _StateRecord(
                state_id=state_id,
                window=dict(snapshot.window),
                locators=bounded_locators,
                created_at=now,
            )
            while len(self._states) > GUI_STATE_CACHE_LIMIT:
                oldest = min(self._states.values(), key=lambda item: item.created_at)
                self._states.pop(oldest.state_id, None)

        return {
            "backend": self._backend.name,
            "state_id": state_id,
            "state_ttl_s": GUI_STATE_TTL_S,
            "window": snapshot.window,
            "elements": _window_relative_elements(bounded_elements, snapshot.window),
            "capabilities": snapshot.capabilities,
            "screenshot_path": snapshot.screenshot_path,
        }

    async def frame(self, window_id: str) -> dict[str, Any]:
        screenshot_path = temp_dir() / f"gui-frame-{uuid.uuid4().hex}.png"
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        acquire_temp_file_lease(screenshot_path)
        keep_file = False
        try:
            async with self._execution_lock:
                snapshot = await _await_native_operation(
                    self._backend.snapshot(
                        str(window_id),
                        screenshot_path=screenshot_path,
                        include_elements=False,
                        max_elements=1,
                        max_depth=1,
                    )
                )
            if snapshot.screenshot_path is None or not screenshot_path.is_file():
                raise GuiUnavailableError("GUI backend did not produce the requested screenshot")
            normalize = asyncio.create_task(
                asyncio.to_thread(
                    _normalize_screenshot_coordinates,
                    screenshot_path,
                    snapshot.window,
                )
            )
            try:
                await asyncio.shield(normalize)
            except BaseException:
                with contextlib.suppress(BaseException):
                    await asyncio.shield(normalize)
                raise
            keep_file = True
            return {
                "backend": self._backend.name,
                "window": snapshot.window,
                "capabilities": snapshot.capabilities,
                "screenshot_path": snapshot.screenshot_path,
            }
        finally:
            if not keep_file:
                _cleanup_gui_screenshot(screenshot_path)

    async def act(
        self,
        window_id: str,
        state_id: str,
        actions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self._validate_action_batch(actions)

        results: list[dict[str, Any]] = []
        async with self._execution_lock:
            async with self._lock:
                self._prune_locked(time.monotonic())
                record = self._states.pop(state_id, None)
            if record is None:
                raise GuiStaleStateError(
                    "GUI state is stale, unknown, or already consumed; call gui_state again"
                )
            if str(record.window.get("id")) != str(window_id):
                raise GuiStaleStateError(
                    "GUI state belongs to a different window; call gui_state again"
                )

            normalized: list[tuple[dict[str, Any], Any | None]] = []
            for index, raw_action in enumerate(actions):
                action = dict(raw_action)
                kind = str(action.get("type") or "").strip().lower()
                if not kind:
                    raise ValueError(f"actions[{index}].type is required")
                action["type"] = kind
                target = action.get("element_id")
                locator = None
                if target is not None:
                    locator = record.locators.get(str(target))
                    if locator is None:
                        raise ValueError(f"Unknown element_id {target!r} for state {state_id}")
                if kind in _COORDINATE_ACTIONS:
                    _validate_coordinate_action(
                        record.window,
                        action,
                        has_locator=locator is not None,
                    )
                normalized.append((action, locator))

            for index, (action, locator) in enumerate(normalized):
                if time.monotonic() - record.created_at > GUI_STATE_TTL_S:
                    raise GuiStaleStateError(
                        "GUI state expired during action batch; call gui_state again"
                    )
                if action["type"] in _COORDINATE_ACTIONS:
                    await self._assert_window_geometry_unchanged(record.window)
                result = await _await_native_operation(
                    self._backend.perform_action(record.window, locator, action)
                )
                results.append({"index": index, "type": action["type"], **(result or {})})

        return {
            "backend": self._backend.name,
            "state_id": state_id,
            "window_id": str(window_id),
            "state_consumed": True,
            "actions": results,
        }

    async def human_act(
        self,
        window_id: str,
        observed_bounds: dict[str, Any],
        actions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        expected_bounds = _bounds_tuple(observed_bounds)
        if expected_bounds is None:
            raise ValueError("Observed window bounds are invalid")
        self._validate_action_batch(actions)

        normalized: list[dict[str, Any]] = []
        for index, raw_action in enumerate(actions):
            action = dict(raw_action)
            kind = str(action.get("type") or "").strip().lower()
            if not kind:
                raise ValueError(f"actions[{index}].type is required")
            if kind not in _HUMAN_ACTIONS:
                raise ValueError(f"Unsupported human GUI action type: {kind}")
            if action.get("element_id") is not None:
                raise ValueError("Human GUI actions do not accept element_id")
            action["type"] = kind
            if kind in _COORDINATE_ACTIONS:
                _validate_coordinate_action(
                    {"bounds": dict(observed_bounds)},
                    action,
                    has_locator=False,
                )
            normalized.append(action)

        results: list[dict[str, Any]] = []
        async with self._execution_lock:
            for index, action in enumerate(normalized):
                current = await self._current_window(
                    window_id,
                    "refresh the displayed frame and try again",
                )
                if _bounds_tuple(current.get("bounds")) != expected_bounds:
                    raise GuiStaleStateError(
                        "Target window moved or resized since the displayed frame; refresh it and try again"
                    )
                if action["type"] in _COORDINATE_ACTIONS:
                    _validate_coordinate_action(current, action, has_locator=False)
                if action["type"] in {"type", "key"}:
                    await _await_native_operation(self._backend.focus_window(current))
                result = await _await_native_operation(
                    self._backend.perform_action(current, None, action)
                )
                results.append({"index": index, "type": action["type"], **(result or {})})

        return {
            "backend": self._backend.name,
            "window_id": str(window_id),
            "human_control": True,
            "actions": results,
        }

    @staticmethod
    def _validate_action_batch(actions: list[dict[str, Any]]) -> None:
        if not actions:
            raise ValueError("actions must contain at least one GUI action")
        if len(actions) > GUI_MAX_ACTIONS:
            raise ValueError(f"actions may contain at most {GUI_MAX_ACTIONS} GUI actions")
        total_wait = 0.0
        for index, raw_action in enumerate(actions):
            kind = str(raw_action.get("type") or "").strip().lower()
            if not kind:
                raise ValueError(f"actions[{index}].type is required")
            if kind not in _GUI_ACTIONS:
                raise ValueError(f"Unsupported GUI action type: {kind}")

            target = raw_action.get("element_id")
            if target is not None and not str(target).strip():
                raise ValueError(f"actions[{index}].element_id must not be empty")
            if kind in _COORDINATE_ACTIONS:
                has_x = raw_action.get("x") is not None
                has_y = raw_action.get("y") is not None
                if has_x != has_y:
                    raise ValueError(
                        f"{kind} requires both x and y when either coordinate is provided"
                    )
                if target is None and not has_x:
                    raise ValueError(
                        f"actions[{index}] requires x and y, or an element_id"
                    )
                if kind == "drag" and (
                    raw_action.get("to_x") is None or raw_action.get("to_y") is None
                ):
                    raise ValueError(f"actions[{index}] drag requires to_x and to_y")
            if kind == "type" and raw_action.get("text") is None:
                raise ValueError(f"actions[{index}].text is required for type")
            if kind == "key" and raw_action.get("keys") is None:
                raise ValueError(f"actions[{index}].keys is required for key")
            if kind == "set_value" and target is None:
                raise ValueError(f"actions[{index}].element_id is required for set_value")

            text = raw_action.get("text")
            if text is not None and len(str(text).encode("utf-8")) > GUI_MAX_TEXT_BYTES:
                raise ValueError(
                    f"actions[{index}].text may not exceed {GUI_MAX_TEXT_BYTES} UTF-8 bytes"
                )
            keys = raw_action.get("keys")
            if keys is not None:
                if isinstance(keys, str):
                    key_parts = [
                        part.strip()
                        for part in keys.replace("+", " ").split()
                        if part.strip()
                    ]
                    key_bytes = len(keys.encode("utf-8"))
                elif isinstance(keys, list):
                    key_parts = [str(part).strip() for part in keys if str(part).strip()]
                    key_bytes = sum(len(part.encode("utf-8")) for part in key_parts)
                else:
                    raise ValueError(
                        f"actions[{index}].keys must be a string or list"
                    )
                if not key_parts:
                    raise ValueError(
                        f"actions[{index}].keys must contain at least one key"
                    )
                if len(key_parts) > GUI_MAX_KEY_PARTS:
                    raise ValueError(
                        f"actions[{index}].keys may contain at most {GUI_MAX_KEY_PARTS} parts"
                    )
                if key_bytes > GUI_MAX_KEYS_BYTES:
                    raise ValueError(
                        f"actions[{index}].keys may not exceed {GUI_MAX_KEYS_BYTES} UTF-8 bytes"
                    )
            if kind != "wait":
                continue
            try:
                seconds = float(raw_action.get("seconds", 1.0))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"actions[{index}].seconds must be numeric") from exc
            total_wait += max(0.0, min(seconds, 30.0))
        if total_wait > GUI_MAX_TOTAL_WAIT_S:
            raise ValueError(
                f"Total GUI wait time may not exceed {GUI_MAX_TOTAL_WAIT_S:g} seconds"
            )

    async def _current_window(
        self,
        window_id: str,
        stale_hint: str = "call gui_state again",
    ) -> dict[str, Any]:
        current = await self._backend.list_windows()
        wanted = str(window_id)
        match = next(
            (item for item in current.get("windows", []) if str(item.get("id")) == wanted),
            None,
        )
        if match is None:
            raise GuiStaleStateError(
                f"Target window is no longer available; {stale_hint}"
            )
        return match

    async def refresh_state(self, window_id: str, state_id: str) -> dict[str, Any]:
        now = time.monotonic()
        async with self._lock:
            self._prune_locked(now)
            record = self._states.get(state_id)
            if record is None:
                raise GuiStaleStateError(
                    "GUI state is stale, unknown, or already consumed; call gui_state again"
                )
            if str(record.window.get("id")) != str(window_id):
                raise GuiStaleStateError(
                    "GUI state belongs to a different window; call gui_state again"
                )
            record.created_at = now
        return {"state_id": state_id, "state_ttl_s": GUI_STATE_TTL_S}

    async def _assert_window_geometry_unchanged(self, observed: dict[str, Any]) -> None:
        match = await self._current_window(str(observed.get("id")))
        old_bounds = _bounds_tuple(observed.get("bounds"))
        new_bounds = _bounds_tuple(match.get("bounds"))
        if old_bounds is not None and new_bounds is not None and old_bounds != new_bounds:
            raise GuiStaleStateError("Target window moved or resized; call gui_state again")

    def _prune_locked(self, now: float) -> None:
        expired = [
            state_id
            for state_id, record in self._states.items()
            if now - record.created_at > GUI_STATE_TTL_S
        ]
        for state_id in expired:
            self._states.pop(state_id, None)


_manager: GuiManager | None = None


def get_gui_manager() -> GuiManager:
    global _manager
    if _manager is None:
        _manager = GuiManager()
    return _manager


def reset_gui_manager() -> None:
    global _manager
    _manager = None


def display_screenshot_path(path: Path) -> str:
    return relative_display(path)
