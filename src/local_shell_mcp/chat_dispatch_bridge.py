from __future__ import annotations

import importlib
import os
import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Any

from .chat_dispatch_watchdog import (
    DEFAULT_WATCHDOG_INTERVAL_S,
    ensure_chat_dispatch_watchdog,
    inspect_chat_dispatch_watchdog,
    stop_chat_dispatch_watchdog,
)

_BACKEND_LOCK = threading.Lock()
_BACKEND_CACHE: tuple[Path, ModuleType] | None = None
_REQUIRED_BACKEND_API = (
    "ChatDispatchStore",
    "TERMINAL_JOB_STATES",
    "chat_dispatch_status",
    "ensure_chat_dispatch_worker",
    "job_payload",
)


def _is_path_within_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        pass

    # Windows may resolve the imported module through a long path while the
    # configured checkout retains an equivalent 8.3 alias (or vice versa).
    # Compare existing ancestors by filesystem identity rather than weakening
    # the fence to a case-folded or prefix-based string comparison.
    for parent in path.parents:
        try:
            if os.path.samefile(parent, root):
                return True
        except OSError:
            continue
    return False


def _resolve_lws_repo(settings: Any) -> Path:
    configured = str(getattr(settings, "chat_dispatch_lws_repo", None) or "").strip()
    if configured:
        candidates = [Path(os.path.expandvars(os.path.expanduser(configured)))]
    else:
        workspace = Path(settings.workspace_root).resolve()
        candidates = [
            workspace / "tools" / "localshell-web-supervisor",
            workspace / "localshell-web-supervisor",
        ]
    for candidate in candidates:
        root = candidate.resolve()
        if (root / "src" / "lws" / "chat_dispatch.py").is_file():
            return root
    rendered = ", ".join(str(path) for path in candidates)
    raise RuntimeError(
        "Chat dispatch backend was not found. Configure "
        "LOCAL_SHELL_MCP_CHAT_DISPATCH_LWS_REPO or install localshell-web-supervisor under "
        f"the workspace tools directory. Checked: {rendered}"
    )


def _load_backend(settings: Any) -> tuple[Path, ModuleType]:
    global _BACKEND_CACHE
    root = _resolve_lws_repo(settings)
    with _BACKEND_LOCK:
        if _BACKEND_CACHE is not None and _BACKEND_CACHE[0] == root:
            return _BACKEND_CACHE
        src = str(root / "src")
        if src not in sys.path:
            sys.path.insert(0, src)
        module = importlib.import_module("lws.chat_dispatch")
        module_path = Path(getattr(module, "__file__", "")).resolve()
        if not _is_path_within_root(module_path, root):
            raise RuntimeError(
                f"Refusing chat dispatch backend loaded from unexpected path: {module_path}"
            )
        missing = [name for name in _REQUIRED_BACKEND_API if not hasattr(module, name)]
        if missing:
            raise RuntimeError(
                "The localshell-web-supervisor chat dispatch backend is incompatible; "
                f"missing API: {', '.join(missing)}"
            )
        _BACKEND_CACHE = (root, module)
        return _BACKEND_CACHE


def _bounded_max_windows(settings: Any, requested: int | None) -> int:
    value = int(
        getattr(settings, "chat_dispatch_max_windows", 4)
        if requested is None
        else requested
    )
    if value < 1 or value > 16:
        raise ValueError("max_windows must be between 1 and 16")
    return value


def _bounded_idle_close(settings: Any, requested: int | None) -> int:
    value = int(
        getattr(settings, "chat_dispatch_idle_close_s", 90)
        if requested is None
        else requested
    )
    if value < 1 or value > 86400:
        raise ValueError("idle_close_s must be between 1 and 86400 seconds")
    return value


