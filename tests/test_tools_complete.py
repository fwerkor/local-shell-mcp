from __future__ import annotations

import asyncio
import subprocess

import pytest
from mcp.types import CallToolResult

import local_shell_mcp.downloads as downloads
import local_shell_mcp.tools as tools
from local_shell_mcp.errors import PathNotFoundError
from local_shell_mcp.models import CommandResult
from local_shell_mcp.settings import get_settings


def _configure(
    tmp_path,
    monkeypatch,
    *,
    remote_enabled: bool = True,
    disable_local: bool = False,
):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", str(remote_enabled).lower())
    monkeypatch.setenv("LOCAL_SHELL_MCP_DISABLE_LOCAL", str(disable_local).lower())
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "http://testserver")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_disable_local_requires_remote_targets_and_hides_local_only_tools(
    tmp_path, monkeypatch
):
    _configure(tmp_path, monkeypatch, disable_local=True)
    manager = FakeRemoteManager()
    monkeypatch.setattr(tools, "remote_manager", lambda: manager)
    mcp = tools.build_mcp()

    for name in tools.LOCAL_ONLY_TOOL_NAMES:
        assert name not in mcp._tool_manager._tools

    local_result = await mcp._tool_manager._tools["run_shell"].fn(command="pwd")
    assert local_result.isError is True
    assert "Local access is disabled" in local_result.structuredContent["message"]

    explicit_local_result = await mcp._tool_manager._tools["run_shell"].fn(
        command="pwd", machine="local"
    )
    assert explicit_local_result["ok"] is True
    assert manager.calls[-1][0:2] == ("local", "run_shell_tool")

    remote_result = await mcp._tool_manager._tools["run_shell"].fn(command="pwd", machine="node")
    assert remote_result["ok"] is True
    assert manager.calls[-1][0:2] == ("node", "run_shell_tool")
    assert manager.calls[-1][2]["command"] == "pwd"

    transfer_result = await mcp._tool_manager._tools["remote_transfer"].fn(
        source_path="a",
        destination_path="b",
        source_machine="node",
    )
    assert transfer_result.isError is True
    assert "both remote endpoints" in transfer_result.structuredContent["message"]

    job_list_result = await mcp._tool_manager._tools["job_list"].fn()
    assert job_list_result["ok"] is True
    assert job_list_result["data"]["jobs"] == []

    local_job_result = await mcp._tool_manager._tools["job_start"].fn(command="echo nope")
    assert local_job_result.isError is True
    assert "Local access is disabled" in local_job_result.structuredContent["message"]


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


def _handled_error_data(result: CallToolResult) -> dict:
    assert result.isError is True
    assert result.structuredContent["ok"] is False
    return result.structuredContent["data"]


