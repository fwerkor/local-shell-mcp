"""Controller-side metadata projection is reversible through verbose mode."""

from copy import deepcopy

import pytest

from local_shell_mcp.result_compaction import compact_native_result


def envelope(data):
    return {"ok": True, "data": data}


PLAN = {
    "plan_id": "p", "status": "active", "objective": "work", "steps": [{"id": "s", "status": "active"}],
    "revision": 2, "continuation_claim_id": "claim", "continuation_reserved": True,
    "in_flight_calls": 1, "execution_lease_s": 900, "last_agent_activity": 20,
    "continuation_count": 2, "continuation_due": False,
}
FILE = {
    "path": "a", "content": "hello", "bytes": 5, "bytes_read": 5, "binary": False,
    "truncated": False, "truncated_bytes": 0, "sha256": "hash", "total_lines": 1,
}
FILE_COMPACT = {"path": "a", "content": "hello", "bytes": 5, "total_lines": 1}
PLAN_COMPACT = {
    key: value for key, value in PLAN.items()
    if key not in {"revision", "continuation_claim_id", "continuation_reserved", "in_flight_calls",
                   "execution_lease_s", "last_agent_activity"}
}
SERVER = {
    "name": "one", "transport": "stdio", "command": "run", "args": [], "cwd": None,
    "url": None, "header_keys": [], "env_keys": ["TOKEN"], "enabled": True, "tool_count": 2,
}
BROWSER = {
    "page_id": "p1", "title": "title", "url": "url",
    "pages": [{"page_id": "p1", "title": "title", "url": "url"},
              {"page_id": "p2", "title": "other", "url": "other"}],
    "errors": [], "network": [], "text_truncated": False, "screenshot_path": None,
    "text": "text", "interactive_elements": [{"ref": "e1", "title": "action"}],
}


@pytest.mark.parametrize("name,args,raw,expected", [
    ("file_read", {}, FILE, FILE_COMPACT),
    ("file_read", {}, {"files": [FILE, {"path": "b", "binary": True, "content": None,
                                        "message": "binary", "preview": "ff"}], "total_content_bytes": 7},
     {"files": [FILE_COMPACT, {"path": "b", "binary": True, "content": None,
                               "message": "binary", "preview": "ff"}], "total_content_bytes": 7}),
    ("file_list", {}, [{"path": "a", "type": "dir", "size": None, "modified": 1},
                        {"path": "b", "type": "link", "size": 2, "modified": 1, "target": "a"}],
     [{"path": "a", "type": "dir"}, {"path": "b", "type": "link", "size": 2, "target": "a"}]),
    ("file_grep", {}, {"ok": True, "matches": [{"text": "x"}], "count": 1, "stderr": "", "truncated": False},
     {"matches": [{"text": "x"}]}),
    ("file_tree", {}, {"exists": True, "is_directory": True, "root": "a", "entries": ["b"],
                       "count": 1, "truncated": False}, {"root": "a", "entries": ["b"]}),
    ("job_list", {}, {"jobs": [{"job_id": "j", "status": "running", "backend": "native",
                                "session_id": "s", "attempts": 1, "exit_code": None}], "next_offset": 1},
     {"jobs": [{"job_id": "j", "status": "running"}], "next_offset": 1}),
    ("job_tail", {"job_id": "j"}, {"job": {"job_id": "j", "status": "running", "output_bytes": 6,
                                          "exit_code": None}, "output": "output"},
     {"job": {"status": "running"}, "output": "output"}),
    ("shell_list", {}, {"sessions": [{"session_id": "s", "backend": "native", "attached": "0"},
                                    {"session_id": "t", "backend": "tmux", "attached": "1"}]},
     {"sessions": [{"session_id": "s"}, {"session_id": "t", "attached": "1"}]}),
    ("shell_read", {"session_id": "s"}, {"session_id": "s", "output": "x"}, {"output": "x"}),
    ("shell_stop", {}, {"session_id": "s", "killed": True, "stderr": ""},
     {"session_id": "s", "killed": True}),
    ("plan_manage", {}, {"session_id": "s", "goal_mode": True, "plan": PLAN},
     {"session_id": "s", "goal_mode": True, "plan": PLAN_COMPACT}),
    ("session_manage", {}, {"session_id": "s", "plan": PLAN, "progress": {
        "summary": None, "findings": [], "next": None, "blockers": [], "updated_at": None}},
     {"session_id": "s", "plan": PLAN_COMPACT}),
    ("skill_list", {}, {"skills_dir": "/skills", "skills_dirs": ["/skills"], "warnings": [],
                         "skills": [{"name": "s", "description": "desc", "source": "managed",
                                     "entry_path": "SKILL.md", "source_path": "/skills",
                                     "related_files": ["x"]}]},
     {"skills": [{"name": "s", "description": "desc", "source": "managed"}]}),
    ("skill_load", {}, {"skills_dirs": [], "skills_dir": "/skills", "name": "s", "content": "body",
                         "related_files": ["x"], "warnings": ["warning"]},
     {"name": "s", "content": "body", "related_files": ["x"], "warnings": ["warning"]}),
    ("mcp_tool_search", {}, {"tools": [{"name": "one:two", "server": "one", "tool": "two",
                                       "title": None, "description": "desc"}],
                             "count": 1, "total_matches": 2, "unrefreshed_servers": []},
     {"tools": [{"name": "one:two", "description": "desc"}], "total_matches": 2}),
    ("mcp_manage", {}, {"servers": [SERVER]}, {"servers": [
        {key: val for key, val in SERVER.items() if key not in {"url", "header_keys"}}]}),
    ("browser_snapshot", {}, BROWSER, {
        **{key: val for key, val in BROWSER.items() if key not in {
            "errors", "network", "text_truncated", "screenshot_path", "pages"}},
        "pages": [{"page_id": "p1"}, {"page_id": "p2", "title": "other", "url": "other"}]}),
    ("browser_act", {}, {"page_id": "p1", "title": "title", "url": "url", "pages": BROWSER["pages"],
                          "results": [{"action": "click"}]},
     {"page_id": "p1", "title": "title", "url": "url", "pages": [
         {"page_id": "p1"}, {"page_id": "p2", "title": "other", "url": "other"}],
      "results": [{"action": "click"}]}),
    ("environment_get", {}, {"version": "v", "settings": {"workspace_root": "/w", "max_output_bytes": 100,
       "auth_mode": "oauth", "command_denylist": ["a"], "python_bin": "python", "ui_port": 10},
       "probe": {"ok": True, "exit_code": 0, "command": "cmd", "stdout": "x", "stderr": "",
                 "timed_out": False, "truncated": False}},
     {"version": "v", "settings": {"workspace_root": "/w", "max_output_bytes": 100,
       "auth_mode": "oauth", "command_denylist": ["a"], "python_bin": "python"},
      "probe": {"exit_code": 0, "stdout": "x"}}),
])
def test_compact_metadata_and_verbose_roundtrip(name, args, raw, expected):
    original = envelope(raw)
    before = deepcopy(original)
    assert compact_native_result(name, args, original) == envelope(expected)
    assert compact_native_result(name, {**args, "verbose": True}, original) == original
    assert original == before


