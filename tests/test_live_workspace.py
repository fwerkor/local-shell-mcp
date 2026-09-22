from __future__ import annotations

import asyncio
import hashlib
import subprocess
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult
from starlette.requests import Request

import local_shell_mcp.live_channel as live_channel_module
import local_shell_mcp.live_channel_routes as live_routes
import local_shell_mcp.session_runtime as session_runtime_module
import local_shell_mcp.tools as tools_module
from local_shell_mcp.auth import Principal
from local_shell_mcp.live_channel import (
    LIVE_EVENT_LIMIT,
    LIVE_RESOURCE_COMPAT_URIS,
    LIVE_RESOURCE_MIME,
    LIVE_RESOURCE_TEMPLATE_URI,
    LIVE_RESOURCE_URI,
    LIVE_RESOURCE_VERSIONED_URI,
    LiveChannelManager,
)
from local_shell_mcp.main import _build_mcp_http_app
from local_shell_mcp.oauth import ALL_OAUTH_SCOPES
from local_shell_mcp.session_runtime import SessionRuntimeManager
from local_shell_mcp.settings import get_settings
from local_shell_mcp.tools import (
    _install_logical_session_arguments,
    _install_mcp_tool_watchdogs,
    build_mcp,
)


def _reserve_claim(sessions: SessionRuntimeManager, session_id: str) -> dict:
    claim = sessions.claim_plan_continuation(session_id)
    assert claim is not None
    validation = sessions.validate_plan_continuation(session_id, claim["claim_id"])
    assert validation["valid"] is True
    return claim


def _configure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, auth: str = "oauth") -> None:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", auth)
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "https://lsm.example.test")
    get_settings.cache_clear()
    monkeypatch.setattr(live_channel_module, "_MANAGER", LiveChannelManager())
    monkeypatch.setattr(
        session_runtime_module, "_MANAGER", SessionRuntimeManager(tmp_path / ".state")
    )


def test_live_workspace_resource_uri_stays_stable_with_versioned_alias():
    asset = (
        Path(live_channel_module.__file__).resolve().parent / "ui_static" / "live-workspace.html"
    )
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()[:16]
    assert LIVE_RESOURCE_URI == "ui://local-shell-mcp/live-workspace.html"
    assert f"ui://local-shell-mcp/live-workspace-{digest}.html" == LIVE_RESOURCE_VERSIONED_URI
    assert LIVE_RESOURCE_VERSIONED_URI not in LIVE_RESOURCE_COMPAT_URIS
    assert "ui://local-shell-mcp/live-workspace-508d16533a186095.html" in LIVE_RESOURCE_COMPAT_URIS


@pytest.mark.asyncio
async def test_remote_only_live_workspace_rejects_local_git_shell(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth="none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_DISABLE_LOCAL", "true")
    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="Local access is disabled"):
        await live_routes._run_machine_shell(
            "local",
            "git status --short --branch",
            cwd=".",
            timeout_s=5,
            max_output_bytes=1024,
        )


def test_live_workspace_tokens_rotate_and_events_are_bounded():
    manager = LiveChannelManager()
    parent_deadline = time.time() + 60
    logical_session_id = "s_token_rotation"
    channel, first_token = manager.open(
        subject="user",
        scopes=tuple(ALL_OAUTH_SCOPES),
        parent_expires_at=parent_deadline,
        logical_session_id=logical_session_id,
    )
    same_channel, second_token = manager.open(
        subject="user",
        scopes=tuple(ALL_OAUTH_SCOPES),
        parent_expires_at=parent_deadline,
        logical_session_id=logical_session_id,
    )

    assert same_channel.live_id == channel.live_id
    assert first_token != second_token
    assert manager.authenticate(first_token) is None
    assert manager.authenticate(second_token) is channel
    assert channel.expires_at <= parent_deadline

    for index in range(LIVE_EVENT_LIMIT + 50):
        manager.publish_channel(
            channel.live_id,
            "test.event",
            actor="system",
            data={"index": index},
        )

    assert len(channel.events) == LIVE_EVENT_LIMIT
    assert channel.events[-1]["data"]["index"] == LIVE_EVENT_LIMIT + 49
    assert channel.events[0]["seq"] == channel.seq - LIVE_EVENT_LIMIT + 1


def test_live_channel_public_state_resolves_and_tolerates_missing_logical_session(
    tmp_path, monkeypatch
):
    _configure(tmp_path, monkeypatch, auth="none")
    sessions = session_runtime_module.get_session_runtime_manager()
    started = sessions.manage("user", action="start", objective="State")
    session_id = started["session_id"]
    sessions.manage_plan(
        session_id,
        action="start",
        objective="State",
        steps=[{"id": "work", "text": "Work"}],
    )
    channel, _ = live_channel_module.get_live_channel_manager().open(
        subject="user",
        scopes=tuple(ALL_OAUTH_SCOPES),
        logical_session_id=started["session_id"],
    )

    state = channel.public_state()
    assert state["session_id"] == started["session_id"]
    assert state["session"]["objective"] == "State"
    assert state["plan"]["status"] == "active"

    channel.logical_session_id = "s_missing"
    missing = channel.public_state()
    assert missing["session_id"] == "s_missing"
    assert missing["session"] is None
    assert missing["plan"] is None


def test_app_reattach_does_not_shorten_shared_channel_expiry():
    manager = LiveChannelManager()
    now = time.time()
    channel, token = manager.open(
        subject="user",
        scopes=tuple(ALL_OAUTH_SCOPES),
        parent_expires_at=now + 600,
        logical_session_id="s_task",
    )
    original_expiry = channel.expires_at

    attached, app_token = manager.open(
        subject="user",
        scopes=("shell:read",),
        parent_expires_at=now + 60,
        live_id=channel.live_id,
        logical_session_id="s_task",
        app_reattach=True,
    )

    assert attached is channel
    assert app_token != token
    assert channel.expires_at == original_expiry
    assert manager.authenticate(token) is channel
    assert manager.authenticate(app_token) is channel
    assert manager.authenticate_context(token)[2] == tuple(ALL_OAUTH_SCOPES)
    assert manager.authenticate_context(app_token)[2] == ("shell:read",)
    app_digest = manager._digest(app_token)
    manager._credentials[app_digest]["expires_at"] = now - 1
    assert manager.authenticate(app_token) is None
    assert manager.authenticate(token) is channel


def test_empty_app_reattach_recovers_unique_recent_explicit_workspace():
    manager = LiveChannelManager()
    channel, model_token = manager.open(
        subject="user",
        scopes=tuple(ALL_OAUTH_SCOPES),
        logical_session_id="s_task",
        machine="local",
        cwd="/workspace/project",
    )

    attached, app_token = manager.open(
        subject="user",
        scopes=("shell:read",),
        app_reattach=True,
        machine="local",
        cwd=".",
    )

    assert attached is channel
    assert attached.logical_session_id == "s_task"
    assert attached.machine == "local"
    assert attached.cwd == "/workspace/project"
    assert app_token != model_token
    assert manager.authenticate(app_token) is channel


def test_empty_app_reattach_refuses_ambiguous_recent_workspaces():
    manager = LiveChannelManager()
    first, _ = manager.open(
        subject="user",
        scopes=tuple(ALL_OAUTH_SCOPES),
        logical_session_id="s_first",
    )
    second, _ = manager.open(
        subject="user",
        scopes=tuple(ALL_OAUTH_SCOPES),
        logical_session_id="s_second",
    )
    assert first is not second

    with pytest.raises(ValueError, match="reattach is ambiguous"):
        manager.open(
            subject="user",
            scopes=("shell:read",),
            app_reattach=True,
        )


def test_empty_app_reattach_refuses_to_replace_existing_workspace_after_claim_expires():
    manager = LiveChannelManager()
    channel, _ = manager.open(
        subject="user",
        scopes=tuple(ALL_OAUTH_SCOPES),
        logical_session_id="s_task",
    )
    manager._app_reattach_claims.clear()

    with pytest.raises(ValueError, match="no recoverable context"):
        manager.open(
            subject="user",
            scopes=("shell:read",),
            app_reattach=True,
        )

    assert list(manager._channels.values()) == [channel]
    assert channel.logical_session_id == "s_task"


