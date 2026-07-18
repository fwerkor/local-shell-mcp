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
_AUDIT_CALL_ID: ContextVar[str] = ContextVar("local_shell_mcp_audit_call_id", default="")
_AUDIT_LOCK = threading.Lock()
_AUDIT_MAX_STRING = 2_000

_AUDIT_FAILURE_STATUSES = frozenset(
    {"error", "failed", "failure", "not_found", "timeout", "timed_out", "cancelled"}
)

_LEGACY_TOOL_DETAIL_EVENTS = frozenset(
    {
        "tool_call_purpose",
        "tool_error",
        "tool_timeout",
        "run_shell_start",
        "run_shell_end",
        "shell_start",
        "shell_send",
        "shell_read",
        "shell_kill",
        "job_start",
        "job_stop",
        "job_retry",
    }
)


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


@contextmanager
def audit_call_context(call_id: str) -> Iterator[None]:
    """Associate implementation-level audit records with one public MCP call."""

    token = _AUDIT_CALL_ID.set(str(call_id))
    try:
        yield
    finally:
        _AUDIT_CALL_ID.reset(token)


def audit(event: str, **fields: Any) -> None:
    if not _AUDIT_ENABLED.get():
        return
    settings = get_settings()
    parent_call_id = _AUDIT_CALL_ID.get()
    if parent_call_id and "parent_call_id" not in fields:
        fields["parent_call_id"] = parent_call_id
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


_TOOL_OPERATION_GROUPS: dict[str, frozenset[str]] = {
    "files": frozenset(
        {
            "search",
            "fetch",
            "list_files",
            "tree_view",
            "glob_search",
            "grep_search",
            "read_file",
            "view_image",
            "write_file",
            "edit_file",
            "delete_file_or_dir",
            "apply_patch",
            "secret_scan",
        }
    ),
    "shell": frozenset(
        {
            "run_shell_tool",
            "run_python_tool",
            "shell_start",
            "shell_send",
            "shell_read",
            "shell_kill",
            "shell_list",
        }
    ),
    "jobs": frozenset({"job_start", "job_list", "job_tail", "job_stop", "job_retry"}),
    "transfer": frozenset(
        {"create_file_link", "list_file_links", "revoke_file_link", "transfer_path"}
    ),
    "browser": frozenset(
        {"browser_capture_tool", "browser_get_text_tool", "playwright_run_script_tool"}
    ),
    "remote": frozenset(
        {
            "remote_invite",
            "remote_list_machines",
            "remote_revoke_machine",
            "remote_rename_machine",
        }
    ),
    "agent": frozenset(
        {
            "environment_info",
            "skills_list",
            "skill_load",
            "skill_read_file",
            "todo_read_tool",
            "todo_write_tool",
            "audit_tail",
        }
    ),
}
_TOOL_OPERATION_BY_NAME = {
    tool: operation
    for operation, tools in _TOOL_OPERATION_GROUPS.items()
    for tool in tools
}


def _operation_type(record: dict[str, Any]) -> str:
    tool = str(record.get("tool") or "")
    if tool in _TOOL_OPERATION_BY_NAME:
        return _TOOL_OPERATION_BY_NAME[tool]

    event = str(record.get("event") or "")
    if event.startswith(("run_shell_", "shell_")):
        return "shell"
    if event.startswith("job_"):
        return "jobs"
    if event.startswith(("browser_", "playwright_")):
        return "browser"
    if event.startswith("remote_"):
        return "remote"
    if event.startswith(("download_", "file_link_", "transfer_")):
        return "transfer"
    return "other"


def _record_node(record: dict[str, Any]) -> str:
    return str(record.get("machine") or record.get("node") or "local")


def _record_session(record: dict[str, Any]) -> str:
    return str(record.get("session") or "")


def _call_input(record: dict[str, Any]) -> Any:
    arguments = record.get("arguments")
    if not isinstance(arguments, dict):
        return None
    keyword_args = arguments.get("keyword_args")
    return keyword_args if keyword_args is not None else arguments


def _call_match_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(record.get("tool") or ""),
        _record_node(record),
        _record_session(record),
    )


def _new_call_entry(record: dict[str, Any], index: int) -> dict[str, Any]:
    call_id = str(record.get("call_id") or "")
    entry: dict[str, Any] = {
        "id": f"call:{call_id}" if call_id else f"legacy-call:{record.get('ts', 0)}:{index}",
        "ts": float(record.get("ts") or 0),
        "event": "mcp_tool_call",
        "tool": str(record.get("tool") or "unknown"),
        "node": _record_node(record),
        "operation": _operation_type(record),
        "paired": False,
        "status": "running",
        "source_events": ["mcp_tool_call_start"],
    }
    if call_id:
        entry["call_id"] = call_id
    session = _record_session(record)
    if session:
        entry["session"] = session
    call_input = _call_input(record)
    if call_input is not None:
        entry["input"] = call_input
    return entry


def _explicit_audit_result_ok(value: Any) -> bool | None:
    if not isinstance(value, dict):
        return None
    direct = value.get("ok") if isinstance(value.get("ok"), bool) else None
    status = value.get("status")
    if isinstance(status, str) and status.casefold() in _AUDIT_FAILURE_STATUSES:
        return False
    if direct is False:
        return False
    nested = _explicit_audit_result_ok(value.get("data"))
    if nested is not None:
        return nested
    return direct


