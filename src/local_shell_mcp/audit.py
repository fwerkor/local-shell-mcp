"""Append structured audit events to a bounded JSONL log in the server state directory."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .settings import get_settings


def _trim_audit_log(path: Path, max_bytes: int) -> None:
    """Keep the audit log bounded by retaining recent complete JSONL records."""
    if max_bytes <= 0 or not path.exists():
        return
    size = path.stat().st_size
    if size <= max_bytes:
        return

    keep_bytes = max(1, max_bytes // 2)
    with path.open("rb") as f:
        f.seek(max(0, size - keep_bytes))
        data = f.read(keep_bytes)
    first_newline = data.find(b"\n")
    if first_newline >= 0:
        data = data[first_newline + 1 :]
    path.write_bytes(data)


def audit(event: str, **fields: Any) -> None:
    """Append one structured audit record and trim the log before it can grow without bound."""
    settings = get_settings()
    record = {
        "ts": time.time(),
        "event": event,
        **fields,
    }
    path: Path = settings.audit_log_path
    path.parent.mkdir(parents=True, exist_ok=True)
    _trim_audit_log(path, settings.max_audit_log_bytes)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
