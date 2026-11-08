"""Expose the existing LSM MCP tool registry to the first-party Python Agent.

Tool schemas and implementations come only from tools.build_mcp(). This module
adds owner-scoped permission checks at the dispatch boundary; it deliberately
contains no duplicate job, shell, file, or Worker RPC implementations.
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from typing import Any

from ..audit import audit
from .machine_permissions import authorize_machine_action, resolve_access
from .providers import ModelToolCall

# These are administrator actions or have separate approval/Agent contracts.
# In particular no model may mutate MCP registration or Worker identity.
_ADMIN_TOOLS = frozenset({
    "mcp_manage", "mcp_tool_search", "mcp_tool_inspect", "mcp_tool_call",
    "remote_manage", "session_manage", "plan_manage",
    "workspace_open", "open_live_workspace", "live_workspace_reconnect",
})
# Some diagnostic calls are read-only despite conservative MCP annotations.
_READ_INSPECTION = frozenset({"gui_list", "gui_state"})
_EXECUTION_TOOLS = frozenset({
    "run_shell", "run_python", "shell_start", "shell_send", "shell_stop",
    "job_start", "job_stop", "job_retry", "browser_run_script",
    "browser_act", "gui_action",
})
# Do not bypass distinct OAuth rights that the existing MCP server requires.
_ADDITIONAL_SCOPES = {
    "gui_list": "shell:execute", "gui_state": "shell:execute",
    "gui_action": "shell:execute",
    "browser_session": "browser:use", "browser_snapshot": "browser:use",
    "browser_act": "browser:use", "browser_run_script": "browser:use",
    "link_create": "file:share", "link_list": "file:share", "link_revoke": "file:share",
}
_MAX_OUTPUT_CHARS = 32768
_MAX_ARGUMENT_BYTES = 32768


@lru_cache(maxsize=8)
def _registry_for_state(state_key: tuple[str, ...]):
    from ..tools import build_mcp

    return build_mcp()


def _registry():
    from ..settings import get_settings

    settings = get_settings()
    # A change in relevant server settings must not silently reuse outdated
    # tool definitions (e.g., when remotes or logical sessions are disabled).
    key = (
        str(settings.state_dir.resolve()), str(settings.workspace_root.resolve()),
        str(settings.auth_mode), str(settings.remote_enabled),
        str(settings.disable_local), str(settings.logical_sessions_enabled),
        str(settings.ui_enabled), str(settings.live_workspace_enabled),
    )
    return _registry_for_state(key)


def _tool(name: str):
    if name in _ADMIN_TOOLS:
        raise PermissionError("The requested administrative tool is not available to Agents")
    tool = _registry()._tool_manager.get_tool(name)
    if tool is None:
        raise ValueError("Unknown LSM tool")
    return tool


def _operation(tool: Any) -> str:
    if tool.name in _READ_INSPECTION or (tool.annotations and tool.annotations.readOnlyHint is True):
        return "read"
    if tool.name in _EXECUTION_TOOLS:
        return "execute"
    return "write"


def _targets(tool: Any, arguments: dict[str, Any]) -> list[str]:
    schema = tool.parameters.get("properties", {})
    if "machine" in schema:
        value = arguments.get("machine")
        if value is not None and not isinstance(value, str):
            raise ValueError("Invalid machine name")
        return [value or "local"]
    if "source_machine" in schema or "destination_machine" in schema:
        # A cross-machine transfer can modify both endpoints; the permission
        # check covers all targets even if one happens to be local.
        source = arguments.get("source_machine") or "local"
        destination = arguments.get("destination_machine") or "local"
        if not isinstance(source, str) or not isinstance(destination, str):
            raise ValueError("Invalid transfer machine")
        return sorted({source, destination})
    # Host-local tools without a machine selector are local operations.
    return ["local"]


def available_tools(owner: str, conversation_id: str, *, scopes: set[str],
                    expires: int | None = None) -> list[dict]:
    """Advertise registered tool schemas filtered by effective machine policy."""
    policy = resolve_access(owner, conversation_id)
    if not any(value != "none" for value in policy.values()):
        return []
    definitions: list[dict] = []
    for tool in _registry()._tool_manager.list_tools():
        if tool.name in _ADMIN_TOOLS:
            continue
        operation = _operation(tool)
        extra_scope = _ADDITIONAL_SCOPES.get(tool.name)
        if extra_scope and extra_scope not in scopes:
            continue
        properties = tool.parameters.get("properties", {})
        if tool.name == "remote_transfer":
            # Transfer requires a writable destination and a readable source;
            # no model-defined endpoint can bypass either machine's policy.
            if not any(level == "write" and _can_authorize(
                owner, conversation_id, machine, "write", scopes, expires,
            ) for machine, level in policy.items()):
                continue
        elif "machine" not in properties:
            if not _can_authorize(owner, conversation_id, "local", operation, scopes, expires):
                continue
        elif not any(_can_authorize(owner, conversation_id, machine, operation, scopes, expires)
                     for machine, level in policy.items() if level != "none"):
            continue
        params = copy.deepcopy(tool.parameters)
        # This internal context is controlled by LSM, never chosen by a model.
        params.get("properties", {}).pop("logical_session_id", None)
        params["required"] = [name for name in params.get("required", []) if name != "logical_session_id"]
        if not params["required"]:
            params.pop("required", None)
        definitions.append({"type": "function", "function": {
            "name": tool.name,
            "description": (tool.description or "")[:2048],
            "parameters": params,
        }})
    return definitions


def _can_authorize(owner: str, conversation_id: str, machine: str, operation: str,
                   scopes: set[str], expires: int | None) -> bool:
    try:
        authorize_machine_action(owner, conversation_id, machine, operation,
                                 scopes=scopes, expires=expires)
        return True
    except (PermissionError, ValueError, KeyError):
        return False


async def call_tool(owner: str, conversation_id: str, call: ModelToolCall, *,
                    granted_scopes: set[str], grant_expires: int | None = None) -> str:
    """Dispatch through FastMCP's original validated, audited tool function."""
    tool = _tool(call.name)
    arguments = call.arguments
    if not isinstance(arguments, dict) or len(json.dumps(arguments, ensure_ascii=False)) > _MAX_ARGUMENT_BYTES:
        raise ValueError("Invalid or oversized LSM tool arguments")
    if "logical_session_id" in arguments:
        raise PermissionError("Models cannot provide LSM internal session credentials")
    operation = _operation(tool)
    if tool.name == "remote_transfer":
        source = arguments.get("source_machine") or "local"
        destination = arguments.get("destination_machine") or "local"
        if not isinstance(source, str) or not isinstance(destination, str):
            raise ValueError("Invalid transfer machines")
        authorize_machine_action(owner, conversation_id, source, "read",
                                 scopes=granted_scopes, expires=grant_expires)
        authorize_machine_action(owner, conversation_id, destination, "write",
                                 scopes=granted_scopes, expires=grant_expires)
    else:
        for machine in _targets(tool, arguments):
            authorize_machine_action(owner, conversation_id, machine, operation,
                                     scopes=granted_scopes, expires=grant_expires)
    extra_scope = _ADDITIONAL_SCOPES.get(tool.name)
    if extra_scope and extra_scope not in granted_scopes:
        raise PermissionError(f"{extra_scope} permission is required")
    # MCP uses None/omitted for the local controller. Passing the literal name
    # `local` would instead incorrectly route to a Worker called local.
    invocation = dict(arguments)
    for field in ("machine", "source_machine", "destination_machine"):
        if invocation.get(field) == "local":
            invocation[field] = None
    return await _invoke_registered(owner, conversation_id, tool.name, invocation,
                                    scopes=granted_scopes, machines=_targets(tool, arguments))


