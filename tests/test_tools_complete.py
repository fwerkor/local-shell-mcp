from __future__ import annotations

import asyncio
import json

import pytest

import local_shell_mcp.downloads as downloads
import local_shell_mcp.tools as tools
from local_shell_mcp.models import CommandResult
from local_shell_mcp.settings import get_settings


def _configure(tmp_path, monkeypatch, *, remote_enabled: bool = True):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", str(remote_enabled).lower())
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "http://testserver")
    get_settings.cache_clear()


def _result() -> CommandResult:
    return CommandResult(
        ok=True,
        exit_code=0,
        timed_out=False,
        duration_ms=1,
        cwd=".",
        command="cmd",
        stdout="ok",
        stderr="",
        truncated=False,
    )


def _raw_tool(mcp, name: str):
    wrapped = mcp._tool_manager._tools[name].fn
    original = wrapped.__kwdefaults__["__original"]
    return original


class FakeRemoteManager:
    def __init__(self):
        self.calls = []

    async def call(self, machine, tool, args, timeout_s=None):
        self.calls.append((machine, tool, args, timeout_s))
        return {"ok": True, "message": "", "data": {"tool": tool}}

    async def create_invite(self, name=None, workdir=None, ttl_s=None):
        return {"name": name, "workdir": workdir, "ttl_s": ttl_s}

    def list_machines(self):
        return {"machines": [{"name": "node"}]}

    def revoke(self, machine):
        return {"machine": machine, "revoked": True}

    def rename(self, machine, new_name):
        return {"old_name": machine, "new_name": new_name}