def test_live_workspace_can_reattach_a_second_mcp_session_by_live_id():
    manager = LiveChannelManager()
    channel, first_token = manager.open(
        subject="user",
        scopes=tuple(ALL_OAUTH_SCOPES),
    )

    attached, app_token = manager.open(
        subject="user",
        scopes=tuple(ALL_OAUTH_SCOPES),
        live_id=channel.live_id,
    )

    assert attached is channel
    assert app_token == first_token
    assert manager.authenticate(first_token) is channel
    assert manager.authenticate(app_token) is channel

    manager.publish_channel(
        channel.live_id,
        "tool.completed",
        actor="agent",
        data={"tool": "run_shell", "call_id": "model-call"},
    )
    assert channel.events[-1]["data"]["call_id"] == "model-call"

    with pytest.raises(PermissionError, match="different principal"):
        manager.open(
            subject="other",
            scopes=tuple(ALL_OAUTH_SCOPES),
            live_id=channel.live_id,
        )


@pytest.mark.asyncio
async def test_live_workspace_expiry_publish_and_wait_paths():
    manager = LiveChannelManager()
    channel, token = manager.open(
        subject="user",
        scopes=tuple(ALL_OAUTH_SCOPES),
    )

    assert manager.authenticate(None) is None
    assert manager.publish_channel("missing", "ignored", actor="system") is None

    immediate = await manager.wait_events(channel, 0, timeout_s=0.1)
    assert immediate and immediate[0]["type"] == "channel.opened"

    after = channel.seq
    assert await manager.wait_events(channel, after, timeout_s=0.01) == []

    async def publish_later() -> None:
        await asyncio.sleep(0.01)
        manager.publish_channel(
            channel.live_id,
            "job.progress",
            actor="system",
            data={"progress": 50},
        )

    publisher = asyncio.create_task(publish_later())
    waited = await manager.wait_events(channel, after, timeout_s=0.5)
    await publisher
    assert waited[-1]["type"] == "job.progress"

    batch_after = channel.seq
    empty_batch = await manager.wait_event_batch(channel, batch_after, timeout_s=0.01)
    assert empty_batch["events"] == []
    assert empty_batch["cursor"] == batch_after

    async def publish_batch_later() -> None:
        await asyncio.sleep(0.01)
        manager.publish_channel(
            channel.live_id,
            "job.batch-progress",
            actor="system",
            data={"progress": 75},
        )

    batch_publisher = asyncio.create_task(publish_batch_later())
    waited_batch = await manager.wait_event_batch(channel, batch_after, timeout_s=0.5)
    await batch_publisher
    assert waited_batch["events"][-1]["type"] == "job.batch-progress"

    for credential in manager._credentials.values():
        if credential["live_id"] == channel.live_id:
            credential["expires_at"] = 0
    channel.expires_at = 0
    assert manager.authenticate(token) is None
    assert manager.by_id(channel.live_id) is None


def test_plan_state_machine_and_auto_promotion(tmp_path):
    sessions = SessionRuntimeManager(tmp_path / ".state")
    started_session = sessions.manage(
        "user", action="start", objective="Make the change fully ready"
    )
    session_id = started_session["session_id"]

    started = sessions.manage_plan(
        session_id,
        action="start",
        objective="Make the change fully ready",
        steps=[{"id": "inspect", "text": "Inspect"}, {"id": "test", "text": "Test"}],
    )
    assert started["session_id"] == session_id
    assert started["goal_mode"] is True
    assert [step["status"] for step in started["plan"]["steps"]] == ["active", "pending"]

    updated = sessions.manage_plan(
        session_id,
        action="update",
        step_id="inspect",
        status="completed",
    )
    assert [step["status"] for step in updated["plan"]["steps"]] == ["completed", "active"]

    with pytest.raises(ValueError, match="unfinished steps"):
        sessions.manage_plan(session_id, action="finish")

    sessions.manage_plan(session_id, action="update", step_id="test", status="completed")
    finished = sessions.manage_plan(session_id, action="finish", note="done")
    assert finished["goal_mode"] is False
    assert finished["plan"]["status"] == "completed"
    assert sessions.plan_state(session_id)["status"] == "completed"


def test_plan_requires_logical_session_and_block_stops_continuation(tmp_path, monkeypatch):
    sessions = SessionRuntimeManager(tmp_path / ".state")
    with pytest.raises(ValueError, match="Unknown logical session"):
        sessions.manage_plan(
            "s_missing",
            action="start",
            objective="Long task",
            steps=[{"text": "Do work"}],
        )

    now = [1_000.0]
    monkeypatch.setattr(session_runtime_module.time, "time", lambda: now[0])
    started_session = sessions.manage("user", action="start", objective="Long task")
    session_id = started_session["session_id"]
    sessions.manage_plan(
        session_id,
        action="start",
        objective="Long task",
        steps=[{"text": "Do work"}],
    )
    now[0] += session_runtime_module.PLAN_EXECUTION_LEASE_S + 1
    claim = _reserve_claim(sessions, session_id)
    sessions.report_plan_continuation(session_id, accepted=True, claim_id=claim["claim_id"])

    sessions.manage_plan(session_id, action="block", note="Need user input")
    now[0] += session_runtime_module.PLAN_EXECUTION_LEASE_S + 1
    assert sessions.claim_plan_continuation(session_id) is None

    resumed = sessions.manage_plan(session_id, action="resume")
    assert resumed["plan"]["status"] == "active"
    assert resumed["plan"]["continuation_due"] is False


def test_plan_continuation_lease_rejection_and_hard_cap(tmp_path, monkeypatch):
    sessions = SessionRuntimeManager(tmp_path / ".state")
    now = [1_000.0]
    monkeypatch.setattr(session_runtime_module.time, "time", lambda: now[0])
    started_session = sessions.manage("user", action="start", objective="Keep going until done")
    session_id = started_session["session_id"]
    sessions.manage_plan(
        session_id,
        action="start",
        objective="Keep going until done",
        steps=[{"id": "work", "text": "Work"}],
    )

    now[0] += session_runtime_module.PLAN_EXECUTION_LEASE_S - 1
    assert sessions.claim_plan_continuation(session_id) is None

    now[0] += 2
    rejected = _reserve_claim(sessions, session_id)
    assert rejected["continuation_count"] == 1
    sessions.report_plan_continuation(
        session_id,
        accepted=False,
        error="host busy",
        claim_id=rejected["claim_id"],
    )
    assert sessions.plan_state(session_id)["continuation_count"] == 1
    assert sessions.claim_plan_continuation(session_id) is None

    for expected in range(2, session_runtime_module.PLAN_MAX_CONTINUATIONS + 1):
        now[0] += (
            max(
                session_runtime_module.PLAN_EXECUTION_LEASE_S,
                session_runtime_module.PLAN_CONTINUATION_FAILURE_BACKOFF_S,
            )
            + 1
        )
        claim = _reserve_claim(sessions, session_id)
        assert claim["continuation_count"] == expected
        assert sessions.claim_plan_continuation(session_id) is None
        sessions.report_plan_continuation(session_id, accepted=True, claim_id=claim["claim_id"])

    now[0] += session_runtime_module.PLAN_EXECUTION_LEASE_S + 1
    assert sessions.claim_plan_continuation(session_id) is None
    assert sessions.plan_state(session_id)["auto_continue_exhausted"] is True


