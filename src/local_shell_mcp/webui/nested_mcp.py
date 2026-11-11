"""Approval gate for LSM's registered nested MCP tools.

Search, inspect and execution reuse their original build_mcp() declarations
and handlers. External calls must first be approved through a durable SQLite
Agent action; mcp_manage is never presented to the model.
"""

from __future__ import annotations

import json

from .lsm_tool_registry import _invoke_registered, registered_definitions
from .providers import ModelToolCall

_MCP_TOOL_NAMES = ("mcp_tool_search", "mcp_tool_inspect", "mcp_tool_call")


def nested_tools() -> list[dict]:
    return registered_definitions(_MCP_TOOL_NAMES)


def _check_mcp_access(owner: str, conversation_id: str, scopes: set[str], *, execution: bool = False) -> None:
    from .routes import _repo

    if _repo().conversation(owner, conversation_id) is None:
        raise PermissionError("Conversation not found")
    flags = _repo().setting(owner, "conversation.permissions." + conversation_id, {})
    if not isinstance(flags, dict) or flags.get("mcp") is not True:
        raise PermissionError("Nested MCP tools are disabled for this conversation")
    if "shell:read" not in scopes:
        raise PermissionError("shell:read is required to discover external tools")
    if execution and "shell:execute" not in scopes:
        raise PermissionError("shell:execute is required to invoke an external tool")


async def discover(owner: str, conversation_id: str, scopes: set[str], call: ModelToolCall) -> str:
    """Use the registered LSM discovery implementations without tool execution."""
    _check_mcp_access(owner, conversation_id, scopes)
    if call.name not in {"mcp_tool_search", "mcp_tool_inspect"}:
        raise PermissionError("MCP execution requires explicit approval")
    if not isinstance(call.arguments, dict):
        raise ValueError("MCP discovery arguments must be an object")
    return await _invoke_registered(owner, conversation_id, call.name, call.arguments, scopes=scopes)


async def approved_call(owner: str, conversation_id: str, scopes: set[str], call: ModelToolCall) -> str:
    _check_mcp_access(owner, conversation_id, scopes, execution=True)
    if call.name != "mcp_tool_call" or not isinstance(call.arguments, dict):
        raise ValueError("The approved tool does not match the pending action")
    arguments = call.arguments
    qualified = arguments.get("name")
    if (not isinstance(qualified, str) or ":" not in qualified or len(qualified) > 256 or
        not isinstance(arguments.get("arguments", {}), dict)):
        raise ValueError("Invalid qualified external MCP tool name or arguments")
    if len(json.dumps(arguments, ensure_ascii=False)) > 8192:
        raise ValueError("External MCP tool input is too large")
    # This function is only reached after the immutable SQLite action ID and
    # the user's explicit approve decision have been validated by resume.
    return await _invoke_registered(owner, conversation_id, "mcp_tool_call", arguments, scopes=scopes)
