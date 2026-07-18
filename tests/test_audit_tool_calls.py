import json
import sys

import pytest
from mcp.types import CallToolResult, TextContent

from local_shell_mcp.audit import audit_result_ok
from local_shell_mcp.settings import get_settings
from local_shell_mcp.shell_ops import quote_shell_argument
from local_shell_mcp.tools import _audit_tool_arguments, build_mcp


@pytest.mark.asyncio
async def test_mcp_tool_calls_are_audited(tmp_path, monkeypatch):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUDIT_LOG_PATH", str(audit_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()

    await build_mcp().call_tool("list_files", {"path": "."})

    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    starts = [record for record in records if record["event"] == "mcp_tool_call_start"]
    ends = [record for record in records if record["event"] == "mcp_tool_call_end"]

    assert starts[-1]["tool"] == "list_files"
    assert starts[-1]["arguments"]["keyword_args"]["path"] == "."
    assert starts[-1]["call_id"] == ends[-1]["call_id"]
    assert ends[-1]["tool"] == "list_files"
    assert ends[-1]["ok"] is True
    assert ends[-1]["duration_ms"] >= 0
    assert ends[-1]["result"]["ok"] is True


def test_audit_result_status_uses_nested_tool_outcome():
    assert audit_result_ok({"ok": True, "data": {"ok": True}}) is True
    assert audit_result_ok({"ok": True, "data": {"ok": False}}) is False
    assert audit_result_ok({"ok": True, "data": {"status": "error"}}) is False
    assert audit_result_ok(
        CallToolResult(
            content=[TextContent(type="text", text="failed")],
            structuredContent={"ok": False},
            isError=True,
        )
    ) is False
    assert audit_result_ok({"value": 1}) is True


@pytest.mark.asyncio
async def test_failed_shell_command_is_audited_as_failed(tmp_path, monkeypatch):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUDIT_LOG_PATH", str(audit_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()
    command = (
        f"{quote_shell_argument(sys.executable)} -c "
        f"{quote_shell_argument('import sys; sys.exit(7)')}"
    )

    await build_mcp().call_tool("run_shell_tool", {"command": command})

    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    end = [record for record in records if record["event"] == "mcp_tool_call_end"][-1]
    assert end["tool"] == "run_shell_tool"
    assert end["ok"] is False
    assert end["result"]["data"]["ok"] is False
    nested = [record for record in records if record["event"] == "run_shell_end"][-1]
    assert nested["parent_call_id"] == end["call_id"]



@pytest.mark.asyncio
async def test_connector_error_is_collapsed_into_failed_parent_call(tmp_path, monkeypatch):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUDIT_LOG_PATH", str(audit_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()

    await build_mcp().call_tool("fetch", {"id": "missing.txt"})

    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    end = [record for record in records if record["event"] == "mcp_tool_call_end"][-1]
    nested = [record for record in records if record["event"] == "tool_error"][-1]
    assert end["tool"] == "fetch"
    assert end["ok"] is False
    assert end["error"] == nested["error"]
    assert nested["parent_call_id"] == end["call_id"]


def test_audit_tool_arguments_preserves_sensitive_keys():
    payload = _audit_tool_arguments((), {"token": "abc", "normal": "value"})

    assert payload["keyword_args"]["token"] == "abc"
    assert payload["keyword_args"]["normal"] == "value"


def test_audit_tool_arguments_preserves_payloads():
    payload = _audit_tool_arguments(
        (),
        {
            "command": "curl -H 'Authorization: Bearer secret-value' example.test",
            "content": "API_TOKEN=secret-value",
            "path": "safe.txt",
        },
    )

    assert payload["keyword_args"]["command"] == (
        "curl -H 'Authorization: Bearer secret-value' example.test"
    )
    assert payload["keyword_args"]["content"] == "API_TOKEN=secret-value"
    assert payload["keyword_args"]["path"] == "safe.txt"


@pytest.mark.asyncio
async def test_mcp_audit_extracts_session_context(tmp_path, monkeypatch):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUDIT_LOG_PATH", str(audit_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()

    await build_mcp().call_tool("shell_read", {"session_id": "missing-session"})

    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    starts = [record for record in records if record["event"] == "mcp_tool_call_start"]
    assert starts[-1]["session"] == "missing-session"


def test_audit_preserves_lower_level_commands_and_embedded_tokens(tmp_path, monkeypatch):
    from local_shell_mcp.audit import audit

    audit_path = tmp_path / "audit.jsonl"
    secret = "configured-secret-value-which-is-long"
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUDIT_LOG_PATH", str(audit_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_OAUTH_JWT_SECRET", secret)
    get_settings.cache_clear()

    audit(
        "run_shell_start",
        command="curl -H 'Authorization: Bearer bearer-value' example.test",
        error=f"failed with ghp_{'A' * 36} and {secret}",
        token_id="safe-identifier",
        nested={"access_token": "nested-secret", "path": "safe.txt"},
    )
    record = json.loads(audit_path.read_text(encoding="utf-8"))

    assert record["command"] == (
        "curl -H 'Authorization: Bearer bearer-value' example.test"
    )
    assert f"ghp_{'A' * 36}" in record["error"]
    assert secret in record["error"]
    assert record["token_id"] == "safe-identifier"
    assert record["nested"]["access_token"] == "nested-secret"
    assert record["nested"]["path"] == "safe.txt"