@pytest.mark.asyncio
async def test_all_public_tool_wrappers_local_and_remote(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    (tmp_path / "found.txt").write_text("needle\n", encoding="utf-8")
    fake_remote = FakeRemoteManager()
    monkeypatch.setattr(tools, "remote_manager", lambda: fake_remote)

    async def async_value(*args, **kwargs):
        return {"args": list(args), "kwargs": kwargs}

    async def image_value(*args, **kwargs):
        return {"ok": True, "args": list(args), "kwargs": kwargs}

    def sync_value(*args, **kwargs):
        return {"args": list(args), "kwargs": kwargs}

    async def fake_grep(*args, **kwargs):
        if kwargs.get("regex") is False:
            return {
                "matches": [
                    {"path": "found.txt", "line": 1},
                    {"path": "found.txt", "line": 2},
                    {"path": "", "line": 3},
                ]
            }
        return {"matches": []}

    monkeypatch.setattr(tools, "grep", fake_grep)
    monkeypatch.setattr(tools, "run_shell", lambda *args, **kwargs: asyncio.sleep(0, result=_result()))
    monkeypatch.setattr(tools, "public_run_shell", lambda *args, **kwargs: asyncio.sleep(0, result=_result()))
    for name in (
        "_run_python",
        "start_shell",
        "send_shell",
        "read_shell",
        "kill_shell",
        "list_shells",
        "start_job",
        "list_jobs",
        "tail_job",
        "stop_job",
        "retry_job",
        "tree",
        "_apply_patch_text",
        "_transfer_path",
        "_secret_scan",
        "browser_capture",
        "browser_get_text",
        "playwright_run_script",
    ):
        monkeypatch.setattr(tools, name, async_value)
    for name in (
        "list_installed_skills",
        "load_installed_skill",
        "read_installed_skill_file",
        "list_dir",
        "glob_paths",
        "read_texts",
        "write_text",
        "edit_text",
        "delete_path",
        "todo_read",
        "todo_write",
    ):
        monkeypatch.setattr(tools, name, sync_value)

    monkeypatch.setattr(tools, "_view_image_result", image_value)
    monkeypatch.setattr(downloads, "create_share_link", sync_value)
    monkeypatch.setattr(downloads, "list_share_links", sync_value)
    monkeypatch.setattr(downloads, "revoke_share_link", sync_value)

    mcp = tools.build_mcp()
    local_cases = {
        "search": {"query": "needle"},
        "fetch": {"id": "found.txt"},
        "environment_info": {},
        "skills_list": {},
        "skill_load": {"name": "skill"},
        "skill_read_file": {"name": "skill", "path": "guide.md"},
        "run_shell_tool": {"command": "true", "purpose": "test", "explanation": "coverage"},
        "run_python_tool": {"code": "print(1)", "purpose": "test"},
        "shell_start": {"purpose": "test"},
        "shell_send": {"session_id": "s", "input_text": "x"},
        "shell_read": {"session_id": "s"},
        "shell_kill": {"session_id": "s"},
        "shell_list": {},
        "job_start": {"command": "true", "purpose": "test"},
        "job_list": {},
        "job_tail": {"job_id": "j"},
        "job_stop": {"job_id": "j"},
        "job_retry": {"job_id": "j", "purpose": "test"},
        "list_files": {},
        "tree_view": {},
        "glob_search": {"pattern": "*.py"},
        "grep_search": {"query": "x"},
        "read_file": {"path": "x"},
        "view_image": {"path": "found.png"},
        "create_file_link": {"path": "found.txt"},
        "list_file_links": {},
        "revoke_file_link": {"token": "t"},
        "write_file": {"path": "x", "content": "y", "purpose": "test"},
        "edit_file": {"path": "x", "edits": [], "purpose": "test"},
        "delete_file_or_dir": {"path": "x", "purpose": "test"},
        "apply_patch": {"patch": "diff", "purpose": "test"},
        "transfer_path": {"source_path": "a", "destination_path": "b", "destination_machine": "node", "purpose": "test"},
        "secret_scan": {},
        "todo_read_tool": {},
        "todo_write_tool": {"todos": []},
        "browser_capture_tool": {"url": "https://example.test"},
        "browser_get_text_tool": {"url": "https://example.test"},
        "playwright_run_script_tool": {"script": "print(1)"},
        "audit_tail": {},
        "remote_invite": {"name": "node"},
        "remote_list_machines": {},
        "remote_revoke_machine": {"machine": "node"},
        "remote_rename_machine": {"machine": "node", "new_name": "renamed"},
    }
    assert set(local_cases) == set(mcp._tool_manager._tools)
    for name, kwargs in local_cases.items():
        result = await _raw_tool(mcp, name)(**kwargs)
        assert result is not None, name

    search_payload = json.loads(await _raw_tool(mcp, "search")(query="needle"))
    assert len(search_payload["results"]) == 1
    assert search_payload["results"][0]["title"] == "found.txt:1"

    remote_cases = {
        "environment_info": {},
        "run_shell_tool": {"command": "true"},
        "run_python_tool": {"code": "print(1)"},
        "shell_start": {},
        "shell_send": {"session_id": "s", "input_text": "x"},
        "shell_read": {"session_id": "s"},
        "shell_kill": {"session_id": "s"},
        "shell_list": {},
        "job_start": {"command": "true"},
        "job_list": {},
        "job_tail": {"job_id": "j"},
        "job_stop": {"job_id": "j"},
        "job_retry": {"job_id": "j"},
        "list_files": {},
        "tree_view": {},
        "glob_search": {"pattern": "*"},
        "grep_search": {"query": "x"},
        "read_file": {"path": "x"},
        "view_image": {"path": "x"},
        "write_file": {"path": "x", "content": "y"},
        "edit_file": {"path": "x", "edits": []},
        "delete_file_or_dir": {"path": "x"},
        "apply_patch": {"patch": "diff"},
        "browser_capture_tool": {"url": "https://x"},
        "browser_get_text_tool": {"url": "https://x"},
        "playwright_run_script_tool": {"script": "x"},
    }
    for name, kwargs in remote_cases.items():
        result = await _raw_tool(mcp, name)(**kwargs, machine="node")
        assert result["ok"] is True, name
    assert len(fake_remote.calls) == len(remote_cases) - 1
    assert all(tool != "view_image" for _, tool, _, _ in fake_remote.calls)


@pytest.mark.asyncio
async def test_tool_wrapper_error_paths_and_remote_disabled(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    async def fail_async(*args, **kwargs):
        raise RuntimeError("boom")

    def fail_sync(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(tools, "grep", fail_async)
    monkeypatch.setattr(tools, "read_text", fail_sync)
    monkeypatch.setattr(tools, "run_shell", fail_async)
    monkeypatch.setattr(tools, "list_installed_skills", fail_sync)
    monkeypatch.setattr(tools, "public_run_shell", fail_async)
    monkeypatch.setattr(tools, "_run_python", fail_async)
    monkeypatch.setattr(tools, "start_shell", fail_async)
    monkeypatch.setattr(tools, "send_shell", fail_async)
    monkeypatch.setattr(tools, "read_shell", fail_async)
    monkeypatch.setattr(tools, "kill_shell", fail_async)
    monkeypatch.setattr(tools, "list_shells", fail_async)
    monkeypatch.setattr(tools, "start_job", fail_async)
    monkeypatch.setattr(tools, "list_jobs", fail_async)
    monkeypatch.setattr(tools, "tail_job", fail_async)
    monkeypatch.setattr(tools, "stop_job", fail_async)
    monkeypatch.setattr(tools, "retry_job", fail_async)
    monkeypatch.setattr(tools, "list_dir", fail_sync)
    monkeypatch.setattr(tools, "tree", fail_async)
    monkeypatch.setattr(tools, "glob_paths", fail_sync)
    monkeypatch.setattr(tools, "read_texts", fail_sync)
    monkeypatch.setattr(tools, "write_text", fail_sync)
    monkeypatch.setattr(tools, "edit_text", fail_sync)
    monkeypatch.setattr(tools, "delete_path", fail_sync)
    monkeypatch.setattr(tools, "_apply_patch_text", fail_async)
    monkeypatch.setattr(tools, "_transfer_path", fail_async)
    monkeypatch.setattr(tools, "_secret_scan", fail_async)
    monkeypatch.setattr(tools, "todo_read", fail_sync)
    monkeypatch.setattr(tools, "todo_write", fail_sync)
    monkeypatch.setattr(tools, "browser_capture", fail_async)
    monkeypatch.setattr(tools, "browser_get_text", fail_async)
    monkeypatch.setattr(tools, "playwright_run_script", fail_async)
    monkeypatch.setattr(tools, "_read_audit_tail_entries", fail_sync)
    fake_remote = FakeRemoteManager()
    monkeypatch.setattr(tools, "remote_manager", lambda: fake_remote)

    mcp = tools.build_mcp()
    checks = [
        ("search", {"query": "x"}),
        ("fetch", {"id": "missing"}),
        ("environment_info", {}),
        ("skills_list", {}),
        ("run_shell_tool", {"command": "x"}),
        ("run_python_tool", {"code": "x"}),
        ("shell_start", {}),
        ("shell_send", {"session_id": "s", "input_text": "x"}),
        ("shell_read", {"session_id": "s"}),
        ("shell_kill", {"session_id": "s"}),
        ("shell_list", {}),
        ("job_start", {"command": "x"}),
        ("job_list", {}),
        ("job_tail", {"job_id": "j"}),
        ("job_stop", {"job_id": "j"}),
        ("job_retry", {"job_id": "j"}),
        ("list_files", {}),
        ("tree_view", {}),
        ("glob_search", {"pattern": "*"}),
        ("grep_search", {"query": "x"}),
        ("read_file", {"path": "x"}),
        ("write_file", {"path": "x", "content": "y"}),
        ("edit_file", {"path": "x", "edits": []}),
        ("delete_file_or_dir", {"path": "x"}),
        ("apply_patch", {"patch": "x"}),
        ("transfer_path", {"source_path": "a", "destination_path": "b"}),
        ("secret_scan", {}),
        ("todo_read_tool", {}),
        ("todo_write_tool", {"todos": []}),
        ("browser_capture_tool", {"url": "x"}),
        ("browser_get_text_tool", {"url": "x"}),
        ("playwright_run_script_tool", {"script": "x"}),
        ("audit_tail", {}),
    ]
    for name, kwargs in checks:
        result = await _raw_tool(mcp, name)(**kwargs)
        if name in {"search", "fetch"}:
            assert isinstance(result, str)
        else:
            assert result["data"]["status"] == "error", name

    _configure(tmp_path, monkeypatch, remote_enabled=False)
    disabled = tools.build_mcp()
    assert not any(
        name.startswith("remote_") or name == "transfer_path"
        for name in disabled._tool_manager._tools
    )


def test_tool_helpers_audit_serialization_timeout_and_tail(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    assert tools._serialize_audit_value("x" * 501) == "x" * 501
    assert tools._serialize_audit_value((1, 2)) == [1, 2]
    serialized = tools._serialize_audit_value(
        {
            "token": "secret",
            "content": "body",
            "safe": {"nested": "value"},
            "items": list(range(30)),
            "object": object(),
        }
    )
    assert serialized["token"] == "secret"
    assert serialized["content"] == "body"
    assert len(serialized["items"]) == 30
    assert "object at" in serialized["object"]
    assert tools._audit_tool_arguments((1, 2), {"password": "x"})["positional_count"] == 2

    assert tools._audit_tool_purpose("x", "  purpose ", " explanation ") == {
        "purpose": "purpose",
        "explanation": "explanation",
    }
    assert tools._audit_tool_purpose("x", " ", None) == {}
    with pytest.raises(ValueError, match="purpose"):
        tools._audit_tool_purpose("x", "x" * 501)
    with pytest.raises(ValueError, match="explanation"):
        tools._audit_tool_purpose("x", explanation="x" * 2001)

    search = json.loads(tools._timeout_payload_for_tool("search", TimeoutError("x")))
    assert search == {"results": []}
    fetch = json.loads(tools._timeout_payload_for_tool("fetch", TimeoutError("x")))
    assert fetch["metadata"]["error"] == "TimeoutError"
    generic = tools._timeout_payload_for_tool("other", TimeoutError("x"))
    assert generic["data"]["status"] == "error"

    audit_path = tmp_path / "audit.jsonl"
    audit_path.write_text(
        '{"event":"one"}\ninvalid\n{"event":"three"}\n', encoding="utf-8"
    )
    tail = tools._read_audit_tail_entries(2)
    assert tail["entries"] == [{"raw": "invalid"}, {"event": "three"}]
    assert tail["bytes_read"] > 0
    audit_path.unlink()
    assert tools._read_audit_tail_entries(10) == {"entries": []}


def test_transport_security_secret_helpers_and_remote_unwrap(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    security = tools._transport_security_settings()
    assert "testserver:*" in security.allowed_hosts
    assert "http://testserver" in security.allowed_origins

    base = tmp_path / "repo"
    base.mkdir()
    (base / ".gitignore").write_text("ignored.txt\n!visible/ignored.txt\n", encoding="utf-8")
    (base / "ignored.txt").write_text("x", encoding="utf-8")
    (base / "visible").mkdir()
    visible = base / "visible" / "ignored.txt"
    visible.write_text("x", encoding="utf-8")
    cache = {}
    assert tools._fallback_path_is_ignored(base / "ignored.txt", base, cache)
    assert not tools._fallback_path_is_ignored(visible, base, cache)
    assert tools._gitignore_spec(base, cache) is not None
    assert tools._gitignore_spec(tmp_path / "missing", {}) is None

    assert tools._is_placeholder_secret_match("generic_assignment", 'token="dummy-value"')
    assert not tools._is_placeholder_secret_match("github_token", "ghp_abc")
    assert not tools._is_placeholder_secret_match("generic_assignment", 'token="real-value"')

    assert tools._unwrap_remote_transfer_result(
        {"ok": True, "data": {"value": 1}}, machine="node", tool="stat"
    ) == {"value": 1}
    with pytest.raises(tools.RemoteTransferError, match="failed"):
        tools._unwrap_remote_transfer_result(
            {"ok": False, "message": "bad"}, machine="node", tool="stat"
        )
    with pytest.raises(tools.RemoteTransferError, match="Boom"):
        tools._unwrap_remote_transfer_result(
            {"ok": True, "data": {"status": "error", "error_type": "Boom", "message": "bad"}},
            machine="node",
            tool="stat",
        )


def test_handled_error_missing_path_and_sync(monkeypatch, tmp_path):
    _configure(tmp_path, monkeypatch)
    result = tools._handled_error(FileNotFoundError("missing.txt"))
    assert result["data"]["status"] == "not_found"
    assert result["data"]["path"].endswith("missing.txt")
    generic = tools._handled_error(ValueError("bad"))
    assert generic["data"]["error_type"] == "ValueError"

    async def value():
        return 42

    loop = asyncio.new_event_loop()
    monkeypatch.setattr(asyncio, "get_event_loop", lambda: loop)
    try:
        assert tools._sync(value()) == 42
    finally:
        loop.close()
