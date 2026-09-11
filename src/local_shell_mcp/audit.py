from __future__ import annotations

import contextlib
import gzip
import hashlib
import io
import json
import math
import os
import re
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
from .state_store import get_state_store, state_lock

_AUDIT_ENABLED: ContextVar[bool] = ContextVar("local_shell_mcp_audit_enabled", default=True)
_AUDIT_ARCHIVE_ENABLED: ContextVar[bool] = ContextVar(
    "local_shell_mcp_audit_archive_enabled", default=True
)
_AUDIT_CALL_ID: ContextVar[str] = ContextVar("local_shell_mcp_audit_call_id", default="")
_AUDIT_CALL_STATE: ContextVar[dict[str, Any] | None] = ContextVar(
    "local_shell_mcp_audit_call_state", default=None
)
_AUDIT_LOCK = threading.Lock()
_AUDIT_PREVIEW_STRING_CHARS = 2_000
_AUDIT_PREVIEW_ITEMS = 100
_AUDIT_INLINE_VALUE_BYTES = 16 * 1024
_AUDIT_PAYLOAD_PRUNE_GRACE_S = 300
_AUDIT_MAINTENANCE_INTERVAL_S = _AUDIT_PAYLOAD_PRUNE_GRACE_S
_AUDIT_LAST_MAINTENANCE: dict[str, float] = {}
_AUDIT_PRESSURE_BACKOFF_UNTIL: dict[str, float] = {}
_AUDIT_PAYLOAD_DIRECTORY = "audit-payloads"
_AUDIT_PAYLOAD_BYTES_KEY = f"{_AUDIT_PAYLOAD_DIRECTORY}/total-bytes"
_AUDIT_PAYLOAD_MARKER = "$local_shell_mcp_audit_payload"
_AUDIT_PAYLOAD_VERSION = 1
_AUDIT_ARCHIVE_DIRECTORY = "audit-archive"
_AUDIT_ARCHIVE_INDEX_KEY = f"{_AUDIT_ARCHIVE_DIRECTORY}/index.json"
_AUDIT_ARCHIVE_VERSION = 1
_AUDIT_ARCHIVE_ZSTD_LEVEL = 12
_AUDIT_ARCHIVE_MAX_PAYLOAD_MATERIALIZATION_BYTES = 16 * 1024 * 1024
_AUDIT_ARCHIVE_KEY_RE = re.compile(r"^audit-archive/[0-9A-Za-z][0-9A-Za-z._-]*\.jsonl\.zst$")
_AUDIT_GENERATED_ARCHIVE_KEY_RE = re.compile(
    r"^audit-archive/(?P<start_ms>\d+)-(?P<end_ms>\d+)-\d+-[0-9a-f]{8}\.jsonl\.zst$"
)
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


