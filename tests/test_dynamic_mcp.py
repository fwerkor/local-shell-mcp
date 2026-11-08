from __future__ import annotations

import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.types import CallToolResult, TextContent, Tool

from local_shell_mcp import dynamic_mcp
from local_shell_mcp.dynamic_mcp import DynamicMCPManager
from local_shell_mcp.settings import get_settings

pytestmark = pytest.mark.usefixtures("legacy_file_state_backend")

@pytest.fixture(autouse=True)
def _settings(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

def _server_script(path: Path) -> Path:
    script = path / "demo_mcp.py"
    script.write_text(
        """
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("demo")

@mcp.tool()
def echo(text: str) -> str:
    return "echo:" + text

if __name__ == "__main__":
    mcp.run(transport="stdio")
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return script

@pytest.mark.asyncio
async def test_stdio_gateway_round_trip_persists_cache_and_redacts_config(tmp_path):
    state_dir = tmp_path / ".state"
    manager = DynamicMCPManager(state_dir)
    script = _server_script(tmp_path)

    registered = await manager.manage(
        action="register",
        name="demo",
        transport="stdio",
        command=sys.executable,
        args=[str(script)],
        cwd=str(tmp_path),
        env={"DEMO_TOKEN": "very-secret"},
        headers={"Authorization": "Bearer also-secret"},
    )
    public = registered["server"]
    assert registered["refreshed"] is True
    assert public["tool_count"] == 1
    assert public["env_keys"] == ["DEMO_TOKEN"]
    assert public["header_keys"] == ["Authorization"]
    assert "very-secret" not in repr(public)
    assert "also-secret" not in repr(public)
    if os.name != "nt":
        assert (state_dir / "dynamic-mcp.json").stat().st_mode & 0o777 == 0o600

    found = await manager.search("echo")
    assert found["tools"][0]["name"] == "demo:echo"
    inspected = await manager.inspect("demo:echo")
    assert inspected["tool"]["inputSchema"]["required"] == ["text"]
    called = await manager.call("demo:echo", {"text": "hello"})
    assert called["result"]["content"][0]["text"] == "echo:hello"

    reloaded = DynamicMCPManager(state_dir)
    assert (await reloaded.search("echo"))["tools"][0]["name"] == "demo:echo"
    listed = await reloaded.manage(action="list")
    assert listed["servers"][0]["name"] == "demo"
    assert (await reloaded.manage(action="get", name="demo"))["server"]["tool_count"] == 1

    await reloaded.manage(action="env_set", name="demo", key="EXTRA", value="secret")
    await reloaded.manage(action="header_set", name="demo", key="X-Test", value="secret")
    changed = await reloaded.manage(action="get", name="demo")
    assert changed["server"]["env_keys"] == ["DEMO_TOKEN", "EXTRA"]
    assert changed["server"]["header_keys"] == ["Authorization", "X-Test"]
    await reloaded.manage(action="env_unset", name="demo", key="EXTRA")
    await reloaded.manage(action="header_unset", name="demo", key="X-Test")
    assert (await reloaded.search(server="demo"))["unrefreshed_servers"] == ["demo"]
    await reloaded.manage(action="refresh", name="demo")

    await reloaded.manage(action="disable", name="demo")
    assert (await reloaded.search("echo"))["tools"] == []
    with pytest.raises(ValueError, match="disabled"):
        await reloaded.call("demo:echo", {"text": "x"})
    await reloaded.manage(action="enable", name="demo")
    assert (await reloaded.search("echo"))["total_matches"] == 1

    removed = await reloaded.manage(action="remove", name="demo")
    assert removed["removed"] is True
    assert (await reloaded.manage(action="list"))["servers"] == []

@pytest.mark.asyncio
async def test_register_without_refresh_and_refresh_failure_are_recoverable(tmp_path, monkeypatch):
    manager = DynamicMCPManager(tmp_path / ".state")
    script = _server_script(tmp_path)

    saved = await manager.manage(
        action="register",
        name="cold",
        command=sys.executable,
        args=[str(script)],
        refresh=False,
    )
    assert saved["refreshed"] is False
    assert saved["server"]["cwd"] == str(tmp_path.resolve())
    search = await manager.search(server="cold")
    assert search["tools"] == []
    assert search["unrefreshed_servers"] == ["cold"]

    async def fail_refresh(_server):
        raise RuntimeError(
            "offline env-secret header-secret "
            "postgres://user:db-pass@db.example.test/app "
            "DefaultEndpointsProtocol=https;AccountKey=storage-secret"
        )

    monkeypatch.setattr(manager, "_fetch_tools", fail_refresh)
    failed = await manager.manage(
        action="register",
        name="broken",
        command=sys.executable,
        args=[str(script)],
        env={
            "TOKEN": "env-secret",
            "DATABASE_URL": "postgres://user:db-pass@db.example.test/app",
            "AZURE_STORAGE_CONNECTION_STRING": (
                "DefaultEndpointsProtocol=https;AccountKey=storage-secret"
            ),
        },
        headers={"Authorization": "header-secret"},
    )
    assert failed["refreshed"] is False
    assert failed["refresh_error"] == (
        "offline <redacted> <redacted> <redacted> <redacted>"
    )
    assert "env-secret" not in repr(failed)
    assert "header-secret" not in repr(failed)
    assert "db-pass" not in repr(failed)
    assert "storage-secret" not in repr(failed)
    assert {row["name"] for row in (await manager.manage(action="list"))["servers"]} == {
        "broken",
        "cold",
    }

@pytest.mark.asyncio
async def test_http_transport_pagination_call_and_tool_limit(tmp_path, monkeypatch):
    manager = DynamicMCPManager(tmp_path / ".state")
    await manager.manage(
        action="register",
        name="web",
        transport="streamable_http",
        url="https://mcp.example.test/mcp",
        headers={"Authorization": "Bearer hidden"},
        refresh=False,
    )

    seen: dict[str, object] = {}

    @asynccontextmanager
    async def fake_http(url, headers):
        seen["url"] = url
        seen["headers"] = headers
        yield object(), object(), lambda: "session"

    class FakeSession:
        def __init__(self, _read, _write):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def initialize(self):
            seen["initialized"] = True

        async def list_tools(self, cursor=None):
            self.calls += 1
            if cursor is None:
                return SimpleNamespace(
                    tools=[Tool(name="alpha", description="first tool", inputSchema={})],
                    nextCursor="next",
                )
            return SimpleNamespace(
                tools=[Tool(name="beta", description="second tool", inputSchema={})],
                nextCursor=None,
            )

        async def call_tool(self, name, arguments):
            seen["call"] = (name, arguments)
            return CallToolResult(
                content=[TextContent(type="text", text="ok Bearer hidden")], isError=False
            )

    monkeypatch.setattr(dynamic_mcp, "streamablehttp_client", fake_http)
    monkeypatch.setattr(dynamic_mcp, "ClientSession", FakeSession)

    refreshed = await manager.manage(action="refresh", name="web")
    assert refreshed["server"]["tool_count"] == 2
    assert seen["url"] == "https://mcp.example.test/mcp"
    assert seen["headers"] == {"Authorization": "Bearer hidden"}
    assert seen["initialized"] is True
    assert [item["name"] for item in (await manager.search("tool"))["tools"]] == [
        "web:alpha",
        "web:beta",
    ]
    called = await manager.call("web:alpha", {"x": 1}, timeout_s=5)
    assert called["result"]["content"][0]["text"] == "ok <redacted>"
    assert "Bearer hidden" not in repr(called)
    assert seen["call"] == ("alpha", {"x": 1})

    monkeypatch.setattr(dynamic_mcp, "_MAX_TOOLS_PER_SERVER", 1)
    with pytest.raises(ValueError, match="more than 1 tools"):
        await manager.refresh("web")

def test_config_redaction_only_treats_secret_like_values_as_substrings():
    server = dynamic_mcp.DynamicMCPServer(
        name="demo",
        transport="stdio",
        env={
            "FLAG": "1",
            "MODE": "on",
            "TYPE_TOKEN": "text",
            "TOKEN": "token-12345",
            "SHORT_TOKEN": "abc",
            "GITHUB_PAT": "github-pat-secret",
            "PGPASSWORD": "postgres-secret",
            "DATABASE_URL": "postgres://user:db-pass@db.example.test/app",
            "AZURE_STORAGE_CONNECTION_STRING": (
                "DefaultEndpointsProtocol=https;AccountKey=storage-secret"
            ),
        },
        headers={"Authorization": "Bearer hidden"},
    )
    payload = {
        "content": [
            {
                "type": "text",
                "text": (
                    "version 1 is on; token-12345; Bearer hidden; abc suffix; "
                    "github-pat-secret; postgres-secret; "
                    "postgres://user:db-pass@db.example.test/app; "
                    "DefaultEndpointsProtocol=https;AccountKey=storage-secret"
                ),
            }
        ],
        "structuredContent": {
            "type": "abc",
            "mode": "on",
            "flag": "1",
            "token": "abc",
            "Bearer hidden": True,
            "prefix-token-12345-suffix": "value",
        },
    }

    redacted = dynamic_mcp._redact_config_value(payload, server)

    assert redacted["content"][0]["type"] == "text"
    assert redacted["content"][0]["text"] == (
        "version 1 is on; <redacted>; <redacted>; abc suffix; <redacted>; <redacted>; "
        "<redacted>; <redacted>"
    )
    assert redacted["structuredContent"]["type"] == "<redacted>"
    assert redacted["structuredContent"]["mode"] == "on"
    assert redacted["structuredContent"]["flag"] == "1"
    assert redacted["structuredContent"]["token"] == "<redacted>"
    assert redacted["structuredContent"]["<redacted>"] is True
    assert redacted["structuredContent"]["prefix-<redacted>-suffix"] == "value"
    assert "Bearer hidden" not in repr(redacted)
    assert "token-12345" not in repr(redacted)
    assert "github-pat-secret" not in repr(redacted)
    assert "postgres-secret" not in repr(redacted)
    assert "db-pass" not in repr(redacted)
    assert "storage-secret" not in repr(redacted)

def test_config_redaction_preserves_call_tool_result_root_keys():
    server = dynamic_mcp.DynamicMCPServer(
        name="demo",
        transport="stdio",
        env={
            "CONTENT_TOKEN": "content",
            "ERROR_TOKEN": "isError",
            "STRUCTURED_TOKEN": "structuredContent",
            "META_TOKEN": "_meta",
        },
    )
    payload = {
        "content": [{"type": "text", "text": "ok"}],
        "structuredContent": {"content": "content"},
        "isError": True,
        "_meta": {"isError": "isError"},
    }

    redacted = dynamic_mcp._redact_config_value(payload, server)

    assert set(redacted) == {"content", "structuredContent", "isError", "_meta"}
    assert redacted["isError"] is True
    assert redacted["structuredContent"] == {"<redacted>": "<redacted>"}
    assert redacted["_meta"] == {"<redacted>": "<redacted>"}

@pytest.mark.asyncio
async def test_legacy_stdio_registry_without_cwd_uses_workspace(tmp_path):
    state_dir = tmp_path / ".state"
    state_dir.mkdir()
    registry = state_dir / "dynamic-mcp.json"
    registry.write_text(
        json.dumps(
            {
                "version": 1,
                "servers": [
                    {
                        "name": "legacy",
                        "transport": "stdio",
                        "enabled": True,
                        "command": sys.executable,
                        "args": [],
                        "cwd": None,
                        "env": {},
                        "headers": {},
                        "tools": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    manager = DynamicMCPManager(state_dir)
    server = (await manager.manage(action="get", name="legacy"))["server"]
    assert server["cwd"] == str(tmp_path.resolve())

@pytest.mark.asyncio
async def test_registry_uses_same_compact_encoding_as_schema_limits(tmp_path):
    state_dir = tmp_path / ".state"
    manager = DynamicMCPManager(state_dir)
    await manager.manage(
        action="register",
        name="compact",
        command=sys.executable,
        refresh=False,
    )
    raw = (state_dir / "dynamic-mcp.json").read_text(encoding="utf-8")
    assert "\n  " not in raw
    assert json.loads(raw)["servers"][0]["name"] == "compact"

@pytest.mark.asyncio
async def test_tool_schema_cache_enforces_descriptor_and_total_byte_limits(tmp_path, monkeypatch):
    manager = DynamicMCPManager(tmp_path / ".state")
    server = dynamic_mcp.DynamicMCPServer(
        name="demo", transport="stdio", command=sys.executable, cwd=str(tmp_path)
    )

    class FakeSession:
        async def list_tools(self, cursor=None):
            return SimpleNamespace(
                tools=[
                    Tool(name="one", description="x" * 80, inputSchema={}),
                    Tool(name="two", description="y" * 80, inputSchema={}),
                ],
                nextCursor=None,
            )

    @asynccontextmanager
    async def fake_session(_server):
        yield FakeSession()

    monkeypatch.setattr(manager, "_session", fake_session)
    monkeypatch.setattr(dynamic_mcp, "_MAX_TOOL_DESCRIPTOR_BYTES", 64)
    with pytest.raises(ValueError, match="descriptor exceeds"):
        await manager._fetch_tools(server)

    monkeypatch.setattr(dynamic_mcp, "_MAX_TOOL_DESCRIPTOR_BYTES", 1024)
    monkeypatch.setattr(dynamic_mcp, "_MAX_TOOL_CACHE_BYTES_PER_SERVER", 200)
    with pytest.raises(ValueError, match="cache exceeds"):
        await manager._fetch_tools(server)

@pytest.mark.asyncio
async def test_validation_policy_and_registry_error_paths(tmp_path, monkeypatch):
    manager = DynamicMCPManager(tmp_path / ".state", max_timeout_s=5)
    script = _server_script(tmp_path)

    with pytest.raises(ValueError, match="name must match"):
        await manager.manage(action="register", name="bad name", command=sys.executable)
    with pytest.raises(ValueError, match="transport"):
        await manager.manage(action="register", name="bad", transport="unsupported", command="python")
    with pytest.raises(ValueError, match="command is required"):
        await manager.manage(action="register", name="missing", transport="stdio")
    with pytest.raises(ValueError, match="absolute HTTP"):
        await manager.manage(action="register", name="web", transport="streamable_http")
    with pytest.raises(ValueError, match="command is only valid"):
        await manager.manage(
            action="register",
            name="web",
            transport="streamable_http",
            url="https://example.test/mcp",
            command="python",
        )
    with pytest.raises(PermissionError):
        await manager.manage(
            action="register", name="denied", command="mount", args=["/tmp/x"], refresh=False
        )
    with pytest.raises(ValueError, match="Path escapes workspace"):
        await manager.manage(
            action="register",
            name="outside",
            command=sys.executable,
            cwd=str(tmp_path.parent),
            refresh=False,
        )
    with pytest.raises(ValueError, match="env keys"):
        await manager.manage(
            action="register", name="bad-env", command=sys.executable, env={"": "x"}
        )
    with pytest.raises(ValueError, match="env values"):
        await manager.manage(
            action="register", name="bad-value", command=sys.executable, env={"X": 1}
        )

    await manager.manage(
        action="register",
        name="demo",
        command=sys.executable,
        args=[str(script)],
        refresh=False,
    )
    with pytest.raises(ValueError, match="already exists"):
        await manager.manage(
            action="register",
            name="demo",
            command=sys.executable,
            args=[str(script)],
            refresh=False,
        )
    await manager.manage(
        action="register",
        name="demo",
        command=sys.executable,
        args=[str(script)],
        refresh=False,
        overwrite=True,
    )
    for action in ("get", "enable", "remove", "refresh"):
        with pytest.raises(ValueError, match="unknown dynamic MCP server"):
            await manager.manage(action=action, name="missing")
    with pytest.raises(ValueError, match="name is required"):
        await manager.manage(action="get")
    with pytest.raises(ValueError, match="action must be"):
        await manager.manage(action="wat", name="demo")
    with pytest.raises(ValueError, match="key is required"):
        await manager.manage(action="env_set", name="demo")
    with pytest.raises(ValueError, match="value is required"):
        await manager.manage(action="env_set", name="demo", key="X")
    with pytest.raises(ValueError, match="unknown dynamic MCP server"):
        await manager.search(server="missing")
    with pytest.raises(ValueError, match="<server>:<tool>"):
        await manager.inspect("invalid")
    with pytest.raises(ValueError, match="unknown cached tool"):
        await manager.inspect("demo:nope")
    with pytest.raises(ValueError, match="unknown cached tool"):
        await manager.call("demo:nope")

    registry = tmp_path / ".state" / "dynamic-mcp.json"
    registry.write_text("not json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unable to read"):
        await manager.manage(action="list")
    registry.write_text('{"version":999,"servers":[]}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="unsupported"):
        await manager.manage(action="list")

    class Unsupported:
        pass

    with pytest.raises(TypeError, match="unsupported MCP tool descriptor"):
        dynamic_mcp._tool_json(Unsupported())

@pytest.mark.asyncio
async def test_refresh_detects_removal_race(tmp_path, monkeypatch):
    manager = DynamicMCPManager(tmp_path / ".state")
    await manager.manage(action="register", name="demo", command=sys.executable, refresh=False)

    async def remove_during_fetch(_server):
        await manager.manage(action="remove", name="demo")
        return []

    monkeypatch.setattr(manager, "_fetch_tools", remove_during_fetch)
    with pytest.raises(ValueError, match="removed while refreshing"):
        await manager.refresh("demo")

@pytest.mark.asyncio
async def test_refresh_discards_tools_when_configuration_changes(tmp_path, monkeypatch):
    manager = DynamicMCPManager(tmp_path / ".state")
    await manager.manage(action="register", name="demo", command=sys.executable, refresh=False)

    async def reconfigure_during_fetch(_server):
        await manager.manage(action="env_set", name="demo", key="TOKEN", value="new-value")
        return [Tool(name="stale", inputSchema={})]

    monkeypatch.setattr(manager, "_fetch_tools", reconfigure_during_fetch)
    with pytest.raises(RuntimeError, match="configuration changed while refreshing"):
        await manager.refresh("demo")
    searched = await manager.search(server="demo")
    assert searched["tools"] == []
    assert searched["unrefreshed_servers"] == ["demo"]
