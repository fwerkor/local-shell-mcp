"""Normalize upstream MCP protocol objects and manage client sessions for configured agent bridge servers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from local_shell_mcp.agent_bridge import AgentMcpServerConfig


@dataclass(frozen=True)
class AgentMcpTool:
    """Normalized description of an upstream MCP tool exposed through the bridge."""

    name: str
    description: str
    input_schema: dict[str, Any]


def _value(source: Any, name: str, default: Any = None) -> Any:
    """Read an MCP protocol field from either a mapping or SDK object."""
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def normalize_mcp_tool(tool: Any) -> AgentMcpTool:
    """Normalize SDK-specific MCP tool objects into a stable serializable shape."""
    input_schema = _value(tool, "inputSchema")
    if input_schema is None:
        input_schema = _value(tool, "input_schema", {})

    return AgentMcpTool(
        name=str(_value(tool, "name", "")),
        description=str(_value(tool, "description", "") or ""),
        input_schema=input_schema,
    )


def _normalize_content_item(item: Any) -> Any:
    """Convert MCP content blocks to JSON-serializable dictionaries while preserving unknown fields."""
    if _value(item, "type") == "text":
        return {"type": "text", "text": _value(item, "text", "")}
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    if isinstance(item, dict):
        return item
    return {"type": "repr", "repr": repr(item)}


def normalize_tool_result(result: Any) -> dict[str, Any]:
    """Convert an MCP tool result into a stable payload with content blocks and error state."""
    structured_content = _value(result, "structuredContent")
    if structured_content is None:
        structured_content = _value(result, "structured_content")
    if hasattr(structured_content, "model_dump"):
        structured_content = structured_content.model_dump(mode="json")

    return {
        "is_error": bool(_value(result, "isError", False) or _value(result, "is_error", False)),
        "content": [_normalize_content_item(item) for item in _value(result, "content", [])],
        "structured_content": structured_content,
    }


class AgentMcpClientManager:
    """Create short-lived MCP client sessions for stdio, HTTP, and SSE upstream servers."""

    def __init__(self, call_timeout_s: float = 60) -> None:
        self.call_timeout_s = call_timeout_s

    @asynccontextmanager
    async def _session(
        self, name: str, server: AgentMcpServerConfig
    ) -> AsyncIterator[ClientSession]:
        """Open and initialize the transport-specific MCP client session for one configured server."""
        if server.type == "stdio":
            if not server.command:
                raise ValueError("stdio MCP server requires command")
            params = StdioServerParameters(
                command=server.command,
                args=server.args,
                env=server.env or None,
            )
            async with (
                stdio_client(params) as (read_stream, write_stream),
                ClientSession(read_stream, write_stream) as session,
            ):
                await session.initialize()
                yield session
            return

        if server.type == "http":
            if not server.url:
                raise ValueError("http MCP server requires url")
            async with (
                streamablehttp_client(server.url, headers=server.headers or None) as (
                    read_stream,
                    write_stream,
                    _get_session_id,
                ),
                ClientSession(read_stream, write_stream) as session,
            ):
                await session.initialize()
                yield session
            return

        if server.type == "sse":
            if not server.url:
                raise ValueError("sse MCP server requires url")
            async with (
                sse_client(server.url, headers=server.headers or None) as (
                    read_stream,
                    write_stream,
                ),
                ClientSession(read_stream, write_stream) as session,
            ):
                await session.initialize()
                yield session
            return

        raise ValueError(f"unsupported MCP server type for {name}: {server.type}")

    async def list_tools(self, name: str, server: AgentMcpServerConfig) -> list[AgentMcpTool]:
        """Page through an upstream server's tool list within the configured call timeout."""

        async def _list_tools() -> list[AgentMcpTool]:
            async with self._session(name, server) as session:
                tools: list[AgentMcpTool] = []
                cursor: str | None = None
                while True:
                    result = await session.list_tools(cursor=cursor)
                    tools.extend(
                        normalize_mcp_tool(tool) for tool in _value(result, "tools", result)
                    )
                    cursor = getattr(result, "nextCursor", None)
                    if not cursor:
                        return tools

        return await asyncio.wait_for(_list_tools(), timeout=self.call_timeout_s)

    async def call_tool(
        self,
        name: str,
        server: AgentMcpServerConfig,
        tool: str,
        args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Invoke an upstream MCP tool and normalize its protocol result for local-shell-mcp responses."""

        async def _call_tool() -> dict[str, Any]:
            async with self._session(name, server) as session:
                return normalize_tool_result(await session.call_tool(tool, args))

        return await asyncio.wait_for(_call_tool(), timeout=self.call_timeout_s)
