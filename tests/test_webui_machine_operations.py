"""Machine-level OAuth and Controller-local visibility regressions."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui.lsm_tool_registry import call_tool
from local_shell_mcp.webui.machine_permissions import (
    authorize_machine_action,
    machine_permission_routes,
)
from local_shell_mcp.webui.providers import ModelToolCall
from local_shell_mcp.webui.routes import _repo


@pytest.mark.asyncio
async def test_shell_and_environment_follow_machine_and_oauth_scopes(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "oauth")
    get_settings.cache_clear()
    repo = _repo()
    cid = repo.create_conversation("alice", {"title": "Strict scope"})["conversationId"]
    repo.save_setting("alice", "agent.machine_policy.global", {"local": "write"})
    shell = ModelToolCall("exec", "run_shell", {"command": "echo checked"})
    try:
        with pytest.raises(PermissionError, match="shell:write"):
            await call_tool("alice", cid, shell,
                                   granted_scopes={"shell:read", "shell:execute"})
        with pytest.raises(PermissionError, match="shell:execute"):
            await call_tool("alice", cid, shell,
                                   granted_scopes={"shell:read", "shell:write"})
        with pytest.raises(PermissionError, match="expired"):
            await call_tool("alice", cid, shell,
                                   granted_scopes={"shell:read", "shell:write", "shell:execute"},
                                   grant_expires=1)
        with pytest.raises(PermissionError, match="shell:read"):
            await call_tool("alice", cid, ModelToolCall("i", "environment_get", {}),
                                   granted_scopes=set())
        with pytest.raises(PermissionError, match="not granted"):
            await call_tool("bob", repo.create_conversation("bob", {"title": "No access"})["conversationId"],
                                   ModelToolCall("i", "environment_get", {}),
                                   granted_scopes={"shell:read"})
        with pytest.raises(ValueError, match="Unknown"):
            authorize_machine_action("alice", cid, "local", "admin", scopes={"shell:read"})
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_local_remains_visible_as_machine_when_disabled(tmp_path, monkeypatch):
    from local_shell_mcp.webui import machine_permissions, routes

    settings = SimpleNamespace(auth_mode="none", state_dir=tmp_path, disable_local=True,
                               remote_enabled=True)
    monkeypatch.setattr(machine_permissions, "get_settings", lambda: settings, raising=False)
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr("local_shell_mcp.settings.get_settings", lambda: settings)
    monkeypatch.setattr("local_shell_mcp.human_ui._machine_rows", lambda: {
        "machines": [{"name": "remote", "status": "online"}],
    })
    app = Starlette(routes=machine_permission_routes())

    async def principal(scope, receive, send):
        scope.setdefault("state", {})["principal"] = SimpleNamespace(subject="alice")
        await app(scope, receive, send)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=principal), base_url="http://test") as client:
        result = await client.get("/api/lsm/permissions/machines")
        assert result.status_code == 200
        machines = result.json()["machines"]
        assert machines[0] == {"name": "local", "status": "disabled"}
        assert machines[1]["name"] == "remote"


@pytest.mark.asyncio
async def test_job_start_requires_execution_scope_even_with_machine_write(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "oauth")
    get_settings.cache_clear()
    repo = _repo()
    cid = repo.create_conversation("alice", {"title": "No execute"})["conversationId"]
    repo.save_setting("alice", "agent.machine_policy.conversation." + cid, {"local": "write"})
    try:
        with pytest.raises(PermissionError, match="shell:execute"):
            await call_tool("alice", cid, ModelToolCall(
                "job-1", "job_start", {"command": "pwd"},
            ), granted_scopes={"shell:read", "shell:write"})
    finally:
        get_settings.cache_clear()