def test_remote_protocol_details_only_in_verbose():
    raw = envelope({"machines": [{
        "name": "worker", "status": "online", "workdir": "/work", "info": {
            "workdir": "/work", "poll_protocol_version": 7, "persistent_shell": {
                "backend": "native", "socket_name": "lsm", "tmux_helper_version": None,
                "durable_across_server_restart": False, "warning": "not durable"},
            "cpu_percent": 42, "sample_generation": "a", "sample_sequence": 2},
        "capabilities": ["shell"]}]})
    compact = compact_native_result("remote_list", {}, raw)["data"]["machines"][0]
    assert compact["info"] == {"persistent_shell": {"backend": "native",
        "durable_across_server_restart": False, "warning": "not durable"}, "cpu_percent": 42}
    verbose = compact_native_result("remote_list", {"verbose": True}, raw)["data"]["machines"][0]
    assert verbose["info"]["poll_protocol_version"] == 7
    assert verbose["info"]["workdir"] == "/work"
    assert "capabilities" not in verbose and "sample_generation" not in verbose["info"]
    assert "sample_sequence" not in verbose["info"]


def test_keep_errors_truncation_and_nondefault_metadata():
    failed = {"ok": False, "matches": [], "count": 0, "stderr": "permission denied", "truncated": False}
    assert compact_native_result("file_grep", {}, envelope(failed)) == envelope(failed)
    missing = {"exists": False, "is_directory": False, "entries": [], "message": "missing", "count": 0}
    assert compact_native_result("file_tree", {}, envelope(missing)) == envelope(missing)
    truncated = {**FILE, "bytes_read": 3, "truncated_bytes": 2, "truncated": True, "sha256": None}
    result = compact_native_result("file_read", {}, envelope(truncated))["data"]
    assert result["truncated"] and result["truncated_bytes"] == 2 and result["bytes_read"] == 3
    warning = {"ok": True, "matches": [], "count": 0, "stderr": "warning", "truncated": True}
    assert compact_native_result("file_grep", {}, envelope(warning))["data"] == {
        "matches": [], "stderr": "warning", "truncated": True}
    raw = envelope({"job": {"job_id": "other", "status": "failed", "error": "failure",
                            "exit_code": 1, "log_truncated": True, "attempts": 2}, "output": "error"})
    assert compact_native_result("job_tail", {"job_id": "j"}, raw) == raw
    external = envelope({"result": {"content": FILE, "plan": PLAN, "machines": []}})
    assert compact_native_result("mcp_tool_call", {}, external) is external


@pytest.mark.asyncio
async def test_actual_file_read_and_list_metadata(tmp_path, monkeypatch):
    import json

    from local_shell_mcp.settings import get_settings
    from local_shell_mcp.tools import build_mcp

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".lsm"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    try:
        (tmp_path / "a.txt").write_text("hello")
        mcp = build_mcp()
        for name, args in (("file_read", {"path": "a.txt"}), ("file_list", {"path": "."})):
            content, compact = await mcp.call_tool(name, args)
            assert json.loads(content[0].text) == compact
            content, verbose = await mcp.call_tool(name, {**args, "verbose": True})
            assert json.loads(content[0].text) == verbose
            assert compact_native_result(name, args, verbose) == compact
            if name == "file_read":
                assert "sha256" not in compact["data"] and "sha256" in verbose["data"]
            else:
                assert all("modified" not in row for row in compact["data"])
                assert all("modified" in row for row in verbose["data"])
    finally:
        get_settings.cache_clear()
