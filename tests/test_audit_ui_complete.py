from __future__ import annotations

import json

import local_shell_mcp.audit as audit_module
from local_shell_mcp.settings import get_settings


def _configure(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES", "100")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES", "400")
    get_settings.cache_clear()


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
            {
                "ts": 3,
                "event": "mcp_tool_call_end",
                "tool": "read_file",
                "machine": "worker-a",
                "session": "term-a",
                "ok": False,
            },
            {"ts": 4, "event": "mcp_tool_call_end", "tool": "job_tail", "ok": True},
            {"id": "kept", "ts": 5, "event": "remote_worker_registered", "node": "worker-c"},
        ]
    )
    assert len(rows) == 3
    assert rows[0]["paired"] is True
    assert rows[0]["status"] == "failed"
    assert rows[1]["status"] == "unpaired"
    assert rows[2]["id"] == "kept"
    assert rows[2]["operation"] == "remote"


def test_query_audit_covers_tail_reading_and_filter_rejections(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    assert audit_module.query_audit() == {"entries": [], "count": 0, "total_matched": 0}

    path = get_settings().audit_log_path
    records = [
        {"ts": 1, "event": "shell_send", "machine": "worker-a", "session": "one", "detail": "alpha"},
        {"ts": 2, "event": "job_started", "machine": "worker-b", "session": "two", "detail": "beta"},
        {"ts": 3, "event": "browser_capture", "machine": "worker-c", "session": "three", "detail": "gamma"},
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
