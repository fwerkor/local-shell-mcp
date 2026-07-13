"""Shared service helpers for agent bridge tool adapters."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, is_dataclass
from typing import Any

from ..settings import Settings, get_settings
from .mcp import AgentMcpClientManager
from .models import AgentCapabilityRegistry, AgentMcpServerRecord
from .redaction import (
    _redact_text,
    redact_configured_value_tree,
    redact_configured_values,
    redact_mapping,
)
from .registry import build_agent_registry
from .skills import activate_skill

AgentMcpClientManagerFactory = Callable[[float], Any]


def build_agent_registry_from_settings(
    settings: Settings | None = None,
    client_manager_factory: AgentMcpClientManagerFactory = AgentMcpClientManager,
) -> AgentCapabilityRegistry:
    """Build the current agent capability registry from runtime settings."""
    active_settings = settings or get_settings()
    return build_agent_registry(
        active_settings.agent_config_dir,
        client_manager_factory(active_settings.agent_mcp_call_timeout_s),
        active_settings.agent_mcp_probe_timeout_s,
        None if active_settings.agent_dynamic_mcp_tools else False,
    )


def tool_value(source: Any, name: str, default: Any = None) -> Any:
    """Read a tool attribute from either a mapping-style or object-style MCP representation."""
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def agent_mcp_tool_row(
    server: str,
    tool: Any,
    env: dict[str, str],
    headers: dict[str, str],
    dynamic_tool_name: str | None = None,
) -> dict[str, Any]:
    """Convert an upstream MCP tool into a redacted status row."""
    model_dump = getattr(tool, "model_dump", None)
    if is_dataclass(tool) and not isinstance(tool, type):
        data = asdict(tool)
    elif callable(model_dump):
        dumped = model_dump(mode="json")
        data = dumped if isinstance(dumped, Mapping) else {}
    elif isinstance(tool, dict):
        data = tool
    else:
        data = {}

    input_schema = data.get("input_schema")
    if input_schema is None:
        input_schema = data.get("inputSchema")
    if input_schema is None:
        input_schema = tool_value(tool, "input_schema")
    if input_schema is None:
        input_schema = tool_value(tool, "inputSchema", {})

    row = {
        "server": server,
        "tool": redact_configured_value_tree(
            str(data.get("name") or tool_value(tool, "name", "")), env, headers
        ),
        "description": redact_configured_value_tree(
            str(
                data.get("description")
                or tool_value(tool, "description", "")
                or ""
            ),
            env,
            headers,
        ),
        "input_schema": redact_configured_value_tree(
            input_schema or {}, env, headers
        ),
    }
    if dynamic_tool_name is not None:
        row["dynamic_tool_name"] = redact_configured_value_tree(
            dynamic_tool_name, env, headers
        )
    return row


def redacted_mcp_call_error(
    exc: Exception, *maps: dict[str, str]
) -> ValueError:
    """Wrap upstream MCP call failures after removing configured secrets."""
    error = _redact_text(redact_configured_values(str(exc), *maps))
    return ValueError(f"Agent MCP tool call failed: {error}")


def redact_mcp_payload_strings(value: Any, *maps: dict[str, str]) -> Any:
    """Redact secret-bearing strings inside arbitrary MCP payload objects."""
    return redact_configured_value_tree(value, *maps)


def redact_mcp_error_payload(data: Any, *maps: dict[str, str]) -> Any:
    """Redact only MCP tool-result payloads that are explicitly marked as errors."""
    if not isinstance(data, dict) or not (
        data.get("is_error") or data.get("isError")
    ):
        return data
    return redact_mcp_payload_strings(redact_mapping(data), *maps)


def agent_config_status_payload(
    registry: AgentCapabilityRegistry,
) -> dict[str, Any]:
    """Return a public, redacted agent bridge configuration status payload."""
    return registry.config_status()


def list_agent_skills_payload(
    registry: AgentCapabilityRegistry,
) -> dict[str, Any]:
    """Return discovered agent skills and non-fatal skill warnings."""
    return {
        "skills": [asdict(skill) for skill in registry.skills.values()],
        "warnings": registry.skill_warnings,
    }


def activate_agent_skill_payload(
    registry: AgentCapabilityRegistry, name: str
) -> dict[str, Any]:
    """Load one discovered agent skill payload by name."""
    skill = registry.skills.get(name)
    if skill is None:
        raise ValueError(f"Unknown agent skill: {name}")
    return activate_skill(registry.config_dir, skill)


def list_agent_mcp_servers_payload(
    registry: AgentCapabilityRegistry,
) -> dict[str, Any]:
    """Return configured agent MCP server status rows."""
    return registry.config_status()["mcp_servers"]


def _agent_mcp_records(
    registry: AgentCapabilityRegistry, server: str | None
) -> Iterable[tuple[str, AgentMcpServerRecord]]:
    """Iterate MCP server records after validating an optional server filter."""
    if server is not None and server not in registry.mcp_servers:
        raise ValueError(f"Unknown agent MCP server: {server}")
    if server is not None:
        return [(server, registry.mcp_servers[server])]
    return registry.mcp_servers.items()


def list_agent_mcp_tools_payload(
    registry: AgentCapabilityRegistry, server: str | None = None
) -> dict[str, Any]:
    """Return redacted upstream MCP tool rows, optionally filtered by server."""
    records = _agent_mcp_records(registry, server)
    dynamic_names = {
        (record.server_name, record.tool_name): dynamic_name
        for dynamic_name, record in registry.dynamic_mcp_tool_map.items()
    }
    rows = [
        agent_mcp_tool_row(
            server_name,
            tool,
            record.config.env,
            record.config.headers,
            dynamic_names.get((server_name, str(tool_value(tool, "name", "")))),
        )
        for server_name, record in records
        for tool in record.tools
    ]
    return {"tools": rows}


def _agent_mcp_unavailable_error(record: AgentMcpServerRecord) -> str:
    """Return the redacted availability error for an unreachable MCP server."""
    if not record.error:
        return "unknown error"
    return _redact_text(
        redact_configured_values(
            record.error,
            record.config.env,
            record.config.headers,
        )
    )


async def call_agent_mcp_tool_payload(
    registry: AgentCapabilityRegistry,
    server: str,
    tool: str,
    args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call one upstream MCP tool and redact configured secrets from errors."""
    record = registry.mcp_servers.get(server)
    if record is None:
        raise ValueError(f"Unknown agent MCP server: {server}")
    if not record.config.enabled:
        raise ValueError(f"MCP server {server} is disabled")
    if not record.available:
        raise ValueError(
            f"MCP server {server} is unavailable: "
            f"{_agent_mcp_unavailable_error(record)}"
        )
    try:
        data = await registry.client_manager.call_tool(
            server, record.config, tool, args or {}
        )
    except Exception as exc:
        raise redacted_mcp_call_error(
            exc, record.config.env, record.config.headers
        ) from None
    return redact_mcp_error_payload(
        data, record.config.env, record.config.headers
    )