@pytest.mark.asyncio
async def test_mcp_app_resource_and_render_result_hide_live_token(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth="none")
    mcp = build_mcp()

    tools = {tool.name: tool for tool in await mcp.list_tools()}
    render_tool = tools["workspace_open"]
    compatibility_tool = mcp._tool_manager._tools["open_live_workspace"]  # noqa: SLF001
    reconnect_tool = tools["live_workspace_reconnect"]
    assert "open_live_workspace" not in tools
    assert render_tool.meta["ui"]["resourceUri"] == LIVE_RESOURCE_VERSIONED_URI
    assert render_tool.meta["ui/resourceUri"] == LIVE_RESOURCE_VERSIONED_URI
    assert render_tool.meta["openai/outputTemplate"] == LIVE_RESOURCE_VERSIONED_URI
    assert render_tool.meta["openai/widgetAccessible"] is True
    assert "live_id" not in render_tool.inputSchema["properties"]
    assert render_tool.meta["securitySchemes"] == [{"type": "noauth"}]
    assert render_tool.outputSchema["title"] == "LiveChannelResult"
    assert "session_id" in render_tool.inputSchema["properties"]
    assert "session_run_id" not in render_tool.inputSchema["properties"]
    assert render_tool.annotations.readOnlyHint is True
    assert render_tool.annotations.destructiveHint is False
    assert render_tool.annotations.idempotentHint is True
    assert compatibility_tool.meta == render_tool.meta
    assert set(compatibility_tool.parameters["properties"]) == set(
        render_tool.inputSchema["properties"]
    )
    assert compatibility_tool.parameters["properties"]["session_id"]["default"] is None
    assert "default" not in render_tool.inputSchema["properties"]["session_id"]
    assert "session_id" not in compatibility_tool.parameters.get("required", [])
    assert "session_id" in render_tool.inputSchema.get("required", [])
    assert compatibility_tool.output_schema == render_tool.outputSchema
    assert reconnect_tool.meta["ui"] == {"visibility": ["app"]}
    assert "ui/resourceUri" not in reconnect_tool.meta
    assert "openai/outputTemplate" not in reconnect_tool.meta
    assert "session_run_id" not in reconnect_tool.inputSchema["properties"]

    resources = {str(resource.uri): resource for resource in await mcp.list_resources()}
    resource = resources[LIVE_RESOURCE_URI]
    assert LIVE_RESOURCE_VERSIONED_URI in resources
    assert "ui://local-shell-mcp/live-workspace-508d16533a186095.html" in resources
    assert resource.mimeType == LIVE_RESOURCE_MIME
    assert resource.meta["ui"]["domain"] == "https://lsm.example.test"
    assert resource.meta["ui"]["csp"]["connectDomains"] == [
        "https://lsm.example.test",
        "wss://lsm.example.test",
    ]
    assert resource.meta["ui"]["permissions"] == {"clipboardWrite": {}}
    assert resource.meta["openai/widgetDomain"] == "https://lsm.example.test"

    result = await mcp.call_tool(
        "workspace_open", {"session_id": None, "machine": "local", "cwd": "."}
    )
    assert isinstance(result, CallToolResult)
    assert result.structuredContent["live_id"]
    assert "token" not in result.structuredContent
    hidden = result.meta["local-shell-mcp/live"]
    assert hidden["token"]
    assert hidden["apiBase"] == "https://lsm.example.test"
    assert hidden["token"] not in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")

    reconnected = await mcp.call_tool(
        "live_workspace_reconnect",
        {"machine": "local", "cwd": ".", "live_id": result.structuredContent["live_id"]},
    )
    assert isinstance(reconnected, CallToolResult)
    assert reconnected.structuredContent["live_id"] == result.structuredContent["live_id"]
    reconnect_token = reconnected.meta["local-shell-mcp/live"]["token"]
    assert reconnect_token != hidden["token"]
    channel = live_channel_module.get_live_channel_manager().authenticate(hidden["token"])
    assert channel is not None
    assert live_channel_module.get_live_channel_manager().authenticate(reconnect_token) is channel
    assert reconnect_token not in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")

    compatibility_result = await mcp.call_tool(
        "open_live_workspace", {"machine": "local", "cwd": "."}
    )
    assert isinstance(compatibility_result, CallToolResult)
    # A cached alias call without a Session is intentionally unbound and must not
    # reuse another conversation's unbound workspace through the MCP transport.
    assert compatibility_result.structuredContent["live_id"] != result.structuredContent["live_id"]
    compatibility_token = compatibility_result.meta["local-shell-mcp/live"]["token"]
    assert compatibility_token
    compatibility_channel = live_channel_module.get_live_channel_manager().authenticate(
        compatibility_token
    )
    assert compatibility_channel is not None
    assert compatibility_channel is not channel
    assert compatibility_token not in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")

    templates = {
        str(template.uriTemplate): template for template in await mcp.list_resource_templates()
    }
    assert LIVE_RESOURCE_TEMPLATE_URI in templates

    for uri in (
        LIVE_RESOURCE_URI,
        LIVE_RESOURCE_VERSIONED_URI,
        LIVE_RESOURCE_COMPAT_URIS[0],
        "ui://local-shell-mcp/live-workspace-previous-cache-key.html",
    ):
        contents = list(await mcp.read_resource(uri))
        assert contents[0].mime_type == LIVE_RESOURCE_MIME
        assert "local-shell-mcp-live-workspace" in str(contents[0].content)


@pytest.mark.asyncio
async def test_empty_app_remount_recovers_recent_workspace_tool_result(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth="none")
    mcp = build_mcp()

    _, started = await mcp.call_tool(
        "session_manage",
        {"action": "start", "objective": "Survive ChatGPT app remount"},
    )
    session_id = started["data"]["session_id"]
    opened = await mcp.call_tool(
        "workspace_open",
        {"cwd": "/workspace/project", "session_id": session_id},
    )
    old_live_id = opened.structuredContent["live_id"]
    assert opened.structuredContent["session_id"] == session_id

    reconnected = await mcp.call_tool(
        "live_workspace_reconnect",
        {"machine": "local", "cwd": "."},
    )

    assert isinstance(reconnected, CallToolResult)
    assert reconnected.structuredContent["live_id"] == old_live_id
    assert reconnected.structuredContent["session_id"] == session_id
    assert reconnected.structuredContent["cwd"] == "/workspace/project"


@pytest.mark.asyncio
async def test_live_workspace_reconnect_restores_persisted_logical_session(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth="none")
    mcp = build_mcp()

    _, started = await mcp.call_tool(
        "session_manage",
        {"action": "start", "objective": "Persist across workspace recovery"},
    )
    session_id = started["data"]["session_id"]
    opened = await mcp.call_tool("workspace_open", {"cwd": ".", "session_id": session_id})
    assert isinstance(opened, CallToolResult)
    old_live_id = opened.structuredContent["live_id"]
    assert opened.structuredContent["session_id"] == session_id

    attached_reconnect = await mcp.call_tool(
        "live_workspace_reconnect",
        {
            "cwd": ".",
            "live_id": old_live_id,
            "session_id": session_id,
        },
    )
    assert isinstance(attached_reconnect, CallToolResult)
    assert attached_reconnect.structuredContent["session_id"] == session_id

    monkeypatch.setattr(live_channel_module, "_MANAGER", LiveChannelManager())
    monkeypatch.setattr(
        session_runtime_module,
        "_MANAGER",
        SessionRuntimeManager(tmp_path / ".state"),
    )

    reconnected = await mcp.call_tool(
        "live_workspace_reconnect",
        {
            "cwd": ".",
            "live_id": old_live_id,
            "session_id": session_id,
        },
    )
    assert isinstance(reconnected, CallToolResult)
    assert reconnected.structuredContent["session_id"] == session_id
    recovered = live_channel_module.get_live_channel_manager().by_id(
        reconnected.structuredContent["live_id"]
    )
    assert recovered is not None
    assert recovered.logical_session_id == session_id