def audit_result_ok(value: Any) -> bool:
    explicit = _explicit_audit_result_ok(value)
    return True if explicit is None else explicit


def _call_record_ok(record: dict[str, Any]) -> bool | None:
    direct = record.get("ok") if isinstance(record.get("ok"), bool) else None
    if direct is False:
        return False
    nested = _explicit_audit_result_ok(record.get("result"))
    return nested if nested is not None else direct


def _finish_call_entry(entry: dict[str, Any], record: dict[str, Any]) -> None:
    ok = _call_record_ok(record)
    entry["paired"] = True
    entry["ok"] = ok
    entry["status"] = "success" if ok is True else "failed" if ok is False else "completed"
    entry["source_events"] = ["mcp_tool_call_start", "mcp_tool_call_end"]
    if "duration_ms" in record:
        entry["duration_ms"] = record["duration_ms"]
    if "result" in record:
        entry["output"] = record["result"]
    for name in ("error", "error_type"):
        if record.get(name):
            entry[name] = record[name]


def _unpaired_end_entry(record: dict[str, Any], index: int) -> dict[str, Any]:
    call_id = str(record.get("call_id") or "")
    entry: dict[str, Any] = {
        "id": f"call:{call_id}" if call_id else f"legacy-end:{record.get('ts', 0)}:{index}",
        "ts": float(record.get("ts") or 0),
        "event": "mcp_tool_call",
        "tool": str(record.get("tool") or "unknown"),
        "node": _record_node(record),
        "operation": _operation_type(record),
        "paired": False,
        "status": "unpaired",
        "source_events": ["mcp_tool_call_end"],
    }
    if call_id:
        entry["call_id"] = call_id
    session = _record_session(record)
    if session:
        entry["session"] = session
    if "duration_ms" in record:
        entry["duration_ms"] = record["duration_ms"]
    if "result" in record:
        entry["output"] = record["result"]
    ok = _call_record_ok(record)
    if ok is not None:
        entry["ok"] = ok
    for name in ("error", "error_type"):
        if name in record:
            entry[name] = record[name]
    return entry


def _coalesce_audit_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pending_by_id: dict[str, dict[str, Any]] = {}
    pending_legacy: dict[tuple[str, str, str], list[dict[str, Any]]] = {}

    for index, record in enumerate(records):
        event = str(record.get("event") or "")
        if event == "auth_ok":
            continue
        if record.get("parent_call_id"):
            continue
        if event in _LEGACY_TOOL_DETAIL_EVENTS and (
            pending_by_id or any(pending_legacy.values())
        ):
            continue
        if event == "mcp_tool_call_start":
            entry = _new_call_entry(record, index)
            rows.append(entry)
            call_id = str(record.get("call_id") or "")
            if call_id:
                pending_by_id[call_id] = entry
            else:
                pending_legacy.setdefault(_call_match_key(record), []).append(entry)
            continue
        if event == "mcp_tool_call_end":
            call_id = str(record.get("call_id") or "")
            entry = pending_by_id.pop(call_id, None) if call_id else None
            if entry is None and not call_id:
                pending = pending_legacy.get(_call_match_key(record), [])
                if pending:
                    entry = pending.pop(0)
            if entry is None:
                rows.append(_unpaired_end_entry(record, index))
            else:
                _finish_call_entry(entry, record)
            continue

        rows.append(
            {
                **record,
                "id": str(record.get("id") or f"record:{record.get('ts', 0)}:{index}"),
                "node": _record_node(record),
                "operation": _operation_type(record),
            }
        )

    return rows


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
    """Read, pair, filter, and sort the bounded JSONL audit log for the human UI."""

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

    records: list[dict[str, Any]] = []
    for line in raw.splitlines():
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(record, dict):
            records.append(record)

    rows = _coalesce_audit_records(records)
    needle = (search or "").casefold().strip()
    node_filter = (node or "").casefold().strip()
    event_filter = (event or "").casefold().strip()
    operation_filter = (operation or "").casefold().strip()
    session_filter = (session or "").casefold().strip()
    matched: list[dict[str, Any]] = []

    for row in rows:
        ts = float(row.get("ts") or 0)
        if start_ts is not None and ts < start_ts:
            continue
        if end_ts is not None and ts > end_ts:
            continue
        if node_filter and node_filter != str(row.get("node") or "local").casefold():
            continue
        event_text = " ".join(
            [str(row.get("event") or ""), *map(str, row.get("source_events") or [])]
        )
        if event_filter and event_filter not in event_text.casefold():
            continue
        if operation_filter and operation_filter != str(row.get("operation") or "").casefold():
            continue
        if session_filter and session_filter != str(row.get("session") or "").casefold():
            continue
        if needle and needle not in json.dumps(row, ensure_ascii=False, default=str).casefold():
            continue
        matched.append(row)

    reverse = sort.lower() != "asc"
    matched.sort(key=lambda item: float(item.get("ts") or 0), reverse=reverse)
    total = len(matched)
    return {
        "entries": matched[:bounded_limit],
        "count": min(total, bounded_limit),
        "total_matched": total,
    }
