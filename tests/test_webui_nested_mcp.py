"""Nested MCP discovery and explicit durable approval before external execution."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui import generation_routes, nested_mcp, routes
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig


class MockRegistry:
    def __init__(self):
        self.actions = []

    async def search(self, query="", *, server=None, limit=20):
        self.actions.append(("search", query))
        return {"tools": [{"name": "test:echo", "description": "Echo a string"}]}

    async def inspect(self, name):
        self.actions.append(("inspect", name))
        return {"name": name, "tool": {"inputSchema": {"type": "object"}}}

    async def call(self, name, arguments=None, *, timeout_s=None):
        self.actions.append(("call", name, arguments))
        return {"name": name, "result": {"content": [{"type": "text", "text": "echo:approved"}]}}


@pytest.mark.asyncio
@pytest.mark.parametrize("decision,expected", [
    ("approve", "External MCP returned echo:approved."),
    ("reject", "External MCP was rejected by the user."),
])
async def test_mcp_discovery_and_tool_call_requires_human_approval(tmp_path, monkeypatch, decision, expected):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    registry = MockRegistry()
    monkeypatch.setattr(nested_mcp, "_manager", lambda: registry)
    monkeypatch.setattr(generation_routes, "provider_config", lambda *_: ProviderConfig(
        "openai", "mock", "http://127.0.0.1:11434/v1/chat/completions", "",
    ))

    async def model(profile, history, *, tools, **kwargs):
        assert {tool["function"]["name"] for tool in tools} == {
            "mcp_tool_search", "mcp_tool_inspect", "mcp_tool_call"
        }
        count = sum(1 for item in history if item.get("role") == "tool")
        if count == 0:
            yield ModelToolCall("search-1", "mcp_tool_search", {"query": "echo"})
        elif count == 1:
            yield ModelToolCall("call-2", "mcp_tool_call", {
                "name": "test:echo", "arguments": {"text": "hello"},
            })
        else:
            if decision == "approve":
                assert "echo:approved" in history[-1]["content"]
                yield "External MCP returned echo:approved."
            else:
                assert "rejected" in history[-1]["content"]
                yield "External MCP was rejected by the user."

    monkeypatch.setattr(generation_routes, "stream_model_with_tools", model)
    app = Starlette(routes=[*generation_routes.generation_routes(), *routes.webui_routes()])
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            cid = (await client.post("/api/convos", json={"title": "External MCP"})).json()["conversationId"]
            from local_shell_mcp.webui.routes import _repo

            _repo().save_setting("local", "conversation.permissions." + cid, {"mcp": True})
            submitted = await client.post("/api/agents/chat", json={"text": "Find and use echo", "conversationId": cid})
            assert submitted.status_code == 202, submitted.text
            for _ in range(120):
                status = (await client.get(f"/api/agents/chat/status/{cid}")).json()
                if status.get("status") in {"requires_action", "complete", "error"}:
                    break
                await asyncio.sleep(.02)
            assert status["status"] == "requires_action", status
            pending = status["pendingAction"]
            assert pending["payload"]["type"] == "tool_approval"
            assert pending["payload"]["action_requests"][0]["tool_call_id"] == "call-2"
            assert all(entry[0] != "call" for entry in registry.actions)
            stale = await client.post("/api/agents/chat/resume", json={
                "conversationId": cid, "actionId": "wrong", "decisions": [
                    {"tool_call_id": "call-2", "decision": "approve"},
                ],
            })
            assert stale.status_code == 409
            partial = await client.post("/api/agents/chat/resume", json={
                "conversationId": cid, "actionId": pending["actionId"], "decisions": [],
            })
            assert partial.status_code == 400
            chosen = await client.post("/api/agents/chat/resume", json={
                "conversationId": cid, "actionId": pending["actionId"], "decisions": [
                    {"tool_call_id": "call-2", "decision": decision},
                ],
            })
            assert chosen.status_code == 200, chosen.text
            for _ in range(120):
                status = (await client.get(f"/api/agents/chat/status/{cid}")).json()
                if status.get("status") in {"complete", "error"}:
                    break
                await asyncio.sleep(.02)
            assert status["status"] == "complete", status
            finished = generation_routes._generation_store().latest("local", cid)
            final = generation_routes._generation_store().events("local", finished.run_id)[-1][1]
            assert final["responseMessage"]["text"] == expected
            assert sum(1 for entry in registry.actions if entry[0] == "call") == (1 if decision == "approve" else 0)
            assert (await client.post("/api/agents/chat/resume", json={
                "conversationId": cid, "actionId": pending["actionId"], "decisions": [
                    {"tool_call_id": "call-2", "decision": decision},
                ],
            })).status_code == 409
    finally:
        await generation_routes.shutdown_generations()
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_nested_mcp_disabled_by_default_and_management_tool_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    from local_shell_mcp.webui.routes import _repo

    repo = _repo()
    cid = repo.create_conversation("local", {"title": "No MCP"})["conversationId"]
    registry = MockRegistry()
    monkeypatch.setattr(nested_mcp, "_manager", lambda: registry)
    try:
        with pytest.raises(PermissionError, match="disabled"):
            await nested_mcp.discover("local", cid, {"shell:read"},
                                      ModelToolCall("1", "mcp_tool_search", {}))
        repo.save_setting("local", "conversation.permissions." + cid, {"mcp": True})
        inspected = json.loads(await nested_mcp.discover("local", cid, {"shell:read"},
                                                         ModelToolCall("2", "mcp_tool_inspect", {"name": "test:echo"})))
        assert inspected["name"] == "test:echo"
        with pytest.raises(PermissionError, match="approval"):
            await nested_mcp.discover("local", cid, {"shell:read"},
                                      ModelToolCall("3", "mcp_tool_call", {"name": "test:echo"}))
        with pytest.raises(PermissionError, match="shell:execute"):
            await nested_mcp.approved_call("local", cid, {"shell:read"},
                                           ModelToolCall("3", "mcp_tool_call", {"name": "test:echo"}))
        assert all(tool["function"]["name"] != "mcp_manage" for tool in nested_mcp.MCP_TOOLS)
    finally:
        get_settings.cache_clear()
