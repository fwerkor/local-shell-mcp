"""Registry adapter reject-by-default behavior and bounded MCP outputs."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

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
async def test_deny_bad_names_machine_selectors_session_and_oversized_input(bound_policy):
    repo, cid = bound_policy
    scopes = {"shell:read", "shell:write", "shell:execute", "remote:use"}
    for name, args, error in [
        ("not_registered", {}, ValueError),
        ("mcp_manage", {}, PermissionError),
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


def test_original_schema_respects_other_tools_and_empty_policy(bound_policy):
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
    assert registry.available_tools("local", cid, scopes=base) == []
    assert registry.registered_definitions(("totally_missing",)) == []
    assert registry._encode_result(([], {"ok": True})) == '{"ok": true}'
    assert registry._encode_result(([SimpleNamespace(text="hello"), {"type": "image"}], None)) == (
        '["hello", {"type": "non_text_result"}]'
    )
    assert '... [truncated]' in registry._encode_result({"payload": "z" * 40000})
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
    with pytest.raises(ValueError, match="too large"):
        await registry._invoke_registered("local", cid, "fake", {"payload": "a" * 35000},
                                          scopes={"shell:read"})