def registered_definitions(names: tuple[str, ...]) -> list[dict]:
    """Use exact original MCP schemas for separately approved Agent tools."""
    definitions = []
    for name in names:
        tool = _registry()._tool_manager.get_tool(name)
        if tool is None:
            continue
        params = copy.deepcopy(tool.parameters)
        params.get("properties", {}).pop("logical_session_id", None)
        required = [field for field in params.get("required", []) if field != "logical_session_id"]
        if required:
            params["required"] = required
        else:
            params.pop("required", None)
        definitions.append({"type": "function", "function": {
            "name": name, "description": (tool.description or "")[:2048],
            "parameters": params,
        }})
    return definitions


async def _invoke_registered(owner: str, conversation_id: str, name: str,
                             arguments: dict[str, Any], *, scopes: set[str],
                             machines: list[str] | None = None) -> str:
    """Call only an explicitly vetted tool using MCP's own validated executor."""
    from ..auth import _CURRENT_PRINCIPAL, Principal

    if "logical_session_id" in arguments:
        raise PermissionError("Models cannot provide LSM internal session credentials")
    if len(json.dumps(arguments, ensure_ascii=False)) > _MAX_ARGUMENT_BYTES:
        raise ValueError("LSM tool input is too large")
    invocation = dict(arguments)
    invocation["logical_session_id"] = None
    token = _CURRENT_PRINCIPAL.set(Principal(
        email=None, subject=owner,
        claims={"scope": " ".join(sorted(scopes)), "auth": "webui-agent"},
    ))
    try:
        data = await _registry()._tool_manager.call_tool(name, invocation, convert_result=True)
        result = _encode_result(data)
        structured = data[1] if isinstance(data, tuple) and len(data) == 2 else data
        succeeded = not (isinstance(structured, dict) and structured.get("ok") is False)
    except Exception as exc:
        audit("webui_agent_lsm_tool", owner=owner, conversation_id=conversation_id,
              tool=name, machines=machines or [], ok=False, error_type=type(exc).__name__)
        raise
    finally:
        _CURRENT_PRINCIPAL.reset(token)
    audit("webui_agent_lsm_tool", owner=owner, conversation_id=conversation_id,
          tool=name, machines=machines or [], ok=succeeded)
    return result


def _encode_result(value: Any) -> str:
    if isinstance(value, tuple) and len(value) == 2:
        content, structured = value
        if structured is not None:
            value = structured
        else:
            value = [item.text if hasattr(item, "text") else {"type": "non_text_result"}
                     for item in content]
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) > _MAX_OUTPUT_CHARS:
        return text[:_MAX_OUTPUT_CHARS] + "... [truncated]"
    return text
