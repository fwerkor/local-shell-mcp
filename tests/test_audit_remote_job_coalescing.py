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


def test_remote_lifecycle_time_filters_use_child_timestamp(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    records = [
        {"ts": 10, "event": "mcp_tool_call_start", "call_id": "call-1", "tool": "run_shell"},
        {"ts": 12, "event": "remote_job_enqueued", "parent_call_id": "call-1", "job_id": "job-1", "machine": "worker-a"},
        {"ts": 16, "event": "remote_job_claimed", "job_id": "job-1", "machine": "worker-a"},
        {"ts": 24, "event": "remote_job_result_accepted", "job_id": "job-1", "machine": "worker-a"},
        {"ts": 25, "event": "mcp_tool_call_end", "call_id": "call-1", "tool": "run_shell", "ok": True},
    ]
    get_settings().audit_log_path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )

    detail = audit_module.get_audit_entry("call:call-1")
    assert [item["ts"] for item in detail["related_events"]] == [12, 16, 24]
    assert audit_module.query_audit(start_ts=20)["total_matched"] == 0
    assert audit_module.query_audit(event="remote_job_result_accepted", start_ts=20, end_ts=24)["total_matched"] == 1
    assert audit_module.query_audit(event="remote_job_result_accepted", end_ts=20)["total_matched"] == 0
    assert audit_module.query_audit(event="remote_job_claimed", start_ts=15, end_ts=18)["total_matched"] == 1
    assert audit_module.query_audit(event="remote_job_claimed", start_ts=20)["total_matched"] == 0
    assert audit_module.query_audit(event="mcp_tool_call_start", start_ts=20)["total_matched"] == 0


def test_remote_worker_node_filter_includes_nested_transfer_nodes(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    records = [
        {"ts": 1, "event": "mcp_tool_call_start", "call_id": "transfer", "tool": "remote_transfer", "arguments": {"keyword_args": {"source_machine": "worker-a", "destination_machine": "worker-b"}}},
        {"ts": 2, "event": "remote_job_enqueued", "parent_call_id": "transfer", "job_id": "job-a", "machine": "worker-a"},
        {"ts": 3, "event": "remote_job_claimed", "job_id": "job-a", "machine": "worker-a"},
        {"ts": 4, "event": "remote_job_result_accepted", "job_id": "job-a", "machine": "worker-a"},
        {"ts": 5, "event": "remote_job_enqueued", "parent_call_id": "transfer", "job_id": "job-b", "machine": "worker-b"},
        {"ts": 6, "event": "remote_job_claimed", "job_id": "job-b", "machine": "worker-b"},
        {"ts": 7, "event": "remote_job_result_accepted", "job_id": "job-b", "machine": "worker-b"},
        {"ts": 8, "event": "mcp_tool_call_end", "call_id": "transfer", "tool": "remote_transfer", "ok": True},
    ]
    get_settings().audit_log_path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )

    assert audit_module.query_audit(node="worker-a")["total_matched"] == 1
    assert audit_module.query_audit(node="worker-b")["total_matched"] == 1
    assert audit_module.query_audit(node="worker-c")["total_matched"] == 0
    assert audit_module.query_audit(node="worker-b", operation="remote")["total_matched"] == 1
    assert audit_module.query_audit(node="worker-a", event="remote_job_claimed", start_ts=3, end_ts=3)["total_matched"] == 1
    assert audit_module.query_audit(node="worker-b", event="remote_job_claimed", start_ts=3, end_ts=3)["total_matched"] == 0
    assert audit_module.query_audit(node="worker-b", event="remote_job_result_accepted", start_ts=4, end_ts=4)["total_matched"] == 0
    assert audit_module.query_audit(node="worker-b", event="remote_job_result_accepted", start_ts=7, end_ts=7)["total_matched"] == 1


def test_nested_event_without_machine_inherits_parent_node():
    records = [
        {"ts": 1, "event": "mcp_tool_call_start", "call_id": "file", "tool": "revoke_file_link"},
        {"ts": 2, "event": "download_link_revoked", "parent_call_id": "file", "path": "report.txt"},
        {"ts": 3, "event": "mcp_tool_call_end", "call_id": "file", "tool": "revoke_file_link", "ok": True},
    ]
    result = audit_module._matching_audit_rows(
        records, node="local", event="download_link_revoked", operation=None,
        session=None, search=None, start_ts=1, end_ts=3,
    )
    assert [row["id"] for row in result] == ["call:file"]


def test_bounded_audit_unit_keeps_remote_job_association():
    records = [
        {"ts": 1, "event": "mcp_tool_call_start", "call_id": "call-1", "tool": "run_shell", "payload": "x" * 4000},
        {"ts": 2, "event": "remote_job_enqueued", "parent_call_id": "call-1", "job_id": "job-1", "machine": "worker-a", "payload": "x" * 4000},
        {"ts": 3, "event": "remote_job_claimed", "job_id": "job-1", "machine": "worker-a", "payload": "x" * 4000},
        {"ts": 4, "event": "remote_job_result_accepted", "job_id": "job-1", "machine": "worker-a", "payload": "x" * 4000},
        {"ts": 5, "event": "mcp_tool_call_end", "call_id": "call-1", "tool": "run_shell", "ok": True, "payload": "x" * 4000},
    ]
    unit = [
        (index, audit_module._encode_audit_record(record), record, set())
        for index, record in enumerate(records)
    ]
    bounded = audit_module._bounded_preview_unit(unit, 1300)
    assert len(bounded) == 5
    assert sum(len(raw) for _, raw in bounded) <= 1300
    retained = [json.loads(raw) for _, raw in bounded]
    assert all(record.get("payload") is None for record in retained)
    assert [record["job_id"] for record in retained[1:4]] == ["job-1"] * 3
    assert retained[2]["parent_call_id"] == retained[3]["parent_call_id"] == "call-1"
    assert [record["event"] for record in audit_module._coalesce_audit_records(retained)] == [
        "mcp_tool_call"
    ]
    assert len(audit_module._coalesce_audit_records(retained)[0]["related_events"]) == 3
    without_enqueued = [record for record in retained if record["event"] != "remote_job_enqueued"]
    assert len(audit_module._coalesce_audit_records(without_enqueued)) == 1
