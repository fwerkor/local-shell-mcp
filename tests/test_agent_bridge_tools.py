import json

import pytest

import local_shell_mcp.tools as tools_module
from local_shell_mcp.agent_mcp import AgentMcpTool
from local_shell_mcp.config.settings import get_settings
from local_shell_mcp.tools import build_mcp


def _payload(response):  # noqa: ANN001
    return json.loads(response[0].text)


REALISTIC_SECRET_ERROR = (
    'env={"GITHUB_TOKEN": "ghp_secret"} '
    '{ "X-API-Key": "super secret with spaces!" } '
    "AWS_SECRET_ACCESS_KEY=abc123\n"
    "Authorization: Basic abc123\n"
    "Cookie: session=abc123; refresh=def456\n"
    "standalone sk-1234567890abcdef1234567890abcdef AKIA1234567890ABCDEF\n"
    "password: multi word secret"
)
REALISTIC_SECRET_VALUES = [
    "ghp_secret",
    "super secret with spaces!",
    "abc123",
    "def456",
    "sk-1234567890abcdef1234567890abcdef",
    "AKIA1234567890ABCDEF",
    "multi word secret",
]
CONFIGURED_ENV_VALUE = "custom-secret"
CONFIGURED_HEADER_VALUE = "super-secret"
CONFIGURED_VALUE_ERROR = f"env={{'CUSTOM': '{CONFIGURED_ENV_VALUE}'}} headers={{'X-Auth': '{CONFIGURED_HEADER_VALUE}'}}"
SERIALIZED_ENV_VALUE = "line1\nline2"
SERIALIZED_HEADER_VALUE = 'token "quoted" \\ path'
SERIALIZED_ENV_VALUE_ESCAPED = json.dumps(SERIALIZED_ENV_VALUE)[1:-1]
SERIALIZED_HEADER_VALUE_ESCAPED = json.dumps(SERIALIZED_HEADER_VALUE)[1:-1]
SERIALIZED_CONFIGURED_VALUE_ERROR = (
    f"env exact={SERIALIZED_ENV_VALUE} escaped={SERIALIZED_ENV_VALUE_ESCAPED} "
    f"headers exact={SERIALIZED_HEADER_VALUE} escaped={SERIALIZED_HEADER_VALUE_ESCAPED}"
)


def _assert_realistic_secret_values_redacted(payload: str) -> None:
    for secret in REALISTIC_SECRET_VALUES:
        assert secret not in payload
    assert "<redacted>" in payload


def _assert_configured_values_redacted(payload: str) -> None:
    assert CONFIGURED_ENV_VALUE not in payload
    assert CONFIGURED_HEADER_VALUE not in payload
    assert "<redacted>" in payload


def _assert_serialized_configured_values_redacted(
    payload: str, message: str
) -> None:
    payload_secret_forms = [
        SERIALIZED_ENV_VALUE,
        SERIALIZED_ENV_VALUE_ESCAPED,
        json.dumps(SERIALIZED_ENV_VALUE_ESCAPED)[1:-1],
        SERIALIZED_HEADER_VALUE,
        SERIALIZED_HEADER_VALUE_ESCAPED,
        json.dumps(SERIALIZED_HEADER_VALUE_ESCAPED)[1:-1],
    ]
    message_secret_forms = [
        SERIALIZED_ENV_VALUE,
        SERIALIZED_ENV_VALUE_ESCAPED,
        SERIALIZED_HEADER_VALUE,
        SERIALIZED_HEADER_VALUE_ESCAPED,
    ]
    for secret in payload_secret_forms:
        assert secret not in payload
    for secret in message_secret_forms:
        assert secret not in message
    assert "<redacted>" in payload
    assert "<redacted>" in message


