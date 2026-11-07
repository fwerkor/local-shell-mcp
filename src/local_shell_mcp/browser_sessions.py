from __future__ import annotations

import asyncio
import contextlib
import os
import re
import sys
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if __package__:
    from .fs_ops import relative_display, resolve_path
else:
    from browser_external_paths import relative_display, resolve_path

_MAX_SESSIONS = 8
_IDLE_TIMEOUT_S = 3600
_MAX_ACTIONS = 50
_MAX_SNAPSHOT_ELEMENTS = 200
_MAX_SNAPSHOT_TEXT_CHARS = 100_000
_MAX_ELEMENT_METADATA_CHARS = 2_000
_MAX_BROWSER_ARTIFACT_FILES = 100
_MAX_BROWSER_ARTIFACT_BYTES = 512 * 1024 * 1024
_PROFILE_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_REF_ATTRIBUTE = "data-local-shell-mcp-ref"


@dataclass(slots=True)
class BrowserPageState:
    page_id: str
    page: Any
    refs: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class BrowserSessionState:
    session_id: str
    playwright: Any
    context: Any
    browser: Any | None
    browser_name: str
    profile_id: str | None
    created_at: float
    last_used_at: float
    pages: dict[str, BrowserPageState] = field(default_factory=dict)
    errors: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=100))
    network: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=100))
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class BrowserSessionManager:
    """Persistent Playwright sessions for high-level browser tools.

    Playwright is imported lazily so remote workers can still bootstrap on machines where the
    browser dependency is not installed until a browser tool is actually invoked.
    """

    def __init__(self, state_dir: Path) -> None:
        self._state_dir = Path(state_dir)
        self._sessions: dict[str, BrowserSessionState] = {}
        self._cleanup_pending: dict[str, BrowserSessionState] = {}
        self._closing_sessions: dict[str, BrowserSessionState] = {}
        self._starting_sessions = 0
        self._lock = asyncio.Lock()
        self._artifact_lock = asyncio.Lock()

    async def manage(
        self,
        *,
        action: str,
        session_id: str | None = None,
        browser: str = "chromium",
        headless: bool = True,
        width: int = 1440,
        height: int = 1000,
        url: str | None = None,
        wait_until: str = "domcontentloaded",
        profile_id: str | None = None,
        storage_state_path: str | None = None,
        save_storage_state_path: str | None = None,
    ) -> dict[str, Any]:
        action = action.strip().lower()
        if action == "start":
            return await self.start(
                browser=browser,
                headless=headless,
                width=width,
                height=height,
                url=url,
                wait_until=wait_until,
                profile_id=profile_id,
                storage_state_path=storage_state_path,
            )
        if action == "list":
            await self._cleanup_idle()
            async with self._lock:
                sessions = list(self._sessions.values())
                cleanup_pending = sorted(
                    self._cleanup_pending.keys() | self._closing_sessions.keys()
                )
            return {
                "sessions": [await self._session_summary(item) for item in sessions],
                "cleanup_pending": cleanup_pending,
            }
        if action == "close":
            if not session_id:
                raise ValueError("session_id is required for action=close")
            return await self.close(session_id, save_storage_state_path=save_storage_state_path)
        if action == "cleanup":
            return {"closed": await self._cleanup_idle(force=True)}
        raise ValueError("action must be start, list, close, or cleanup")

    async def start(
        self,
        *,
        browser: str = "chromium",
        headless: bool = True,
        width: int = 1440,
        height: int = 1000,
        url: str | None = None,
        wait_until: str = "domcontentloaded",
        profile_id: str | None = None,
        storage_state_path: str | None = None,
    ) -> dict[str, Any]:
        if browser not in {"chromium", "firefox", "webkit"}:
            raise ValueError("browser must be chromium, firefox, or webkit")
        if wait_until not in {"load", "domcontentloaded", "networkidle", "commit"}:
            raise ValueError("invalid wait_until")
        width = max(320, min(int(width), 7680))
        height = max(240, min(int(height), 4320))
        if profile_id and (profile_id in {".", ".."} or not _PROFILE_RE.fullmatch(profile_id)):
            raise ValueError("profile_id must match [A-Za-z0-9._-] and be at most 80 characters")
        if profile_id and storage_state_path:
            raise ValueError("profile_id and storage_state_path cannot be combined")

        await self._cleanup_idle()
        async with self._lock:
            if (
                len(self._sessions)
                + len(self._cleanup_pending)
                + len(self._closing_sessions)
                + self._starting_sessions
                >= _MAX_SESSIONS
            ):
                raise ValueError(f"at most {_MAX_SESSIONS} browser sessions may be active")
            self._starting_sessions += 1
        slot_reserved = True

        playwright = None
        browser_handle = None
        context = None
        session = None
        inserted = False
        try:
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:  # pragma: no cover - depends on worker environment.
                raise RuntimeError(
                    "Playwright is not installed in the configured Python environment; "
                    "install it with python -m pip install playwright"
                ) from exc

            playwright = await async_playwright().start()
            browser_type = getattr(playwright, browser)
            viewport = {"width": width, "height": height}
            if profile_id:
                profile_dir = self._state_dir / "browser-profiles" / profile_id
                profile_dir.mkdir(parents=True, exist_ok=True)
                context = await browser_type.launch_persistent_context(
                    user_data_dir=str(profile_dir), headless=headless, viewport=viewport
                )
            else:
                browser_handle = await browser_type.launch(headless=headless)
                context_options: dict[str, Any] = {"viewport": viewport}
                if storage_state_path:
                    state_path = resolve_path(storage_state_path, must_exist=True)
                    context_options["storage_state"] = str(state_path)
                context = await browser_handle.new_context(**context_options)

            session = BrowserSessionState(
                session_id=uuid.uuid4().hex,
                playwright=playwright,
                context=context,
                browser=browser_handle,
                browser_name=browser,
                profile_id=profile_id,
                created_at=time.time(),
                last_used_at=time.time(),
            )
            page_state = await self._ensure_page(session)
            if url:
                await page_state.page.goto(url, wait_until=wait_until, timeout=60_000)
            async with self._lock:
                self._sessions[session.session_id] = session
                self._starting_sessions -= 1
                slot_reserved = False
                inserted = True
            return await self._session_summary(session, current_page_id=page_state.page_id)
        except (Exception, asyncio.CancelledError):
            if inserted and session is not None:
                async with self._lock:
                    self._sessions.pop(session.session_id, None)
            if session is not None:
                with contextlib.suppress(Exception):
                    await self._close_state(session)
            else:
                if context is not None:
                    with contextlib.suppress(Exception):
                        await context.close()
                if browser_handle is not None:
                    with contextlib.suppress(Exception):
                        await browser_handle.close()
                if playwright is not None:
                    with contextlib.suppress(Exception):
                        await playwright.stop()
            raise
        finally:
            if slot_reserved:
                async with self._lock:
                    self._starting_sessions -= 1

    async def close(
        self, session_id: str, *, save_storage_state_path: str | None = None
    ) -> dict[str, Any]:
        async with self._lock:
            session = self._sessions.pop(session_id, None)
            if session is None:
                session = self._cleanup_pending.pop(session_id, None)
            if session is not None:
                self._closing_sessions[session.session_id] = session
        if session is None:
            raise ValueError(f"unknown browser session: {session_id}")
        save_error: BaseException | None = None
        try:
            if save_storage_state_path:
                target = resolve_path(save_storage_state_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                await session.context.storage_state(path=str(target))
        except (Exception, asyncio.CancelledError) as exc:
            save_error = exc
        try:
            await self._close_state(session)
        except (Exception, asyncio.CancelledError):
            async with self._lock:
                self._closing_sessions.pop(session.session_id, None)
                self._cleanup_pending.setdefault(session.session_id, session)
            raise
        async with self._lock:
            self._closing_sessions.pop(session.session_id, None)
        if save_error is not None:
            raise save_error
        result: dict[str, Any] = {"session_id": session_id, "closed": True}
        if save_storage_state_path:
            result["storage_state_path"] = relative_display(resolve_path(save_storage_state_path))
        return result

    async def snapshot(
        self,
        session_id: str,
        *,
        page_id: str | None = None,
        include_text: bool = True,
        screenshot: bool = True,
        full_page: bool = False,
        max_text_chars: int = _MAX_SNAPSHOT_TEXT_CHARS,
        max_elements: int = 100,
    ) -> dict[str, Any]:
        session = await self._get_session(session_id)
        async with session.lock:
            page_state = await self._select_page(session, page_id)
            page = page_state.page
            session.last_used_at = time.time()
            max_text_chars = max(0, min(int(max_text_chars), _MAX_SNAPSHOT_TEXT_CHARS))
            max_elements = max(1, min(int(max_elements), _MAX_SNAPSHOT_ELEMENTS))
            elements = await self._capture_interactive_elements(page_state, max_elements)
            text = ""
            truncated = False
            if include_text:
                bounded_text = await page.locator("body").evaluate(
                    """
(element, limit) => {
  const text = element.innerText || '';
  return {text: text.slice(0, limit), truncated: text.length > limit};
}
""",
                    max_text_chars,
                )
                text = str(bounded_text["text"])
                truncated = bool(bounded_text["truncated"])
            screenshot_path = None
            if screenshot:
                artifacts = self._state_dir / "browser-artifacts"
                artifacts.mkdir(parents=True, exist_ok=True)
                target = (
                    artifacts / f"{session_id[:12]}-{page_state.page_id}-{uuid.uuid4().hex[:8]}.png"
                )
                await page.screenshot(path=str(target), full_page=bool(full_page))
                async with self._artifact_lock:
                    await asyncio.to_thread(self._prune_artifacts, artifacts, target)
                screenshot_path = str(target)
            await self._sync_pages(session)
            return {
                "session_id": session_id,
                "page_id": page_state.page_id,
                "title": await page.title(),
                "url": page.url,
                "pages": await self._page_summaries(session),
                "text": text if include_text else None,
                "text_truncated": truncated,
                "interactive_elements": elements,
                "errors": list(session.errors)[-20:],
                "network": list(session.network)[-30:],
                "screenshot_path": screenshot_path,
            }

    async def act(
        self,
        session_id: str,
        actions: list[dict[str, Any]],
        *,
        page_id: str | None = None,
        timeout_ms: int = 30_000,
    ) -> dict[str, Any]:
        if not actions:
            raise ValueError("actions must contain at least one browser action")
        if len(actions) > _MAX_ACTIONS:
            raise ValueError(f"actions may contain at most {_MAX_ACTIONS} entries")
        timeout_ms = max(1, min(int(timeout_ms), 120_000))
        session = await self._get_session(session_id)
        results: list[dict[str, Any]] = []
        async with session.lock:
            current = await self._select_page(session, page_id)
            session.last_used_at = time.time()
            for index, raw_action in enumerate(actions):
                if not isinstance(raw_action, dict):
                    raise ValueError(f"actions[{index}] must be an object")
                action = str(raw_action.get("action") or "").strip().lower()
                if not action:
                    raise ValueError(f"actions[{index}].action is required")
                result, current = await self._run_action(
                    session, current, action, raw_action, timeout_ms
                )
                results.append({"index": index, "action": action, **result})
            await self._sync_pages(session)
            return {
                "session_id": session_id,
                "page_id": current.page_id,
                "title": await current.page.title(),
                "url": current.page.url,
                "pages": await self._page_summaries(session),
                "results": results,
            }

    async def _run_action(
        self,
        session: BrowserSessionState,
        current: BrowserPageState,
        action: str,
        data: dict[str, Any],
        timeout_ms: int,
    ) -> tuple[dict[str, Any], BrowserPageState]:
        page = current.page
        if action == "navigate":
            url = str(data.get("url") or "").strip()
            if not url:
                raise ValueError("navigate requires url")
            wait_until = str(data.get("wait_until") or "domcontentloaded")
            if wait_until not in {"load", "domcontentloaded", "networkidle", "commit"}:
                raise ValueError("invalid wait_until")
            response = await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            return {"status": response.status if response else None, "url": page.url}, current
        if action == "new_page":
            page = await session.context.new_page()
            current = self._register_page(session, page)
            url = str(data.get("url") or "").strip()
            if url:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            return {"page_id": current.page_id, "url": page.url}, current
        if action == "close_page":
            await page.close()
            await self._sync_pages(session)
            current = await self._select_page(session, None)
            return {"closed": True, "page_id": current.page_id}, current
        if action == "wait":
            milliseconds = max(0, min(int(data.get("ms", 1000)), 30_000))
            await page.wait_for_timeout(milliseconds)
            return {"waited_ms": milliseconds}, current
        if action == "wait_for_text":
            text = str(data.get("text") or "")
            if not text:
                raise ValueError("wait_for_text requires text")
            await page.get_by_text(text).first.wait_for(timeout=timeout_ms)
            return {"matched": text}, current
        if action == "wait_for_url":
            url = str(data.get("url") or "")
            if not url:
                raise ValueError("wait_for_url requires url")
            await page.wait_for_url(url, timeout=timeout_ms)
            return {"url": page.url}, current

        target = str(data.get("target") or "").strip()
        if not target:
            raise ValueError(f"{action} requires target")
        locator = self._locator(current, target)
        if action == "click":
            await locator.click(timeout=timeout_ms)
        elif action == "fill":
            await locator.fill(str(data.get("value") or ""), timeout=timeout_ms)
        elif action == "type":
            await locator.press_sequentially(str(data.get("value") or ""), timeout=timeout_ms)
        elif action == "select":
            value = data.get("value")
            if isinstance(value, list):
                await locator.select_option([str(item) for item in value], timeout=timeout_ms)
            else:
                await locator.select_option(str(value or ""), timeout=timeout_ms)
        elif action == "press":
            key = str(data.get("key") or "").strip()
            if not key:
                raise ValueError("press requires key")
            await locator.press(key, timeout=timeout_ms)
        elif action == "check":
            await locator.check(timeout=timeout_ms)
        elif action == "uncheck":
            await locator.uncheck(timeout=timeout_ms)
        elif action == "hover":
            await locator.hover(timeout=timeout_ms)
        else:
            raise ValueError(
                "unsupported browser action; use navigate, new_page, close_page, click, fill, type, "
                "select, press, check, uncheck, hover, wait, wait_for_text, or wait_for_url"
            )
        return {"target": target}, current

    async def _capture_interactive_elements(
        self, page_state: BrowserPageState, max_elements: int
    ) -> list[dict[str, Any]]:
        token = uuid.uuid4().hex[:12]
        raw = await page_state.page.locator(
            "a,button,input,textarea,select,[role='button'],[role='link'],[contenteditable='true']"
        ).evaluate_all(
            """
(elements, payload) => {
  const [attribute, token, maxElements, maxMetadataChars] = payload;
  const clip = (value) => typeof value === 'string' ? value.slice(0, maxMetadataChars) : null;
  const visible = elements.filter((element) => {
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
  }).slice(0, maxElements);
  return visible.map((element, index) => {
    const ref = `e${index + 1}`;
    const marker = `${token}-${ref}`;
    element.setAttribute(attribute, marker);
    const text = (element.innerText || element.value || element.getAttribute('aria-label') || element.getAttribute('title') || '').trim().slice(0, 500);
    return {
      ref,
      marker,
      tag: element.tagName.toLowerCase(),
      role: clip(element.getAttribute('role')),
      type: clip(element.getAttribute('type')),
      text,
      name: clip(element.getAttribute('name')),
      placeholder: clip(element.getAttribute('placeholder')),
      href: clip(element.href || null),
      disabled: Boolean(element.disabled),
    };
  });
}
""",
            [_REF_ATTRIBUTE, token, max_elements, _MAX_ELEMENT_METADATA_CHARS],
        )
        page_state.refs = {
            str(item["ref"]): f'[{_REF_ATTRIBUTE}="{item.pop("marker")}"]' for item in raw
        }
        return raw

    def _locator(self, page_state: BrowserPageState, target: str) -> Any:
        selector = page_state.refs.get(target, target)
        return page_state.page.locator(selector).first

    async def _get_session(self, session_id: str) -> BrowserSessionState:
        await self._cleanup_idle()
        async with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"unknown browser session: {session_id}")
        return session

    async def _ensure_page(self, session: BrowserSessionState) -> BrowserPageState:
        await self._sync_pages(session)
        if session.pages:
            return next(iter(session.pages.values()))
        return self._register_page(session, await session.context.new_page())

    async def _select_page(
        self, session: BrowserSessionState, page_id: str | None
    ) -> BrowserPageState:
        await self._sync_pages(session)
        if page_id:
            page = session.pages.get(page_id)
            if page is None:
                raise ValueError(f"unknown browser page: {page_id}")
            return page
        if session.pages:
            return next(reversed(session.pages.values()))
        return self._register_page(session, await session.context.new_page())

    async def _sync_pages(self, session: BrowserSessionState) -> None:
        live_pages = [page for page in session.context.pages if not page.is_closed()]
        live_ids = {id(page) for page in live_pages}
        for page_id, state in list(session.pages.items()):
            if id(state.page) not in live_ids:
                session.pages.pop(page_id, None)
        known = {id(state.page) for state in session.pages.values()}
        for page in live_pages:
            if id(page) not in known:
                self._register_page(session, page)

    def _register_page(self, session: BrowserSessionState, page: Any) -> BrowserPageState:
        for state in session.pages.values():
            if state.page is page:
                return state
        state = BrowserPageState(page_id=uuid.uuid4().hex[:12], page=page)
        session.pages[state.page_id] = state
        page.on(
            "pageerror",
            lambda error, page_id=state.page_id: session.errors.append(
                {"page_id": page_id, "kind": "pageerror", "message": str(error)}
            ),
        )
        page.on(
            "console",
            lambda message, page_id=state.page_id: self._record_console_error(
                session, page_id, message
            ),
        )
        page.on(
            "requestfailed",
            lambda request, page_id=state.page_id: session.errors.append(
                {
                    "page_id": page_id,
                    "kind": "requestfailed",
                    "method": request.method,
                    "url": request.url,
                    "failure": request.failure,
                }
            ),
        )
        page.on(
            "response",
            lambda response, page_id=state.page_id: session.network.append(
                {
                    "page_id": page_id,
                    "method": response.request.method,
                    "status": response.status,
                    "url": response.url,
                }
            ),
        )
        return state

    @staticmethod
    def _record_console_error(session: BrowserSessionState, page_id: str, message: Any) -> None:
        if message.type == "error":
            session.errors.append({"page_id": page_id, "kind": "console", "message": message.text})

    async def _session_summary(
        self, session: BrowserSessionState, *, current_page_id: str | None = None
    ) -> dict[str, Any]:
        await self._sync_pages(session)
        return {
            "session_id": session.session_id,
            "browser": session.browser_name,
            "profile_id": session.profile_id,
            "current_page_id": current_page_id,
            "pages": await self._page_summaries(session),
            "created_at": session.created_at,
            "last_used_at": session.last_used_at,
        }

    @staticmethod
    async def _page_summaries(session: BrowserSessionState) -> list[dict[str, Any]]:
        rows = []
        for state in session.pages.values():
            if state.page.is_closed():
                continue
            rows.append(
                {"page_id": state.page_id, "title": await state.page.title(), "url": state.page.url}
            )
        return rows

    async def _cleanup_idle(self, *, force: bool = False) -> int:
        cutoff = time.time() - _IDLE_TIMEOUT_S
        async with self._lock:
            stale_ids = [
                session_id
                for session_id, state in self._sessions.items()
                if force or state.last_used_at < cutoff
            ]
            stale = [self._sessions.pop(session_id) for session_id in stale_ids]
            pending = list(self._cleanup_pending.values()) if force else []
            pending_ids = {session.session_id for session in pending}
            if force:
                self._cleanup_pending.clear()
            candidates = stale + [
                session for session in pending if session.session_id not in stale_ids
            ]
            for session in candidates:
                self._closing_sessions[session.session_id] = session
        closed = 0
        first_error: Exception | None = None
        for index, session in enumerate(candidates):
            try:
                await self._close_state(session)
            except asyncio.CancelledError:
                async with self._lock:
                    self._closing_sessions.pop(session.session_id, None)
                    self._cleanup_pending.setdefault(session.session_id, session)
                    for remaining in candidates[index + 1 :]:
                        self._closing_sessions.pop(remaining.session_id, None)
                        if remaining.session_id in pending_ids:
                            self._cleanup_pending.setdefault(remaining.session_id, remaining)
                        else:
                            self._sessions.setdefault(remaining.session_id, remaining)
                raise
            except Exception as exc:
                async with self._lock:
                    self._closing_sessions.pop(session.session_id, None)
                    self._cleanup_pending.setdefault(session.session_id, session)
                if first_error is None:
                    first_error = exc
            else:
                async with self._lock:
                    self._closing_sessions.pop(session.session_id, None)
                closed += 1
        if force and first_error is not None:
            raise first_error
        return closed

    @staticmethod
    async def _close_state(session: BrowserSessionState) -> None:
        try:
            await session.context.close()
        finally:
            try:
                if session.browser is not None:
                    await session.browser.close()
            finally:
                await session.playwright.stop()

    @staticmethod
    def _prune_artifacts(directory: Path, current: Path) -> None:
        current_size = current.stat().st_size
        if current_size > _MAX_BROWSER_ARTIFACT_BYTES:
            current.unlink(missing_ok=True)
            raise ValueError("browser screenshot exceeds the artifact retention byte limit")

        others = sorted(
            (path for path in directory.glob("*.png") if path != current),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        kept_files = 1
        kept_bytes = current_size
        for path in others:
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                continue
            if (
                kept_files < _MAX_BROWSER_ARTIFACT_FILES
                and kept_bytes + size <= _MAX_BROWSER_ARTIFACT_BYTES
            ):
                kept_files += 1
                kept_bytes += size
                continue
            path.unlink(missing_ok=True)


_BROWSER_MANAGERS: dict[str, BrowserSessionManager] = {}


def get_browser_session_manager(state_dir: Path) -> BrowserSessionManager:
    key = str(Path(state_dir).resolve())
    manager = _BROWSER_MANAGERS.get(key)
    if manager is None:
        if (
            getattr(sys, "frozen", False)
            or os.environ.get("LOCAL_SHELL_MCP_BROWSER_RUNTIME") == "external"
        ):
            from .browser_external_client import ExternalBrowserSessionManager

            manager = ExternalBrowserSessionManager(Path(state_dir))
        else:
            manager = BrowserSessionManager(Path(state_dir))
        _BROWSER_MANAGERS[key] = manager
    return manager