@pytest.mark.asyncio
async def test_dynamic_mcp_downstream_error_is_exposed_as_tool_error(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    async def fake_call(_self, name, arguments=None, *, timeout_s=None):
        return {
            "name": name,
            "result": {
                "content": [{"type": "text", "text": "downstream failed"}],
                "isError": True,
            },
        }

    monkeypatch.setattr(tools.DynamicMCPManager, "call", fake_call)
    mcp = tools.build_mcp()
    result = await _raw_tool(mcp, "mcp_tool_call")("demo:fail", {"x": 1})
    data = _handled_error_data(result)
    assert data["name"] == "demo:fail"
    assert data["result"]["isError"] is True


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
    monkeypatch.setattr(
        tools, "run_shell", lambda *args, **kwargs: asyncio.sleep(0, result=_result())
    )
    monkeypatch.setattr(
        tools, "public_run_shell", lambda *args, **kwargs: asyncio.sleep(0, result=_result())
    )
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
        "_start_transfer_job",
        "_secret_scan",
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
    ):
        monkeypatch.setattr(tools, name, sync_value)

    monkeypatch.setattr(tools, "_view_image_result", image_value)
    monkeypatch.setattr(tools, "manage_chat_dispatch", sync_value)
    monkeypatch.setattr(downloads, "create_share_link", sync_value)
    monkeypatch.setattr(downloads, "list_share_links", sync_value)
    monkeypatch.setattr(downloads, "revoke_share_link", sync_value)

    mcp = tools.build_mcp()
    local_cases = {
        "workspace_open": {"session_id": None},
        "open_live_workspace": {},
        "live_workspace_reconnect": {"live_id": "missing-live-id"},
        "environment_get": {},
        "skill_list": {},
        "skill_load": {"name": "skill"},
        "skill_read": {"name": "skill", "path": "guide.md"},
        "run_shell": {"command": "true", "purpose": "test", "explanation": "coverage"},
        "run_python": {"code": "print(1)", "purpose": "test"},
        "shell_start": {"purpose": "test"},
        "shell_send": {"session_id": "s", "input_text": "x"},
        "shell_read": {"session_id": "s"},
        "shell_stop": {"session_id": "s"},
        "shell_list": {},
        "job_start": {"command": "true", "purpose": "test"},
        "job_list": {"include_finished": False, "limit": 7},
        "job_tail": {"job_id": "j"},
        "job_stop": {"job_id": "j"},
        "job_retry": {"job_id": "j", "purpose": "test"},
        "file_list": {},
        "file_tree": {},
        "file_glob": {"pattern": "*.py"},
        "file_grep": {"query": "x"},
        "file_read": {"path": "x"},
        "image_view": {"path": "found.png"},
        "link_create": {"path": "found.txt"},
        "link_list": {},
        "link_revoke": {"token": "t"},
        "file_write": {"path": "x", "content": "y", "purpose": "test"},
        "file_edit": {"path": "x", "edits": [], "purpose": "test"},
        "file_delete": {"path": "x", "purpose": "test"},
        "file_patch": {"patch": "diff", "purpose": "test"},
        "remote_transfer": {
            "source_path": "a",
            "destination_path": "b",
            "destination_machine": "node",
            "purpose": "test",
        },
        "secret_scan": {},
        "session_manage": {"action": "get", "session_id": "missing"},
        "plan_manage": {"action": "get", "session_id": "missing"},
        "mcp_manage": {"action": "list"},
        "mcp_tool_search": {},
        "mcp_tool_inspect": {"name": "missing:tool"},
        "mcp_tool_call": {"name": "missing:tool"},
        "browser_session": {"action": "list"},
        "browser_snapshot": {"session_id": "missing"},
        "browser_act": {"session_id": "missing", "actions": [{"action": "wait"}]},
        "browser_run_script": {"script": "print(1)"},
        "chat_dispatch": {"action": "status"},
        "audit_tail": {},
        "remote_manage": {"action": "list"},
    }
    assert set(local_cases) == set(mcp._tool_manager._tools)
    for name, kwargs in local_cases.items():
        result = await _raw_tool(mcp, name)(**kwargs)
        assert result is not None, name

    invite = await _raw_tool(mcp, "remote_manage")(
        action="invite", name="node", workdir="/workspace", ttl_s=120
    )
    assert invite["ok"] is True
    assert invite["data"] == {"name": "node", "workdir": "/workspace", "ttl_s": 120}
    renamed = await _raw_tool(mcp, "remote_manage")(
        action="rename", machine="node", new_name="renamed"
    )
    assert renamed["ok"] is True
    assert renamed["data"] == {"old_name": "node", "new_name": "renamed"}
    revoked = await _raw_tool(mcp, "remote_manage")(action="revoke", machine="node")
    assert revoked["ok"] is True
    assert revoked["data"] == {"machine": "node", "revoked": True}
    invalid = await _raw_tool(mcp, "remote_manage")(action="rename", machine="node")
    assert invalid.isError is True
    assert _handled_error_data(invalid)["message"] == "new_name is required for action=rename"

    remote_cases = {
        "environment_get": {},
        "run_shell": {"command": "true"},
        "run_python": {"code": "print(1)"},
        "shell_start": {},
        "shell_send": {"session_id": "s", "input_text": "x"},
        "shell_read": {"session_id": "s"},
        "shell_stop": {"session_id": "s"},
        "shell_list": {},
        "job_start": {"command": "true"},
        "job_list": {"include_finished": False, "limit": 7},
        "job_tail": {"job_id": "j"},
        "job_stop": {"job_id": "j"},
        "job_retry": {"job_id": "j"},
        "file_list": {},
        "file_tree": {},
        "file_glob": {"pattern": "*"},
        "file_grep": {"query": "x"},
        "file_read": {"path": "x"},
        "image_view": {"path": "x"},
        "file_write": {"path": "x", "content": "y"},
        "file_edit": {"path": "x", "edits": []},
        "file_delete": {"path": "x"},
        "file_patch": {"patch": "diff"},
        "browser_session": {"action": "list"},
        "browser_snapshot": {"session_id": "s"},
        "browser_act": {"session_id": "s", "actions": [{"action": "wait"}]},
        "browser_run_script": {"script": "x"},
    }
    for name, kwargs in remote_cases.items():
        result = await _raw_tool(mcp, name)(**kwargs, machine="node")
        assert result["ok"] is True, name
    assert len(fake_remote.calls) == len(remote_cases) - 1
    assert all(tool != "view_image" for _, tool, _, _ in fake_remote.calls)
    job_list_call = next(call for call in fake_remote.calls if call[1] == "job_list")
    assert job_list_call[2] == {"include_finished": False, "limit": 7}


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
    monkeypatch.setattr(tools, "_start_transfer_job", fail_async)
    monkeypatch.setattr(tools, "_secret_scan", fail_async)
    monkeypatch.setattr(tools, "playwright_run_script", fail_async)
    monkeypatch.setattr(tools, "_read_audit_tail_entries", fail_sync)
    fake_remote = FakeRemoteManager()
    monkeypatch.setattr(tools, "remote_manager", lambda: fake_remote)

    mcp = tools.build_mcp()
    checks = [
        ("environment_get", {}),
        ("skill_list", {}),
        ("run_shell", {"command": "x"}),
        ("run_python", {"code": "x"}),
        ("shell_start", {}),
        ("shell_send", {"session_id": "s", "input_text": "x"}),
        ("shell_read", {"session_id": "s"}),
        ("shell_stop", {"session_id": "s"}),
        ("shell_list", {}),
        ("job_start", {"command": "x"}),
        ("job_list", {}),
        ("job_tail", {"job_id": "j"}),
        ("job_stop", {"job_id": "j"}),
        ("job_retry", {"job_id": "j"}),
        ("file_list", {}),
        ("file_tree", {}),
        ("file_glob", {"pattern": "*"}),
        ("file_grep", {"query": "x"}),
        ("file_read", {"path": "x"}),
        ("file_write", {"path": "x", "content": "y"}),
        ("file_edit", {"path": "x", "edits": []}),
        ("file_delete", {"path": "x"}),
        ("file_patch", {"patch": "x"}),
        ("remote_transfer", {"source_path": "a", "destination_path": "b"}),
        ("secret_scan", {}),
        ("browser_run_script", {"script": "x"}),
        ("audit_tail", {}),
    ]
    for name, kwargs in checks:
        result = await _raw_tool(mcp, name)(**kwargs)
        assert isinstance(result, CallToolResult), name
        assert _handled_error_data(result)["status"] == "error", name

    _configure(tmp_path, monkeypatch, remote_enabled=False)
    disabled = tools.build_mcp()
    assert not any(name.startswith("remote_") for name in disabled._tool_manager._tools)


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

    managed = tools._safe_audit_call_arguments(
        "mcp_manage",
        {
            "action": "env_set",
            "name": "demo",
            "env": {"TOKEN": "secret"},
            "headers": {"Authorization": "Bearer secret"},
            "value": "secret",
        },
    )
    assert managed["env"] == {"TOKEN": "<redacted>"}
    assert managed["headers"] == {"Authorization": "<redacted>"}
    assert managed["value"] == "<redacted>"
    dynamic_call = tools._safe_audit_call_arguments(
        "mcp_tool_call", {"name": "demo:tool", "arguments": {"token": "secret"}, "timeout_s": 5}
    )
    assert dynamic_call == {"name": "demo:tool", "argument_keys": ["token"], "timeout_s": 5}
    browser_call = tools._safe_audit_call_arguments(
        "browser_act",
        {
            "session_id": "s",
            "actions": [{"action": "fill", "target": "e1", "value": "secret"}],
        },
    )
    assert browser_call["actions"][0]["value"] == "<redacted>"

    assert tools._audit_tool_purpose("x", "  purpose ", " explanation ") == {
        "purpose": "purpose",
        "explanation": "explanation",
    }
    assert tools._audit_tool_purpose("x", " ", None) == {}
    assert tools._live_event_arguments(
        "run_shell",
        {
            "cwd": "/workspace",
            "purpose": "Run the focused tests",
            "explanation": "Validate the Activity metadata change before pushing",
            "command": "pytest -q",
        },
    ) == {
        "tool": "run_shell",
        "cwd": "/workspace",
        "purpose": "Run the focused tests",
        "command": "pytest -q",
    }
    with pytest.raises(ValueError, match="purpose"):
        tools._audit_tool_purpose("x", "x" * 501)
    with pytest.raises(ValueError, match="explanation"):
        tools._audit_tool_purpose("x", explanation="x" * 2001)

    generic = tools._timeout_payload_for_tool("other", TimeoutError("x"))
    assert isinstance(generic, CallToolResult)
    assert _handled_error_data(generic)["status"] == "error"

    audit_path = tmp_path / "audit.jsonl"
    audit_path.write_text('{"event":"one"}\ninvalid\n{"event":"three"}\n', encoding="utf-8")
    tail = tools._read_audit_tail_entries(2)
    assert tail["entries"] == [{"raw": "invalid"}, {"event": "three"}]
    assert tail["bytes_read"] > 0
    audit_path.unlink()
    assert tools._read_audit_tail_entries(10) == {"entries": []}


