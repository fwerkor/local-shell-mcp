"""Registry adapter reject-by-default behavior and lossless native MCP output."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui import lsm_tool_registry as registry
from local_shell_mcp.webui.providers import ModelToolCall
from local_shell_mcp.webui.routes import _repo


@pytest.fixture
def bound_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "true")
    get_settings.cache_clear()
    registry._registry_for_state.cache_clear()
    repo = _repo()
    cid = repo.create_conversation("local", {"title": "Tool boundary"})["conversationId"]
    repo.save_setting("local", "agent.machine_policy.conversation." + cid,
                      {"local": "write", "worker1": "read", "worker2": "write"})
    yield repo, cid
    registry._registry_for_state.cache_clear()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_deny_bad_names_machine_selectors_session_and_oversized_input(bound_policy, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_HTTP_REQUEST_BYTES", "32768")
    get_settings.cache_clear()
    repo, cid = bound_policy
    scopes = {"shell:read", "shell:write", "shell:execute", "remote:use"}
    for name, args, error in [
        ("not_registered", {}, ValueError),
        ("mcp_tool_call", {}, PermissionError),
        ("file_read", {"path": "a", "machine": 123}, ValueError),
        ("remote_transfer", {"source_machine": ["local"], "destination_machine": "worker2"}, ValueError),
        ("remote_transfer", {"source_machine": "local", "destination_machine": "worker1"}, PermissionError),
        ("job_get", {"job_id": "x", "logical_session_id": "fake"}, PermissionError),
        ("job_list", {"limit": 3, "unused": "x" * 34000}, ValueError),
    ]:
        with pytest.raises(error):
            await registry.call_tool("local", cid, ModelToolCall("test", name, args),
                                     granted_scopes=scopes)
    with pytest.raises(PermissionError, match="remote:use"):
        await registry.call_tool("local", cid, ModelToolCall("a", "job_get", {
            "machine": "worker1", "job_id": "j",
        }), granted_scopes={"shell:read"})
    with pytest.raises(PermissionError, match="browser:use"):
        await registry.call_tool("local", cid, ModelToolCall("a", "browser_snapshot", {
            "machine": "local", "session_id": "sess",
        }), granted_scopes={"shell:read"})
    with pytest.raises(PermissionError, match="file:share"):
        await registry.call_tool("local", cid, ModelToolCall("a", "link_list", {}),
                                 granted_scopes={"shell:read"})
    assert registry._targets(SimpleNamespace(parameters={"properties": {
        "source_machine": {}, "destination_machine": {},
    }}), {"source_machine": "local", "destination_machine": "worker2"}) == ["local", "worker2"]


def test_original_schema_respects_other_tools_and_empty_policy(bound_policy, tmp_path):
    repo, cid = bound_policy
    base = {"shell:read", "shell:write", "shell:execute", "remote:use"}
    found = registry.available_tools("local", cid, scopes=base)
    names = {entry["function"]["name"] for entry in found}
    assert "remote_transfer" in names
    assert "link_list" not in names  # file:share scope absent.
    assert "browser_snapshot" not in names  # browser:use scope absent.
    assert "gui_list" in names
    repo.save_setting("local", "agent.machine_policy.conversation." + cid,
                      {"local": "none", "worker1": "none", "worker2": "none"})
    assert {item["function"]["name"] for item in registry.available_tools(
        "local", cid, scopes=base,
    )} == {"session_manage", "plan_manage"}
    assert registry.registered_definitions(("totally_missing",)) == []
    assert registry._encode_result(([], {"ok": True})) == '{"ok": true}'
    from mcp.types import (
        EmbeddedResource,
        ImageContent,
        ResourceLink,
        TextContent,
        TextResourceContents,
    )

    blocks = [TextContent(type="text", text="hello"),
              ImageContent(type="image", data="aGVsbG8=", mimeType="image/png", _meta={"source": "native"}),
              EmbeddedResource(type="resource", resource=TextResourceContents(uri="file:///known.txt", text="kept")),
              ResourceLink(type="resource_link", name="native-file", uri="file:///known.txt")]
    assert json.loads(registry._encode_result((blocks, None))) == [block.model_dump(mode="json", by_alias=True) for block in blocks]
    assert json.loads(registry._encode_result((blocks, None)))[1]["_meta"] == {"source": "native"}
    assert json.loads(registry._encode_result({"path": tmp_path})) == {"path": str(tmp_path)}
    oversized = {"payload": "z" * 40000}
    assert json.loads(registry._encode_result(oversized)) == oversized
    assert '"ok": true' in registry._encode_result(SimpleNamespace(model_dump=lambda **_: {"ok": True}))
    assert registry._can_authorize("local", cid, "local", "read", base, None) is False


@pytest.mark.asyncio
async def test_executor_error_audit_and_context_reset(bound_policy, monkeypatch):
    from local_shell_mcp.auth import current_principal

    repo, cid = bound_policy
    observed = []

    class FakeTools:
        async def call_tool(self, name, args, *, convert_result):
            observed.append((name, args, current_principal().subject))
            raise RuntimeError("upstream deliberately failed")

    monkeypatch.setattr(registry, "_registry", lambda: SimpleNamespace(_tool_manager=FakeTools()))
    with pytest.raises(RuntimeError, match="deliberately"):
        await registry._invoke_registered("local", cid, "fake", {}, scopes={"shell:read"})
    assert observed[0][2] == "local"
    assert current_principal() is None
    with pytest.raises(PermissionError, match="internal session"):
        await registry._invoke_registered("local", cid, "fake", {"logical_session_id": "x"},
                                          scopes={"shell:read"})
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_HTTP_REQUEST_BYTES", "32768")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="configured 32768 byte request limit"):
        await registry._invoke_registered("local", cid, "fake", {"payload": "a" * 35000},
                                          scopes={"shell:read"})


def test_every_native_tool_has_audited_policy_and_new_tools_are_denied(bound_policy, monkeypatch):
    repo, cid = bound_policy
    tools = registry._registry()._tool_manager.list_tools()
    classified = (registry._READ_TOOLS | registry._WRITE_TOOLS | registry._EXECUTION_TOOLS |
                  registry._CONTROLLER_MANAGEMENT | registry._AGENT_CONTROL | registry._SEPARATE_TOOLS)
    assert {tool.name for tool in tools} == classified
    # A new tool cannot acquire read permission through an optimistic hint.
    unknown = SimpleNamespace(name="future_tool", annotations=SimpleNamespace(readOnlyHint=True))
    with pytest.raises(PermissionError, match="audited"):
        registry._operation(unknown)
    monkeypatch.setattr(registry, "_registry", lambda: SimpleNamespace(
        _tool_manager=SimpleNamespace(list_tools=lambda: [unknown])))
    assert registry.available_tools("local", cid, scopes={"shell:read", "shell:write"}) == []


@pytest.mark.asyncio
async def test_transfer_job_retry_rechecks_persisted_endpoints(bound_policy, monkeypatch):
    from contextlib import contextmanager

    from local_shell_mcp import jobs

    repo, cid = bound_policy
    record = {"job_id": "transfer-job", "kind": "managed", "managed_kind": "transfer",
              "managed_payload": {"source_machine": "worker1", "destination_machine": "worker2"}}
    @contextmanager
    def store():
        yield {"jobs": [record]}
    monkeypatch.setattr(jobs, "_store_transaction", store)
    monkeypatch.setattr(jobs, "_find_job", lambda store, job_id: record)
    invoked = []
    async def original(*args, **kwargs):
        invoked.append(args)
        return '{"ok": true}'
    monkeypatch.setattr(registry, "_invoke_registered", original)
    scopes = {"shell:read", "shell:write", "shell:execute", "remote:use"}
    call = ModelToolCall("retry", "job_retry", {"job_id": "transfer-job"})
    assert await registry.call_tool("local", cid, call, granted_scopes=scopes) == '{"ok": true}'
    assert len(invoked) == 1
    repo.save_setting("local", "agent.machine_policy.conversation." + cid,
                      {"local": "write", "worker1": "none", "worker2": "write"})
    with pytest.raises(PermissionError, match="not granted"):
        await registry.call_tool("local", cid, call, granted_scopes=scopes)
    assert len(invoked) == 1
    repo.save_setting("local", "agent.machine_policy.conversation." + cid,
                      {"local": "write", "worker1": "read", "worker2": "read"})
    with pytest.raises(PermissionError, match="read-only"):
        await registry.call_tool("local", cid, call, granted_scopes=scopes)
    record["managed_kind"] = "future-handler"
    with pytest.raises(PermissionError, match="audited"):
        await registry.call_tool("local", cid, call, granted_scopes=scopes)
    record["kind"] = "shell"
    assert jobs.job_retry_machine_requirements("transfer-job") == []


@pytest.mark.asyncio
async def test_browser_session_listing_is_read_only_but_start_is_not(bound_policy, monkeypatch):
    repo, cid = bound_policy
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "read"})
    scopes = {"shell:read", "browser:use"}
    names = {t["function"]["name"] for t in registry.available_tools("local", cid, scopes=scopes)}
    assert "browser_session" in names
    observed = []
    async def invoke(*args, **kwargs):
        observed.append(args)
        return '{"ok": true}'
    monkeypatch.setattr(registry, "_invoke_registered", invoke)
    await registry.call_tool("local", cid, ModelToolCall("list", "browser_session", {"action": "list"}),
                             granted_scopes=scopes)
    with pytest.raises(PermissionError, match="read-only"):
        await registry.call_tool("local", cid, ModelToolCall("start", "browser_session", {"action": "start"}),
                                 granted_scopes=scopes)
    assert len(observed) == 1


@pytest.mark.asyncio
async def test_write_machine_grant_preserves_native_read_and_write_scopes(bound_policy, monkeypatch):
    repo, cid = bound_policy
    dispatched = []
    async def invoke(*args, **kwargs):
        dispatched.append(args)
        return '{"ok": true}'
    monkeypatch.setattr(registry, "_invoke_registered", invoke)
    with pytest.raises(PermissionError, match="shell:read"):
        await registry.call_tool("local", cid, ModelToolCall("write", "file_write", {
            "path": "notes.txt", "content": "blocked"}), granted_scopes={"shell:write"})
    assert dispatched == []


@pytest.mark.asyncio
async def test_large_native_arguments_reuse_transport_and_operation_limits(bound_policy, tmp_path, monkeypatch):
    _, cid = bound_policy
    audits = []
    monkeypatch.setattr(registry, "audit", lambda event, **data: audits.append((event, data)))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_HTTP_REQUEST_BYTES", "200000")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_FILE_WRITE_BYTES", "100000")
    get_settings.cache_clear()
    registry._registry_for_state.cache_clear()
    scopes = {"shell:read", "shell:write"}
    payload = "a" * 70000
    result = json.loads(await registry.call_tool("local", cid, ModelToolCall("write-large", "file_write", {
        "path": "native-large.txt", "content": payload,
    }), granted_scopes=scopes))
    assert result["ok"] is True
    assert (tmp_path / "native-large.txt").read_text() == payload
    assert audits[-1][0] == "webui_agent_lsm_tool" and audits[-1][1]["ok"] is True

    # The request fits the shared transport budget; the original file executor
    # still rejects it with its own configured error structure and no file.
    result = json.loads(await registry.call_tool("local", cid, ModelToolCall("write-native-denied", "file_write", {
        "path": "native-denied.txt", "content": "x" * 100001,
    }), granted_scopes=scopes))
    assert result["isError"] is True
    assert result["structuredContent"]["data"]["error_type"] == "ValueError"
    assert "100000" in result["structuredContent"]["message"]
    assert not (tmp_path / "native-denied.txt").exists()
    assert audits[-1][0] == "webui_agent_lsm_tool" and audits[-1][1]["ok"] is False

    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_HTTP_REQUEST_BYTES", "1000")
    get_settings.cache_clear()
    for payload in ("x" * 1000, "🙂" * 300):
        with pytest.raises(ValueError, match="configured 1000 byte request limit"):
            await registry.call_tool("local", cid, ModelToolCall("transport-denied", "file_write", {
                "path": "transport-denied.txt", "content": payload,
            }), granted_scopes=scopes)
    assert not (tmp_path / "transport-denied.txt").exists()


@pytest.mark.asyncio
async def test_both_internal_entries_reject_invalid_json_and_forged_credentials(bound_policy, tmp_path):
    _, cid = bound_policy
    scopes = {"shell:read", "shell:write"}
    cyclic = {"path": "invalid.txt"}
    cyclic["content"] = cyclic
    malformed = [None, [], {"content": float("nan")}, {"content": float("inf")},
                 {"content": {1, 2}}, {"content": b"binary"}, {"content": "\ud800"}, cyclic]
    for arguments in malformed:
        with pytest.raises(ValueError):
            await registry.call_tool("local", cid, ModelToolCall("invalid", "file_write", arguments),
                                     granted_scopes=scopes)
        with pytest.raises(ValueError):
            await registry._invoke_registered("local", cid, "file_write", arguments, scopes=scopes)
    for invoke in (
        lambda arguments: registry.call_tool("local", cid, ModelToolCall("forged", "file_write", arguments), granted_scopes=scopes),
        lambda arguments: registry._invoke_registered("local", cid, "file_write", arguments, scopes=scopes),
    ):
        with pytest.raises(PermissionError, match="internal session credentials"):
            await invoke({"logical_session_id": "forged", "path": "forged.txt", "content": "never"})
    assert not (tmp_path / "invalid.txt").exists()
    assert not (tmp_path / "forged.txt").exists()


@pytest.mark.asyncio
async def test_original_schema_still_rejects_missing_required_arguments(bound_policy):
    _, cid = bound_policy
    with pytest.raises(ToolError, match="(?is)path.*required|required.*path"):
        await registry.call_tool("local", cid, ModelToolCall("missing-path", "file_write", {"content": "never"}),
                                 granted_scopes={"shell:read", "shell:write"})


def test_native_mcp_error_envelopes_control_audit_status():
    from mcp.types import CallToolResult, TextContent

    content = [TextContent(type="text", text="do not classify arbitrary content")]
    assert registry._result_succeeded(CallToolResult(content=content, isError=False))
    assert not registry._result_succeeded(CallToolResult(content=content, isError=True))
    assert not registry._result_succeeded(CallToolResult(content=content, structuredContent={"ok": False}))
    assert registry._result_succeeded(CallToolResult(content=content, structuredContent={"data": {"ok": False}}))
    assert not registry._result_succeeded((content, {"ok": False}))
    assert registry._result_succeeded((content, {"ok": True}))