@pytest.mark.asyncio
async def test_fixed_bridge_tools_exist_with_missing_config(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace")
    )
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(tmp_path / "agent-config")
    )
    get_settings.cache_clear()

    mcp = build_mcp()
    tools = {tool.name for tool in await mcp.list_tools()}

    assert "agent_config_status" in tools
    assert "list_agent_skills" in tools
    assert "activate_agent_skill" in tools
    assert "list_agent_mcp_servers" in tools
    assert "list_agent_mcp_tools" in tools
    assert "call_agent_mcp_tool" in tools


@pytest.mark.asyncio
async def test_agent_config_status_reports_missing_config(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace")
    )
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(tmp_path / "agent-config")
    )
    get_settings.cache_clear()

    response = await build_mcp().call_tool("agent_config_status", {})
    payload = response[0].text

    assert "missing_config" in payload


@pytest.mark.asyncio
async def test_agent_config_status_redacts_probe_error(tmp_path, monkeypatch):
    config_dir = tmp_path / "agent-config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "mcpServers": {
                    "bad": {
                        "type": "http",
                        "url": "https://bad.example/mcp",
                        "env": {"CUSTOM": CONFIGURED_ENV_VALUE},
                        "headers": {"X-Auth": CONFIGURED_HEADER_VALUE},
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeMcpClientManager:
        async def list_tools(self, name, server):  # noqa: ANN001, ARG002
            raise RuntimeError(
                f"{REALISTIC_SECRET_ERROR} {CONFIGURED_VALUE_ERROR}"
            )

        async def call_tool(self, name, server, tool, args):  # noqa: ANN001, ARG002
            raise AssertionError("unavailable server should not be called")

    monkeypatch.setattr(
        tools_module,
        "AgentMcpClientManager",
        lambda _timeout: FakeMcpClientManager(),
    )
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace")
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    get_settings.cache_clear()

    response = await build_mcp().call_tool("agent_config_status", {})
    payload = response[0].text

    _assert_realistic_secret_values_redacted(payload)
    _assert_configured_values_redacted(payload)


@pytest.mark.asyncio
async def test_agent_config_status_redacts_env_and_header_values(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / "agent-config"
    config_dir.mkdir()
    env_token = "ghp_1234567890abcdef1234567890abcdef123456"
    header_value = "Bearer supersecret"
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "mcpServers": {
                    "off": {
                        "type": "http",
                        "url": "https://off.example/mcp",
                        "enabled": False,
                        "env": {"CUSTOM": env_token},
                        "headers": {"X-Auth": header_value},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace")
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    get_settings.cache_clear()

    response = await build_mcp().call_tool("agent_config_status", {})
    payload = response[0].text
    server = _payload(response)["data"]["mcp_servers"]["off"]

    assert env_token not in payload
    assert header_value not in payload
    assert server["env"] == {"CUSTOM": "<redacted>"}
    assert server["headers"] == {"X-Auth": "<redacted>"}


@pytest.mark.asyncio
async def test_agent_config_status_redacts_serialized_configured_values(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / "agent-config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "mcpServers": {
                    "bad": {
                        "type": "http",
                        "url": "https://bad.example/mcp",
                        "env": {"CUSTOM": SERIALIZED_ENV_VALUE},
                        "headers": {"X-Auth": SERIALIZED_HEADER_VALUE},
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeMcpClientManager:
        async def list_tools(self, name, server):  # noqa: ANN001, ARG002
            raise RuntimeError(SERIALIZED_CONFIGURED_VALUE_ERROR)

        async def call_tool(self, name, server, tool, args):  # noqa: ANN001, ARG002
            raise AssertionError("unavailable server should not be called")

    monkeypatch.setattr(
        tools_module,
        "AgentMcpClientManager",
        lambda _timeout: FakeMcpClientManager(),
    )
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace")
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    get_settings.cache_clear()

    response = await build_mcp().call_tool("agent_config_status", {})
    payload = response[0].text
    message = _payload(response)["data"]["mcp_servers"]["bad"]["error"]

    _assert_serialized_configured_values_redacted(payload, message)


@pytest.mark.asyncio
async def test_activate_agent_skill_returns_skill_content(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / "agent-config"
    skill_dir = config_dir / "skills" / "debugging"
    skill_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps({"version": 1}), encoding="utf-8"
    )
    (skill_dir / "SKILL.md").write_text(
        "# Debugging\n\nFind root causes.\n", encoding="utf-8"
    )
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace")
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    get_settings.cache_clear()

    response = await build_mcp().call_tool(
        "activate_agent_skill", {"name": "debugging"}
    )
    payload = response[0].text

    assert "Find root causes." in payload
    assert "skills/debugging/SKILL.md" in payload


@pytest.mark.asyncio
async def test_agent_mcp_fixed_tools_route_and_reject_unavailable_servers(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / "agent-config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "mcpServers": {
                    "docs": {"type": "http", "url": "https://docs.example/mcp"},
                    "bad": {"type": "http", "url": "https://bad.example/mcp"},
                    "off": {
                        "type": "http",
                        "url": "https://off.example/mcp",
                        "enabled": False,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeMcpClientManager:
        def __init__(self):
            self.list_calls = []
            self.call_calls = []

        async def list_tools(self, name, server):  # noqa: ANN001
            self.list_calls.append((name, server.url))
            if name == "bad":
                raise RuntimeError("probe failed")
            return [
                AgentMcpTool(
                    name="search",
                    description="Search docs",
                    input_schema={
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                    },
                )
            ]

        async def call_tool(self, name, server, tool, args):  # noqa: ANN001
            self.call_calls.append((name, server.url, tool, args))
            return {"server": name, "tool": tool, "args": args}

    fake_manager = FakeMcpClientManager()
    monkeypatch.setattr(
        tools_module, "AgentMcpClientManager", lambda _timeout: fake_manager
    )
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace")
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    get_settings.cache_clear()

    mcp = build_mcp()

    servers = _payload(await mcp.call_tool("list_agent_mcp_servers", {}))[
        "data"
    ]
    assert set(servers) == {"docs", "bad", "off"}
    assert servers["docs"]["available"] is True
    assert servers["bad"]["available"] is False
    assert servers["off"]["available"] is False

    tools = _payload(await mcp.call_tool("list_agent_mcp_tools", {}))["data"][
        "tools"
    ]
    assert tools == [
        {
            "server": "docs",
            "tool": "search",
            "description": "Search docs",
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
            "dynamic_tool_name": "agent_mcp__docs__search",
        }
    ]

    result = _payload(
        await mcp.call_tool(
            "call_agent_mcp_tool",
            {"server": "docs", "tool": "search", "args": {"query": "mcp"}},
        )
    )
    assert result["data"] == {
        "server": "docs",
        "tool": "search",
        "args": {"query": "mcp"},
    }
    assert fake_manager.call_calls == [
        ("docs", "https://docs.example/mcp", "search", {"query": "mcp"})
    ]

    disabled = _payload(
        await mcp.call_tool(
            "call_agent_mcp_tool",
            {"server": "off", "tool": "search", "args": {}},
        )
    )
    assert disabled["data"]["error_type"] == "ValueError"
    assert disabled["data"]["message"] == "MCP server off is disabled"

    unavailable = _payload(
        await mcp.call_tool(
            "call_agent_mcp_tool",
            {"server": "bad", "tool": "search", "args": {}},
        )
    )
    assert unavailable["data"]["error_type"] == "ValueError"
    assert unavailable["data"]["message"] == (
        "MCP server bad is unavailable: RuntimeError: probe failed"
    )

    unknown = _payload(
        await mcp.call_tool(
            "call_agent_mcp_tool",
            {"server": "missing", "tool": "search", "args": {}},
        )
    )
    assert unknown["data"]["error_type"] == "ValueError"
    assert unknown["data"]["message"] == "Unknown agent MCP server: missing"
    assert fake_manager.call_calls == [
        ("docs", "https://docs.example/mcp", "search", {"query": "mcp"})
    ]


@pytest.mark.asyncio
async def test_call_agent_mcp_tool_redacts_unavailable_probe_error(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / "agent-config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "mcpServers": {
                    "bad": {
                        "type": "http",
                        "url": "https://bad.example/mcp",
                        "env": {"CUSTOM": CONFIGURED_ENV_VALUE},
                        "headers": {"X-Auth": CONFIGURED_HEADER_VALUE},
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeMcpClientManager:
        async def list_tools(self, name, server):  # noqa: ANN001, ARG002
            raise RuntimeError(
                "Authorization: Bearer super-secret --token super-secret "
                "https://example.com?token=super-secret "
                '{"api_key": "super-secret"} '
                "{'token': 'super-secret'} "
                '["--token", "super-secret"] '
                "['--token', 'super-secret'] "
                "https://user:super-secret@example.com/path "
                f"{CONFIGURED_VALUE_ERROR}"
            )

        async def call_tool(self, name, server, tool, args):  # noqa: ANN001, ARG002
            raise AssertionError("unavailable server should not be called")

    monkeypatch.setattr(
        tools_module,
        "AgentMcpClientManager",
        lambda _timeout: FakeMcpClientManager(),
    )
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace")
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    get_settings.cache_clear()

    response = await build_mcp().call_tool(
        "call_agent_mcp_tool", {"server": "bad", "tool": "search", "args": {}}
    )
    payload = response[0].text

    assert "super-secret" not in payload
    assert "<redacted>" in payload
    _assert_configured_values_redacted(payload)


@pytest.mark.asyncio
async def test_call_agent_mcp_tool_redacts_call_error(tmp_path, monkeypatch):
    config_dir = tmp_path / "agent-config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "mcpServers": {
                    "docs": {
                        "type": "http",
                        "url": "https://docs.example/mcp",
                        "env": {"CUSTOM": CONFIGURED_ENV_VALUE},
                        "headers": {"X-Auth": CONFIGURED_HEADER_VALUE},
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeMcpClientManager:
        async def list_tools(self, name, server):  # noqa: ANN001, ARG002
            return [
                AgentMcpTool(
                    name="search",
                    description="Search docs",
                    input_schema={"type": "object"},
                )
            ]

        async def call_tool(self, name, server, tool, args):  # noqa: ANN001, ARG002
            raise RuntimeError(
                f"{REALISTIC_SECRET_ERROR} {CONFIGURED_VALUE_ERROR}"
            )

    monkeypatch.setattr(
        tools_module,
        "AgentMcpClientManager",
        lambda _timeout: FakeMcpClientManager(),
    )
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace")
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    get_settings.cache_clear()

    response = await build_mcp().call_tool(
        "call_agent_mcp_tool", {"server": "docs", "tool": "search", "args": {}}
    )
    payload = response[0].text

    _assert_realistic_secret_values_redacted(payload)
    _assert_configured_values_redacted(payload)


@pytest.mark.asyncio
async def test_call_agent_mcp_tool_redacts_serialized_configured_values(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / "agent-config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "mcpServers": {
                    "docs": {
                        "type": "http",
                        "url": "https://docs.example/mcp",
                        "env": {"CUSTOM": SERIALIZED_ENV_VALUE},
                        "headers": {"X-Auth": SERIALIZED_HEADER_VALUE},
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeMcpClientManager:
        async def list_tools(self, name, server):  # noqa: ANN001, ARG002
            return [
                AgentMcpTool(
                    name="search", description="Search docs", input_schema={}
                )
            ]

        async def call_tool(self, name, server, tool, args):  # noqa: ANN001, ARG002
            raise RuntimeError(SERIALIZED_CONFIGURED_VALUE_ERROR)

    monkeypatch.setattr(
        tools_module,
        "AgentMcpClientManager",
        lambda _timeout: FakeMcpClientManager(),
    )
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace")
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    get_settings.cache_clear()

    response = await build_mcp().call_tool(
        "call_agent_mcp_tool", {"server": "docs", "tool": "search", "args": {}}
    )
    payload = response[0].text
    message = _payload(response)["data"]["message"]

    _assert_serialized_configured_values_redacted(payload, message)


@pytest.mark.asyncio
async def test_call_agent_mcp_tool_redacts_error_payload(tmp_path, monkeypatch):
    config_dir = tmp_path / "agent-config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "mcpServers": {
                    "docs": {
                        "type": "http",
                        "url": "https://docs.example/mcp",
                        "env": {"CUSTOM": CONFIGURED_ENV_VALUE},
                        "headers": {"X-Auth": CONFIGURED_HEADER_VALUE},
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    class ErrorPayloadMcpManager:
        async def list_tools(self, name, server):  # noqa: ANN001, ARG002
            return [
                AgentMcpTool(
                    name="search", description="Search docs", input_schema={}
                )
            ]

        async def call_tool(self, name, server, tool, args):  # noqa: ANN001, ARG002
            return {
                "is_error": True,
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"{REALISTIC_SECRET_ERROR} content env={CONFIGURED_ENV_VALUE} "
                            f"header={CONFIGURED_HEADER_VALUE}"
                        ),
                    }
                ],
                "structured_content": {
                    "details": [
                        f"structured env={CONFIGURED_ENV_VALUE}",
                        {"header": CONFIGURED_HEADER_VALUE},
                    ],
                    "keyed": {
                        f"env-{CONFIGURED_ENV_VALUE}": "env key",
                        CONFIGURED_HEADER_VALUE: "header key",
                    },
                },
            }

    monkeypatch.setattr(
        tools_module,
        "AgentMcpClientManager",
        lambda _timeout: ErrorPayloadMcpManager(),
    )
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace")
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    get_settings.cache_clear()

    response = await build_mcp().call_tool(
        "call_agent_mcp_tool", {"server": "docs", "tool": "search", "args": {}}
    )
    payload = response[0].text
    data = _payload(response)["data"]

    assert data["is_error"] is True
    _assert_realistic_secret_values_redacted(payload)
    _assert_configured_values_redacted(payload)
    assert "<redacted>" in data["content"][0]["text"]
    assert "<redacted>" in json.dumps(data["structured_content"])
    assert "env-<redacted>" in data["structured_content"]["keyed"]
    assert "<redacted>" in data["structured_content"]["keyed"]


@pytest.mark.asyncio
async def test_agent_mcp_public_metadata_redacts_configured_values(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / "agent-config"
    config_dir.mkdir()
    high_confidence_token = "sk-1234567890abcdef1234567890abcdef"
    upstream_tool_name = f"search-{CONFIGURED_ENV_VALUE}-{CONFIGURED_HEADER_VALUE}-{high_confidence_token}"
    schema_secret_key = f"query_{CONFIGURED_ENV_VALUE}"
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "mcpServers": {
                    "docs": {
                        "type": "http",
                        "url": "https://docs.example/mcp",
                        "env": {"CUSTOM": CONFIGURED_ENV_VALUE},
                        "headers": {"X-Auth": CONFIGURED_HEADER_VALUE},
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    class MetadataLeakMcpManager:
        def __init__(self):
            self.call_calls = []

        async def list_tools(self, name, server):  # noqa: ANN001, ARG002
            return [
                AgentMcpTool(
                    name=upstream_tool_name,
                    description=(
                        f"Search env={CONFIGURED_ENV_VALUE} header={CONFIGURED_HEADER_VALUE} "
                        f"token={high_confidence_token}"
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            schema_secret_key: {
                                "type": "string",
                                "description": f"Uses {CONFIGURED_HEADER_VALUE}",
                                CONFIGURED_HEADER_VALUE: f"default {CONFIGURED_ENV_VALUE}",
                            }
                        },
                        "required": [schema_secret_key],
                    },
                )
            ]

        async def call_tool(self, name, server, tool, args):  # noqa: ANN001, ARG002
            self.call_calls.append((name, tool, args))
            return {"ok": True}

    fake_manager = MetadataLeakMcpManager()
    monkeypatch.setattr(
        tools_module, "AgentMcpClientManager", lambda _timeout: fake_manager
    )
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace")
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    get_settings.cache_clear()

    mcp = build_mcp()
    rows = _payload(await mcp.call_tool("list_agent_mcp_tools", {}))["data"][
        "tools"
    ]
    rows_payload = json.dumps(rows)

    for secret in (
        CONFIGURED_ENV_VALUE,
        CONFIGURED_HEADER_VALUE,
        high_confidence_token,
    ):
        assert secret not in rows_payload
    assert "<redacted>" in rows_payload

    row = rows[0]
    assert row["tool"] == "search-<redacted>-<redacted>-<redacted>"
    assert row["input_schema"]["properties"]["query_<redacted>"][
        "<redacted>"
    ] == ("default <redacted>")
    dynamic_tool_name = row["dynamic_tool_name"]
    assert "redacted" in dynamic_tool_name
    for secret in (
        CONFIGURED_ENV_VALUE,
        CONFIGURED_HEADER_VALUE,
        high_confidence_token,
    ):
        assert secret not in dynamic_tool_name

    dynamic_tool = {tool.name: tool for tool in await mcp.list_tools()}[
        dynamic_tool_name
    ]
    dynamic_description = dynamic_tool.description or ""
    for secret in (
        CONFIGURED_ENV_VALUE,
        CONFIGURED_HEADER_VALUE,
        high_confidence_token,
    ):
        assert secret not in dynamic_description
    assert "<redacted>" in dynamic_description

    await mcp.call_tool(dynamic_tool_name, {"args": {"query": "abc"}})
    assert fake_manager.call_calls == [
        ("docs", upstream_tool_name, {"query": "abc"})
    ]


class FakeDynamicMcpManager:
    async def list_tools(self, name, server):  # noqa: ANN001, ARG002
        if name == "docs":
            return [
                AgentMcpTool(
                    name="search",
                    description="Search docs",
                    input_schema={
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                    },
                )
            ]
        return []

    async def call_tool(self, name, server, tool, args):  # noqa: ANN001, ARG002
        return {
            "server": name,
            "tool": tool,
            "args": args,
            "content": [{"type": "text", "text": "ok"}],
        }


@pytest.mark.asyncio
async def test_dynamic_skill_tool_is_visible_and_callable(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / "agent-config"
    skill_dir = config_dir / "skills" / "paper-writer"
    skill_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps({"version": 1}), encoding="utf-8"
    )
    (skill_dir / "SKILL.md").write_text(
        "# Paper Writer\n\nDraft papers.\n", encoding="utf-8"
    )
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace")
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    get_settings.cache_clear()

    mcp = build_mcp()
    tools = {tool.name for tool in await mcp.list_tools()}

    assert "activate_skill__paper_writer" in tools
    response = await mcp.call_tool("activate_skill__paper_writer", {})
    assert "Draft papers." in response[0].text


@pytest.mark.asyncio
async def test_dynamic_mcp_tool_is_visible_and_callable(tmp_path, monkeypatch):
    config_dir = tmp_path / "agent-config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "mcpServers": {
                    "docs": {"type": "http", "url": "https://example.com/mcp"}
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace")
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(
        tools_module,
        "AgentMcpClientManager",
        lambda timeout: FakeDynamicMcpManager(),
    )
    get_settings.cache_clear()

    mcp = build_mcp()
    tool_names = {tool.name for tool in await mcp.list_tools()}

    assert "agent_mcp__docs__search" in tool_names
    response = await mcp.call_tool(
        "agent_mcp__docs__search", {"args": {"query": "abc"}}
    )
    assert "abc" in response[0].text


@pytest.mark.asyncio
async def test_dynamic_mcp_tool_redacts_configured_values_in_call_error(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / "agent-config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "mcpServers": {
                    "docs": {
                        "type": "http",
                        "url": "https://example.com/mcp",
                        "env": {"CUSTOM": CONFIGURED_ENV_VALUE},
                        "headers": {"X-Auth": CONFIGURED_HEADER_VALUE},
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    class FailingDynamicMcpManager:
        async def list_tools(self, name, server):  # noqa: ANN001, ARG002
            return [
                AgentMcpTool(
                    name="search",
                    description="Search docs",
                    input_schema={"type": "object"},
                )
            ]

        async def call_tool(self, name, server, tool, args):  # noqa: ANN001, ARG002
            raise RuntimeError(CONFIGURED_VALUE_ERROR)

    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace")
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(
        tools_module,
        "AgentMcpClientManager",
        lambda timeout: FailingDynamicMcpManager(),
    )
    get_settings.cache_clear()

    response = await build_mcp().call_tool(
        "agent_mcp__docs__search", {"args": {}}
    )
    payload = response[0].text

    _assert_configured_values_redacted(payload)


@pytest.mark.asyncio
async def test_dynamic_mcp_tool_redacts_error_payload(tmp_path, monkeypatch):
    config_dir = tmp_path / "agent-config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "mcpServers": {
                    "docs": {
                        "type": "http",
                        "url": "https://example.com/mcp",
                        "env": {"CUSTOM": CONFIGURED_ENV_VALUE},
                        "headers": {"X-Auth": CONFIGURED_HEADER_VALUE},
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    class ErrorPayloadDynamicMcpManager:
        async def list_tools(self, name, server):  # noqa: ANN001, ARG002
            return [
                AgentMcpTool(
                    name="search", description="Search docs", input_schema={}
                )
            ]

        async def call_tool(self, name, server, tool, args):  # noqa: ANN001, ARG002
            return {
                "is_error": True,
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"{REALISTIC_SECRET_ERROR} content env={CONFIGURED_ENV_VALUE} "
                            f"header={CONFIGURED_HEADER_VALUE}"
                        ),
                    }
                ],
                "structured_content": {
                    "details": {
                        "env": CONFIGURED_ENV_VALUE,
                        "message": f"header={CONFIGURED_HEADER_VALUE}",
                    },
                    "keyed": {
                        f"env-{CONFIGURED_ENV_VALUE}": "env key",
                        CONFIGURED_HEADER_VALUE: "header key",
                    },
                },
            }

    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace")
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(
        tools_module,
        "AgentMcpClientManager",
        lambda _timeout: ErrorPayloadDynamicMcpManager(),
    )
    get_settings.cache_clear()

    response = await build_mcp().call_tool(
        "agent_mcp__docs__search", {"args": {}}
    )
    payload = response[0].text
    data = _payload(response)["data"]

    assert data["is_error"] is True
    _assert_realistic_secret_values_redacted(payload)
    _assert_configured_values_redacted(payload)
    assert "<redacted>" in data["content"][0]["text"]
    assert "<redacted>" in json.dumps(data["structured_content"])
    assert "env-<redacted>" in data["structured_content"]["keyed"]
    assert "<redacted>" in data["structured_content"]["keyed"]


@pytest.mark.asyncio
async def test_build_mcp_respects_manifest_dynamic_tool_disable(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / "agent-config"
    skill_dir = config_dir / "skills" / "paper-writer"
    skill_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "mcpServers": {
                    "docs": {"type": "http", "url": "https://example.com/mcp"}
                },
                "dynamicTools": {"mcp": False, "skills": False},
            }
        ),
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text(
        "# Paper Writer\n\nDraft papers.\n", encoding="utf-8"
    )
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace")
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(
        tools_module,
        "AgentMcpClientManager",
        lambda timeout: FakeDynamicMcpManager(),
    )
    get_settings.cache_clear()

    mcp = build_mcp()
    tool_names = {tool.name for tool in await mcp.list_tools()}
    status = _payload(await mcp.call_tool("agent_config_status", {}))["data"]

    assert "activate_skill__paper_writer" not in tool_names
    assert "agent_mcp__docs__search" not in tool_names
    assert status["dynamic_tools"] == {"mcp": False, "skills": False}


@pytest.mark.asyncio
async def test_agent_bridge_hot_reloads_dynamic_skill_tools(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / "agent-config"
    skill_dir = config_dir / "skills" / "paper-writer"
    skill_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps({"version": 1}), encoding="utf-8"
    )
    (skill_dir / "SKILL.md").write_text(
        "# Paper Writer\n\nDraft papers.\n", encoding="utf-8"
    )
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace")
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    get_settings.cache_clear()

    mcp = build_mcp()
    tool_names = {tool.name for tool in await mcp.list_tools()}
    assert "activate_skill__paper_writer" in tool_names
    assert "activate_skill__debugging" not in tool_names

    debugging_dir = config_dir / "skills" / "debugging"
    debugging_dir.mkdir()
    (debugging_dir / "SKILL.md").write_text(
        "# Debugging\n\nFind root causes.\n", encoding="utf-8"
    )

    tool_names = {tool.name for tool in await mcp.list_tools()}
    assert "activate_skill__paper_writer" in tool_names
    assert "activate_skill__debugging" in tool_names
    response = await mcp.call_tool("activate_skill__debugging", {})
    assert "Find root causes." in response[0].text

    (skill_dir / "SKILL.md").unlink()
    tool_names = {tool.name for tool in await mcp.list_tools()}
    assert "activate_skill__paper_writer" not in tool_names
    assert "activate_skill__debugging" in tool_names


@pytest.mark.asyncio
async def test_agent_bridge_hot_reloads_mcp_server_tools(tmp_path, monkeypatch):
    config_dir = tmp_path / "agent-config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps({"version": 1}), encoding="utf-8"
    )

    class ReloadingMcpManager:
        def __init__(self):
            self.call_calls = []

        async def list_tools(self, name, server):  # noqa: ANN001
            return [
                AgentMcpTool(
                    name="search", description=f"Search {name}", input_schema={}
                )
            ]

        async def call_tool(self, name, server, tool, args):  # noqa: ANN001
            self.call_calls.append((name, server.url, tool, args))
            return {
                "server": name,
                "url": server.url,
                "tool": tool,
                "args": args,
            }

    fake_manager = ReloadingMcpManager()
    monkeypatch.setenv(
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace")
    )
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(
        tools_module, "AgentMcpClientManager", lambda _timeout: fake_manager
    )
    get_settings.cache_clear()

    mcp = build_mcp()
    tool_names = {tool.name for tool in await mcp.list_tools()}
    assert "agent_mcp__docs__search" not in tool_names

    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "mcpServers": {
                    "docs": {"type": "http", "url": "https://docs.example/mcp"}
                },
            }
        ),
        encoding="utf-8",
    )
    tool_names = {tool.name for tool in await mcp.list_tools()}
    assert "agent_mcp__docs__search" in tool_names
    response = await mcp.call_tool(
        "agent_mcp__docs__search", {"args": {"query": "abc"}}
    )
    assert _payload(response)["data"] == {
        "server": "docs",
        "url": "https://docs.example/mcp",
        "tool": "search",
        "args": {"query": "abc"},
    }

    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "mcpServers": {
                    "api": {"type": "http", "url": "https://api.example/mcp"},
                },
            }
        ),
        encoding="utf-8",
    )
    tool_names = {tool.name for tool in await mcp.list_tools()}
    assert "agent_mcp__docs__search" not in tool_names
    assert "agent_mcp__api__search" in tool_names

    response = await mcp.call_tool(
        "call_agent_mcp_tool", {"server": "api", "tool": "search"}
    )
    assert _payload(response)["data"]["url"] == "https://api.example/mcp"
