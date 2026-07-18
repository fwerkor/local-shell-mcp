from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path

import pytest

import local_shell_mcp.audit as audit_module
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


def test_audit_call_helpers_cover_legacy_unpaired_and_optional_fields():
    assert audit_module._operation_type({"event": "run_shell_start"}) == "shell"
    assert audit_module._operation_type({"event": "job_started"}) == "jobs"
    assert audit_module._operation_type({"event": "browser_capture"}) == "browser"
    assert audit_module._operation_type({"event": "download_created"}) == "transfer"
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
    assert len(rows) == 5
    assert rows[0]["paired"] is True
    assert rows[0]["status"] == "failed"
    assert rows[1]["event"] == "tool_call_purpose"
    assert rows[2]["event"] == "run_shell_start"
    assert rows[3]["status"] == "unpaired"
    assert rows[4]["id"] == "kept"
    assert rows[4]["operation"] == "remote"


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
    assert audit_module.query_audit(operation="transfer")["total_matched"] == 0
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

    audit_module._prune_payload_store(log_path)
    assert payload.exists()

    stale = time.time() - audit_module._AUDIT_PAYLOAD_PRUNE_GRACE_S - 1
    os.utime(payload, (stale, stale))
    audit_module._prune_payload_store(log_path)
    assert not payload.exists()


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
    audit_module._prune_payload_store(log_path)

    assert payload.exists()


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
    assert len(entries) == 1
    assert entries[0]["id"] == "call:latest-call"
    assert entries[0]["paired"] is True
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
    assert [entry["event"] for entry in entries] == ["second_large_event"]
    assert audit_module.get_audit_entry(entries[0]["id"])["payload"] == second
