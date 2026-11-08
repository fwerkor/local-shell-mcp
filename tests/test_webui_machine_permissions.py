"""Machine-by-machine permission inheritance, scope fencing and SQLite persistence."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette

# Pre-import modules that bind get_settings at import time before any test
# monkeypatches the global settings factory.
from local_shell_mcp import audit as audit_module  # noqa: F401
from local_shell_mcp import fs_ops as fs_ops_module  # noqa: F401
from local_shell_mcp import human_ui as human_ui_module  # noqa: F401
from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import misc_routes, routes
from local_shell_mcp.webui.machine_permissions import (
    access_level,
    machine_permission_routes,
    require_machine_scope,
    resolve_access,
    validate_access_map,
)
from local_shell_mcp.webui.storage import WorkspaceRepository


def test_effective_permission_precedence_and_isolation(tmp_path):
    repo = WorkspaceRepository(SQLiteDatabase(tmp_path / "state"))
    project = repo.create_project("alice", "Research")
    pid = project["id"]
    chat = repo.create_conversation("alice", {"title": "Message", "projectId": pid})
    cid = chat["conversationId"]
    repo.save_setting("alice", "agent.machine_policy.global", {"local": "read", "worker1": "write"})
    repo.save_setting("alice", "agent.machine_policy.project." + pid,
                      {"local": "write", "worker1": "none", "worker2": "read"})
    repo.save_setting("alice", "agent.machine_policy.conversation." + cid, {"local": "none", "worker2": "write"})
    assert resolve_access("alice", cid, repo=repo) == {
        "local": "none", "worker1": "none", "worker2": "write"
    }
    assert access_level("alice", cid, "worker2", repo=repo) == "write"
    assert access_level("alice", cid, "never-authorized", repo=repo) == "none"
    assert resolve_access("alice", project_id=pid, repo=repo)["local"] == "write"
    plain = repo.create_conversation("alice", {"title": "No project"})
    assert access_level("alice", plain["conversationId"], "local", repo=repo) == "read"
    assert resolve_access("bob", repo=repo) == {}
    with pytest.raises(KeyError):
        resolve_access("bob", cid, repo=repo)
    with pytest.raises(KeyError):
        resolve_access("alice", project_id="unknown", repo=repo)


@pytest.mark.parametrize("value", [
    [], {"local": "admin"}, {"*": "read"}, {"local": True},
    {"../../../": "read"}, {"": "read"}, {"m": None},
    {str(i): "read" for i in range(129)},
])
def test_invalid_machine_maps_fail_closed(value):
    with pytest.raises(ValueError):
        validate_access_map(value)


def test_scopes_are_checked_per_machine_and_access_type():
    with pytest.raises(PermissionError, match="shell:read"):
        require_machine_scope(set(), "local", "read")
    with pytest.raises(PermissionError, match="shell:write"):
        require_machine_scope({"shell:read"}, "local", "write")
    with pytest.raises(PermissionError, match="remote:use"):
        require_machine_scope({"shell:read"}, "remote1", "read")
    with pytest.raises(PermissionError, match="expired"):
        require_machine_scope({"shell:read"}, "local", "read", expires=1)
    require_machine_scope({"shell:read", "remote:use"}, "remote1", "read")
    require_machine_scope({"shell:write"}, "local", "write")


@pytest.mark.asyncio
async def test_permission_http_scopes_and_multiuser_defaults(tmp_path, monkeypatch):
    from local_shell_mcp import settings as setting_module
    from local_shell_mcp.webui import machine_permissions

    settings = SimpleNamespace(auth_mode="oauth", state_dir=tmp_path, disable_local=False, remote_enabled=True)
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(setting_module, "get_settings", lambda: settings)
    monkeypatch.setattr(machine_permissions, "_principal_scopes", lambda req: {
        part for part in req.headers.get("x-scopes", "").split() if part
    })
    monkeypatch.setattr("local_shell_mcp.human_ui._machine_rows", lambda: {
        "machines": [{"name": "local", "status": "online"}, {"name": "worker1", "status": "offline"}]
    })
    app = Starlette(routes=[*machine_permission_routes(), *misc_routes.misc_routes(), *routes.webui_routes()])

    async def authenticated(scope, receive, send):
        if scope.get("type") == "http":
            owner = next((v.decode() for k, v in scope.get("headers", []) if k == b"x-owner"), None)
            if owner:
                scope.setdefault("state", {})["principal"] = SimpleNamespace(subject=owner, claims={"scope": ""})
        await app(scope, receive, send)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=authenticated), base_url="http://test") as client:
        owner = {"x-owner": "alice", "x-scopes": "shell:read shell:write remote:use"}
        read_only = {"x-owner": "alice", "x-scopes": "shell:read"}
        bob = {"x-owner": "bob", "x-scopes": "shell:read shell:write remote:use"}
        assert (await client.get("/api/lsm/permissions/defaults")).status_code == 401
        assert (await client.get("/api/lsm/permissions/machines", headers=owner)).json()["machines"][0]["name"] == "local"
        assert len((await client.get("/api/lsm/permissions/machines", headers=read_only)).json()["machines"]) == 1
        assert (await client.put("/api/lsm/permissions/defaults", headers=read_only,
                                 json={"machines": {"local": "write"}})).status_code == 403
        assert (await client.put("/api/lsm/permissions/defaults", headers=read_only,
                                 json={"machines": {"worker1": "read"}})).status_code == 403
        assert (await client.put("/api/lsm/permissions/defaults", headers=owner,
                                 json={"machines": {"local": "read", "worker1": "write"}})).status_code == 200
        assert (await client.get("/api/lsm/permissions/defaults", headers=bob)).json()["machines"] == {}
        project = (await client.post("/api/projects", headers=owner, json={"name": "Project"})).json()
        pid = project["id"]
        chat = (await client.post("/api/convos", headers=owner,
                                  json={"title": "Chat", "projectId": pid})).json()
        cid = chat["conversationId"]
        assert (await client.get(f"/api/lsm/permissions/projects/{pid}", headers=bob)).status_code == 404
        assert (await client.put(f"/api/lsm/permissions/projects/{pid}", headers=owner,
                                 json={"machines": {"worker1": "none"}})).status_code == 200
        default = (await client.get(f"/api/lsm/preferences/{cid}", headers=owner)).json()
        assert default["effective"] == {"local": "read", "worker1": "none"}
        assert default["projectId"] == pid
        changed = await client.put(f"/api/lsm/preferences/{cid}", headers=owner,
                                   json={"web": False, "mcp": False, "memory": False,
                                         "machines": {"local": "write"}})
        assert changed.status_code == 200
        assert changed.json()["effective"] == {"local": "write", "worker1": "none"}
        assert (await client.put(f"/api/lsm/preferences/{cid}", headers=read_only,
                                 json={"machines": {"local": "write"}})).status_code == 403
        assert (await client.get(f"/api/lsm/preferences/{cid}", headers=bob)).status_code == 404
        assert (await client.put("/api/lsm/permissions/defaults", headers=owner,
                                 json={"machines": {"unknown-worker": "admin"}})).status_code == 400


@pytest.mark.asyncio
async def test_new_conversation_inherits_project_machine_policy_on_first_turn(tmp_path, monkeypatch):
    import asyncio

    from local_shell_mcp.settings import get_settings
    from local_shell_mcp.webui import generation_routes
    from local_shell_mcp.webui.providers import ProviderConfig

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()
    repo = WorkspaceRepository(SQLiteDatabase(get_settings().state_dir))
    project = repo.create_project("local", "Default project")
    repo.save_setting("local", "agent.machine_policy.global", {"local": "none"})
    repo.save_setting("local", "agent.machine_policy.project." + project["id"], {"local": "read"})
    observed = []

    async def stream_with_tools(*_args, **kwargs):
        observed.append(kwargs["tools"])
        yield "Project defaults applied."

    monkeypatch.setattr(generation_routes, "provider_config", lambda *_: ProviderConfig(
        "openai", "test", "http://127.0.0.1:11434/v1/chat/completions", "",
    ))
    monkeypatch.setattr(generation_routes, "stream_model_with_tools", stream_with_tools)
    app = Starlette(routes=generation_routes.generation_routes())
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            first = await client.post("/api/agents/chat", json={
                "conversationId": "new", "projectId": project["id"], "text": "Start project chat",
            })
            assert first.status_code == 202, first.text
            cid = first.json()["conversationId"]
            for _ in range(50):
                if (await client.get(f"/api/agents/chat/status/{cid}")).json().get("status") == "complete":
                    break
                await asyncio.sleep(0.02)
            assert len(observed) == 1
            names = {tool["function"]["name"] for tool in observed[0]}
            assert {"environment_get", "file_list", "file_read", "file_tree", "file_grep",
                    "job_list", "job_get", "job_tail", "shell_list", "shell_read"} <= names
            assert not {"run_shell", "job_start", "shell_send", "file_write", "mcp_manage"} & names
            assert repo.conversation("local", cid)["projectId"] == project["id"]
            assert access_level("local", cid, "local", repo=repo) == "read"
            missing = await client.post("/api/agents/chat", json={
                "conversationId": "new", "projectId": "not-allowed", "text": "Invalid project",
            })
            assert missing.status_code == 404
    finally:
        await generation_routes.shutdown_generations()
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_agent_write_capability_is_only_advertised_for_write_policy(tmp_path, monkeypatch):
    import asyncio

    from local_shell_mcp.settings import get_settings
    from local_shell_mcp.webui import generation_routes
    from local_shell_mcp.webui.providers import ProviderConfig

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    repo = WorkspaceRepository(SQLiteDatabase(get_settings().state_dir))
    cid = repo.create_conversation("local", {"title": "Writable"})["conversationId"]
    repo.save_setting("local", "agent.machine_policy.conversation." + cid, {"local": "write"})
    available = []

    async def stream_with_tools(*_args, **kwargs):
        available.extend(tool["function"]["name"] for tool in kwargs["tools"])
        yield "Writable."

    monkeypatch.setattr(generation_routes, "provider_config", lambda *_: ProviderConfig(
        "openai", "test", "http://127.0.0.1:11434/v1/chat/completions", "",
    ))
    monkeypatch.setattr(generation_routes, "stream_model_with_tools", stream_with_tools)
    app = Starlette(routes=generation_routes.generation_routes())
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            result = await client.post("/api/agents/chat", json={"conversationId": cid, "text": "Write allowed"})
            assert result.status_code == 202
            for _ in range(50):
                if (await client.get(f"/api/agents/chat/status/{cid}")).json().get("status") == "complete":
                    break
                await asyncio.sleep(0.02)
            assert {"environment_get", "file_list", "file_read", "file_tree", "file_grep",
                    "job_list", "job_get", "job_tail", "shell_list", "shell_read",
                    "file_write", "file_edit", "file_patch", "run_shell", "run_python",
                    "job_start", "job_stop", "job_retry", "shell_start", "shell_send",
                    "shell_stop"} <= set(available)
            assert "mcp_manage" not in available
    finally:
        await generation_routes.shutdown_generations()
        get_settings.cache_clear()
