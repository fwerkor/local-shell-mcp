from __future__ import annotations

import asyncio
import platform
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

from ..fs_ops import relative_display, temp_dir

GUI_STATE_TTL_S = 30.0
GUI_STATE_CACHE_LIMIT = 32
GUI_MAX_ELEMENTS = 1000
GUI_MAX_DEPTH = 20

_COORDINATE_ACTIONS = {
    "click",
    "double_click",
    "right_click",
    "move",
    "scroll",
    "drag",
}


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


class GuiManager:
    """Own short-lived observed states and dispatch actions to the native backend."""

    def __init__(self, backend: GuiBackend | None = None) -> None:
        self._backend = backend or _backend_for_platform()
        self._states: dict[str, _StateRecord] = {}
        self._lock = asyncio.Lock()

    @property
    def backend_name(self) -> str:
        return self._backend.name

    async def list_windows(self) -> dict[str, Any]:
        result = await self._backend.list_windows()
        result.setdefault("backend", self._backend.name)
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

        try:
            snapshot = await self._backend.snapshot(
                str(window_id),
                screenshot_path=screenshot_path,
                include_elements=include_elements,
                max_elements=max_elements,
                max_depth=max_depth,
            )
        except Exception:
            if screenshot_path is not None:
                screenshot_path.unlink(missing_ok=True)
            raise

        if screenshot_path is not None:
            if snapshot.screenshot_path is None:
                screenshot_path.unlink(missing_ok=True)
            elif not screenshot_path.is_file():
                raise GuiUnavailableError("GUI backend did not produce the requested screenshot")
            else:
                try:
                    await asyncio.to_thread(
                        _normalize_screenshot_coordinates, screenshot_path, snapshot.window
                    )
                except Exception:
                    screenshot_path.unlink(missing_ok=True)
                    raise

        state_id = uuid.uuid4().hex
        now = time.monotonic()
        async with self._lock:
            self._prune_locked(now)
            self._states[state_id] = _StateRecord(
                state_id=state_id,
                window=dict(snapshot.window),
                locators=dict(snapshot.locators),
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
            "elements": snapshot.elements,
            "capabilities": snapshot.capabilities,
            "screenshot_path": snapshot.screenshot_path,
        }

    async def act(
        self,
        window_id: str,
        state_id: str,
        actions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not actions:
            raise ValueError("actions must contain at least one GUI action")

        async with self._lock:
            self._prune_locked(time.monotonic())
            record = self._states.pop(state_id, None)
        if record is None:
            raise GuiStaleStateError(
                "GUI state is stale, unknown, or already consumed; call gui_state again"
            )
        if str(record.window.get("id")) != str(window_id):
            raise GuiStaleStateError("GUI state belongs to a different window; call gui_state again")

        normalized: list[tuple[dict[str, Any], Any | None]] = []
        uses_coordinates = False
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
            elif kind in _COORDINATE_ACTIONS:
                uses_coordinates = True
            normalized.append((action, locator))

        if uses_coordinates:
            await self._assert_window_geometry_unchanged(record.window)

        results: list[dict[str, Any]] = []
        for index, (action, locator) in enumerate(normalized):
            result = await self._backend.perform_action(record.window, locator, action)
            results.append({"index": index, "type": action["type"], **(result or {})})

        return {
            "backend": self._backend.name,
            "state_id": state_id,
            "window_id": str(window_id),
            "state_consumed": True,
            "actions": results,
        }

    async def _assert_window_geometry_unchanged(self, observed: dict[str, Any]) -> None:
        current = await self._backend.list_windows()
        observed_id = str(observed.get("id"))
        match = next(
            (item for item in current.get("windows", []) if str(item.get("id")) == observed_id),
            None,
        )
        if match is None:
            raise GuiStaleStateError("Target window is no longer available; call gui_state again")
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