def manage_chat_dispatch(
    settings: Any,
    *,
    action: str = "enqueue",
    prompt: str | None = None,
    conversation_key: str | None = None,
    conversation_url: str | None = None,
    project_url: str | None = None,
    dispatch_id: str | None = None,
    idempotency_key: str | None = None,
    max_windows: int | None = None,
    idle_close_s: int | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Model-facing synchronous control plane for the short-lived LWS chat dispatcher."""

    normalized = str(action or "enqueue").strip().lower()
    if normalized not in {
        "enqueue",
        "status",
        "cancel",
        "ensure",
        "watchdog_start",
        "watchdog_status",
        "watchdog_stop",
    }:
        raise ValueError(
            "action must be one of: enqueue, status, cancel, ensure, "
            "watchdog_start, watchdog_status, watchdog_stop"
        )
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    if normalized == "enqueue":
        if not str(idempotency_key or "").strip():
            raise ValueError(
                "idempotency_key is required for action=enqueue so an interrupted tool call "
                "cannot create a duplicate browser side effect"
            )
        if conversation_url and project_url:
            raise ValueError("provide conversation_url or project_url, not both")
        if project_url and not str(conversation_key or "").strip():
            raise ValueError(
                "conversation_key is required with project_url so retries resolve the same child"
            )
    watchdog_interval = int(
        getattr(settings, "chat_dispatch_watchdog_interval_s", DEFAULT_WATCHDOG_INTERVAL_S)
    )
    if normalized == "watchdog_status":
        return {"action": normalized, "watchdog": inspect_chat_dispatch_watchdog(settings)}
    if normalized == "watchdog_start":
        # Fail before creating a resident process if the configured LWS checkout is missing
        # or exposes an incompatible dispatch contract.
        _load_backend(settings)
        return {
            "action": normalized,
            "watchdog": ensure_chat_dispatch_watchdog(
                settings,
                interval_s=watchdog_interval,
            ),
        }
    if normalized == "watchdog_stop":
        return {"action": normalized, "watchdog": stop_chat_dispatch_watchdog(settings)}
    root, backend = _load_backend(settings)
    windows = _bounded_max_windows(settings, max_windows)
    idle = _bounded_idle_close(settings, idle_close_s)

    if normalized == "enqueue":
        if prompt is None or not str(prompt).strip():
            raise ValueError("prompt is required for action=enqueue")
        with backend.ChatDispatchStore() as store:
            job = store.enqueue(
                prompt=prompt,
                conversation_key=conversation_key,
                conversation_url=conversation_url,
                project_url=project_url,
                dispatch_key=idempotency_key,
                max_windows=windows,
                idle_close_s=idle,
            )
            payload = backend.job_payload(job)
            should_start = job.state not in backend.TERMINAL_JOB_STATES
        worker = (
            backend.ensure_chat_dispatch_worker(
                max_windows=windows,
                idle_close_s=idle,
                repo_root=root,
            )
            if should_start
            else {"started": False, "detail": "dispatch is already terminal"}
        )
        watchdog = (
            ensure_chat_dispatch_watchdog(settings, interval_s=watchdog_interval)
            if bool(getattr(settings, "chat_dispatch_watchdog_enabled", True))
            else {"started": False, "status": "disabled"}
        )
        return {
            "action": normalized,
            "dispatch": payload,
            "worker": worker,
            "watchdog": watchdog,
            "message": "dispatch durably queued" if should_start else "existing idempotent dispatch returned",
        }

    if normalized == "status":
        return {
            "action": normalized,
            "watchdog": inspect_chat_dispatch_watchdog(settings),
            **backend.chat_dispatch_status(dispatch_id=dispatch_id, limit=limit),
        }

    if normalized == "cancel":
        if not dispatch_id:
            raise ValueError("dispatch_id is required for action=cancel")
        with backend.ChatDispatchStore() as store:
            job = store.cancel(dispatch_id)
            payload = backend.job_payload(job)
        worker = backend.ensure_chat_dispatch_worker(
            max_windows=windows,
            idle_close_s=idle,
            repo_root=root,
        )
        return {
            "action": normalized,
            "dispatch": payload,
            "worker": worker,
            "message": "dispatch cancelled before ambiguous/sent side effects",
        }

    worker = backend.ensure_chat_dispatch_worker(
        max_windows=windows,
        idle_close_s=idle,
        repo_root=root,
    )
    watchdog = (
        ensure_chat_dispatch_watchdog(settings, interval_s=watchdog_interval)
        if bool(getattr(settings, "chat_dispatch_watchdog_enabled", True))
        else {"started": False, "status": "disabled"}
    )
    return {
        "action": normalized,
        "worker": worker,
        "watchdog": watchdog,
        **backend.chat_dispatch_status(dispatch_id=dispatch_id, limit=limit),
    }
