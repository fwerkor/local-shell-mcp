from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from pathlib import Path

from .settings import get_settings

_TODO_LOCK = threading.Lock()


class TodoConflictError(RuntimeError):
    pass


def _todo_path() -> Path:
    path = get_settings().state_dir / "todos.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def todo_read() -> dict:
    path = _todo_path()
    if not path.exists():
        return {"revision": 0, "updated_at": None, "todos": []}
    settings = get_settings()
    size = path.stat().st_size
    if size > settings.max_todo_bytes:
        raise ValueError(f"Refusing to read {size} todo bytes; max is {settings.max_todo_bytes}")
    return json.loads(path.read_text(encoding="utf-8"))


def todo_write(todos: list[dict], expected_revision: int | None = None) -> dict:
    settings = get_settings()
    if len(todos) > settings.max_todos:
        raise ValueError(f"Refusing to write {len(todos)} todos; max is {settings.max_todos}")
    normalized = []
    for idx, item in enumerate(todos):
        normalized.append(
            {
                "id": str(item.get("id") or idx + 1),
                "content": str(item.get("content") or ""),
                "status": str(item.get("status") or "pending"),
                "priority": str(item.get("priority") or "medium"),
            }
        )

    with _TODO_LOCK:
        current = todo_read()
        current_revision = int(current.get("revision") or 0)
        if expected_revision is not None and expected_revision != current_revision:
            raise TodoConflictError(
                f"Todo list changed from revision {expected_revision} to {current_revision}; reload before saving"
            )
        payload = {
            "revision": current_revision + 1,
            "updated_at": time.time(),
            "todos": normalized,
        }
        encoded = json.dumps(payload, ensure_ascii=False, indent=2)
        encoded_bytes = len(encoded.encode("utf-8"))
        if encoded_bytes > settings.max_todo_bytes:
            raise ValueError(f"Refusing to write {encoded_bytes} todo bytes; max is {settings.max_todo_bytes}")
        path = _todo_path()
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            tmp.write_text(encoded, encoding="utf-8")
            tmp.replace(path)
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
        return payload