@pytest.mark.asyncio
async def test_live_workspace_reconnect_ignores_deleted_cached_session(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth="none")
    mcp = build_mcp()

    _, started = await mcp.call_tool(
        "session_manage", {"action": "start", "objective": "Deleted while app sleeps"}
    )
    session_id = started["data"]["session_id"]
    opened = await mcp.call_tool("workspace_open", {"cwd": ".", "session_id": session_id})
    old_live_id = opened.structuredContent["live_id"]
    channel = live_channel_module.get_live_channel_manager().by_id(old_live_id)
    assert channel is not None and channel.logical_session_id == session_id

    session_manager = session_runtime_module.get_session_runtime_manager()
    session_manager.manage(
        "local-mcp-client",
        action="cancel",
        session_id=session_id,
    )
    session_manager.manage(
        "local-mcp-client",
        action="delete",
        session_id=session_id,
    )
    assert channel.logical_session_id == session_id

    reconnected = await mcp.call_tool(
        "live_workspace_reconnect",
        {"cwd": ".", "live_id": old_live_id, "session_id": session_id},
    )

    assert reconnected.structuredContent["session_id"] is None
    assert channel.logical_session_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "terminal_event"),
    [("finish", "session.completed"), ("cancel", "session.cancelled")],
)
async def test_terminal_session_remains_visible_without_capturing_unattached_tools(
    tmp_path, monkeypatch, action, terminal_event
):
    _configure(tmp_path, monkeypatch, auth="none")
    mcp = build_mcp()
    _, started = await mcp.call_tool(
        "session_manage", {"action": "start", "objective": "Terminal boundary"}
    )
    session_id = started["data"]["session_id"]
    opened = await mcp.call_tool("workspace_open", {"cwd": ".", "session_id": session_id})
    channel = live_channel_module.get_live_channel_manager().by_id(
        opened.structuredContent["live_id"]
    )
    assert channel is not None and channel.logical_session_id == session_id

    await mcp.call_tool(
        "session_manage",
        {"action": action, "session_id": session_id},
    )

    assert channel.logical_session_id == session_id
    _, listed = await mcp.call_tool("file_list", {"path": ".", "logical_session_id": None})
    assert listed["ok"] is True
    session = session_runtime_module.get_session_runtime_manager().get(
        session_id, subject="local-mcp-client"
    )
    assert session["recent_activity"][-1]["type"] == terminal_event
    assert not any(
        event["data"].get("tool") == "file_list"
        for event in session["recent_activity"]
        if event["type"].startswith("tool.")
    )


@pytest.mark.asyncio
async def test_live_workspace_reconnect_drops_attachment_after_principal_change(
    tmp_path, monkeypatch
):
    _configure(tmp_path, monkeypatch, auth="none")
    subject = ["alice"]
    monkeypatch.setattr("local_shell_mcp.tools._current_principal_subject", lambda: subject[0])
    mcp = build_mcp()

    _, started = await mcp.call_tool(
        "session_manage",
        {"action": "start", "objective": "Private task"},
    )
    session_id = started["data"]["session_id"]
    opened = await mcp.call_tool("workspace_open", {"cwd": ".", "session_id": session_id})
    assert opened.structuredContent["session_id"] == session_id

    subject[0] = "bob"
    reconnected = await mcp.call_tool(
        "live_workspace_reconnect",
        {"cwd": "."},
    )

    assert reconnected.structuredContent["session_id"] is None
    with pytest.raises(PermissionError, match="different principal"):
        session_runtime_module.get_session_runtime_manager().get(session_id, subject="bob")


