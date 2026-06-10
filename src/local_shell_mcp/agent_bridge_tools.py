"""Register agent bridge skills and upstream MCP tools as callable tools on the public FastMCP server."""

from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, is_dataclass
from typing import Any

from .agent_bridge import (
    AgentCapabilityRegistry,
    _redact_text,
    activate_skill,
    agent_config_fingerprint,
    build_agent_registry,
    redact_configured_value_tree,
    redact_configured_values,
    redact_mapping,
)

OkFn = Callable[..., dict[str, Any]]
HandledErrorFn = Callable[[Exception], dict[str, Any]]


def _tool_value(source: Any, name: str, default: Any = None) -> Any:
    """Read a tool attribute from either a mapping-style or object-style MCP representation."""
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _tool_row(
    server: str,
    tool: Any,
    env: dict[str, str],
    headers: dict[str, str],
    dynamic_tool_name: str | None = None,
) -> dict[str, Any]:
    """Convert an upstream MCP tool into a redacted status row with schema and dynamic-name metadata."""
    if is_dataclass(tool) and not isinstance(tool, type):
        data = asdict(tool)
    elif hasattr(tool, "model_dump"):
        data = tool.model_dump(mode="json")
    elif isinstance(tool, dict):
        data = tool
    else:
        data = {}

    input_schema = data.get("input_schema")
    if input_schema is None:
        input_schema = data.get("inputSchema")
    if input_schema is None:
        input_schema = _tool_value(tool, "input_schema")
    if input_schema is None:
        input_schema = _tool_value(tool, "inputSchema", {})

    row = {
        "server": server,
        "tool": redact_configured_value_tree(
            str(data.get("name") or _tool_value(tool, "name", "")), env, headers
        ),
        "description": redact_configured_value_tree(
            str(data.get("description") or _tool_value(tool, "description", "") or ""),
            env,
            headers,
        ),
        "input_schema": redact_configured_value_tree(input_schema or {}, env, headers),
    }
    if dynamic_tool_name is not None:
        row["dynamic_tool_name"] = redact_configured_value_tree(dynamic_tool_name, env, headers)
    return row


def _redacted_mcp_call_error(exc: Exception, *maps: dict[str, str]) -> ValueError:
    """Wrap upstream MCP call failures after removing configured secrets and token-like values."""
    error = _redact_text(redact_configured_values(str(exc), *maps))
    return ValueError(f"Agent MCP tool call failed: {error}")


def _redact_mcp_payload_strings(value: Any, *maps: dict[str, str]) -> Any:
    """Redact secret-bearing strings inside arbitrary MCP payload objects."""
    return redact_configured_value_tree(value, *maps)


def _redact_mcp_error_payload(data: Any, *maps: dict[str, str]) -> Any:
    """Redact only MCP tool-result payloads that are explicitly marked as errors."""
    if not isinstance(data, dict) or not (data.get("is_error") or data.get("isError")):
        return data
    return _redact_mcp_payload_strings(redact_mapping(data), *maps)


