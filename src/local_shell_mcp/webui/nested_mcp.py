"""Progressive MCP tool discovery with mandatory approval for external calls.

The Agent model can search/inspect registered nested MCP schemas. Execution is
never reachable from a mere model call: an explicit durable approval is required.
The management endpoint is deliberately not in the model tool registry.
"""

from __future__ import annotations

import json

from .providers import ModelToolCall

MCP_TOOLS = [
    {"type": "function", "function": {
        "name": "mcp_tool_search", "description": "Search registered external MCP tool summaries.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "server": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        }, "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "mcp_tool_inspect", "description": "Inspect one registered external MCP tool schema.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}},
                       "required": ["name"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "mcp_tool_call", "description": "Request user approval to call one registered external MCP tool.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}, "arguments": {"type": "object"},
        }, "required": ["name"], "additionalProperties": False},
    }},
]


def _manager():
    from ..dynamic_mcp import DynamicMCPManager
    from ..settings import get_settings

    settings = get_settings()
    return DynamicMCPManager(settings.state_dir, max_timeout_s=settings.max_timeout_s)


def _check_mcp_access(owner: str, conversation_id: str, scopes: set[str], *, execution: bool = False) -> None:
    from .routes import _repo

    record = _repo().conversation(owner, conversation_id)
    if record is None:
        raise PermissionError("Conversation not found")
    flags = _repo().setting(owner, "conversation.permissions." + conversation_id, {})
    if not isinstance(flags, dict) or flags.get("mcp") is not True:
        raise PermissionError("Nested MCP tools are disabled for this conversation")
    if "shell:read" not in scopes:
        raise PermissionError("shell:read is required to discover external tools")
    if execution and "shell:execute" not in scopes:
        raise PermissionError("shell:execute is required to invoke an external tool")


async def discover(owner: str, conversation_id: str, scopes: set[str], call: ModelToolCall) -> str:
    """Search and inspect are read-only; caller still enforces owner/scopes."""
    from ..audit import audit

    _check_mcp_access(owner, conversation_id, scopes)
    manager = _manager()
    args = call.arguments
    if call.name == "mcp_tool_search":
        if set(args) - {"query", "server", "limit"}:
            raise ValueError("Unsupported MCP search argument")
        query = args.get("query", "")
        server = args.get("server")
        limit = args.get("limit", 20)
        if (not isinstance(query, str) or len(query) > 512 or
            (server is not None and (not isinstance(server, str) or len(server) > 128)) or
            type(limit) is not int or not 1 <= limit <= 20):
            raise ValueError("Invalid MCP discovery query")
        result = await manager.search(query, server=server, limit=limit)
    elif call.name == "mcp_tool_inspect":
        if set(args) != {"name"} or not isinstance(args.get("name"), str) or len(args["name"]) > 256:
            raise ValueError("A registered MCP tool name is required")
        result = await manager.inspect(args["name"])
    else:
        raise PermissionError("MCP execution requires explicit approval")
    audit("agent_nested_mcp", owner=owner, conversation_id=conversation_id,
          tool=call.name, phase="discovery", ok=True)
    encoded = json.dumps(result, ensure_ascii=False, default=str)
    if len(encoded) > 16384:
        return encoded[:16384] + "... [truncated]"
    return encoded


async def approved_call(owner: str, conversation_id: str, scopes: set[str], call: ModelToolCall) -> str:
    from ..audit import audit

    _check_mcp_access(owner, conversation_id, scopes, execution=True)
    if call.name != "mcp_tool_call":
        raise ValueError("The approved tool name does not match the pending action")
    args = call.arguments
    if set(args) - {"name", "arguments"} or not isinstance(args.get("name"), str):
        raise ValueError("Invalid external MCP tool invocation")
    qualified = args["name"]
    if len(qualified) > 256 or ":" not in qualified or not isinstance(args.get("arguments", {}), dict):
        raise ValueError("Invalid qualified tool name or arguments")
    if len(json.dumps(args.get("arguments", {}))) > 8192:
        raise ValueError("External MCP tool input is too large")
    manager = _manager()
    try:
        result = await manager.call(qualified, args.get("arguments") or {}, timeout_s=120)
        audit("agent_nested_mcp", owner=owner, conversation_id=conversation_id,
              tool=qualified, phase="approved_call", ok=True)
    except Exception as exc:
        audit("agent_nested_mcp", owner=owner, conversation_id=conversation_id,
              tool=qualified, phase="approved_call", ok=False, error_type=type(exc).__name__)
        raise
    encoded = json.dumps(result, ensure_ascii=False, default=str)
    if len(encoded) > 32000:
        return encoded[:32000] + "... [truncated]"
    return encoded