@pytest.mark.asyncio
async def test_cancelled_tool_call_releases_logical_inflight_lease(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth="none")
    manager = session_runtime_module.get_session_runtime_manager()
    started = manager.manage("local-mcp-client", action="start", objective="Cancelable task")
    session_id = started["session_id"]
    entered = asyncio.Event()
    never = asyncio.Event()
    event_loop_thread = threading.get_ident()
    begin_threads: list[int] = []
    finish_threads: list[int] = []
    original_begin = manager.begin_tool_call
    original_finish = manager.finish_tool_call

    def observed_begin(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        begin_threads.append(threading.get_ident())
        return original_begin(*args, **kwargs)

    def observed_finish(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        finish_threads.append(threading.get_ident())
        return original_finish(*args, **kwargs)

    monkeypatch.setattr(manager, "begin_tool_call", observed_begin)
    monkeypatch.setattr(manager, "finish_tool_call", observed_finish)
    mcp = FastMCP("cancel-test")

    @mcp.tool()
    async def wait_forever() -> dict[str, bool]:
        entered.set()
        await never.wait()
        return {"ok": True}

    _install_logical_session_arguments(mcp)
    _install_mcp_tool_watchdogs(mcp)
    task = asyncio.create_task(mcp.call_tool("wait_forever", {"logical_session_id": session_id}))
    await asyncio.wait_for(entered.wait(), timeout=1)
    assert manager._sessions[session_id].in_flight_calls

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert manager._sessions[session_id].in_flight_calls == {}
    assert begin_threads and all(thread_id != event_loop_thread for thread_id in begin_threads)
    assert finish_threads and all(thread_id != event_loop_thread for thread_id in finish_threads)


@pytest.mark.asyncio
async def test_cancelled_thread_mutation_holds_logical_lease_until_worker_finishes(
    tmp_path, monkeypatch
):
    _configure(tmp_path, monkeypatch, auth="none")
    manager = session_runtime_module.get_session_runtime_manager()
    started = manager.manage("local-mcp-client", action="start", objective="Thread mutation")
    session_id = started["session_id"]
    entered = threading.Event()
    release = threading.Event()
    from local_shell_mcp.fs_ops import write_text as real_write_text

    def blocking_write_text(path, content, overwrite=True):  # noqa: ANN001, ANN202
        entered.set()
        assert release.wait(timeout=5)
        return real_write_text(path, content, overwrite)

    monkeypatch.setattr("local_shell_mcp.tools.write_text", blocking_write_text)
    mcp = build_mcp()
    task = asyncio.create_task(
        mcp.call_tool(
            "file_write",
            {
                "path": "threaded.txt",
                "content": "completed after cancellation",
                "logical_session_id": session_id,
            },
        )
    )
    assert await asyncio.to_thread(entered.wait, 1)
    assert manager._sessions[session_id].in_flight_calls

    task.cancel()
    await asyncio.sleep(0.05)
    assert not task.done()
    assert manager._sessions[session_id].in_flight_calls
    with pytest.raises(ValueError, match="tool calls are in flight"):
        manager.manage("local-mcp-client", action="finish", session_id=session_id)

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert manager._sessions[session_id].in_flight_calls == {}
    assert (tmp_path / "threaded.txt").read_text(encoding="utf-8") == "completed after cancellation"


@pytest.mark.asyncio
async def test_predispatch_failure_releases_logical_inflight_lease(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth="none")
    manager = session_runtime_module.get_session_runtime_manager()
    started = manager.manage("local-mcp-client", action="start", objective="Setup failure")
    session_id = started["session_id"]
    mcp = build_mcp()

    def fail_start_audit(event, **kwargs):  # noqa: ANN001, ANN003, ANN202
        if event == "mcp_tool_call_start":
            raise OSError("audit volume unavailable")

    monkeypatch.setattr("local_shell_mcp.tools.audit", fail_start_audit)
    with pytest.raises(Exception, match="audit volume unavailable"):
        await mcp.call_tool(
            "file_write",
            {
                "path": "never.txt",
                "content": "must not run",
                "logical_session_id": session_id,
            },
        )

    assert manager._sessions[session_id].in_flight_calls == {}
    assert not (tmp_path / "never.txt").exists()


@pytest.mark.asyncio
async def test_lease_heartbeat_survives_renewal_audit_failure(monkeypatch):
    calls = 0

    class FlakyManager:
        def renew_tool_call(self, lease):  # noqa: ANN001, ANN201
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("state backend unavailable")
            return False

    async def no_wait(_seconds):  # noqa: ANN001, ANN202
        return None

    def fail_audit(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise OSError("audit backend unavailable")

    monkeypatch.setattr(tools_module.asyncio, "sleep", no_wait)
    monkeypatch.setattr(tools_module, "audit", fail_audit)

    await tools_module._renew_session_tool_lease(
        FlakyManager(),
        {"session_id": "s_test", "run_id": "r_test", "call_id": "call-test"},
        tool_name="file_write",
        call_id="call-test",
    )

    assert calls == 2


@pytest.mark.asyncio
async def test_completed_tool_retries_durable_lease_cleanup(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth="none")
    manager = session_runtime_module.get_session_runtime_manager()
    started = manager.manage("local-mcp-client", action="start", objective="Cleanup retry")
    session_id = started["session_id"]
    lease = manager.begin_tool_call(
        session_id,
        "call-cleanup",
        subject="local-mcp-client",
        data={"tool": "write_file"},
    )
    assert lease is not None
    original_save = manager._save_locked
    failures_left = 2

    def fail_completion_writes(session):  # noqa: ANN001, ANN202
        nonlocal failures_left
        if failures_left:
            failures_left -= 1
            raise OSError("state backend temporarily unavailable")
        return original_save(session)

    async def no_wait(_seconds):  # noqa: ANN001, ANN202
        return None

    monkeypatch.setattr(manager, "_save_locked", fail_completion_writes)
    monkeypatch.setattr(tools_module.asyncio, "sleep", no_wait)
    await tools_module._finish_session_tool_activity(
        manager,
        lease,
        "tool.completed",
        {"call_id": "call-cleanup", "ok": True, "tool": "write_file"},
        tool_name="write_file",
        call_id="call-cleanup",
        stage="completed",
    )
    pending = list(tools_module._PENDING_SESSION_LEASE_CLEANUPS)
    assert pending
    await asyncio.gather(*pending)

    restored = SessionRuntimeManager(tmp_path / ".state")
    restored.get(session_id, subject="local-mcp-client")
    assert restored._in_flight_count_locked(session_id) == 0


@pytest.mark.asyncio
async def test_session_lease_cleanup_retry_queue_is_bounded(monkeypatch):
    class BrokenManager:
        def retry_tool_call_cleanup(self, _lease):  # noqa: ANN001, ANN201
            raise OSError("state backend unavailable")

    manager = BrokenManager()
    monkeypatch.setattr(tools_module, "SESSION_IN_FLIGHT_LEASE_S", 0.0)
    session_id = "s_bounded"
    for index in range(tools_module._SESSION_LEASE_CLEANUP_MAX_PENDING_PER_SESSION + 40):
        call_id = f"call-{index}"
        tools_module._schedule_session_tool_cleanup_retry(
            manager,
            {"session_id": session_id, "run_id": "r_test", "call_id": call_id},
            tool_name="file_write",
            call_id=call_id,
        )

    queue_key = (id(manager), session_id)
    assert len(tools_module._SESSION_LEASE_CLEANUP_QUEUES[queue_key]) == (
        tools_module._SESSION_LEASE_CLEANUP_MAX_PENDING_PER_SESSION
    )
    assert len(tools_module._SESSION_LEASE_CLEANUP_TASKS) == 1
    pending = list(tools_module._PENDING_SESSION_LEASE_CLEANUPS)
    assert len(pending) == 1
    await asyncio.gather(*pending)
    assert queue_key not in tools_module._SESSION_LEASE_CLEANUP_QUEUES
    assert queue_key not in tools_module._SESSION_LEASE_CLEANUP_TASKS


@pytest.mark.asyncio
async def test_tool_does_not_execute_when_start_lease_persistence_fails(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth="none")
    mcp = build_mcp()
    _, started = await mcp.call_tool(
        "session_manage", {"action": "start", "objective": "Persist activity"}
    )
    session_id = started["data"]["session_id"]
    manager = session_runtime_module.get_session_runtime_manager()

    def fail_save(_session):
        raise OSError("state volume full")

    monkeypatch.setattr(manager, "_save_locked", fail_save)
    with pytest.raises(Exception, match="refusing to execute"):
        await mcp.call_tool(
            "file_write",
            {
                "path": "completed.txt",
                "content": "must not be written",
                "logical_session_id": session_id,
            },
        )
    assert not (tmp_path / "completed.txt").exists()


@pytest.mark.asyncio
async def test_ambiguous_start_persistence_failure_retries_lease_cleanup(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth="none")
    mcp = build_mcp()
    _, started = await mcp.call_tool(
        "session_manage", {"action": "start", "objective": "Ambiguous lease write"}
    )
    session_id = started["data"]["session_id"]
    manager = session_runtime_module.get_session_runtime_manager()
    original_save = manager._save_locked
    failed_after_write = False

    def persist_then_drop_response(session):  # noqa: ANN001, ANN202
        nonlocal failed_after_write
        original_save(session)
        if (
            not failed_after_write
            and session.activity
            and session.activity[-1]["type"] == "tool.started"
        ):
            failed_after_write = True
            raise OSError("redis response lost after SET")

    monkeypatch.setattr(manager, "_save_locked", persist_then_drop_response)
    with pytest.raises(Exception, match="refusing to execute"):
        await mcp.call_tool(
            "file_write",
            {
                "path": "must-not-run.txt",
                "content": "no",
                "logical_session_id": session_id,
            },
        )

    pending = list(tools_module._PENDING_SESSION_LEASE_CLEANUPS)
    if pending:
        await asyncio.gather(*pending)
    assert failed_after_write is True
    assert not (tmp_path / "must-not-run.txt").exists()
    restored = SessionRuntimeManager(tmp_path / ".state")
    restored.get(session_id, subject="local-mcp-client")
    assert restored._in_flight_count_locked(session_id) == 0


@pytest.mark.asyncio
async def test_live_workspace_keeps_model_and_human_mutations_collaborative(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth="none")
    mcp = build_mcp()
    _, started = await mcp.call_tool(
        "session_manage", {"action": "start", "objective": "Collaborative task"}
    )
    session_id = started["data"]["session_id"]
    result = await mcp.call_tool("workspace_open", {"cwd": ".", "session_id": session_id})
    assert isinstance(result, CallToolResult)
    live_token = result.meta["local-shell-mcp/live"]["token"]
    channel = live_channel_module.get_live_channel_manager().by_id(
        result.structuredContent["live_id"]
    )
    assert channel is not None

    reopened = await mcp.call_tool("workspace_open", {"cwd": ".", "session_id": session_id})
    assert isinstance(reopened, CallToolResult)
    assert reopened.structuredContent["live_id"] == result.structuredContent["live_id"]
    refreshed_live_token = reopened.meta["local-shell-mcp/live"]["token"]
    assert refreshed_live_token != live_token
    await mcp.call_tool(
        "file_write",
        {
            "path": "shared.txt",
            "content": "shared",
            "logical_session_id": session_id,
        },
    )
    assert (tmp_path / "shared.txt").read_text(encoding="utf-8") == "shared"
    _, structured = await mcp.call_tool(
        "file_list", {"path": ".", "logical_session_id": session_id}
    )
    assert structured["ok"] is True
    assert live_channel_module.get_live_channel_manager().authenticate(live_token) is None
    assert (
        live_channel_module.get_live_channel_manager().authenticate(refreshed_live_token) is channel
    )
    event_types = [event["type"] for event in channel.events]
    assert "tool.completed" in event_types


def test_live_continuation_failed_before_validation_releases_claim(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth="oauth")
    live_manager = live_channel_module.get_live_channel_manager()
    session_manager = session_runtime_module.get_session_runtime_manager()
    logical = session_manager.manage("user", action="start", objective="Continue safely")
    session_id = logical["session_id"]
    session_manager.manage_plan(
        session_id,
        action="start",
        objective="Continue safely",
        steps=[{"id": "work", "text": "Work"}],
    )
    logical_state = session_manager._sessions[logical["session_id"]]
    assert logical_state.plan is not None
    logical_state.plan.last_agent_activity -= session_runtime_module.PLAN_EXECUTION_LEASE_S + 1
    _channel, token = live_manager.open(
        subject="user",
        scopes=tuple(ALL_OAUTH_SCOPES),
        logical_session_id=logical["session_id"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    app = _build_mcp_http_app(build_mcp())

    with TestClient(app, base_url="http://testserver") as client:
        claimed = client.post(
            "/api/live/plan/continuation",
            headers=headers,
            json={"action": "claim", "claim_id": "c_http_retry"},
        )
        claim_id = claimed.json()["data"]["claim_id"]
        recovered = client.post(
            "/api/live/plan/continuation",
            headers=headers,
            json={"action": "claim", "claim_id": "c_http_retry"},
        )
        reported = client.post(
            "/api/live/plan/continuation",
            headers=headers,
            json={
                "action": "report",
                "claim_id": claim_id,
                "accepted": False,
                "error": "updateModelContext failed",
            },
        )

    assert claim_id == "c_http_retry"
    assert recovered.status_code == 200
    assert recovered.json()["data"]["claimed"] is True
    assert recovered.json()["data"]["claim_id"] == claim_id
    assert reported.status_code == 200
    plan = reported.json()["data"]["plan"]
    assert plan["continuation_pending"] is False
    assert plan["continuation_reserved"] is False
    assert plan["continuation_count"] == 0


def test_live_http_token_cors_and_collaborative_human_mutation(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth="oauth")
    manager = live_channel_module.get_live_channel_manager()
    session_manager = session_runtime_module.get_session_runtime_manager()
    logical = session_manager.manage(
        "user", action="start", objective="Exercise human goal controls"
    )
    session_id = logical["session_id"]
    channel, token = manager.open(
        subject="user",
        scopes=tuple(ALL_OAUTH_SCOPES),
        logical_session_id=logical["session_id"],
    )
    headers = {"Authorization": f"Bearer {token}", "Origin": "https://chatgpt.com"}
    app = _build_mcp_http_app(build_mcp())

    with TestClient(app, base_url="http://testserver") as client:
        preflight = client.options(
            "/api/live/snapshot",
            headers={
                "Origin": "https://chatgpt.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        assert preflight.status_code == 204
        assert preflight.headers["access-control-allow-origin"] == "*"

        snapshot = client.get("/api/live/snapshot", headers=headers)
        assert snapshot.status_code == 200
        assert snapshot.headers["access-control-allow-origin"] == "*"
        assert snapshot.json()["data"]["channel"]["live_id"] == channel.live_id
        assert snapshot.json()["data"]["channel"]["session"]["session_id"] == logical["session_id"]
        assert (
            snapshot.json()["data"]["channel"]["session"]["objective"]
            == "Exercise human goal controls"
        )

        bootstrap = client.get("/api/ui/bootstrap", headers=headers)
        assert bootstrap.status_code == 200

        events = client.get("/api/live/events?after=0&timeout=1", headers=headers)
        assert events.status_code == 200
        assert events.json()["data"]["events"]
        assert events.json()["data"]["session"]["session_id"] == logical["session_id"]

        invalid_cursor = client.get("/api/live/events?after=not-a-number", headers=headers)
        assert invalid_cursor.status_code == 400
        assert invalid_cursor.json()["message"] == "Invalid event cursor"

        session_manager.manage_plan(
            session_id,
            action="start",
            objective="Exercise human goal controls",
            steps=[{"id": "work", "text": "Do the work"}],
        )
        not_due = client.post(
            "/api/live/plan/continuation",
            headers=headers,
            json={"action": "claim"},
        )
        assert not_due.status_code == 200
        assert not_due.json()["data"]["claimed"] is False

        logical_state = session_manager._sessions[logical["session_id"]]
        assert logical_state.plan is not None
        logical_state.plan.last_agent_activity -= session_runtime_module.PLAN_EXECUTION_LEASE_S + 1
        claimed = client.post(
            "/api/live/plan/continuation",
            headers=headers,
            json={"action": "claim"},
        )
        assert claimed.status_code == 200
        assert claimed.json()["data"]["claimed"] is True
        claim_id = claimed.json()["data"]["claim_id"]
        assert claim_id
        validated = client.post(
            "/api/live/plan/continuation",
            headers=headers,
            json={"action": "validate", "claim_id": claim_id},
        )
        assert validated.status_code == 200
        assert validated.json()["data"]["valid"] is True
        reported = client.post(
            "/api/live/plan/continuation",
            headers=headers,
            json={"action": "report", "claim_id": claim_id, "accepted": True},
        )
        assert reported.status_code == 200
        assert reported.json()["data"]["plan"]["continuation_count"] == 1
        invalid_continuation = client.post(
            "/api/live/plan/continuation",
            headers=headers,
            json={"action": "invalid"},
        )
        assert invalid_continuation.status_code == 400

        logical_state.plan.last_agent_activity -= session_runtime_module.PLAN_EXECUTION_LEASE_S + 1
        stale_claim = client.post(
            "/api/live/plan/continuation",
            headers=headers,
            json={"action": "claim"},
        )
        stale_claim_id = stale_claim.json()["data"]["claim_id"]
        paused = client.post(
            "/api/live/plan",
            headers=headers,
            json={"action": "pause", "note": "Auto continuation cancelled by user"},
        )
        assert paused.status_code == 200
        assert paused.json()["data"]["plan"]["status"] == "blocked"
        assert paused.json()["data"]["plan"]["note"] == "Auto continuation cancelled by user"
        invalidated = client.post(
            "/api/live/plan/continuation",
            headers=headers,
            json={"action": "validate", "claim_id": stale_claim_id},
        )
        assert invalidated.status_code == 200
        assert invalidated.json()["data"]["valid"] is False
        resumed = client.post("/api/live/plan", headers=headers, json={"action": "resume"})
        assert resumed.status_code == 200
        assert resumed.json()["data"]["plan"]["status"] == "active"
        cancelled = client.post("/api/live/plan", headers=headers, json={"action": "cancel"})
        assert cancelled.status_code == 200
        assert cancelled.json()["data"]["plan"]["status"] == "cancelled"
        assert any(
            event["type"] == "plan.cancelled" and event["actor"] == "human"
            for event in channel.events
        )
        invalid_plan = client.post("/api/live/plan", headers=headers, json={"action": "invalid"})
        assert invalid_plan.status_code == 400

        written = client.post(
            "/api/ui/files/write",
            headers=headers,
            json={"machine": "local", "path": "human.txt", "content": "shared"},
        )
        assert written.status_code == 200
        assert (tmp_path / "human.txt").read_text(encoding="utf-8") == "shared"

        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        (tmp_path / "tracked.txt").write_text("before\n", encoding="utf-8")
        subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Live Workspace Test",
                "-c",
                "user.email=live-workspace@example.invalid",
                "commit",
                "-qm",
                "seed",
            ],
            cwd=tmp_path,
            check=True,
        )
        (tmp_path / "tracked.txt").write_text("after\n", encoding="utf-8")
        git = client.get("/api/live/git?cwd=.", headers=headers)
        assert git.status_code == 200
        git_data = git.json()["data"]
        assert "tracked.txt" in git_data["status"]["stdout"]
        assert "before" in git_data["diff"]["stdout"]
        assert any(event["type"] == "human.inspected_diff" for event in channel.events)

        subprocess.run(["git", "checkout", "--", "tracked.txt"], cwd=tmp_path, check=True)
        clean_git = client.get("/api/live/git?cwd=.", headers=headers)
        assert clean_git.status_code == 200
        assert clean_git.json()["data"]["diff"]["stdout"] == ""

        # A live token is deliberately not valid for the MCP transport itself.
        mcp_attempt = client.post(
            "/mcp",
            headers={**headers, "Content-Type": "application/json"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert mcp_attempt.status_code in {401, 403}


def test_live_http_token_authenticates_when_global_auth_is_disabled(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth="none")
    manager = live_channel_module.get_live_channel_manager()
    channel, token = manager.open(
        subject="user",
        scopes=tuple(ALL_OAUTH_SCOPES),
    )
    app = _build_mcp_http_app(build_mcp())
    with TestClient(app, base_url="http://testserver") as client:
        same_origin = client.get(
            "/api/ui/files?machine=local&path=.",
            headers={"Origin": "http://testserver"},
        )
        anonymous_cross_origin = client.get(
            "/api/ui/files?machine=local&path=.",
            headers={"Origin": "https://malicious.example"},
        )
        snapshot = client.get(
            "/api/live/snapshot",
            headers={"Authorization": f"Bearer {token}", "Origin": "https://chatgpt.com"},
        )
        no_session_continuation = client.post(
            "/api/live/plan/continuation",
            headers={"Authorization": f"Bearer {token}"},
            json={"action": "claim"},
        )
        no_session_plan = client.post(
            "/api/live/plan",
            headers={"Authorization": f"Bearer {token}"},
            json={"action": "pause"},
        )
        _, replacement = manager.open(
            subject="user",
            scopes=tuple(ALL_OAUTH_SCOPES),
        )
        original_ui = client.get(
            "/api/ui/files?machine=local&path=.",
            headers={"Authorization": f"Bearer {token}", "Origin": "https://chatgpt.com"},
        )
        current_ui = client.get(
            "/api/ui/files?machine=local&path=.",
            headers={"Authorization": f"Bearer {replacement}", "Origin": "https://chatgpt.com"},
        )
    assert same_origin.status_code == 200
    assert anonymous_cross_origin.status_code == 401
    assert snapshot.status_code == 200
    assert snapshot.json()["data"]["channel"]["live_id"] == channel.live_id
    assert no_session_continuation.status_code == 200
    assert no_session_continuation.json()["data"] == {
        "claimed": False,
        "plan": None,
        "session_id": None,
    }
    assert no_session_plan.status_code == 409
    # A second unbound open is a distinct Workspace, so it must not rotate or
    # invalidate another conversation's credential. Both remain independently valid.
    assert original_ui.status_code == 200
    assert current_ui.status_code == 200
    assert manager.authenticate(token) is channel
    assert manager.authenticate(replacement) is not channel


def test_live_events_empty_batch_does_not_advance_cursor(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth="none")
    manager = live_channel_module.get_live_channel_manager()
    _, token = manager.open(
        subject="user",
        scopes=tuple(ALL_OAUTH_SCOPES),
    )

    async def empty_wait(channel, after, timeout_s):  # noqa: ARG001
        manager.publish_channel(
            channel.live_id,
            "tool.completed",
            actor="agent",
            data={"tool": "late"},
        )
        return {
            "events": [],
            "session_id": channel.logical_session_id,
            "binding_generation": channel.binding_generation,
            "seq": channel.seq,
            "cursor": after,
        }

    monkeypatch.setattr(manager, "wait_event_batch", empty_wait)
    app = _build_mcp_http_app(build_mcp())
    with TestClient(app, base_url="http://testserver") as client:
        response = client.get(
            "/api/live/events?after=0&timeout=1",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["events"] == []
    assert data["cursor"] == 0
    assert manager.events_since(manager.authenticate(token), 0)[-1]["data"]["tool"] == "late"


def test_live_workspace_is_hidden_when_ui_is_disabled(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth="none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_ENABLED", "false")
    get_settings.cache_clear()
    mcp = build_mcp()

    async def inspect_surface():
        tools = {tool.name for tool in await mcp.list_tools()}
        resources = {str(resource.uri) for resource in await mcp.list_resources()}
        return tools, resources

    tools, resources = asyncio.run(inspect_surface())
    assert "workspace_open" not in tools
    assert "open_live_workspace" not in tools
    assert LIVE_RESOURCE_URI not in resources

    app = _build_mcp_http_app(mcp)
    with TestClient(app, base_url="http://testserver") as client:
        assert client.get("/api/live/snapshot").status_code == 404


def test_live_workspace_is_hidden_when_feature_is_disabled(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth="none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_ENABLED", "true")
    monkeypatch.setenv("LOCAL_SHELL_MCP_LIVE_WORKSPACE_ENABLED", "false")
    get_settings.cache_clear()
    mcp = build_mcp()

    async def inspect_surface():
        tools = {tool.name for tool in await mcp.list_tools()}
        resources = {str(resource.uri) for resource in await mcp.list_resources()}
        return tools, resources

    tools, resources = asyncio.run(inspect_surface())
    assert "workspace_open" not in tools
    assert "open_live_workspace" not in tools
    assert LIVE_RESOURCE_URI not in resources

    app = _build_mcp_http_app(mcp)
    with TestClient(app, base_url="http://testserver") as client:
        assert client.get("/api/live/snapshot").status_code == 404
        assert client.get("/ui/").status_code == 200


def test_live_workspace_is_hidden_in_stdio_mode(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth="none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODE", "stdio")
    get_settings.cache_clear()
    mcp = build_mcp()

    async def inspect_surface():
        tools = {tool.name for tool in await mcp.list_tools()}
        resources = {str(resource.uri) for resource in await mcp.list_resources()}
        return tools, resources

    tools, resources = asyncio.run(inspect_surface())
    assert "workspace_open" not in tools
    assert "open_live_workspace" not in tools
    assert LIVE_RESOURCE_URI not in resources


def test_live_git_routes_remote_inspection_to_selected_machine(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth="oauth")
    manager = live_channel_module.get_live_channel_manager()
    _, token = manager.open(
        subject="user",
        scopes=tuple(ALL_OAUTH_SCOPES),
    )

    class FakeRemote:
        def __init__(self):
            self.calls = []

        async def call(self, machine, tool, args, timeout_s=None):
            self.calls.append((machine, tool, args, timeout_s))
            command = args["command"]
            stdout = (
                "## main\n" if "status" in command else "diff --git a/remote.txt b/remote.txt\n"
            )
            return {
                "ok": True,
                "message": "",
                "data": {
                    "ok": True,
                    "exit_code": 0,
                    "timed_out": False,
                    "duration_ms": 1,
                    "cwd": ".",
                    "command": command,
                    "stdout": stdout,
                    "stderr": "",
                    "truncated": False,
                },
            }

    fake_remote = FakeRemote()
    monkeypatch.setattr(live_routes, "remote_manager", lambda: fake_remote)
    app = _build_mcp_http_app(build_mcp())
    with TestClient(app, base_url="http://testserver") as client:
        response = client.get(
            "/api/live/git?machine=worker&cwd=.",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["machine"] == "worker"
    assert "remote.txt" in data["diff"]["stdout"]
    assert len(fake_remote.calls) == 3
    assert all(call[0] == "worker" and call[1] == "run_shell_tool" for call in fake_remote.calls)
    assert all(call[2]["_human"] is True for call in fake_remote.calls)


def test_live_route_helpers_reject_missing_or_expired_workspace(monkeypatch):
    request = Request(
        {"type": "http", "method": "GET", "path": "/api/live/snapshot", "headers": []}
    )
    request.state.principal = Principal(
        email=None,
        subject="user",
        claims={"scope": "shell:read"},
    )
    with pytest.raises(Exception, match="live-workspace token"):
        live_routes._live_channel(request)

    request.state.principal = Principal(
        email=None,
        subject="user",
        claims={"scope": "shell:read", "live_id": "expired"},
    )
    monkeypatch.setattr(live_routes, "get_live_channel_manager", lambda: LiveChannelManager())
    with pytest.raises(Exception, match="Live workspace expired"):
        live_routes._live_channel(request)


def test_live_route_principal_falls_back_to_request_verification(monkeypatch):
    request = Request(
        {"type": "http", "method": "GET", "path": "/api/live/snapshot", "headers": []}
    )
    expected = Principal(email=None, subject="verified", claims={})
    monkeypatch.setattr(live_routes, "current_principal", lambda: None)
    monkeypatch.setattr(live_routes, "verify_request", lambda _request: expected)
    assert live_routes._principal(request) is expected


def test_live_route_generic_error_response():
    response = live_routes._error(RuntimeError("boom"))
    assert response.status_code == 400
    assert b"boom" in response.body


@pytest.mark.asyncio
async def test_live_remote_git_shell_rejects_failed_and_invalid_payloads(monkeypatch):
    class FakeRemote:
        def __init__(self):
            self.response = {"ok": False, "message": "remote failed"}
            self.calls = []

        async def call(self, *args, **kwargs):  # noqa: ANN002, ANN003
            self.calls.append((args, kwargs))
            return self.response

    fake = FakeRemote()
    monkeypatch.setattr(live_routes, "remote_manager", lambda: fake)

    with pytest.raises(RuntimeError, match="remote failed"):
        await live_routes._run_machine_shell(
            "worker",
            "git status --short --branch",
            cwd=".",
            timeout_s=15,
            max_output_bytes=80_000,
        )
    args, kwargs = fake.calls[-1]
    assert args[2]["timeout_s"] == 15
    assert kwargs["execution_timeout_s"] == 15
    assert kwargs["rpc_timeout_s"] == live_routes.remote_execution_rpc_timeout_s(15)

    fake.response = {"ok": True, "data": "not-a-dict"}
    with pytest.raises(RuntimeError, match="invalid data"):
        await live_routes._run_machine_shell(
            "worker",
            "git status --short --branch",
            cwd=".",
            timeout_s=15,
            max_output_bytes=80_000,
        )


@pytest.mark.asyncio
async def test_live_snapshot_returns_missing_token_error():
    request = Request(
        {"type": "http", "method": "GET", "path": "/api/live/snapshot", "headers": []}
    )
    request.state.principal = Principal(
        email=None,
        subject="user",
        claims={"scope": "shell:read"},
    )
    response = await live_routes.live_snapshot(request)
    assert response.status_code == 403
    assert b"live-workspace token" in response.body


@pytest.mark.asyncio
async def test_live_events_detaches_channel_when_durable_session_disappears(monkeypatch):
    manager = LiveChannelManager()
    channel, token = manager.open(
        subject="user",
        scopes=tuple(ALL_OAUTH_SCOPES),
        logical_session_id="s_deleted_elsewhere",
    )

    class MissingSessionManager:
        def get(self, session_id, *, subject=None):  # noqa: ANN001, ANN201
            raise ValueError(f"Unknown logical session: {session_id}")

    monkeypatch.setattr(live_routes, "get_live_channel_manager", lambda: manager)
    monkeypatch.setattr(live_routes, "get_session_runtime_manager", lambda: MissingSessionManager())
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/live/events",
            "query_string": b"after=0&timeout=1",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
        }
    )
    request.state.principal = Principal(
        email=None,
        subject="user",
        claims={"scope": " ".join(ALL_OAUTH_SCOPES), "live_id": channel.live_id},
    )

    response = await live_routes.live_events(request)

    assert response.status_code == 200
    assert channel.logical_session_id is None
    assert "s_deleted_elsewhere" not in manager._logical_session_channels


def test_live_workspace_stale_live_id_falls_back_to_logical_channel():
    manager = LiveChannelManager()
    channel, _ = manager.open(
        subject="user",
        scopes=tuple(ALL_OAUTH_SCOPES),
        logical_session_id="s_task",
    )

    reattached, _ = manager.open(
        subject="user",
        scopes=tuple(ALL_OAUTH_SCOPES),
        live_id="expired-live-id",
        logical_session_id="s_task",
    )

    assert reattached is channel
    assert manager.active_for_logical_session("s_task", subject="user") is channel
    assert len(manager._channels) == 1


def test_live_workspace_detaches_deleted_logical_session():
    manager = LiveChannelManager()
    channel, _ = manager.open(
        subject="user",
        scopes=tuple(ALL_OAUTH_SCOPES),
        logical_session_id="s_deleted",
    )

    detached = manager.detach_logical_session("s_deleted")

    assert detached == [channel]
    assert channel.logical_session_id is None
    assert "s_deleted" not in manager._logical_session_channels
    assert channel.events[-1]["type"] == "session.detached"


@pytest.mark.asyncio
async def test_live_workspace_session_lookups_run_off_event_loop(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth="none")
    manager = session_runtime_module.get_session_runtime_manager()
    target = manager.manage(
        "local-mcp-client",
        action="start",
        objective="Reconnect target",
    )
    loop_thread = threading.get_ident()
    get_threads: list[int] = []
    original_get = manager.get

    def observed_get(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        get_threads.append(threading.get_ident())
        return original_get(*args, **kwargs)

    monkeypatch.setattr(manager, "get", observed_get)
    mcp = build_mcp()
    await mcp.call_tool(
        "live_workspace_reconnect",
        {"cwd": ".", "session_id": target["session_id"]},
    )

    assert get_threads and all(thread_id != loop_thread for thread_id in get_threads)


def test_live_resource_fallbacks_and_explicit_channel_rebinding(tmp_path, monkeypatch):
    missing = tmp_path / "missing.html"
    monkeypatch.setattr(live_channel_module, "_LIVE_RESOURCE_PATH", missing)
    assert live_channel_module._versioned_live_resource_uri().endswith("-unbuilt.html")

    aliases = tmp_path / "aliases.json"
    monkeypatch.setattr(live_channel_module, "_LIVE_RESOURCE_ALIASES_PATH", aliases)
    assert live_channel_module._compat_live_resource_uris() == ()
    aliases.write_text("{}", encoding="utf-8")
    assert live_channel_module._compat_live_resource_uris() == ()
    aliases.write_text(
        '[123, "bad", "0123456789ABCDEF", "0123456789abcdef", "0123456789abcdeg"]',
        encoding="utf-8",
    )
    assert live_channel_module._compat_live_resource_uris() == (
        "ui://local-shell-mcp/live-workspace-0123456789abcdef.html",
    )

    manager = LiveChannelManager()
    channel, _ = manager.open(subject="user", scopes=tuple(ALL_OAUTH_SCOPES))
    with manager._lock:
        manager._set_logical_session_locked(channel, "s_one")
        first_generation = channel.binding_generation
        manager._set_logical_session_locked(channel, "s_one")
        assert channel.binding_generation == first_generation
        manager._set_logical_session_locked(channel, "s_two")
    assert manager.active_for_logical_session("s_one") is None
    assert manager.active_for_logical_session("s_two") is channel
    assert manager.active_for_logical_session("s_two", subject="other") is None
    detached = manager.detach_logical_session("s_two")
    assert detached == [channel]
    assert channel.logical_session_id is None


def test_live_routes_reject_binding_churn_and_stale_continuation(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth="oauth")
    live_manager = live_channel_module.get_live_channel_manager()
    session_manager = session_runtime_module.get_session_runtime_manager()
    session_id = session_manager.manage(
        "user", action="start", objective="Binding churn"
    )["session_id"]
    session_manager.manage_plan(
        session_id,
        action="start",
        objective="Binding churn",
        steps=[{"id": "work", "text": "Work"}],
    )
    channel, token = live_manager.open(
        subject="user",
        scopes=tuple(ALL_OAUTH_SCOPES),
        logical_session_id=session_id,
    )
    headers = {"Authorization": f"Bearer {token}"}
    app = _build_mcp_http_app(build_mcp())

    with TestClient(app, base_url="http://testserver") as client:
        monkeypatch.setattr(live_manager, "binding_matches", lambda *_args, **_kwargs: False)
        snapshot = client.get("/api/live/snapshot", headers=headers)
        assert snapshot.status_code == 409
        events = client.get("/api/live/events?after=0&timeout=1", headers=headers)
        assert events.status_code == 409

        paused = client.post(
            "/api/live/plan", headers=headers, json={"action": "pause"}
        )
        assert paused.status_code == 409

        # Restore the real binding check and reactivate the Plan after the human
        # mutation above; then exercise continuation request validation.
        monkeypatch.undo()
        _configure(tmp_path, monkeypatch, auth="oauth")
        live_manager = live_channel_module.get_live_channel_manager()
        session_manager = session_runtime_module.get_session_runtime_manager()
        session_id = session_manager.manage(
            "user", action="start", objective="Stale continuation"
        )["session_id"]
        session_manager.manage_plan(
            session_id,
            action="start",
            objective="Stale continuation",
            steps=[{"id": "work", "text": "Work"}],
        )
        state = session_manager._sessions[session_id]
        assert state.plan is not None
        state.plan.last_agent_activity -= session_runtime_module.PLAN_EXECUTION_LEASE_S + 1
        channel, token = live_manager.open(
            subject="user",
            scopes=tuple(ALL_OAUTH_SCOPES),
            logical_session_id=session_id,
        )
        headers = {"Authorization": f"Bearer {token}"}
        app = _build_mcp_http_app(build_mcp())
        missing_validate = client.post(
            "/api/live/plan/continuation",
            headers=headers,
            json={"action": "validate"},
        )
        assert missing_validate.status_code == 400
        missing_report = client.post(
            "/api/live/plan/continuation",
            headers=headers,
            json={"action": "report", "accepted": False},
        )
        assert missing_report.status_code == 400

    # Use a fresh TestClient after reconfiguring module globals above.
    with TestClient(app, base_url="http://testserver") as client:
        monkeypatch.setattr(live_manager, "binding_matches", lambda *_args, **_kwargs: False)
        stale = client.post(
            "/api/live/plan/continuation",
            headers=headers,
            json={"action": "claim", "claim_id": "c_binding_changed"},
        )
        assert stale.status_code == 409
    assert session_manager.plan_state(session_id)["continuation_pending"] is False


def test_live_git_route_reports_local_failure(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth="oauth")
    manager = live_channel_module.get_live_channel_manager()
    _channel, token = manager.open(subject="user", scopes=tuple(ALL_OAUTH_SCOPES))
    monkeypatch.setenv("LOCAL_SHELL_MCP_DISABLE_LOCAL", "true")
    get_settings.cache_clear()
    app = _build_mcp_http_app(build_mcp())
    with TestClient(app, base_url="http://testserver") as client:
        response = client.get(
            "/api/live/git?machine=local&cwd=.",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 400
    assert "Local access is disabled" in response.json()["message"]