class AgentBridgeToolReloader:
    """Keeps dynamic bridge tools synchronized with on-disk agent configuration changes."""

    def __init__(
        self,
        mcp: Any,
        registry: AgentCapabilityRegistry,
        meta: dict[str, Any],
        ok: OkFn,
        handled_error: HandledErrorFn,
        probe_timeout_s: float,
        dynamic_mcp_tools: bool | None,
        dynamic_skill_tools: bool | None,
    ) -> None:
        self.mcp = mcp
        self.registry = registry
        self.meta = meta
        self.ok = ok
        self.handled_error = handled_error
        self.probe_timeout_s = probe_timeout_s
        self.dynamic_mcp_tools = dynamic_mcp_tools
        self.dynamic_skill_tools = dynamic_skill_tools
        self._dynamic_tool_names: set[str] = set()
        self._fingerprint = agent_config_fingerprint(registry.config_dir)
        self._lock = threading.RLock()

    def current_registry(self) -> AgentCapabilityRegistry:
        """Return the latest bridge registry, refreshing dynamic tools if the config fingerprint changed."""
        self.refresh_if_needed()
        return self.registry

    def refresh_if_needed(self) -> None:
        """Rebuild the registry and dynamic tool set when bridge config files change on disk."""
        fingerprint = agent_config_fingerprint(self.registry.config_dir)
        if fingerprint == self._fingerprint:
            return
        with self._lock:
            fingerprint = agent_config_fingerprint(self.registry.config_dir)
            if fingerprint == self._fingerprint:
                return
            self._remove_dynamic_tools()
            self.registry = build_agent_registry(
                self.registry.config_dir,
                self.registry.client_manager,
                self.probe_timeout_s,
                self.dynamic_mcp_tools,
                self.dynamic_skill_tools,
            )
            self._fingerprint = fingerprint
            self.register_dynamic_tools()

    def register_dynamic_tools(self) -> None:
        """Register generated skill and MCP handlers on the FastMCP server."""
        self._remove_dynamic_tools()
        for dynamic_name, record in self.registry.dynamic_skill_tool_map.items():
            skill = self.registry.skills[record.skill_name]
            description = f"[agent skill] Activate {record.skill_name}: {skill.description}"
            self.mcp.add_tool(
                make_skill_handler(self, record.skill_name),
                name=dynamic_name,
                description=description,
                meta=self.meta,
            )
            self._dynamic_tool_names.add(dynamic_name)

        for dynamic_name, record in self.registry.dynamic_mcp_tool_map.items():
            server_record = self.registry.mcp_servers[record.server_name]
            tool = next(
                candidate
                for candidate in server_record.tools
                if str(_tool_value(candidate, "name", "")) == record.tool_name
            )
            tool_description = redact_configured_value_tree(
                str(_tool_value(tool, "description", "") or record.tool_name),
                server_record.config.env,
                server_record.config.headers,
            )
            description = redact_configured_value_tree(
                f"[agent mcp: {record.server_name}] {tool_description}",
                server_record.config.env,
                server_record.config.headers,
            )
            self.mcp.add_tool(
                make_mcp_handler(self, record.server_name, record.tool_name),
                name=dynamic_name,
                description=description,
                meta=self.meta,
            )
            self._dynamic_tool_names.add(dynamic_name)

    def _remove_dynamic_tools(self) -> None:
        """Remove previously generated dynamic tools before rebuilding the registry."""
        for tool_name in self._dynamic_tool_names:
            with suppress(Exception):
                self.mcp.remove_tool(tool_name)
        self._dynamic_tool_names.clear()


def make_skill_handler(reloader: AgentBridgeToolReloader, skill_name: str):  # noqa: ANN202
    """Create a FastMCP handler that activates one discovered skill from the current registry."""

    async def handler() -> dict:
        try:
            registry = reloader.current_registry()
            skill = registry.skills[skill_name]
            return reloader.ok(activate_skill(registry.config_dir, skill))
        except Exception as exc:
            return reloader.handled_error(exc)

    return handler


def make_mcp_handler(reloader: AgentBridgeToolReloader, server_name: str, tool_name: str):  # noqa: ANN202
    """Create a FastMCP handler that proxies one upstream MCP tool with redacted arguments and errors."""

    async def handler(args: dict[str, Any] | None = None) -> dict:
        try:
            registry = reloader.current_registry()
            record = registry.mcp_servers[server_name]
            try:
                data = await registry.client_manager.call_tool(
                    server_name, record.config, tool_name, args or {}
                )
            except Exception as exc:
                raise _redacted_mcp_call_error(
                    exc,
                    record.config.env,
                    record.config.headers,
                ) from None
            return reloader.ok(
                _redact_mcp_error_payload(
                    data,
                    record.config.env,
                    record.config.headers,
                )
            )
        except Exception as exc:
            return reloader.handled_error(exc)

    return handler


def _install_agent_bridge_reload_hooks(mcp: Any, reloader: AgentBridgeToolReloader) -> None:
    """Patch tool-listing paths so dynamic bridge tools refresh before discovery responses are built."""
    original_list_tools = mcp.list_tools
    original_call_tool = mcp.call_tool

    async def list_tools_with_agent_reload():  # noqa: ANN202
        reloader.refresh_if_needed()
        return await original_list_tools()

    async def call_tool_with_agent_reload(name: str, arguments: dict[str, Any]):  # noqa: ANN202
        reloader.refresh_if_needed()
        return await original_call_tool(name, arguments)

    mcp.list_tools = list_tools_with_agent_reload
    mcp.call_tool = call_tool_with_agent_reload


