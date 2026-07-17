from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from .settings import get_settings

_AUDIT_ENABLED: ContextVar[bool] = ContextVar("local_shell_mcp_audit_enabled", default=True)
_AUDIT_LOCK = threading.Lock()
_AUDIT_MAX_STRING = 2_000


def _format_audit_text(value: str) -> str:
    if len(value) > _AUDIT_MAX_STRING:
        return value[:_AUDIT_MAX_STRING] + "…<truncated>"
    return value


def _serialize_audit_value(value: Any) -> Any:
    if isinstance(value, str):
        return _format_audit_text(value)
    if isinstance(value, dict):
        return {
            str(name): _serialize_audit_value(item)
            for name, item in list(value.items())[:100]
        }
    if isinstance(value, (list, tuple)):
        return [_serialize_audit_value(item) for item in list(value)[:100]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _format_audit_text(repr(value))


def _trim_audit_log(path: Path, max_bytes: int) -> None:
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
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_bytes(data)
        with contextlib.suppress(OSError):
            tmp.chmod(0o600)
        tmp.replace(path)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


@contextmanager
def suppress_audit() -> Iterator[None]:
    """Exclude direct human UI activity from the MCP audit stream."""

    token = _AUDIT_ENABLED.set(False)
    try:
        yield
    finally:
        _AUDIT_ENABLED.reset(token)


def audit(event: str, **fields: Any) -> None:
    if not _AUDIT_ENABLED.get():
        return
    settings = get_settings()
    record = {
        "ts": time.time(),
        "event": _format_audit_text(event),
        **{name: _serialize_audit_value(value) for name, value in fields.items()},
    }
    path: Path = settings.audit_log_path
    encoded = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    with _AUDIT_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        _trim_audit_log(path, settings.max_audit_log_bytes)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as f:
            f.write(encoded)
            f.flush()
        with contextlib.suppress(OSError):
            path.chmod(0o600)


def _operation_type(record: dict[str, Any]) -> str:
    event = str(record.get("event") or "")
    tool = str(record.get("tool") or "")
    value = tool or event
    for prefix in ("remote_", "mcp_tool_call_", "tool_", "oauth_", "shell_", "git_"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break
    return value.split("_", 1)[0] if value else "other"


def query_audit(
    *,
    limit: int = 200,
    node: str | None = None,
    event: str | None = None,
    operation: str | None = None,
    session: str | None = None,
    search: str | None = None,
    start_ts: float | None = None,
    end_ts: float | None = None,
    sort: str = "desc",
) -> dict[str, Any]:
    """Read, filter, and sort the bounded JSONL audit log for the human UI."""

    settings = get_settings()
    path = settings.audit_log_path
    bounded_limit = max(1, min(int(limit), 2_000))
    if not path.exists():
        return {"entries": [], "count": 0, "total_matched": 0}

    max_bytes = max(1, min(settings.max_audit_tail_bytes * 4, settings.max_audit_log_bytes))
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(size - max_bytes)
            handle.readline()
        raw = handle.read(max_bytes)

    rows: list[dict[str, Any]] = []
    needle = (search or "").casefold().strip()
    node_filter = (node or "").casefold().strip()
    event_filter = (event or "").casefold().strip()
    operation_filter = (operation or "").casefold().strip()
    session_filter = (session or "").casefold().strip()

    for line in raw.splitlines():
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(record, dict):
            continue
        ts = float(record.get("ts") or 0)
        if start_ts is not None and ts < start_ts:
            continue
        if end_ts is not None and ts > end_ts:
            continue
        record_node = str(record.get("machine") or record.get("node") or "local")
        if node_filter and node_filter != record_node.casefold():
            continue
        record_event = str(record.get("event") or "")
        if event_filter and event_filter not in record_event.casefold():
            continue
        record_operation = _operation_type(record)
        if operation_filter and operation_filter not in record_operation.casefold():
            continue
        record_session = str(record.get("session") or "")
        if session_filter and session_filter != record_session.casefold():
            continue
        if needle and needle not in json.dumps(record, ensure_ascii=False, default=str).casefold():
            continue
        rows.append(
            {
                **record,
                "node": record_node,
                "operation": record_operation,
            }
        )

    reverse = sort.lower() != "asc"
    rows.sort(key=lambda item: float(item.get("ts") or 0), reverse=reverse)
    total = len(rows)
    return {
        "entries": rows[:bounded_limit],
        "count": min(total, bounded_limit),
        "total_matched": total,
    }