def _parse_payload_byte_count(raw: bytes | None) -> int | None:
    if raw is None:
        return None
    try:
        value = int(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        return None
    return value if value >= 0 else None


def _scan_state_payload_bytes() -> int:
    store = get_state_store()
    prefix = f"{_AUDIT_PAYLOAD_DIRECTORY}/"
    return sum(
        store.size_bytes(key) or 0 for key in store.list_keys(prefix) if key.endswith(".json.gz")
    )


def _state_payload_bytes() -> int:
    store = get_state_store()
    current = _parse_payload_byte_count(store.read_bytes(_AUDIT_PAYLOAD_BYTES_KEY))
    if current is not None:
        return current
    with state_lock(_AUDIT_PAYLOAD_BYTES_KEY):
        current = _parse_payload_byte_count(store.read_bytes(_AUDIT_PAYLOAD_BYTES_KEY))
        if current is None:
            current = _scan_state_payload_bytes()
            store.write_bytes(_AUDIT_PAYLOAD_BYTES_KEY, str(current).encode("ascii"))
        return current


def _set_state_payload_bytes(value: int) -> None:
    get_state_store().write_bytes(_AUDIT_PAYLOAD_BYTES_KEY, str(max(0, int(value))).encode("ascii"))


def _write_payload(value: Any) -> dict[str, Any]:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    if get_settings().state_backend != "file":
        store = get_state_store()
        key = f"{_AUDIT_PAYLOAD_DIRECTORY}/{digest}.json.gz"
        compressed = gzip.compress(raw, compresslevel=6, mtime=0)
        with state_lock(_AUDIT_PAYLOAD_BYTES_KEY):
            current = _parse_payload_byte_count(store.read_bytes(_AUDIT_PAYLOAD_BYTES_KEY))
            counter_needs_write = current is None
            if current is None:
                current = _scan_state_payload_bytes()
            existing_size = store.size_bytes(key)
            if existing_size is None:
                next_total = current + len(compressed)
                store.write_bytes(_AUDIT_PAYLOAD_BYTES_KEY, str(next_total).encode("ascii"))
                try:
                    store.write_bytes(key, compressed)
                except Exception:
                    with contextlib.suppress(Exception):
                        store.write_bytes(_AUDIT_PAYLOAD_BYTES_KEY, str(current).encode("ascii"))
                    raise
            elif counter_needs_write:
                store.write_bytes(_AUDIT_PAYLOAD_BYTES_KEY, str(current).encode("ascii"))
        return {
            _AUDIT_PAYLOAD_MARKER: {
                "version": _AUDIT_PAYLOAD_VERSION,
                "sha256": digest,
                "bytes": len(raw),
            },
            "preview": _preview_audit_value(value),
        }
    path = _payload_path(digest)
    created = not path.exists()
    if created:
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
    if created:
        _AUDIT_PRESSURE_BACKOFF_UNTIL.pop(os.fspath(get_settings().audit_log_path), None)
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


def _payload_declared_bytes(value: dict[str, Any]) -> int:
    metadata = value[_AUDIT_PAYLOAD_MARKER]
    assert isinstance(metadata, dict)
    return int(metadata["bytes"])


def _unavailable_payload(value: dict[str, Any], digest: str, detail: str) -> dict[str, Any]:
    return {
        "error": "Audit payload is unavailable",
        "payload_id": digest,
        "detail": detail,
        "preview": value.get("preview"),
    }


def _resolve_payload_reference(value: Any, *, full: bool, max_bytes: int | None = None) -> Any:
    if not _is_payload_reference(value):
        return value
    if not full:
        return value.get("preview")
    digest = _payload_digest(value)
    if max_bytes is not None:
        max_bytes = max(0, int(max_bytes))
        declared_bytes = _payload_declared_bytes(value)
        if declared_bytes > max_bytes:
            return _unavailable_payload(
                value,
                digest,
                f"payload exceeds safe materialization limit ({declared_bytes} > {max_bytes} bytes)",
            )
    try:
        if get_settings().state_backend == "file":
            encoded = _payload_path(digest).read_bytes()
        else:
            encoded = get_state_store().read_bytes(f"{_AUDIT_PAYLOAD_DIRECTORY}/{digest}.json.gz")
            if encoded is None:
                raise FileNotFoundError(digest)
        if max_bytes is None:
            raw = gzip.decompress(encoded)
        else:
            with gzip.GzipFile(fileobj=io.BytesIO(encoded), mode="rb") as payload_stream:
                raw = payload_stream.read(max_bytes + 1)
            if len(raw) > max_bytes:
                return _unavailable_payload(
                    value,
                    digest,
                    f"payload exceeds safe materialization limit ({max_bytes} bytes)",
                )
        return json.loads(raw)
    except (
        OSError,
        EOFError,
        UnicodeDecodeError,
        gzip.BadGzipFile,
        json.JSONDecodeError,
        zlib.error,
    ) as exc:
        return _unavailable_payload(value, digest, str(exc))


def _resolve_record_payloads(record: dict[str, Any], *, full: bool) -> dict[str, Any]:
    return {name: _resolve_payload_reference(value, full=full) for name, value in record.items()}


def _collect_payload_ids(record: Any, destination: set[str]) -> None:
    if not isinstance(record, dict):
        return
    for value in record.values():
        if _is_payload_reference(value):
            destination.add(_payload_digest(value))


def _prune_payload_store(log_path: Path) -> bool:
    directory = _payload_directory_path(log_path)
    if not directory.is_dir():
        return True
    referenced: set[str] = set()
    try:
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return False
    for line in lines:
        with contextlib.suppress(json.JSONDecodeError):
            _collect_payload_ids(json.loads(line), referenced)
    prune_before = time.time() - _AUDIT_PAYLOAD_PRUNE_GRACE_S
    complete = True
    for payload in directory.glob("*.json.gz"):
        digest = payload.name.removesuffix(".json.gz")
        if digest in referenced:
            continue
        try:
            if payload.stat().st_mtime > prune_before:
                continue
            payload.unlink()
        except OSError:
            complete = False
    for temporary in directory.glob(".*.tmp"):
        try:
            if temporary.stat().st_mtime > prune_before:
                continue
            temporary.unlink()
        except OSError:
            complete = False
    return complete


def _payload_file_size(digest: str, log_path: Path | None = None) -> int:
    try:
        return _payload_path(digest, log_path).stat().st_size
    except OSError:
        return 0


def _audit_log_bytes(log_path: Path) -> int:
    try:
        return log_path.stat().st_size
    except OSError:
        return 0


def _audit_storage_bytes(log_path: Path) -> int:
    """Return the cheap on-disk size used by retained audit data."""

    total = _audit_log_bytes(log_path)
    directory = _payload_directory_path(log_path)
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if not entry.name.endswith(".json.gz"):
                    continue
                try:
                    if entry.is_file():
                        total += entry.stat().st_size
                except OSError:
                    continue
    except OSError:
        pass
    return total


def _audit_pressure_backoff_active(log_path: Path) -> bool:
    key = os.fspath(log_path)
    deadline = _AUDIT_PRESSURE_BACKOFF_UNTIL.get(key)
    if deadline is None:
        return False
    if time.monotonic() < deadline:
        return True
    _AUDIT_PRESSURE_BACKOFF_UNTIL.pop(key, None)
    return False


def _audit_storage_limit_exceeded(log_path: Path, max_bytes: int) -> bool:
    if max_bytes <= 0:
        return False
    if _audit_log_bytes(log_path) > max_bytes:
        return True
    if _audit_pressure_backoff_active(log_path):
        return False
    return _audit_storage_bytes(log_path) > max_bytes


def _audit_maintenance_due(log_path: Path) -> bool:
    now = time.monotonic()
    previous = _AUDIT_LAST_MAINTENANCE.get(os.fspath(log_path))
    return previous is None or now - previous >= _AUDIT_MAINTENANCE_INTERVAL_S


def _mark_audit_maintenance(log_path: Path) -> None:
    _AUDIT_LAST_MAINTENANCE[os.fspath(log_path)] = time.monotonic()


def _update_audit_pressure_backoff(log_path: Path, max_bytes: int) -> None:
    key = os.fspath(log_path)
    if max_bytes > 0 and _audit_storage_bytes(log_path) > max_bytes:
        _AUDIT_PRESSURE_BACKOFF_UNTIL[key] = time.monotonic() + _AUDIT_PAYLOAD_PRUNE_GRACE_S
    else:
        _AUDIT_PRESSURE_BACKOFF_UNTIL.pop(key, None)


def _encode_audit_record(record: dict[str, Any]) -> bytes:
    return (json.dumps(record, ensure_ascii=False, default=str) + "\n").encode("utf-8")


def _bounded_preview_record(record: dict[str, Any], max_bytes: int) -> bytes:
    preview = _resolve_record_payloads(record, full=False)
    payload_ids: set[str] = set()
    _collect_payload_ids(record, payload_ids)
    if payload_ids:
        preview["audit_payloads_omitted"] = "full payload omitted from live audit log"
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


def _parse_retention_lines(
    raw_lines: list[bytes],
) -> tuple[list[tuple[bytes, dict[str, Any] | None, set[str]]], set[str]]:
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
    return parsed, all_referenced


def _select_retention_lines(
    parsed: list[tuple[bytes, dict[str, Any] | None, set[str]]],
    payload_sizes: dict[str, int],
    max_bytes: int,
) -> list[tuple[int, bytes]] | None:
    total_bytes = sum(len(raw_line) for raw_line, _record, _payload_ids in parsed) + sum(
        payload_sizes.values()
    )
    if total_bytes <= max_bytes:
        return None

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
    return selected


def _archive_directory_path(log_path: Path) -> Path:
    return log_path.parent / _AUDIT_ARCHIVE_DIRECTORY


def _archive_index_path(log_path: Path) -> Path:
    return _archive_directory_path(log_path) / "index.json"


def _archive_index_payload(entries: list[dict[str, Any]]) -> bytes:
    return json.dumps(
        {"version": _AUDIT_ARCHIVE_VERSION, "archives": entries},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _validated_archive_key(value: Any) -> str | None:
    if not isinstance(value, str) or "\\" in value:
        return None
    return value if _AUDIT_ARCHIVE_KEY_RE.fullmatch(value) else None


def _validated_archive_entry(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    key = _validated_archive_key(value.get("key"))
    start_ts = value.get("start_ts")
    end_ts = value.get("end_ts")
    if (
        key is None
        or isinstance(start_ts, bool)
        or not isinstance(start_ts, (int, float))
        or not math.isfinite(float(start_ts))
        or float(start_ts) < 0
        or isinstance(end_ts, bool)
        or not isinstance(end_ts, (int, float))
        or not math.isfinite(float(end_ts))
        or float(end_ts) < float(start_ts)
    ):
        return None
    normalized: dict[str, Any] = {
        "key": key,
        "start_ts": float(start_ts),
        "end_ts": float(end_ts),
    }
    for name in ("records", "raw_bytes", "compressed_bytes"):
        item = value.get(name)
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            return None
        normalized[name] = item
    return normalized


def _validated_archive_directory(log_path: Path, *, create: bool = False) -> Path:
    directory = _archive_directory_path(log_path)
    if directory.is_symlink():
        raise ValueError("audit archive directory must not be a symlink")
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise ValueError("audit archive directory must not be a symlink")
    resolved_parent = log_path.parent.resolve()
    resolved_directory = directory.resolve(strict=False)
    if resolved_directory.parent != resolved_parent:
        raise ValueError("audit archive directory escapes audit log directory")
    return directory


def _archive_file_path(log_path: Path, key: str) -> Path:
    validated = _validated_archive_key(key)
    if validated is None:
        raise ValueError(f"invalid audit archive key: {key!r}")
    directory = _validated_archive_directory(log_path)
    candidate = log_path.parent / validated
    resolved_directory = directory.resolve()
    resolved_candidate = candidate.resolve(strict=False)
    if resolved_candidate.parent != resolved_directory:
        raise ValueError(f"audit archive path escapes archive directory: {key!r}")
    return candidate


def _parse_archive_index(raw: bytes | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []
    if not isinstance(payload, dict) or payload.get("version") != _AUDIT_ARCHIVE_VERSION:
        return []
    archives = payload.get("archives")
    if not isinstance(archives, list):
        return []
    validated = [_validated_archive_entry(entry) for entry in archives]
    return [entry for entry in validated if entry is not None]


def _recovered_archive_entry(key: str, compressed_bytes: int) -> dict[str, Any] | None:
    match = _AUDIT_GENERATED_ARCHIVE_KEY_RE.fullmatch(key)
    if match is None or compressed_bytes < 0:
        return None
    start_ms = int(match.group("start_ms"))
    end_ms = int(match.group("end_ms"))
    if end_ms < start_ms:
        return None
    return _archive_metadata(
        key=key,
        start_ts=start_ms / 1000,
        end_ts=end_ms / 1000,
        records=0,
        raw_bytes=0,
        compressed_bytes=compressed_bytes,
    )


def _reconcile_archive_entries(
    indexed: list[dict[str, Any]], discovered: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    indexed_by_key = {entry["key"]: entry for entry in indexed}
    reconciled: list[dict[str, Any]] = []
    for recovered in discovered:
        current = indexed_by_key.get(recovered["key"])
        if current is None:
            reconciled.append(recovered)
            continue
        reconciled.append(
            {
                **current,
                "start_ts": recovered["start_ts"],
                "end_ts": recovered["end_ts"],
                "compressed_bytes": recovered["compressed_bytes"],
            }
        )
    return reconciled


def _discover_file_archives(log_path: Path) -> list[dict[str, Any]]:
    try:
        directory = _validated_archive_directory(log_path)
        prune_before = time.time() - _AUDIT_PAYLOAD_PRUNE_GRACE_S
        with os.scandir(directory) as entries:
            discovered: list[dict[str, Any]] = []
            for entry in entries:
                if not entry.is_file(follow_symlinks=False):
                    continue
                if entry.name.startswith(".") and entry.name.endswith(".tmp"):
                    try:
                        if entry.stat(follow_symlinks=False).st_mtime <= prune_before:
                            os.unlink(entry.path)
                    except OSError:
                        pass
                    continue
                key = f"{_AUDIT_ARCHIVE_DIRECTORY}/{entry.name}"
                try:
                    size = entry.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
                recovered = _recovered_archive_entry(key, size)
                if recovered is not None:
                    discovered.append(recovered)
            return discovered
    except (FileNotFoundError, NotADirectoryError, OSError, ValueError):
        return []


def _load_file_archive_index(log_path: Path) -> list[dict[str, Any]]:
    try:
        indexed = _parse_archive_index(_archive_index_path(log_path).read_bytes())
    except OSError:
        indexed = []
    return _reconcile_archive_entries(indexed, _discover_file_archives(log_path))


def _write_file_archive_index(log_path: Path, entries: list[dict[str, Any]]) -> None:
    _validated_archive_directory(log_path, create=True)
    path = _archive_index_path(log_path)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        _write_private_bytes(temporary, _archive_index_payload(entries))
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)


def _load_state_archive_index() -> list[dict[str, Any]]:
    store = get_state_store()
    indexed = _parse_archive_index(store.read_bytes(_AUDIT_ARCHIVE_INDEX_KEY))
    discovered: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for key in store.list_keys(f"{_AUDIT_ARCHIVE_DIRECTORY}/"):
        if key == _AUDIT_ARCHIVE_INDEX_KEY or key in seen_keys:
            continue
        seen_keys.add(key)
        size = store.size_bytes(key)
        if size is None:
            continue
        recovered = _recovered_archive_entry(key, size)
        if recovered is not None:
            discovered.append(recovered)
    return _reconcile_archive_entries(indexed, discovered)


def _write_state_archive_index(entries: list[dict[str, Any]]) -> None:
    get_state_store().write_bytes(_AUDIT_ARCHIVE_INDEX_KEY, _archive_index_payload(entries))


def _archive_time_bounds(
    parsed: list[tuple[bytes, dict[str, Any] | None, set[str]]], indexes: list[int]
) -> tuple[float, float]:
    timestamps: list[float] = []
    for index in indexes:
        record = parsed[index][1]
        if not isinstance(record, dict):
            continue
        raw_timestamp = record.get("ts")
        if isinstance(raw_timestamp, bool) or not isinstance(raw_timestamp, (int, float)):
            continue
        timestamp = float(raw_timestamp)
        if math.isfinite(timestamp) and timestamp > 0:
            timestamps.append(timestamp)
    now = time.time()
    return (min(timestamps), max(timestamps)) if timestamps else (now, now)


def _archive_key(start_ts: float, end_ts: float) -> str:
    start_ms = max(0, int(start_ts * 1000))
    end_ms = max(start_ms, int(end_ts * 1000))
    return (
        f"{_AUDIT_ARCHIVE_DIRECTORY}/{start_ms:013d}-{end_ms:013d}-"
        f"{time.time_ns()}-{uuid.uuid4().hex[:8]}.jsonl.zst"
    )


def _encode_archive_line_with_budget(
    raw_line: bytes,
    record: dict[str, Any] | None,
    remaining_payload_bytes: int,
) -> tuple[bytes, int]:
    if record is None:
        envelope: dict[str, Any] = {
            "version": _AUDIT_ARCHIVE_VERSION,
            "raw": raw_line.decode("utf-8", errors="replace").rstrip("\r\n"),
        }
    else:
        payloads: dict[str, Any] = {}
        for name, value in record.items():
            if not _is_payload_reference(value):
                continue
            declared_bytes = _payload_declared_bytes(value)
            payloads[name] = _resolve_payload_reference(
                value,
                full=True,
                max_bytes=remaining_payload_bytes,
            )
            resolved = payloads[name]
            if declared_bytes > remaining_payload_bytes:
                continue
            if (
                isinstance(resolved, dict)
                and resolved.get("error") == "Audit payload is unavailable"
                and resolved.get("payload_id") == _payload_digest(value)
            ):
                remaining_payload_bytes = 0
                continue
            materialized_bytes = len(
                json.dumps(
                    resolved,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
            )
            remaining_payload_bytes = max(0, remaining_payload_bytes - materialized_bytes)
        envelope = {
            "version": _AUDIT_ARCHIVE_VERSION,
            "record": record,
        }
        if payloads:
            envelope["payloads"] = payloads
    encoded = (
        json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), default=str) + "\n"
    ).encode("utf-8")
    return encoded, remaining_payload_bytes


def _encode_archive_line(raw_line: bytes, record: dict[str, Any] | None) -> bytes:
    encoded, _remaining_payload_bytes = _encode_archive_line_with_budget(
        raw_line,
        record,
        _AUDIT_ARCHIVE_MAX_PAYLOAD_MATERIALIZATION_BYTES,
    )
    return encoded


def _archive_metadata(
    *, key: str, start_ts: float, end_ts: float, records: int, raw_bytes: int, compressed_bytes: int
) -> dict[str, Any]:
    return {
        "key": key,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "records": records,
        "raw_bytes": raw_bytes,
        "compressed_bytes": compressed_bytes,
    }


def _write_file_archive(
    log_path: Path,
    parsed: list[tuple[bytes, dict[str, Any] | None, set[str]]],
    indexes: list[int],
) -> dict[str, Any] | None:
    if not indexes:
        return None
    start_ts, end_ts = _archive_time_bounds(parsed, indexes)
    key = _archive_key(start_ts, end_ts)
    path = _archive_file_path(log_path, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    raw_bytes = 0
    remaining_payload_bytes = _AUDIT_ARCHIVE_MAX_PAYLOAD_MATERIALIZATION_BYTES
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        from . import audit_archive_codec

        with (
            os.fdopen(descriptor, "wb") as destination,
            audit_archive_codec.stream_writer(
                destination, level=_AUDIT_ARCHIVE_ZSTD_LEVEL
            ) as compressor,
        ):
            for index in indexes:
                raw_line, record, _payload_ids = parsed[index]
                encoded, remaining_payload_bytes = _encode_archive_line_with_budget(
                    raw_line,
                    record,
                    remaining_payload_bytes,
                )
                compressor.write(encoded)
                raw_bytes += len(encoded)
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)
    return _archive_metadata(
        key=key,
        start_ts=start_ts,
        end_ts=end_ts,
        records=len(indexes),
        raw_bytes=raw_bytes,
        compressed_bytes=path.stat().st_size,
    )


def _write_state_archive(
    parsed: list[tuple[bytes, dict[str, Any] | None, set[str]]], indexes: list[int]
) -> dict[str, Any] | None:
    if not indexes:
        return None
    start_ts, end_ts = _archive_time_bounds(parsed, indexes)
    key = _archive_key(start_ts, end_ts)
    from . import audit_archive_codec

    destination = io.BytesIO()
    raw_bytes = 0
    remaining_payload_bytes = _AUDIT_ARCHIVE_MAX_PAYLOAD_MATERIALIZATION_BYTES
    with audit_archive_codec.stream_writer(
        destination, level=_AUDIT_ARCHIVE_ZSTD_LEVEL
    ) as compressor:
        for index in indexes:
            raw_line, record, _payload_ids = parsed[index]
            encoded, remaining_payload_bytes = _encode_archive_line_with_budget(
                raw_line,
                record,
                remaining_payload_bytes,
            )
            compressor.write(encoded)
            raw_bytes += len(encoded)
    compressed = destination.getvalue()
    get_state_store().write_bytes(key, compressed)
    return _archive_metadata(
        key=key,
        start_ts=start_ts,
        end_ts=end_ts,
        records=len(indexes),
        raw_bytes=raw_bytes,
        compressed_bytes=len(compressed),
    )


def _archive_bytes(entries: list[dict[str, Any]]) -> int:
    return sum(entry["compressed_bytes"] for entry in entries)


def _prune_file_archives(
    log_path: Path, entries: list[dict[str, Any]], max_archive_bytes: int
) -> list[dict[str, Any]]:
    ordered = sorted(entries, key=lambda entry: (entry["end_ts"], entry["key"]))
    total = _archive_bytes(ordered)
    retained: list[dict[str, Any]] = []
    for entry in ordered:
        if total <= max_archive_bytes:
            retained.append(entry)
            continue
        try:
            _archive_file_path(log_path, entry["key"]).unlink(missing_ok=True)
        except (OSError, ValueError):
            retained.append(entry)
        else:
            total -= entry["compressed_bytes"]
    _write_file_archive_index(log_path, retained)
    return retained


def _prune_state_archives(
    entries: list[dict[str, Any]], max_archive_bytes: int
) -> list[dict[str, Any]]:
    retained = sorted(entries, key=lambda entry: (entry["end_ts"], entry["key"]))
    total = _archive_bytes(retained)
    store = get_state_store()
    while retained and total > max_archive_bytes:
        oldest = retained.pop(0)
        total -= oldest["compressed_bytes"]
        store.delete(str(oldest["key"]))
    _write_state_archive_index(retained)
    return retained


def _archived_source_indexes(
    parsed: list[tuple[bytes, dict[str, Any] | None, set[str]]], selected: list[tuple[int, bytes]]
) -> list[int]:
    selected_by_index = dict(selected)
    return [
        index
        for index, (raw_line, record, _payload_ids) in enumerate(parsed)
        if (index not in selected_by_index or selected_by_index[index] != raw_line)
        and not (isinstance(record, dict) and record.get("audit_payloads_omitted"))
    ]


def _enforce_audit_storage_limit(
    log_path: Path, max_bytes: int, max_archive_bytes: int | None = None
) -> bool:
    if max_archive_bytes is None:
        max_archive_bytes = get_settings().max_audit_archive_bytes
    if max_bytes <= 0 or not log_path.exists():
        return True
    try:
        raw_lines = log_path.read_bytes().splitlines(keepends=True)
    except OSError:
        return False

    parsed, all_referenced = _parse_retention_lines(raw_lines)
    payload_sizes = {digest: _payload_file_size(digest, log_path) for digest in all_referenced}
    selected = _select_retention_lines(parsed, payload_sizes, max_bytes)
    archive_entries = _load_file_archive_index(log_path)
    if selected is None:
        if archive_entries and _archive_bytes(archive_entries) > max_archive_bytes:
            _prune_file_archives(log_path, archive_entries, max_archive_bytes)
        return _prune_payload_store(log_path)

    archived_indexes = _archived_source_indexes(parsed, selected)
    if _AUDIT_ARCHIVE_ENABLED.get() and max_archive_bytes > 0 and archived_indexes:
        from . import audit_archive_codec

        try:
            archive = _write_file_archive(log_path, parsed, archived_indexes)
        except (OSError, audit_archive_codec.ZstdError):
            return False
        if archive is not None:
            archive_entries.append(archive)
            try:
                _write_file_archive_index(log_path, archive_entries)
            except (OSError, ValueError):
                with contextlib.suppress(OSError, ValueError):
                    _archive_file_path(log_path, archive["key"]).unlink(missing_ok=True)
                return False

    temporary = log_path.with_name(f".{log_path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        _write_private_bytes(temporary, b"".join(raw_line for _, raw_line in selected))
        os.replace(temporary, log_path)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)
    if archive_entries:
        _prune_file_archives(log_path, archive_entries, max_archive_bytes)
    return _prune_payload_store(log_path)


def _enforce_state_audit_storage_limit(
    max_bytes: int, max_archive_bytes: int | None = None
) -> None:
    if max_archive_bytes is None:
        max_archive_bytes = get_settings().max_audit_archive_bytes
    if max_bytes <= 0:
        return
    store = get_state_store()
    raw_lines = (store.read_bytes("audit.jsonl") or b"").splitlines(keepends=True)
    parsed, all_referenced = _parse_retention_lines(raw_lines)
    payload_sizes = {
        digest: store.size_bytes(f"{_AUDIT_PAYLOAD_DIRECTORY}/{digest}.json.gz") or 0
        for digest in all_referenced
    }
    selected = _select_retention_lines(parsed, payload_sizes, max_bytes)
    archive_entries = _load_state_archive_index()
    if selected is not None:
        archived_indexes = _archived_source_indexes(parsed, selected)
        if _AUDIT_ARCHIVE_ENABLED.get() and max_archive_bytes > 0 and archived_indexes:
            archive = _write_state_archive(parsed, archived_indexes)
            if archive is not None:
                archive_entries.append(archive)
                try:
                    _write_state_archive_index(archive_entries)
                except Exception:
                    with contextlib.suppress(Exception):
                        store.delete(archive["key"])
                    raise
        store.write_bytes("audit.jsonl", b"".join(raw_line for _, raw_line in selected))
        _, all_referenced = _parse_retention_lines([raw_line for _index, raw_line in selected])
    if archive_entries and _archive_bytes(archive_entries) > max_archive_bytes:
        _prune_state_archives(archive_entries, max_archive_bytes)
    prefix = f"{_AUDIT_PAYLOAD_DIRECTORY}/"
    retained_payload_bytes = 0
    with state_lock(_AUDIT_PAYLOAD_BYTES_KEY):
        for key in store.list_keys(prefix):
            if not key.endswith(".json.gz"):
                continue
            digest = key.removeprefix(prefix).removesuffix(".json.gz")
            if digest not in all_referenced:
                store.delete(key)
                continue
            retained_payload_bytes += store.size_bytes(key) or 0
        _set_state_payload_bytes(retained_payload_bytes)


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
def suppress_audit_archives() -> Iterator[None]:
    token = _AUDIT_ARCHIVE_ENABLED.set(False)
    try:
        yield
    finally:
        _AUDIT_ARCHIVE_ENABLED.reset(token)


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
    with _AUDIT_LOCK:
        if settings.state_backend != "file":
            store = get_state_store()
            with state_lock("audit.jsonl"):
                record = {
                    "id": uuid.uuid4().hex,
                    "ts": time.time(),
                    "event": event,
                    **{name: _serialize_audit_value(value) for name, value in fields.items()},
                }
                encoded = json.dumps(record, ensure_ascii=False, default=str) + "\n"
                log_bytes = store.append_bytes("audit.jsonl", encoded.encode("utf-8"))
                retention_needed = log_bytes + _state_payload_bytes() > settings.max_audit_log_bytes
                maintenance_due = _audit_maintenance_due(settings.audit_log_path)
                if retention_needed or maintenance_due:
                    _enforce_state_audit_storage_limit(settings.max_audit_log_bytes)
                    _mark_audit_maintenance(settings.audit_log_path)
            return
        record = {
            "id": uuid.uuid4().hex,
            "ts": time.time(),
            "event": event,
            **{name: _serialize_audit_value(value) for name, value in fields.items()},
        }
        encoded = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        path: Path = settings.audit_log_path
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as f:
            f.write(encoded)
            f.flush()
        with contextlib.suppress(OSError):
            path.chmod(0o600)
        retention_needed = _audit_storage_limit_exceeded(path, settings.max_audit_log_bytes)
        maintenance_due = settings.max_audit_log_bytes > 0 and _audit_maintenance_due(path)
        if retention_needed or maintenance_due:
            maintained = _enforce_audit_storage_limit(path, settings.max_audit_log_bytes)
            if maintained:
                _mark_audit_maintenance(path)
                _update_audit_pressure_backoff(path, settings.max_audit_log_bytes)


_TOOL_OPERATION_GROUPS: dict[str, frozenset[str]] = {
    "files": frozenset(
        {
            "file_list",
            "file_tree",
            "file_glob",
            "file_grep",
            "file_read",
            "image_view",
            "file_write",
            "file_edit",
            "file_delete",
            "file_patch",
            "link_create",
            "link_list",
            "link_revoke",
            "secret_scan",
            # Historical names remain classified for retained audit records.
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
            "create_file_link",
            "list_file_links",
            "revoke_file_link",
        }
    ),
    "shell": frozenset(
        {
            "run_shell",
            "run_python",
            "shell_start",
            "shell_send",
            "shell_read",
            "shell_stop",
            "shell_list",
            "run_shell_tool",
            "run_python_tool",
            "shell_kill",
        }
    ),
    "jobs": frozenset({"job_start", "job_list", "job_tail", "job_stop", "job_retry"}),
    "browser": frozenset(
        {
            "browser_session",
            "browser_snapshot",
            "browser_act",
            "browser_run_script",
            "browser_capture_tool",
            "browser_get_text_tool",
            "playwright_run_script_tool",
        }
    ),
    "remote": frozenset(
        {
            "remote_manage",
            "remote_transfer",
        }
    ),
    "agent": frozenset(
        {
            "environment_get",
            "skill_list",
            "skill_load",
            "skill_read",
            "environment_info",
            "skills_list",
            "skill_read_file",
            "mcp_manage",
            "mcp_tool_search",
            "mcp_tool_inspect",
            "mcp_tool_call",
            "session_manage",
            "plan_manage",
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
    if event.startswith(("download_", "file_link_")):
        return "files"
    if event.startswith("transfer_"):
        return "remote"
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
        name: value for name, value in record.items() if name not in {"id", "ts", "parent_call_id"}
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


_AUDIT_SUMMARY_FIELDS = frozenset(
    {
        "id",
        "call_id",
        "ts",
        "event",
        "node",
        "machine",
        "operation",
        "tool",
        "session",
        "command",
        "purpose",
        "ok",
        "paired",
        "status",
        "duration_ms",
        "error",
        "error_type",
    }
)


def _audit_summary_entry(row: dict[str, Any]) -> dict[str, Any]:
    return {name: value for name, value in row.items() if name in _AUDIT_SUMMARY_FIELDS}


def _read_audit_records() -> list[dict[str, Any]]:
    settings = get_settings()
    max_bytes = max(1, settings.max_audit_log_bytes)
    if settings.state_backend == "file":
        path = settings.audit_log_path
        if not path.exists():
            return []
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
                handle.readline()
            raw = handle.read(max_bytes)
    else:
        raw = get_state_store().read_bytes("audit.jsonl") or b""
        if len(raw) > max_bytes:
            raw = raw[-max_bytes:]
            newline = raw.find(b"\n")
            if newline >= 0:
                raw = raw[newline + 1 :]

    records: list[dict[str, Any]] = []
    for line in raw.splitlines():
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _matching_audit_rows(
    records: list[dict[str, Any]],
    *,
    node: str | None,
    event: str | None,
    operation: str | None,
    session: str | None,
    search: str | None,
    start_ts: float | None,
    end_ts: float | None,
) -> list[dict[str, Any]]:
    needle = (search or "").casefold().strip()
    node_filter = (node or "").casefold().strip()
    event_filter = (event or "").casefold().strip()
    operation_filter = (operation or "").casefold().strip()
    session_filter = (session or "").casefold().strip()
    matched: list[dict[str, Any]] = []
    for row in _coalesce_audit_records(records):
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
    return matched


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
    summary_only: bool = False,
) -> dict[str, Any]:
    """Read, pair, filter, and sort the bounded live audit log."""

    bounded_limit = max(1, min(int(limit), 2_000))
    records = _read_audit_records()
    preview_records = [_resolve_record_payloads(record, full=False) for record in records]
    matched = _matching_audit_rows(
        preview_records,
        node=node,
        event=event,
        operation=operation,
        session=session,
        search=search,
        start_ts=start_ts,
        end_ts=end_ts,
    )
    reverse = sort.lower() != "asc"
    matched.sort(key=lambda item: float(item.get("ts") or 0), reverse=reverse)
    total = len(matched)
    visible = matched[:bounded_limit]
    return {
        "entries": [
            _audit_summary_entry(row) if summary_only else _public_audit_entry(row)
            for row in visible
        ],
        "count": min(total, bounded_limit),
        "total_matched": total,
    }


def _find_audit_row(records: list[dict[str, Any]], entry_id: str) -> dict[str, Any] | None:
    return next(
        (row for row in _coalesce_audit_records(records) if str(row.get("id") or "") == entry_id),
        None,
    )


def get_audit_entry(entry_id: str, *, full: bool = True) -> dict[str, Any]:
    """Return one live audit entry, optionally materializing hot-store payloads."""

    normalized = str(entry_id).strip()
    if not normalized:
        raise ValueError("audit entry id is required")
    records = _read_audit_records()
    preview_records = [_resolve_record_payloads(record, full=False) for record in records]
    selected = _find_audit_row(preview_records, normalized)
    if selected is None:
        raise ValueError(f"Unknown audit entry: {normalized}")
    if not full:
        return _public_audit_entry(selected)

    materialized_records = list(preview_records)
    for index in selected[_AUDIT_SOURCE_INDEXES]:
        materialized_records[index] = _resolve_record_payloads(records[index], full=True)
    materialized = _find_audit_row(materialized_records, normalized)
    return _public_audit_entry(materialized or selected)
