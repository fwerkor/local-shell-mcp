from __future__ import annotations

import json

import local_shell_mcp.audit as audit_module
from local_shell_mcp.settings import get_settings


def _configure(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES", "200000")
    get_settings.cache_clear()


def test_remote_job_lifecycle_coalesces_by_job_id_and_preserves_details(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    records = [
        {
            "ts": 1,
            "event": "mcp_tool_call_start",
            "call_id": "shell",
            "tool": "run_shell",
            "machine": "worker-a",
        },
        {
            "ts": 2,
            "event": "mcp_tool_call_start",
            "call_id": "file",
            "tool": "file_write",
            "machine": "worker-b",
        },
        {
            "ts": 3,
            "event": "remote_job_claimed",
            "job_id": "job-shell",
            "tool": "run_shell_tool",
            "machine": "worker-a",
        },
        {
            "ts": 4,
            "event": "remote_job_enqueued",
            "job_id": "job-shell",
            "parent_call_id": "shell",
            "tool": "run_shell_tool",
            "machine": "worker-a",
        },
        {
            "ts": 5,
            "event": "remote_job_enqueued",
            "job_id": "job-file",
            "parent_call_id": "file",
            "tool": "write_file",
            "machine": "worker-b",
        },
        {
            "ts": 6,
            "event": "remote_job_claimed",
            "job_id": "job-file",
            "tool": "write_file",
            "machine": "worker-b",
        },
        {
            "ts": 7,
            "event": "remote_job_result_accepted",
            "job_id": "job-shell",
            "tool": "run_shell_tool",
            "machine": "worker-a",
            "execution_s": 0.3,
        },
        {
            "ts": 8,
            "event": "mcp_tool_call_end",
            "call_id": "file",
            "tool": "file_write",
            "machine": "worker-b",
            "ok": True,
        },
        {
            "ts": 9,
            "event": "remote_job_result_accepted",
            "job_id": "job-file",
            "tool": "write_file",
            "machine": "worker-b",
            "accepted": True,
        },
        {
            "ts": 10,
            "event": "mcp_tool_call_end",
            "call_id": "shell",
            "tool": "run_shell",
            "machine": "worker-a",
            "ok": True,
        },
        {
            "ts": 11,
            "event": "remote_job_claimed",
            "job_id": "missing-enqueue",
            "machine": "worker-c",
        },
        {"ts": 12, "event": "remote_worker_registered", "machine": "worker-c"},
    ]
    raw = "".join(json.dumps(record) + "\n" for record in records)
    get_settings().audit_log_path.write_text(raw, encoding="utf-8")

    rows = audit_module._coalesce_audit_records(records)
    assert [row["event"] for row in rows] == [
        "mcp_tool_call",
        "mcp_tool_call",
        "remote_job_claimed",
        "remote_worker_registered",
    ]
    assert rows[0]["status"] == rows[1]["status"] == "success"
    assert [event["event"] for event in rows[0]["related_events"]] == [
        "remote_job_claimed",
        "remote_job_enqueued",
        "remote_job_result_accepted",
    ]
    assert [event["event"] for event in rows[1]["related_events"]] == [
        "remote_job_enqueued",
        "remote_job_claimed",
        "remote_job_result_accepted",
    ]
    assert rows[0]["related_events"][-1]["execution_s"] == 0.3
    assert rows[1]["related_events"][-1]["accepted"] is True
    assert rows[0][audit_module._AUDIT_SOURCE_INDEXES] == [0, 2, 3, 6, 9]
    assert rows[1][audit_module._AUDIT_SOURCE_INDEXES] == [1, 4, 5, 7, 8]

    listing = audit_module.query_audit(sort="asc", summary_only=True)
    assert listing["total_matched"] == 4
    assert [entry["detail_revision"] for entry in listing["entries"][:2]] == [5, 5]
    detail = audit_module.get_audit_entry("call:shell")
    assert detail["related_events"] == rows[0]["related_events"]
    assert audit_module.query_audit(event="remote_job_result_accepted")["total_matched"] == 2
    assert get_settings().audit_log_path.read_text(encoding="utf-8") == raw

    units = audit_module._retention_units(
        [(audit_module._encode_audit_record(record), record, set()) for record in records]
    )
    assert len(units) == 4
    assert sorted(len(unit) for unit in units) == [1, 1, 5, 5]
