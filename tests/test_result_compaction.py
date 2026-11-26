"""Native result compaction preserves the MCP contract and actionable data."""
import copy
import json

import jsonschema
import pytest

from local_shell_mcp.models import CommandResult, ToolResult
from local_shell_mcp.result_compaction import compact_native_result
from local_shell_mcp.settings import get_settings
from local_shell_mcp.tools import build_mcp


def _envelope(data):
    return {"ok": True, "message": "", "data": data}


def test_shell_compaction_preserves_failure_and_unknown_fields():
    command = "echo " + "x" * 1000
    data = dict(ok=True, exit_code=0, cwd=".", command=command, stdout="",
                stderr="", timed_out=False, truncated=False, persisted=False,
                duration_ms=0, extra={"empty": None, "flag": False})
    original = _envelope(data)
    before = copy.deepcopy(original)
    compact = compact_native_result("run_shell", {"command": command}, original)
    assert compact == {"ok": True, "data": {
        "exit_code": 0, "stdout": "", "duration_ms": 0, "extra": data["extra"],
    }}
    assert original == before
    failed = {**data, "ok": False, "exit_code": 7, "stderr": "failure",
              "timed_out": True, "truncated": True, "persisted": True, "job_id": "job_x"}
    projected = compact_native_result("run_shell", {"command": command}, _envelope(failed))["data"]
    for key in ("ok", "exit_code", "stderr", "timed_out", "truncated", "persisted", "job_id"):
        assert projected[key] == failed[key]
    assert compact_native_result("run_shell", {"command": "other"}, original)["data"]["command"] == command


def test_job_and_session_detail_are_available_and_errors_are_retained():
    raw = _envelope({"job": {"job_id": "j", "status": "failed", "command": "long",
                              "error": "crash", "exit_code": 1, "log_truncated": True,
                              "progress": {"step": 3}, "attempts": 2}, "output": "logs",
                     "message": "job completed with exit code 1"})
    compact = compact_native_result("job_tail", {}, raw)["data"]
    assert compact["job"] == {"job_id": "j", "status": "failed", "error": "crash",
                              "exit_code": 1, "log_truncated": True,
                              "progress": {"step": 3}, "attempts": 2}
    assert compact["output"] == "logs"
    assert "message" not in compact
    assert compact_native_result("job_tail", {"verbose": True}, raw)["data"] == raw["data"]
    history = [{"type": "tool.completed", "actor": "agent", "data": {"command": "x"}},
               {"type": "tool.failed", "actor": "agent", "data": {"error": "y"}},
               {"type": "tool.completed", "actor": "human"}]
    session = _envelope({"session_id": "s", "plan": None, "recent_activity": history})
    projected = compact_native_result("session_manage", {}, session)["data"]
    assert projected == {"session_id": "s", "recent_activity": history[1:], "omitted_activity_count": 1}
    assert compact_native_result("session_manage", {"verbose": True}, session)["data"] == session["data"]


def test_machine_and_job_list_keep_actionable_metadata():
    row = {"name": "worker", "status": "online", "last_seen": 123,
           "offline_after_s": 30, "reset_generation": 1, "queue_depth": 0,
           "interactive_queue_depth": 0, "transfer_queue_depth": 0,
           "capabilities": ["shell"], "info": {"gpu": "AMD"}}
    raw = _envelope({"machines": [row]})
    compact = compact_native_result("remote_manage", {"action": "list"}, raw)["data"]["machines"][0]
    assert compact == {key: row[key] for key in ("name", "status", "queue_depth", "capabilities", "info")}
    assert compact_native_result("remote_manage", {"action": "list", "verbose": True}, raw)["data"] == raw["data"]
    assert compact_native_result("remote_manage", {"action": "reset"}, raw)["data"] == raw["data"]
    jobs = _envelope({"jobs": [{"job_id": "j", "command_truncated": True, "log_truncated": False,
                                "name": None, "error": "failure"}], "next_offset": 2})
    assert compact_native_result("job_list", {}, jobs)["data"] == {
        "jobs": [{"job_id": "j", "command_truncated": True, "error": "failure"}], "next_offset": 2}


@pytest.mark.parametrize("name", ["mcp_tool_call", "file_read", "browser_act"])
def test_user_data_is_never_recursively_stripped(name):
    data = {"message": "", "value": None, "truncated": False, "command": "x", "rows": []}
    assert compact_native_result(name, {}, _envelope(data))["data"] == data
    error = {"ok": False, "message": "", "data": data}
    assert compact_native_result(name, {}, error) is error
    assert ToolResult.model_validate(error).model_dump() == error


@pytest.mark.asyncio
async def test_actual_mcp_schema_and_both_result_representations(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".lsm"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    try:
        async def fake_shell(*args):
            return CommandResult(ok=True, exit_code=0, duration_ms=1, cwd=".",
                                 command=args[0], stdout="hello")
        monkeypatch.setattr("local_shell_mcp.tools.public_run_shell", fake_shell)
        mcp = build_mcp()
        tools = {tool.name: tool for tool in await mcp.list_tools()}
        content, structured = await mcp.call_tool("run_shell", {"command": "echo hello"})
        assert json.loads(content[0].text) == structured
        assert structured == {"ok": True, "data": {"exit_code": 0, "duration_ms": 1, "stdout": "hello"}}
        jsonschema.validate(structured, tools["run_shell"].outputSchema)
        for name in ("job_tail", "session_manage", "remote_manage"):
            assert tools[name].inputSchema["properties"]["verbose"]["default"] is False
    finally:
        get_settings.cache_clear()
