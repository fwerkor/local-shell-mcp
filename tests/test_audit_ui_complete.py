from __future__ import annotations

import gzip
import json
import os
import stat
import time
from pathlib import Path

import pytest

import local_shell_mcp.audit as audit_module
import local_shell_mcp.audit_archive_codec as audit_archive_codec
from local_shell_mcp.settings import get_settings


def _configure(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES", "100")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES", "400")
    get_settings.cache_clear()


def test_audit_call_context_marks_nested_records(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    with audit_module.audit_call_context("call-123"):
        audit_module.audit("run_shell_start", command="true")

    record = json.loads(get_settings().audit_log_path.read_text(encoding="utf-8"))
    assert record["parent_call_id"] == "call-123"


def test_audit_call_context_propagates_nested_false_outcomes(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    with audit_module.audit_call_context("call-failed") as state:
        audit_module.audit("shell_kill", ok=False, session="missing")

    assert state["failed"] is True
    record = json.loads(get_settings().audit_log_path.read_text(encoding="utf-8"))
    assert record["parent_call_id"] == "call-failed"
    assert record["ok"] is False


def test_audit_call_helpers_cover_legacy_unpaired_and_optional_fields():
    assert audit_module._operation_type({"event": "run_shell_start"}) == "shell"
    assert audit_module._operation_type({"event": "job_started"}) == "jobs"
    assert audit_module._operation_type({"event": "browser_capture"}) == "browser"
    assert audit_module._operation_type({"tool": "browser_snapshot"}) == "browser"
    for legacy_browser_tool in (
        "browser_capture_tool",
        "browser_get_text_tool",
        "playwright_run_script_tool",
    ):
        assert audit_module._operation_type({"tool": legacy_browser_tool}) == "browser"
    assert audit_module._operation_type({"tool": "mcp_tool_call"}) == "agent"
    assert audit_module._operation_type({"event": "download_created"}) == "files"
    assert audit_module._operation_type({"event": "transfer_completed"}) == "remote"
    assert audit_module._operation_type({"tool": "remote_transfer"}) == "remote"
    assert audit_module._call_input({"arguments": "invalid"}) is None
    assert audit_module._call_input({"arguments": {"positional_count": 2}}) == {
        "positional_count": 2
    }

    legacy_start = {
        "ts": 1,
        "event": "mcp_tool_call_start",
        "tool": "read_file",
        "machine": "worker-a",
        "session": "term-a",
        "arguments": {"path": "legacy.txt"},
    }
    entry = audit_module._new_call_entry(legacy_start, 4)
    assert entry["id"] == "legacy-call:1:4"
    assert entry["session"] == "term-a"
    assert entry["input"] == {"path": "legacy.txt"}

    audit_module._finish_call_entry(
        entry,
        {
            "ok": None,
            "duration_ms": 9,
            "result": {"value": 1},
            "error": "unknown status",
            "error_type": "RuntimeError",
        },
    )
    assert entry["status"] == "completed"
    assert entry["duration_ms"] == 9
    assert entry["output"] == {"value": 1}
    assert entry["error_type"] == "RuntimeError"

    unpaired = audit_module._unpaired_end_entry(
        {
            "ts": 2,
            "event": "mcp_tool_call_end",
            "call_id": "orphan",
            "tool": "job_tail",
            "node": "worker-b",
            "session": "term-b",
            "duration_ms": 4,
            "result": {"lines": []},
            "ok": False,
            "error": "missing start",
            "error_type": "LookupError",
        },
        5,
    )
    assert unpaired == {
        "id": "call:orphan",
        "ts": 2.0,
        "event": "mcp_tool_call",
        "tool": "job_tail",
        "node": "worker-b",
        "operation": "jobs",
        "paired": False,
        "status": "unpaired",
        "source_events": ["mcp_tool_call_end"],
        "call_id": "orphan",
        "session": "term-b",
        "duration_ms": 4,
        "output": {"lines": []},
        "ok": False,
        "error": "missing start",
        "error_type": "LookupError",
    }

    rows = audit_module._coalesce_audit_records(
        [
            {"ts": 0, "event": "auth_ok"},
            legacy_start,
            {"ts": 1.5, "event": "tool_call_purpose", "tool": "read_file"},
            {"ts": 1.6, "event": "run_shell_start", "command": "true"},
            {
                "ts": 1.7,
                "event": "future_internal_event",
                "parent_call_id": "nested-call",
            },
            {
                "ts": 3,
                "event": "mcp_tool_call_end",
                "tool": "read_file",
                "machine": "worker-a",
                "session": "term-a",
                "ok": True,
                "result": {"ok": True, "data": {"ok": False}},
            },
            {"ts": 4, "event": "mcp_tool_call_end", "tool": "job_tail", "ok": True},
            {"id": "kept", "ts": 5, "event": "remote_worker_registered", "node": "worker-c"},
        ]
    )
    assert len(rows) == 6
    assert rows[0]["paired"] is True
    assert rows[0]["status"] == "failed"
    assert rows[1]["event"] == "tool_call_purpose"
    assert rows[2]["event"] == "run_shell_start"
    assert rows[3]["event"] == "future_internal_event"
    assert rows[4]["status"] == "unpaired"
    assert rows[5]["id"] == "kept"
    assert rows[5]["operation"] == "remote"


def test_coalescing_keeps_semantic_child_details_without_duplicate_rows():
    records = [
        {"ts": 1, "event": "mcp_tool_call_start", "call_id": "call-1", "tool": "revoke_file_link"},
        {
            "ts": 2,
            "event": "download_link_revoked",
            "parent_call_id": "call-1",
            "path": "/tmp/report.txt",
            "token": "token-1",
        },
        {
            "ts": 3,
            "event": "shell_kill",
            "parent_call_id": "call-1",
            "ok": False,
        },
        {
            "ts": 4,
            "event": "mcp_tool_call_end",
            "call_id": "call-1",
            "tool": "revoke_file_link",
            "ok": True,
        },
    ]

    rows = audit_module._coalesce_audit_records(records)

    assert len(rows) == 1
    assert rows[0]["related_events"] == [
        {"event": "download_link_revoked", "path": "/tmp/report.txt", "token": "token-1"}
    ]
    assert rows[0][audit_module._AUDIT_SOURCE_INDEXES] == [0, 1, 2, 3]
    summary = audit_module._audit_summary_entry(rows[0])
    assert summary["detail_revision"] == 4
    assert "related_events" not in summary
    units = audit_module._retention_units([(b"line\n", record, set()) for record in records])
    assert len(units) == 1
    assert [item[0] for item in units[0]] == [0, 1, 2, 3]


def test_query_audit_covers_tail_reading_and_filter_rejections(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    assert audit_module.query_audit() == {"entries": [], "count": 0, "total_matched": 0}

    path = get_settings().audit_log_path
    records = [
        {
            "ts": 1,
            "event": "shell_send",
            "machine": "worker-a",
            "session": "one",
            "detail": "alpha",
        },
        {
            "ts": 2,
            "event": "job_started",
            "machine": "worker-b",
            "session": "two",
            "detail": "beta",
        },
        {
            "ts": 3,
            "event": "browser_capture",
            "machine": "worker-c",
            "session": "three",
            "detail": "gamma",
        },
    ]
    payload = b"prefix-without-json\n" + b"x" * 500 + b"\n\xff\n"
    payload += ("\n".join(json.dumps(record) for record in records) + "\n").encode()
    path.write_bytes(payload)

    all_rows = audit_module.query_audit(sort="asc")
    assert [row["ts"] for row in all_rows["entries"]] == [1, 2, 3]
    assert audit_module.query_audit(start_ts=2.5)["entries"][0]["ts"] == 3
    assert audit_module.query_audit(end_ts=1.5)["entries"][0]["ts"] == 1
    assert audit_module.query_audit(node="missing")["total_matched"] == 0
    assert audit_module.query_audit(event="missing")["total_matched"] == 0
    assert audit_module.query_audit(operation="remote")["total_matched"] == 0
    assert audit_module.query_audit(session="missing")["total_matched"] == 0
    assert audit_module.query_audit(search="missing")["total_matched"] == 0


def test_trim_audit_log_without_newline_keeps_bounded_tail(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_bytes(b"x" * 200)

    audit_module._trim_audit_log(path, 100)

    assert path.read_bytes() == b"x" * 50


def test_payload_reference_namespace_does_not_capture_user_dictionaries():
    legacy_shaped = {
        "$audit_payload": "a" * 64,
        "bytes": 12,
        "preview": "user value",
    }
    namespaced_but_not_internal = {
        audit_module._AUDIT_PAYLOAD_MARKER: {
            "version": audit_module._AUDIT_PAYLOAD_VERSION,
            "sha256": "b" * 64,
            "bytes": 12,
        },
        "preview": "user value",
        "extra": True,
    }

    assert audit_module._resolve_payload_reference(legacy_shaped, full=True) == legacy_shaped
    assert (
        audit_module._resolve_payload_reference(namespaced_but_not_internal, full=True)
        == namespaced_but_not_internal
    )


def test_payload_files_are_created_private_from_the_first_write(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    observed_modes: list[int] = []
    real_open = os.open

    def tracking_open(path, flags, mode=0o777):
        if str(path).endswith(".tmp"):
            observed_modes.append(mode)
        return real_open(path, flags, mode)

    monkeypatch.setattr(audit_module.os, "open", tracking_open)
    reference = audit_module._write_payload("secret:" + "x" * 30_000)
    payload = audit_module._payload_path(audit_module._payload_digest(reference))

    assert observed_modes
    assert set(observed_modes) == {0o600}
    if os.name != "nt":
        assert stat.S_IMODE(payload.stat().st_mode) == 0o600


def test_payload_pruning_defers_recent_unreferenced_files(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    log_path = get_settings().audit_log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("{}\n", encoding="utf-8")
    reference = audit_module._write_payload("pending:" + "x" * 30_000)
    payload = audit_module._payload_path(audit_module._payload_digest(reference))

    temporary = audit_module._payload_directory(log_path) / ".interrupted.json.gz.123.tmp"
    temporary.write_bytes(b"partial")

    audit_module._prune_payload_store(log_path)
    assert payload.exists()
    assert temporary.exists()

    stale = time.time() - audit_module._AUDIT_PAYLOAD_PRUNE_GRACE_S - 1
    os.utime(payload, (stale, stale))
    os.utime(temporary, (stale, stale))
    audit_module._prune_payload_store(log_path)
    assert not payload.exists()
    assert not temporary.exists()


def test_payload_pruning_defers_when_the_log_cannot_be_read(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    directory = get_settings().audit_log_path.parent / audit_module._AUDIT_PAYLOAD_DIRECTORY
    directory.mkdir(parents=True)
    payload = directory / f"{'a' * 64}.json.gz"
    payload.write_bytes(b"payload")
    log_path = get_settings().audit_log_path
    log_path.write_text("{}\n", encoding="utf-8")

    def fail_read_text(self: Path, *args, **kwargs):
        raise OSError("temporary read failure")

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    assert audit_module._prune_payload_store(log_path) is False
    assert payload.exists()


def test_payload_pruning_retries_transient_stale_delete_failure(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    log_path = get_settings().audit_log_path
    log_path.write_text("{}\n", encoding="utf-8")
    reference = audit_module._write_payload(os.urandom(18_000).hex())
    payload = audit_module._payload_path(audit_module._payload_digest(reference))
    stale = time.time() - audit_module._AUDIT_PAYLOAD_PRUNE_GRACE_S - 1
    os.utime(payload, (stale, stale))
    original_unlink = Path.unlink
    failures = 0

    def fail_once(path: Path, *args, **kwargs):
        nonlocal failures
        if path == payload and failures == 0:
            failures += 1
            raise OSError("transient delete failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_once)

    assert audit_module._enforce_audit_storage_limit(log_path, 200_000) is False
    assert payload.exists()
    assert audit_module._enforce_audit_storage_limit(log_path, 200_000) is True
    assert not payload.exists()


def test_get_audit_entry_rejects_empty_and_unknown_ids(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="audit entry id is required"):
        audit_module.get_audit_entry("  ")
    with pytest.raises(ValueError, match="Unknown audit entry: missing"):
        audit_module.get_audit_entry("missing")


def test_get_audit_entry_loads_only_the_selected_payloads(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES", "200000")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES", "200000")
    get_settings.cache_clear()

    for call_id, fill in (("selected", "s"), ("unrelated", "u")):
        audit_module.audit(
            "mcp_tool_call_start",
            call_id=call_id,
            tool="write_file",
            arguments={"keyword_args": {"content": fill * 30_000}},
        )
        audit_module.audit(
            "mcp_tool_call_end",
            call_id=call_id,
            tool="write_file",
            ok=True,
            result={"stdout": fill * 30_000},
        )

    records = [
        json.loads(line)
        for line in get_settings().audit_log_path.read_text(encoding="utf-8").splitlines()
    ]
    unrelated_ids: set[str] = set()
    for record in records:
        if record.get("call_id") == "unrelated":
            audit_module._collect_payload_ids(record, unrelated_ids)

    real_payload_path = audit_module._payload_path

    def guarded_payload_path(digest: str):
        if digest in unrelated_ids:
            raise AssertionError("unrelated payload was materialized")
        return real_payload_path(digest)

    monkeypatch.setattr(audit_module, "_payload_path", guarded_payload_path)
    detail = audit_module.get_audit_entry("call:selected")

    assert detail["input"]["content"] == "s" * 30_000
    assert detail["output"]["stdout"] == "s" * 30_000


def test_audit_payload_helpers_cover_edge_paths(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES", "200000")
    get_settings.cache_clear()

    class CustomValue:
        def __repr__(self) -> str:
            return "custom-value"

    assert audit_module._preview_audit_value([1, "x", CustomValue()]) == [
        1,
        "x",
        "custom-value",
    ]
    assert audit_module._preview_audit_value(None) is None
    assert (
        audit_module._is_payload_reference(
            {audit_module._AUDIT_PAYLOAD_MARKER: "invalid", "preview": "x"}
        )
        is False
    )
    assert (
        audit_module._is_payload_reference(
            {
                audit_module._AUDIT_PAYLOAD_MARKER: {
                    "version": audit_module._AUDIT_PAYLOAD_VERSION,
                    "sha256": "a" * 64,
                },
                "preview": "x",
            }
        )
        is False
    )

    missing_reference = {
        audit_module._AUDIT_PAYLOAD_MARKER: {
            "version": audit_module._AUDIT_PAYLOAD_VERSION,
            "sha256": "f" * 64,
            "bytes": 10,
        },
        "preview": "missing-preview",
    }
    unavailable = audit_module._resolve_payload_reference(missing_reference, full=True)
    assert unavailable["error"] == "Audit payload is unavailable"
    assert unavailable["preview"] == "missing-preview"
    retained_preview = json.loads(
        audit_module._bounded_preview_record(
            {"id": "payload-preview", "ts": 1, "event": "preview", "payload": missing_reference},
            1000,
        )
    )
    assert retained_preview["audit_payloads_omitted"] == "full payload omitted from live audit log"

    collected: set[str] = set()
    audit_module._collect_payload_ids("not-a-record", collected)
    assert collected == set()
    assert audit_module._payload_file_size("e" * 64) == 0

    oversized = {
        "id": "oversized",
        "ts": 1,
        "event": "custom_event",
        "payload": "x" * 10_000,
    }
    assert audit_module._bounded_preview_record(oversized, 20) == b""
    bounded = json.loads(audit_module._bounded_preview_record(oversized, 300))
    assert bounded["audit_payloads_omitted"] == "record exceeded audit retention limit"
    assert audit_module._bounded_preview_unit([], 100) == []
    unit = [
        (0, b"invalid\n", None, set()),
        (1, b"record\n", oversized, set()),
    ]
    assert [index for index, _ in audit_module._bounded_preview_unit(unit, 600)] == [1]

    log_path = get_settings().audit_log_path
    audit_module._enforce_audit_storage_limit(log_path, 100)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_bytes(b"{" + b"x" * 200 + b"\n" + audit_module._encode_audit_record(oversized))
    audit_module._enforce_audit_storage_limit(log_path, 300)
    retained = json.loads(log_path.read_text(encoding="utf-8"))
    assert retained["id"] == "oversized"
    assert retained["audit_payloads_omitted"] == "record exceeded audit retention limit"


def test_audit_skips_full_retention_scan_while_storage_is_below_budget(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES", "20000000")
    get_settings.cache_clear()
    log_path = get_settings().audit_log_path
    log_path.write_text(
        json.dumps({"id": "seed", "ts": 1, "event": "seed", "detail": "x" * 1_000_000}) + "\n",
        encoding="utf-8",
    )
    calls = 0
    original = audit_module._enforce_audit_storage_limit

    def track_enforcement(path: Path, max_bytes: int) -> bool:
        nonlocal calls
        calls += 1
        return original(path, max_bytes)

    monkeypatch.setattr(audit_module, "_enforce_audit_storage_limit", track_enforcement)

    for index in range(100):
        audit_module.audit("small_event", index=index)

    assert calls == 1
    assert len(log_path.read_text(encoding="utf-8").splitlines()) == 101


def test_audit_periodically_runs_payload_housekeeping_below_budget(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES", "20000000")
    get_settings.cache_clear()
    log_path = get_settings().audit_log_path
    audit_module._AUDIT_LAST_MAINTENANCE.pop(os.fspath(log_path), None)
    calls = 0
    original = audit_module._enforce_audit_storage_limit

    def track_enforcement(path: Path, max_bytes: int) -> bool:
        nonlocal calls
        calls += 1
        return original(path, max_bytes)

    monkeypatch.setattr(audit_module, "_enforce_audit_storage_limit", track_enforcement)

    audit_module.audit("maintenance_event")

    assert calls == 1


def test_audit_pressure_backoff_avoids_repeated_scans_for_recent_orphans(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES", "12000")
    get_settings.cache_clear()
    log_path = get_settings().audit_log_path
    log_path.write_text("{}\n", encoding="utf-8")
    audit_module._write_payload(os.urandom(18_000).hex())
    calls = 0
    original = audit_module._enforce_audit_storage_limit

    def track_enforcement(path: Path, max_bytes: int) -> bool:
        nonlocal calls
        calls += 1
        return original(path, max_bytes)

    monkeypatch.setattr(audit_module, "_enforce_audit_storage_limit", track_enforcement)

    audit_module.audit("pressure_trigger")
    for index in range(20):
        audit_module.audit("small_event", index=index)

    assert calls == 1
    assert audit_module._audit_pressure_backoff_active(log_path) is True


def test_audit_storage_size_ignores_interrupted_payload_temporaries(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    log_path = get_settings().audit_log_path
    log_path.write_bytes(b"{}\n")
    directory = log_path.parent / audit_module._AUDIT_PAYLOAD_DIRECTORY
    directory.mkdir()
    (directory / ".interrupted.json.gz.123.tmp").write_bytes(b"x" * 50_000)

    assert audit_module._audit_storage_bytes(log_path) == log_path.stat().st_size


def test_new_payload_clears_pressure_backoff_and_rechecks_budget(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES", "12000")
    get_settings.cache_clear()
    log_path = get_settings().audit_log_path
    key = os.fspath(log_path)
    audit_module._AUDIT_LAST_MAINTENANCE[key] = time.monotonic()
    audit_module._AUDIT_PRESSURE_BACKOFF_UNTIL[key] = time.monotonic() + 300
    calls = 0
    original = audit_module._enforce_audit_storage_limit

    def track_enforcement(path: Path, max_bytes: int) -> bool:
        nonlocal calls
        calls += 1
        return original(path, max_bytes)

    monkeypatch.setattr(audit_module, "_enforce_audit_storage_limit", track_enforcement)

    audit_module.audit("large_event", payload=os.urandom(18_000).hex())

    assert calls == 1


def test_reused_payload_preserves_pressure_backoff(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES", "12000")
    get_settings.cache_clear()
    log_path = get_settings().audit_log_path
    key = os.fspath(log_path)
    value = os.urandom(18_000).hex()
    audit_module._write_payload(value)
    audit_module._AUDIT_LAST_MAINTENANCE[key] = time.monotonic()
    audit_module._AUDIT_PRESSURE_BACKOFF_UNTIL[key] = time.monotonic() + 300
    calls = 0
    original = audit_module._enforce_audit_storage_limit

    def track_enforcement(path: Path, max_bytes: int) -> bool:
        nonlocal calls
        calls += 1
        return original(path, max_bytes)

    monkeypatch.setattr(audit_module, "_enforce_audit_storage_limit", track_enforcement)

    audit_module.audit("reused_payload", payload=value)

    assert calls == 0
    assert audit_module._audit_pressure_backoff_active(log_path) is True


def test_failed_retention_pass_is_retried_without_backoff(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES", "12000")
    get_settings.cache_clear()
    log_path = get_settings().audit_log_path
    key = os.fspath(log_path)
    original_read_bytes = Path.read_bytes
    failures = 0

    def fail_once(path: Path) -> bytes:
        nonlocal failures
        if path == log_path and failures == 0:
            failures += 1
            raise OSError("transient audit read failure")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_once)

    audit_module.audit("large_event", payload=os.urandom(18_000).hex())

    assert failures == 1
    assert key not in audit_module._AUDIT_LAST_MAINTENANCE
    assert key not in audit_module._AUDIT_PRESSURE_BACKOFF_UNTIL

    audit_module.audit("retry_event")

    assert key in audit_module._AUDIT_LAST_MAINTENANCE
    assert audit_module._audit_pressure_backoff_active(log_path) is True


def test_audit_enters_full_retention_scan_only_after_storage_exceeds_budget(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES", "3000")
    get_settings.cache_clear()
    calls = 0
    original = audit_module._enforce_audit_storage_limit

    def track_enforcement(path: Path, max_bytes: int) -> bool:
        nonlocal calls
        calls += 1
        return original(path, max_bytes)

    monkeypatch.setattr(audit_module, "_enforce_audit_storage_limit", track_enforcement)

    for index in range(100):
        audit_module.audit("budget_pressure", index=index, detail="x" * 80)

    assert calls > 0
    assert get_settings().audit_log_path.stat().st_size <= 3000


def test_small_retention_budget_externalizes_recoverable_values(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES", "12000")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES", "12000")
    get_settings.cache_clear()
    value = "compressible:" + "x" * 10_000

    audit_module.audit("budgeted_event", payload=value)

    raw = json.loads(get_settings().audit_log_path.read_text(encoding="utf-8"))
    assert audit_module._is_payload_reference(raw["payload"])
    entry = audit_module.query_audit()["entries"][0]
    assert audit_module.get_audit_entry(entry["id"])["payload"] == value


def test_payload_store_follows_configured_audit_log(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    audit_path = tmp_path / "persisted-audit" / "records.jsonl"
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUDIT_LOG_PATH", str(audit_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / "separate-state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES", "200000")
    get_settings.cache_clear()

    audit_module.audit("large_event", payload="x" * 30_000)

    payloads = list((audit_path.parent / audit_module._AUDIT_PAYLOAD_DIRECTORY).glob("*.json.gz"))
    assert len(payloads) == 1
    assert not (get_settings().state_dir / audit_module._AUDIT_PAYLOAD_DIRECTORY).exists()


def test_audit_retention_keeps_latest_call_pair_together(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES", "500000")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES", "500000")
    get_settings.cache_clear()

    audit_module.audit("older_event", payload=os.urandom(18_000).hex())
    latest_input = os.urandom(9_000).hex()
    latest_output = os.urandom(9_000).hex()
    audit_module.audit(
        "mcp_tool_call_start",
        call_id="latest-call",
        tool="write_file",
        arguments={"keyword_args": {"content": latest_input}},
    )
    audit_module.audit(
        "mcp_tool_call_end",
        call_id="latest-call",
        tool="write_file",
        ok=True,
        result={"stdout": latest_output},
    )

    log_path = get_settings().audit_log_path
    raw_lines = log_path.read_bytes().splitlines(keepends=True)
    pair_records = [
        json.loads(line) for line in raw_lines if json.loads(line).get("call_id") == "latest-call"
    ]
    pair_payloads: set[str] = set()
    for record in pair_records:
        audit_module._collect_payload_ids(record, pair_payloads)
    pair_bytes = sum(
        len(line) for line in raw_lines if json.loads(line).get("call_id") == "latest-call"
    ) + sum(audit_module._payload_file_size(digest, log_path) for digest in pair_payloads)
    total_bytes = log_path.stat().st_size + sum(
        path.stat().st_size for path in audit_module._payload_directory().glob("*.json.gz")
    )
    assert total_bytes > pair_bytes + 100

    audit_module._enforce_audit_storage_limit(log_path, pair_bytes + 100)

    entries = audit_module.query_audit(sort="asc")["entries"]
    latest = next(entry for entry in entries if entry["id"] == "call:latest-call")
    assert latest["paired"] is True
    archives = audit_module._load_file_archive_index(log_path)
    assert len(archives) == 1
    assert archives[0]["compressed_bytes"] < archives[0]["raw_bytes"]
    detail = audit_module.get_audit_entry("call:latest-call")
    assert detail["input"]["content"] == latest_input
    assert detail["output"]["stdout"] == latest_output


def test_audit_retention_bounds_log_and_external_payload_bytes(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    max_bytes = 26_000
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES", "200000")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES", str(max_bytes))
    get_settings.cache_clear()

    first = os.urandom(18_000).hex()
    second = os.urandom(18_000).hex()
    audit_module.audit("first_large_event", payload=first)
    first_payloads = set(
        (get_settings().audit_log_path.parent / audit_module._AUDIT_PAYLOAD_DIRECTORY).glob(
            "*.json.gz"
        )
    )
    assert len(first_payloads) == 1
    stale = time.time() - audit_module._AUDIT_PAYLOAD_PRUNE_GRACE_S - 1
    for payload in first_payloads:
        os.utime(payload, (stale, stale))

    audit_module.audit("second_large_event", payload=second)

    payload_directory = get_settings().audit_log_path.parent / audit_module._AUDIT_PAYLOAD_DIRECTORY
    stored_bytes = get_settings().audit_log_path.stat().st_size + sum(
        path.stat().st_size for path in payload_directory.glob("*.json.gz")
    )
    assert stored_bytes <= max_bytes
    assert all(not path.exists() for path in first_payloads)
    entries = audit_module.query_audit(sort="asc")["entries"]
    hot_events = [
        json.loads(line)["event"] for line in get_settings().audit_log_path.read_text().splitlines()
    ]
    assert [entry["event"] for entry in entries] == hot_events
    second_entry = next(entry for entry in entries if entry["event"] == "second_large_event")
    assert audit_module.get_audit_entry(second_entry["id"])["payload"] == second


def test_audit_archive_budget_prunes_oldest_compressed_files(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES", "2500")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_ARCHIVE_BYTES", "1200")
    get_settings.cache_clear()

    for batch in range(8):
        for index in range(20):
            audit_module.audit("archive_budget_event", batch=batch, index=index, detail="x" * 120)

    archives = audit_module._load_file_archive_index(get_settings().audit_log_path)
    assert archives
    assert sum(entry["compressed_bytes"] for entry in archives) <= 1200
    keys = {entry["key"] for entry in archives}
    files = {
        path.relative_to(tmp_path).as_posix()
        for path in (tmp_path / audit_module._AUDIT_ARCHIVE_DIRECTORY).glob("*.jsonl.zst")
    }
    assert files == keys


def test_archive_pruning_retains_entry_when_file_delete_fails(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    log_path = get_settings().audit_log_path
    key = audit_module._archive_key(1, 2)
    archive_path = audit_module._archive_file_path(log_path, key)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(b"archive")
    entry = {
        "key": key,
        "start_ts": 1.0,
        "end_ts": 2.0,
        "records": 1,
        "raw_bytes": 20,
        "compressed_bytes": archive_path.stat().st_size,
    }
    original_unlink = Path.unlink

    def fail_archive_unlink(path: Path, *args, **kwargs):
        if path == archive_path:
            raise PermissionError("archive is busy")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_archive_unlink)
    assert audit_module._prune_file_archives(log_path, [entry], 0) == [entry]
    assert audit_module._load_file_archive_index(log_path) == [entry]
    assert archive_path.exists()

    monkeypatch.setattr(Path, "unlink", original_unlink)
    assert audit_module._prune_file_archives(log_path, [entry], 0) == []
    assert not archive_path.exists()


def test_archive_index_rejects_paths_outside_archive_directory(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    log_path = get_settings().audit_log_path
    victim = tmp_path / "victim.jsonl.zst"
    victim.write_bytes(b"keep")
    index_path = log_path.parent / audit_module._AUDIT_ARCHIVE_DIRECTORY / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "version": audit_module._AUDIT_ARCHIVE_VERSION,
                "archives": [
                    {
                        "key": "audit-archive/../../victim.jsonl.zst",
                        "compressed_bytes": 999999,
                        "start_ts": 1,
                        "end_ts": 2,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert audit_module._load_file_archive_index(log_path) == []
    with pytest.raises(ValueError, match="invalid audit archive key"):
        audit_module._archive_file_path(log_path, "audit-archive/../../victim.jsonl.zst")
    assert victim.read_bytes() == b"keep"


def test_archive_time_bounds_ignore_invalid_timestamps():
    parsed = [
        (b"bad\n", {"ts": "bad"}, set()),
        (b"infinite\n", {"ts": float("inf")}, set()),
        (b"boolean\n", {"ts": True}, set()),
        (b"valid\n", {"ts": 7.5}, set()),
    ]

    assert audit_module._archive_time_bounds(parsed, [0, 1, 2, 3]) == (7.5, 7.5)


def test_corrupt_utf8_payload_is_unavailable_instead_of_raising(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    reference = audit_module._write_payload("payload")
    digest = audit_module._payload_digest(reference)
    audit_module._payload_path(digest).write_bytes(gzip.compress(b"\xff"))

    resolved = audit_module._resolve_payload_reference(reference, full=True)

    assert resolved["error"] == "Audit payload is unavailable"
    assert resolved["payload_id"] == digest


def test_archive_payload_materialization_is_bounded(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(audit_module, "_AUDIT_ARCHIVE_MAX_PAYLOAD_MATERIALIZATION_BYTES", 32)
    reference = audit_module._write_payload("small")
    digest = audit_module._payload_digest(reference)
    payload_path = audit_module._payload_path(digest)

    declared_large = json.loads(json.dumps(reference))
    declared_large[audit_module._AUDIT_PAYLOAD_MARKER]["bytes"] = 33
    payload_path.unlink()
    declared_envelope = json.loads(
        audit_module._encode_archive_line(b"{}\n", {"payload": declared_large})
    )
    assert "33 > 32 bytes" in declared_envelope["payloads"]["payload"]["detail"]

    payload_path.write_bytes(gzip.compress(json.dumps("x" * 100).encode()))
    actual_large = json.loads(json.dumps(reference))
    actual_large[audit_module._AUDIT_PAYLOAD_MARKER]["bytes"] = 1
    actual_envelope = json.loads(
        audit_module._encode_archive_line(b"{}\n", {"payload": actual_large})
    )
    assert "32 bytes" in actual_envelope["payloads"]["payload"]["detail"]


def test_archive_payload_materialization_budget_is_shared_across_batch(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(audit_module, "_AUDIT_ARCHIVE_MAX_PAYLOAD_MATERIALIZATION_BYTES", 32)
    first = audit_module._write_payload("x" * 16)
    second = audit_module._write_payload("y" * 16)
    parsed = [
        (b'{"id":"first"}\n', {"id": "first", "payload": first}, set()),
        (b'{"id":"second"}\n', {"id": "second", "payload": second}, set()),
    ]
    log_path = get_settings().audit_log_path

    archive = audit_module._write_file_archive(log_path, parsed, [0, 1])

    assert archive is not None
    archive_path = audit_module._archive_file_path(log_path, archive["key"])
    with audit_archive_codec.zstd.ZstdDecompressor().stream_reader(archive_path.open("rb")) as reader:
        envelopes = [json.loads(line) for line in reader.read().splitlines()]
    assert envelopes[0]["payloads"]["payload"] == "x" * 16
    assert envelopes[1]["payloads"]["payload"]["error"] == "Audit payload is unavailable"
    assert "safe materialization limit" in envelopes[1]["payloads"]["payload"]["detail"]


def test_archive_index_rejects_malformed_metadata(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    valid = {
        "key": "audit-archive/0000000000001-0000000000002-test.jsonl.zst",
        "start_ts": 1,
        "end_ts": 2,
        "records": 1,
        "raw_bytes": 10,
        "compressed_bytes": 5,
    }
    malformed = dict(valid, compressed_bytes="bad")
    raw = json.dumps(
        {"version": audit_module._AUDIT_ARCHIVE_VERSION, "archives": [malformed, valid]}
    ).encode()

    assert audit_module._parse_archive_index(raw) == [{**valid, "start_ts": 1.0, "end_ts": 2.0}]


def test_archive_index_recovers_orphaned_file_from_storage(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    log_path = get_settings().audit_log_path
    key = audit_module._archive_key(1, 2)
    archive_path = audit_module._archive_file_path(log_path, key)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(b"orphaned-archive")
    (archive_path.parent / "index.json").write_bytes(b"{")

    recovered = audit_module._load_file_archive_index(log_path)

    assert [entry["key"] for entry in recovered] == [key]
    assert recovered[0]["compressed_bytes"] == archive_path.stat().st_size
    assert audit_module._prune_file_archives(log_path, recovered, 0) == []
    assert not archive_path.exists()


def test_archive_reconciliation_removes_only_stale_temporary_files(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    log_path = get_settings().audit_log_path
    directory = audit_module._validated_archive_directory(log_path, create=True)
    recent = directory / ".recent.jsonl.zst.1.1.tmp"
    stale = directory / ".stale.jsonl.zst.1.1.tmp"
    recent.write_bytes(b"recent")
    stale.write_bytes(b"stale")
    stale_time = time.time() - audit_module._AUDIT_PAYLOAD_PRUNE_GRACE_S - 1
    os.utime(stale, (stale_time, stale_time))

    audit_module._load_file_archive_index(log_path)

    assert recent.exists()
    assert not stale.exists()


def test_file_archive_pruning_waits_for_hot_log_commit(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    log_path = get_settings().audit_log_path
    original = b"".join(
        (
            json.dumps({"id": f"row-{index}", "ts": index + 1, "event": "old", "detail": "x" * 120})
            + "\n"
        ).encode()
        for index in range(20)
    )
    log_path.write_bytes(original)
    old_key = audit_module._archive_key(1, 2)
    old_path = audit_module._archive_file_path(log_path, old_key)
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_bytes(b"older-history")
    audit_module._write_file_archive_index(
        log_path,
        [audit_module._recovered_archive_entry(old_key, old_path.stat().st_size)],
    )
    original_replace = audit_module.os.replace

    def fail_hot_log_replace(source, destination):
        if Path(destination) == log_path:
            raise OSError("simulated hot-log replace failure")
        return original_replace(source, destination)

    monkeypatch.setattr(audit_module.os, "replace", fail_hot_log_replace)
    with pytest.raises(OSError, match="hot-log replace failure"):
        audit_module._enforce_audit_storage_limit(log_path, 1000, 1)

    monkeypatch.setattr(audit_module.os, "replace", original_replace)
    archives = audit_module._load_file_archive_index(log_path)
    assert old_path.exists()
    assert len(archives) >= 2
    assert log_path.read_bytes() == original


def test_archive_index_write_rejects_symlinked_directory(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    log_path = get_settings().audit_log_path
    outside = tmp_path / "outside"
    outside.mkdir()
    archive_dir = tmp_path / audit_module._AUDIT_ARCHIVE_DIRECTORY
    archive_dir.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="must not be a symlink"):
        audit_module._write_file_archive_index(log_path, [])
    assert not (outside / "index.json").exists()


def test_under_budget_maintenance_does_not_create_archive_index(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    log_path = get_settings().audit_log_path
    log_path.write_text('{"event":"small"}\n', encoding="utf-8")

    assert audit_module._enforce_audit_storage_limit(log_path, 10_000, 0) is True
    assert not (tmp_path / audit_module._AUDIT_ARCHIVE_DIRECTORY).exists()


def test_query_audit_reads_complete_hot_log_not_tail_window(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES", "6000")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES", "200")
    get_settings.cache_clear()
    path = get_settings().audit_log_path
    records = [
        {
            "id": f"row-{index}",
            "ts": index,
            "event": "hot_history",
            "index": index,
            "detail": "x" * 80,
        }
        for index in range(30)
    ]
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    assert path.stat().st_size > get_settings().max_audit_tail_bytes * 4

    result = audit_module.query_audit(limit=100, search="hot_history", sort="asc")

    assert [entry["index"] for entry in result["entries"]] == list(range(30))


def test_corrupt_cold_archive_does_not_affect_hot_query(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    audit_module.audit("hot_event", detail="still-readable")
    log_path = get_settings().audit_log_path
    archive_key = audit_module._archive_key(1, 2)
    archive_path = audit_module._archive_file_path(log_path, archive_key)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(b"not-zstd")
    audit_module._write_file_archive_index(
        log_path,
        [
            {
                "key": archive_key,
                "compressed_bytes": archive_path.stat().st_size,
                "start_ts": 1,
                "end_ts": 2,
            }
        ],
    )

    result = audit_module.query_audit(search="hot_event")

    assert [entry["event"] for entry in result["entries"]] == ["hot_event"]