def register_agent_bridge_tools(
    mcp: Any,
    registry: AgentCapabilityRegistry,
    meta: dict[str, Any],
    ok: OkFn,
    handled_error: HandledErrorFn,
    probe_timeout_s: float = 5,
    dynamic_mcp_tools: bool | None = None,
    dynamic_skill_tools: bool | None = None,
) -> None:
    """Register static bridge-management tools and initialize optional dynamic skill and MCP tool handlers."""
    reloader = AgentBridgeToolReloader(
        mcp,
        registry,
        meta,
        ok,
        handled_error,
        probe_timeout_s,
        dynamic_mcp_tools,
        dynamic_skill_tools,
    )

    @mcp.tool(meta=meta)
    async def agent_config_status() -> dict:
        """Return agent bridge configuration status."""
        return ok(reloader.current_registry().config_status())

    @mcp.tool(meta=meta)
    async def list_agent_skills() -> dict:
        """List agent skills discovered from config."""
        current = reloader.current_registry()
        return ok(
            {
                "skills": [asdict(skill) for skill in current.skills.values()],
                "warnings": current.skill_warnings,
            }
        )

    @mcp.tool(meta=meta)
    async def activate_agent_skill(name: str) -> dict:
        """Load an agent skill's instructions."""
        try:
            current = reloader.current_registry()
            skill = current.skills.get(name)
            if skill is None:
                raise ValueError(f"Unknown agent skill: {name}")
            return ok(activate_skill(current.config_dir, skill))
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=meta)
    async def list_agent_mcp_servers() -> dict:
        """List configured agent MCP servers."""
        return ok(reloader.current_registry().config_status()["mcp_servers"])

    @mcp.tool(meta=meta)
    async def list_agent_mcp_tools(server: str | None = None) -> dict:
        """List tools exposed by configured agent MCP servers."""
        try:
            current = reloader.current_registry()
            if server is not None and server not in current.mcp_servers:
                raise ValueError(f"Unknown agent MCP server: {server}")
            records = (
                [(server, current.mcp_servers[server])]
                if server is not None
                else current.mcp_servers.items()
            )
            dynamic_names = {
                (record.server_name, record.tool_name): dynamic_name
                for dynamic_name, record in current.dynamic_mcp_tool_map.items()
            }
            rows = [
                _tool_row(
                    server_name,
                    tool,
                    record.config.env,
                    record.config.headers,
                    dynamic_names.get((server_name, str(_tool_value(tool, "name", "")))),
                )
                for server_name, record in records
                for tool in record.tools
            ]
            return ok({"tools": rows})
        except Exception as exc:
            return handled_error(exc)

    @mcp.tool(meta=meta)
    async def call_agent_mcp_tool(
        server: str, tool: str, args: dict[str, Any] | None = None
    ) -> dict:
        """Call a tool on a configured agent MCP server."""
        try:
            current = reloader.current_registry()
            record = current.mcp_servers.get(server)
            if record is None:
                raise ValueError(f"Unknown agent MCP server: {server}")
            if not record.config.enabled:
                raise ValueError(f"MCP server {server} is disabled")
            if not record.available:
                error = (
                    _redact_text(
                        redact_configured_values(
                            record.error,
                            record.config.env,
                            record.config.headers,
                        )
                    )
                    if record.error
                    else "unknown error"
                )
                raise ValueError(f"MCP server {server} is unavailable: {error}")
            try:
                data = await current.client_manager.call_tool(
                    server, record.config, tool, args or {}
                )
            except Exception as exc:
                raise _redacted_mcp_call_error(
                    exc,
                    record.config.env,
                    record.config.headers,
                ) from None
            return ok(
                _redact_mcp_error_payload(
                    data,
                    record.config.env,
                    record.config.headers,
                )
            )
        except Exception as exc:
            return handled_error(exc)

    reloader.register_dynamic_tools()
    _install_agent_bridge_reload_hooks(mcp, reloader)
