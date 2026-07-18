from __future__ import annotations

import contextlib
import gzip
import hashlib
import json
import os
import threading
import time
import uuid
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from .settings import get_settings

_AUDIT_ENABLED: ContextVar[bool] = ContextVar("local_shell_mcp_audit_enabled", default=True)
_AUDIT_CALL_ID: ContextVar[str] = ContextVar("local_shell_mcp_audit_call_id", default="")
_AUDIT_CALL_STATE: ContextVar[dict[str, Any] | None] = ContextVar(
    "local_shell_mcp_audit_call_state", default=None
)
_AUDIT_LOCK = threading.Lock()
_AUDIT_PREVIEW_STRING_CHARS = 2_000
_AUDIT_PREVIEW_ITEMS = 100
_AUDIT_INLINE_VALUE_BYTES = 16 * 1024
_AUDIT_PAYLOAD_PRUNE_GRACE_S = 300
_AUDIT_PAYLOAD_DIRECTORY = "audit-payloads"
_AUDIT_PAYLOAD_MARKER = "$local_shell_mcp_audit_payload"
_AUDIT_PAYLOAD_VERSION = 1
_AUDIT_SOURCE_INDEXES = "_audit_source_indexes"

_AUDIT_FAILURE_STATUSES = frozenset(
    {"error", "failed", "failure", "not_found", "timeout", "timed_out", "cancelled"}
)
_NESTED_LIFECYCLE_EVENTS = frozenset(
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
    if len(value) > _AUDIT_PREVIEW_STRING_CHARS:
        return value[:_AUDIT_PREVIEW_STRING_CHARS] + "…<preview>"
    return value


def _jsonable_audit_value(value: Any) -> Any:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return {str(name): _jsonable_audit_value(item) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable_audit_value(item) for item in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return repr(value)


def _preview_audit_value(value: Any) -> Any:
    if isinstance(value, str):
        return _format_audit_text(value)
    if isinstance(value, dict):
        return {
            str(name): _preview_audit_value(item)
            for name, item in list(value.items())[:_AUDIT_PREVIEW_ITEMS]
        }
    if isinstance(value, (list, tuple)):
        return [_preview_audit_value(item) for item in list(value)[:_AUDIT_PREVIEW_ITEMS]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _format_audit_text(repr(value))


def _payload_directory_path(log_path: Path | None = None) -> Path:
    audit_log_path = log_path or get_settings().audit_log_path
    return audit_log_path.parent / _AUDIT_PAYLOAD_DIRECTORY


def _payload_directory(log_path: Path | None = None) -> Path:
    directory = _payload_directory_path(log_path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _payload_path(digest: str, log_path: Path | None = None) -> Path:
    return _payload_directory(log_path) / f"{digest}.json.gz"


def _write_private_bytes(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
        handle.flush()


def _write_payload(value: Any) -> dict[str, Any]:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    path = _payload_path(digest)
    if not path.exists():
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            _write_private_bytes(
                temporary,
                gzip.compress(raw, compresslevel=6, mtime=0),
            )
            os.replace(temporary, path)
        finally:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)
    return {
        _AUDIT_PAYLOAD_MARKER: {
            "version": _AUDIT_PAYLOAD_VERSION,
            "sha256": digest,
            "bytes": len(raw),
        },
        "preview": _preview_audit_value(value),
    }


def _serialize_audit_value(value: Any) -> Any:
    serialized = _jsonable_audit_value(value)
    encoded = json.dumps(
        serialized,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    retention_budget = max(1, get_settings().max_audit_log_bytes)
    inline_limit = min(_AUDIT_INLINE_VALUE_BYTES, max(128, retention_budget // 2))
    if len(encoded) <= inline_limit:
        return serialized
    return _write_payload(serialized)


def _is_payload_reference(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if set(value) != {_AUDIT_PAYLOAD_MARKER, "preview"}:
        return False
    metadata = value.get(_AUDIT_PAYLOAD_MARKER)
    if not isinstance(metadata, dict):
        return False
    if set(metadata) != {"version", "sha256", "bytes"}:
        return False
    digest = metadata.get("sha256")
    return (
        metadata.get("version") == _AUDIT_PAYLOAD_VERSION
        and isinstance(metadata.get("bytes"), int)
        and metadata["bytes"] >= 0
        and isinstance(digest, str)
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    )


def _payload_digest(value: dict[str, Any]) -> str:
    metadata = value[_AUDIT_PAYLOAD_MARKER]
    assert isinstance(metadata, dict)
    return str(metadata["sha256"])


def _resolve_payload_reference(value: Any, *, full: bool) -> Any:
    if not _is_payload_reference(value):
        return value
    if not full:
        return value.get("preview")
    digest = _payload_digest(value)
    try:
        raw = gzip.decompress(_payload_path(digest).read_bytes())
        return json.loads(raw)
    except (OSError, EOFError, gzip.BadGzipFile, json.JSONDecodeError, zlib.error) as exc:
        return {
            "error": "Audit payload is unavailable",
            "payload_id": digest,
            "detail": str(exc),
            "preview": value.get("preview"),
        }


def _resolve_record_payloads(record: dict[str, Any], *, full: bool) -> dict[str, Any]:
    return {name: _resolve_payload_reference(value, full=full) for name, value in record.items()}


def _collect_payload_ids(record: Any, destination: set[str]) -> None:
    if not isinstance(record, dict):
        return
    for value in record.values():
        if _is_payload_reference(value):
            destination.add(_payload_digest(value))


def _prune_payload_store(log_path: Path) -> None:
    directory = _payload_directory_path(log_path)
    if not directory.is_dir():
        return
    referenced: set[str] = set()
    try:
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return
    for line in lines:
        with contextlib.suppress(json.JSONDecodeError):
            _collect_payload_ids(json.loads(line), referenced)
    prune_before = time.time() - _AUDIT_PAYLOAD_PRUNE_GRACE_S
    for payload in directory.glob("*.json.gz"):
        digest = payload.name.removesuffix(".json.gz")
        if digest in referenced:
            continue
        try:
            if payload.stat().st_mtime > prune_before:
                continue
            payload.unlink()
        except OSError:
            continue


def _payload_file_size(digest: str, log_path: Path | None = None) -> int:
    try:
        return _payload_path(digest, log_path).stat().st_size
    except OSError:
        return 0


def _encode_audit_record(record: dict[str, Any]) -> bytes:
    return (json.dumps(record, ensure_ascii=False, default=str) + "\n").encode("utf-8")


def _bounded_preview_record(record: dict[str, Any], max_bytes: int) -> bytes:
    preview = _resolve_record_payloads(record, full=False)
    encoded = _encode_audit_record(preview)
    if len(encoded) <= max_bytes:
        return encoded
    essential = {
        name: preview[name]
        for name in ("id", "ts", "event", "tool", "call_id", "ok", "error", "error_type")
        if name in preview
    }
    essential["audit_payloads_omitted"] = "record exceeded audit retention limit"
    encoded = _encode_audit_record(essential)
    return encoded if len(encoded) <= max_bytes else b""


def _retention_units(
    parsed: list[tuple[bytes, dict[str, Any] | None, set[str]]],
) -> list[list[tuple[int, bytes, dict[str, Any] | None, set[str]]]]:
    units: list[list[tuple[int, bytes, dict[str, Any] | None, set[str]]]] = []
    call_units: dict[str, list[tuple[int, bytes, dict[str, Any] | None, set[str]]]] = {}
    for index, (raw_line, record, payload_ids) in enumerate(parsed):
        call_id = ""
        if isinstance(record, dict):
            if record.get("event") in {"mcp_tool_call_start", "mcp_tool_call_end"}:
                call_id = str(record.get("call_id") or "")
            else:
                call_id = str(record.get("parent_call_id") or "")
        if call_id:
            unit = call_units.get(call_id)
            if unit is None:
                unit = []
                call_units[call_id] = unit
                units.append(unit)
            unit.append((index, raw_line, record, payload_ids))
        else:
            units.append([(index, raw_line, record, payload_ids)])
    units.sort(key=lambda unit: max(item[0] for item in unit))
    return units


def _bounded_preview_unit(
    unit: list[tuple[int, bytes, dict[str, Any] | None, set[str]]],
    max_bytes: int,
) -> list[tuple[int, bytes]]:
    if not unit:
        return []
    per_record = max(1, max_bytes // len(unit))
    bounded: list[tuple[int, bytes]] = []
    for index, _raw_line, record, _payload_ids in unit:
        if record is None:
            continue
        encoded = _bounded_preview_record(record, per_record)
        if encoded:
            bounded.append((index, encoded))
    return bounded


def _enforce_audit_storage_limit(log_path: Path, max_bytes: int) -> None:
    if max_bytes <= 0 or not log_path.exists():
        return
    try:
        raw_lines = log_path.read_bytes().splitlines(keepends=True)
    except OSError:
        return

    parsed: list[tuple[bytes, dict[str, Any] | None, set[str]]] = []
    all_referenced: set[str] = set()
    for raw_line in raw_lines:
        record: dict[str, Any] | None = None
        payload_ids: set[str] = set()
        try:
            loaded = json.loads(raw_line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            loaded = None
        if isinstance(loaded, dict):
            record = loaded
            _collect_payload_ids(record, payload_ids)
            all_referenced.update(payload_ids)
        parsed.append((raw_line, record, payload_ids))

    payload_sizes = {digest: _payload_file_size(digest, log_path) for digest in all_referenced}
    total_bytes = sum(len(raw_line) for raw_line in raw_lines) + sum(payload_sizes.values())
    if total_bytes <= max_bytes:
        _prune_payload_store(log_path)
        return

    target_bytes = max(1, max_bytes // 2)
    selected: list[tuple[int, bytes]] = []
    selected_payloads: set[str] = set()
    selected_bytes = 0
    for unit in reversed(_retention_units(parsed)):
        unit_payloads = set().union(*(item[3] for item in unit))
        new_payloads = unit_payloads - selected_payloads
        added_bytes = sum(len(item[1]) for item in unit) + sum(
            payload_sizes.get(item, 0) for item in new_payloads
        )
        if selected and selected_bytes + added_bytes > target_bytes:
            break
        if not selected and added_bytes > max_bytes:
            bounded = _bounded_preview_unit(unit, max_bytes)
            if not bounded:
                continue
            selected.extend(bounded)
            selected_bytes += sum(len(raw_line) for _, raw_line in bounded)
            continue
        selected.extend((index, raw_line) for index, raw_line, _record, _payload_ids in unit)
        selected_payloads.update(unit_payloads)
        selected_bytes += added_bytes

    selected.sort(key=lambda item: item[0])
    temporary = log_path.with_name(f".{log_path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        _write_private_bytes(temporary, b"".join(raw_line for _, raw_line in selected))
        os.replace(temporary, log_path)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)
    _prune_payload_store(log_path)


def _trim_audit_log(path: Path, max_bytes: int) -> bool:
    if max_bytes <= 0 or not path.exists():
        return False
    size = path.stat().st_size
    if size <= max_bytes:
        return False

    keep_bytes = max(1, max_bytes // 2)
    with path.open("rb") as f:
        f.seek(max(0, size - keep_bytes))
        data = f.read(keep_bytes)
    first_newline = data.find(b"\n")
    if first_newline >= 0:
        data = data[first_newline + 1 :]
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        _write_private_bytes(tmp, data)
        tmp.replace(path)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
    return True


@contextmanager
def suppress_audit() -> Iterator[None]:
    """Exclude direct human UI activity from the MCP audit stream."""

    token = _AUDIT_ENABLED.set(False)
    try:
        yield
    finally:
        _AUDIT_ENABLED.reset(token)


@contextmanager
def audit_call_context(call_id: str) -> Iterator[dict[str, Any]]:
    """Associate implementation-level audit records with one public MCP call."""

    state: dict[str, Any] = {"failed": False}
    call_token = _AUDIT_CALL_ID.set(str(call_id))
    state_token = _AUDIT_CALL_STATE.set(state)
    try:
        yield state
    finally:
        _AUDIT_CALL_STATE.reset(state_token)
        _AUDIT_CALL_ID.reset(call_token)


def audit(event: str, **fields: Any) -> None:
    if not _AUDIT_ENABLED.get():
        return
    settings = get_settings()
    parent_call_id = _AUDIT_CALL_ID.get()
    if parent_call_id and "parent_call_id" not in fields:
        fields["parent_call_id"] = parent_call_id
    call_state = _AUDIT_CALL_STATE.get()
    if call_state is not None and (
        event in {"tool_error", "tool_timeout"} or fields.get("ok") is False
    ):
        call_state["failed"] = True
        if fields.get("error"):
            call_state["error"] = fields["error"]
        if fields.get("error_type"):
            call_state["error_type"] = fields["error_type"]
    path: Path = settings.audit_log_path
    with _AUDIT_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "id": uuid.uuid4().hex,
            "ts": time.time(),
            "event": event,
            **{name: _serialize_audit_value(value) for name, value in fields.items()},
        }
        encoded = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as f:
            f.write(encoded)
            f.flush()
        with contextlib.suppress(OSError):
            path.chmod(0o600)
        _enforce_audit_storage_limit(path, settings.max_audit_log_bytes)


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
    tool: operation for operation, tools in _TOOL_OPERATION_GROUPS.items() for tool in tools
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
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        value = model_dump(mode="json", by_alias=True)
    if not isinstance(value, dict):
        return None
    is_error = value.get("isError", value.get("is_error"))
    if is_error is True:
        return False
    direct = value.get("ok") if isinstance(value.get("ok"), bool) else None
    status = value.get("status")
    if isinstance(status, str) and status.casefold() in _AUDIT_FAILURE_STATUSES:
        return False
    if direct is False:
        return False
    for key in ("structuredContent", "structured_content", "data"):
        nested = _explicit_audit_result_ok(value.get(key))
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


def _nested_semantic_event(record: dict[str, Any]) -> dict[str, Any] | None:
    event = str(record.get("event") or "")
    if not event or event in _NESTED_LIFECYCLE_EVENTS:
        return None
    return {
        name: value
        for name, value in record.items()
        if name not in {"id", "ts", "parent_call_id"}
    }


def _coalesce_audit_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pending_by_id: dict[str, dict[str, Any]] = {}
    entries_by_id: dict[str, dict[str, Any]] = {}
    pending_legacy: dict[tuple[str, str, str], list[dict[str, Any]]] = {}

    for index, record in enumerate(records):
        event = str(record.get("event") or "")
        if event == "auth_ok":
            continue
        parent_call_id = str(record.get("parent_call_id") or "")
        if parent_call_id:
            parent = entries_by_id.get(parent_call_id)
            if parent is not None:
                parent[_AUDIT_SOURCE_INDEXES].append(index)
                semantic = _nested_semantic_event(record)
                if semantic is not None:
                    parent.setdefault("related_events", []).append(semantic)
                continue
            if event in _NESTED_LIFECYCLE_EVENTS:
                continue
        if event == "mcp_tool_call_start":
            entry = _new_call_entry(record, index)
            entry[_AUDIT_SOURCE_INDEXES] = [index]
            rows.append(entry)
            call_id = str(record.get("call_id") or "")
            if call_id:
                pending_by_id[call_id] = entry
                entries_by_id[call_id] = entry
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
                unpaired = _unpaired_end_entry(record, index)
                unpaired[_AUDIT_SOURCE_INDEXES] = [index]
                rows.append(unpaired)
            else:
                _finish_call_entry(entry, record)
                entry[_AUDIT_SOURCE_INDEXES].append(index)
            continue

        rows.append(
            {
                **record,
                "id": str(record.get("id") or f"record:{record.get('ts', 0)}:{index}"),
                "node": _record_node(record),
                "operation": _operation_type(record),
                _AUDIT_SOURCE_INDEXES: [index],
            }
        )

    return rows


def _public_audit_entry(row: dict[str, Any]) -> dict[str, Any]:
    return {name: value for name, value in row.items() if name != _AUDIT_SOURCE_INDEXES}


def _read_audit_records() -> list[dict[str, Any]]:
    settings = get_settings()
    path = settings.audit_log_path
    if not path.exists():
        return []

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
    return records


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

    bounded_limit = max(1, min(int(limit), 2_000))
    records = _read_audit_records()
    if not records:
        return {"entries": [], "count": 0, "total_matched": 0}

    preview_records = [_resolve_record_payloads(record, full=False) for record in records]
    rows = _coalesce_audit_records(preview_records)
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
        "entries": [_public_audit_entry(row) for row in matched[:bounded_limit]],
        "count": min(total, bounded_limit),
        "total_matched": total,
    }


def get_audit_entry(entry_id: str, *, full: bool = True) -> dict[str, Any]:
    """Return one coalesced audit entry, optionally materializing external payloads."""

    normalized = str(entry_id).strip()
    if not normalized:
        raise ValueError("audit entry id is required")
    records = _read_audit_records()
    preview_records = [_resolve_record_payloads(record, full=False) for record in records]
    preview_rows = _coalesce_audit_records(preview_records)
    selected = next(
        (row for row in preview_rows if str(row.get("id") or "") == normalized),
        None,
    )
    if selected is None:
        raise ValueError(f"Unknown audit entry: {normalized}")
    if not full:
        return _public_audit_entry(selected)

    materialized_records = list(preview_records)
    for index in selected[_AUDIT_SOURCE_INDEXES]:
        materialized_records[index] = _resolve_record_payloads(records[index], full=True)

    for row in _coalesce_audit_records(materialized_records):
        if str(row.get("id") or "") == normalized:
            return _public_audit_entry(row)
    raise ValueError(f"Unknown audit entry: {normalized}")
