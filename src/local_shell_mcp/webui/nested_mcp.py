"""Approval gate for LSM's registered nested MCP tools.

Search, inspect and execution reuse their original build_mcp() declarations
and handlers. External calls must first be approved through a durable SQLite
Agent action; mcp_manage is never presented to the model.
"""

from __future__ import annotations

from ..dynamic_mcp import _AGENT_ALLOWED_SERVERS
from .lsm_tool_registry import _invoke_registered, registered_definitions
from .providers import ModelToolCall

_MCP_TOOL_NAMES = ("mcp_tool_search", "mcp_tool_inspect", "mcp_tool_call")


def nested_tools() -> list[dict]:
    return registered_definitions(_MCP_TOOL_NAMES)


def _check_mcp_access(owner: str, conversation_id: str, scopes: set[str], *, execution: bool = False) -> None:
    from .routes import _repo

    if _repo().conversation(owner, conversation_id) is None:
        raise PermissionError("Conversation not found")
    from .misc_routes import effective_features

    if not effective_features(owner, conversation_id)["mcp"]:
        raise PermissionError("Nested MCP tools are disabled for this conversation")
    if "shell:read" not in scopes:
        raise PermissionError("shell:read is required to discover external tools")
    if execution and "shell:execute" not in scopes:
        raise PermissionError("shell:execute is required to invoke an external tool")


def _allowed(owner: str, conversation_id: str, arguments: dict) -> frozenset[str] | None:
    from .misc_routes import effective_features

    selected = effective_features(owner, conversation_id)["mcpServers"]
    if selected is None:
        return None
    allowed = frozenset(selected)
    # Reject named targets before dispatch, including inspect and approved
    # calls that may be resumed after a user's setting was changed.
    name = arguments.get("name")
    server = arguments.get("server")
    target = name.split(":", 1)[0] if isinstance(name, str) else server
    if target is not None and target not in allowed:
        raise PermissionError(f"MCP server is disabled for this chat: {target}")
    return allowed


async def _invoke_selected(owner: str, conversation_id: str, scopes: set[str],
                           name: str, arguments: dict) -> str:
    token = _AGENT_ALLOWED_SERVERS.set(_allowed(owner, conversation_id, arguments))
    try:
        return await _invoke_registered(owner, conversation_id, name, arguments, scopes=scopes)
    finally:
        _AGENT_ALLOWED_SERVERS.reset(token)


async def discover(owner: str, conversation_id: str, scopes: set[str], call: ModelToolCall) -> str:
    """Use the registered LSM discovery implementations without tool execution."""
    _check_mcp_access(owner, conversation_id, scopes)
    if call.name not in {"mcp_tool_search", "mcp_tool_inspect"}:
        raise PermissionError("MCP execution requires explicit approval")
    if not isinstance(call.arguments, dict):
        raise ValueError("MCP discovery arguments must be an object")
    return await _invoke_selected(owner, conversation_id, scopes, call.name, call.arguments)


async def approved_call(owner: str, conversation_id: str, scopes: set[str], call: ModelToolCall) -> str:
    _check_mcp_access(owner, conversation_id, scopes, execution=True)
    if call.name != "mcp_tool_call" or not isinstance(call.arguments, dict):
        raise ValueError("The approved tool does not match the pending action")
    arguments = call.arguments
    qualified = arguments.get("name")
    if (not isinstance(qualified, str) or ":" not in qualified or len(qualified) > 256 or
        not isinstance(arguments.get("arguments", {}), dict)):
        raise ValueError("Invalid qualified external MCP tool name or arguments")
    # This function is only reached after the immutable SQLite action ID and
    # the user's explicit approve decision have been validated by resume.
    return await _invoke_selected(owner, conversation_id, scopes, "mcp_tool_call", arguments)