@pytest.mark.asyncio
async def test_apply_patch_stops_after_failed_preflight(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    target = tmp_path / "sample.py"
    original = "value = 1\n"
    target.write_text(original, encoding="utf-8")
    commands: list[str] = []

    async def fail_check(command, **kwargs):
        commands.append(command)
        return CommandResult(
            ok=False,
            exit_code=1,
            timed_out=False,
            duration_ms=1,
            cwd=str(tmp_path),
            command=command,
            stdout="",
            stderr="patch does not apply",
            truncated=False,
        )

    monkeypatch.setattr(tools, "run_shell", fail_check)
    patch = """*** Begin Patch
*** Update File: sample.py
@@
-value = 1
+value = 2
*** End Patch
"""

    result = await tools._apply_patch_text(patch, str(tmp_path))

    assert result["exit_code"] == 1
    assert len(commands) == 1
    assert " apply --check" in commands[0]
    assert "&&" not in commands[0]
    assert target.read_text(encoding="utf-8") == original


@pytest.mark.asyncio
async def test_apply_patch_honors_nested_cwd_in_git_worktree(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    nested = tmp_path / "nested dir"
    nested.mkdir()
    target = nested / "sample.py"
    target.write_text(
        "def helper():\n    return 0\n\n\ndef target():\n    return 1\n",
        encoding="utf-8",
    )
    patch = """*** Begin Patch
*** Update File: sample.py
@@
 def target():
@@
-    return 1
+    return 2
*** End Patch
"""

    result = await tools._apply_patch_text(patch, str(nested))

    assert result["exit_code"] == 0, result
    assert target.read_text(encoding="utf-8").endswith("def target():\n    return 2\n")


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
    result = tools._handled_error(PathNotFoundError("missing.txt"))
    assert _handled_error_data(result)["status"] == "not_found"
    assert _handled_error_data(result)["path"].endswith("missing.txt")
    generic = tools._handled_error(ValueError("bad"))
    assert _handled_error_data(generic)["error_type"] == "ValueError"

    async def value():
        return 42

    loop = asyncio.new_event_loop()
    monkeypatch.setattr(asyncio, "get_event_loop", lambda: loop)
    try:
        assert tools._sync(value()) == 42
    finally:
        loop.close()


@pytest.mark.asyncio
async def test_remote_shell_failure_returns_mcp_error(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    class FailedRemoteManager:
        async def call(self, machine, tool, args, timeout_s=None):  # noqa: ARG002
            return {
                "ok": False,
                "message": "Shell executable not found: missing-shell",
                "data": {
                    "status": "executable_not_found",
                    "error_type": "FileNotFoundError",
                    "message": "Shell executable not found: missing-shell",
                    "executable": "missing-shell",
                    "command": "echo ok",
                    "cwd": "/workspace",
                    "original_error": "[WinError 2]",
                },
            }

    monkeypatch.setattr(tools, "remote_manager", lambda: FailedRemoteManager())

    result = await tools.build_mcp().call_tool(
        "run_shell",
        {"command": "echo ok", "machine": "node"},
    )

    assert isinstance(result, CallToolResult)
    assert result.isError is True
    assert result.structuredContent["ok"] is False
    assert result.structuredContent["data"]["status"] == "executable_not_found"
    assert result.structuredContent["data"]["executable"] == "missing-shell"
