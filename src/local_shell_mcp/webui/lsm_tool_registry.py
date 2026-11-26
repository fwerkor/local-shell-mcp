"""Expose the existing LSM MCP tool registry to the first-party Python Agent.

Tool schemas and implementations come only from tools.build_mcp(). This module
adds owner-scoped permission checks at the dispatch boundary; it deliberately
contains no duplicate job, shell, file, or Worker RPC implementations.
"""

from __future__ import annotations

import asyncio
import copy
import json
from functools import lru_cache
from typing import Any

from ..audit import audit
from .machine_permissions import (
    MachineReadOnlyError,
    agent_access_policy,
    authorize_machine_action,
    resolve_access,
    resolve_agent_ceiling,
)
from .providers import ModelToolCall

# Controller management belongs to the `local` machine and requires its
# write grant even when a management action operates on a remote registration.
# Do not confuse `remote_manage(machine=...)` with an RPC executed on that Worker.
_CONTROLLER_MANAGEMENT = frozenset({"mcp_manage", "remote_manage"})
# Agent-owned logical sessions/plans are not machine operations. A session
# remains manageable even if all machines have `none` grants.
_AGENT_CONTROL = frozenset({"session_manage", "plan_manage"})
# These have separate human approval or app-only credential contracts; do not
# expose them through the general Agent dispatch path.
_SEPARATE_TOOLS = frozenset({
    "mcp_tool_search", "mcp_tool_inspect", "mcp_tool_call",
    "workspace_open", "open_live_workspace", "live_workspace_reconnect",
})
# Explicit classification is intentional: MCP safety annotations are hints,
# not an authorization contract. New native tools stay denied until audited.
_READ_TOOLS = frozenset({
    "environment_get", "skill_list", "skill_load", "skill_read",
    "shell_read", "shell_list", "job_list", "job_get", "job_tail",
    "file_list", "file_tree", "file_glob", "file_grep", "file_read",
    "image_view", "gui_list", "gui_state", "link_list", "secret_scan",
    "audit_tail", "browser_snapshot",
})
_WRITE_TOOLS = frozenset({
    "link_create", "link_revoke", "file_write", "file_edit", "file_delete",
    "file_patch", "remote_transfer", "browser_session",
})
_EXECUTION_TOOLS = frozenset({
    "run_shell", "run_python", "shell_start", "shell_send", "shell_stop",
    "job_start", "job_stop", "job_retry", "browser_run_script",
    "browser_act", "gui_action",
})
# Do not bypass distinct OAuth rights that the existing MCP server requires.
_ADDITIONAL_SCOPES = {
    "gui_action": "shell:execute",
    "browser_session": "browser:use", "browser_snapshot": "browser:use",
    "browser_act": "browser:use", "browser_run_script": "browser:use",
    "link_create": "file:share", "link_list": "file:share", "link_revoke": "file:share",
    "mcp_manage": "shell:execute", "remote_manage": "remote:use",
}
_AUTHORIZATION_RECHECK_SECONDS = 0.5


class ToolPermissionDenied(PermissionError):
    """An operation was denied before native dispatch, with no side effects."""


@lru_cache(maxsize=8)
def _registry_for_state(state_key: tuple[str, ...]):
    from ..tools import build_mcp

    return build_mcp(agent_dispatch=True)


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
    if name in _SEPARATE_TOOLS:
        raise PermissionError("The requested tool requires its separate Agent flow")
    tool = _registry()._tool_manager.get_tool(name)
    if tool is None:
        raise ValueError("Unknown LSM tool")
    return tool


def _operation(tool: Any, arguments: dict | None = None) -> str:
    if tool.name == "browser_session" and arguments is not None and arguments.get("action") == "list":
        return "read"
    if tool.name in _CONTROLLER_MANAGEMENT or tool.name in _AGENT_CONTROL:
        return "write"
    if tool.name in _READ_TOOLS:
        return "read"
    if tool.name in _EXECUTION_TOOLS:
        return "execute"
    if tool.name in _WRITE_TOOLS:
        return "write"
    raise PermissionError("Native tool has no audited Agent permission policy")


def _targets(tool: Any, arguments: dict[str, Any]) -> list[str]:
    if getattr(tool, "name", None) in _AGENT_CONTROL:
        return []
    if getattr(tool, "name", None) in _CONTROLLER_MANAGEMENT:
        return ["local"]
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


def _agent_allows(policy: dict[str, str], machine: str, operation: str, default: str = "write") -> bool:
    # Agent maps contain explicit exceptions to the Agent default.
    # The chat's machine policy and existing principal scopes remain ceilings.
    level = policy.get(machine, default)
    return level == "write" if operation != "read" else level in {"read", "write"}


def available_tools(owner: str, conversation_id: str, *, scopes: set[str],
                    expires: int | None = None,
                    agent_permissions: dict[str, str] | None = None,
                    agent_default_permission: str = "write") -> list[dict]:
    """Advertise registered tool schemas filtered by effective machine policy."""
    policy = resolve_access(owner, conversation_id)
    if agent_permissions is not None:
        # An Agent is an additional ceiling; it cannot expand its chat grant.
        from .machine_permissions import validate_access_map

        agent_policy, fallback = resolve_agent_ceiling(
            owner, validate_access_map(agent_permissions), agent_default_permission,
        )
        rank = {"none": 0, "read": 1, "write": 2}
        policy = {name: min(level, agent_policy.get(name, fallback), key=rank.get)
                  for name, level in policy.items()}
    definitions: list[dict] = []
    for tool in _registry()._tool_manager.list_tools():
        if tool.name in _SEPARATE_TOOLS:
            continue
        try:
            operation = _operation(tool, {"action": "list"} if tool.name == "browser_session" else None)
        except PermissionError:
            continue
        extra_scope = _ADDITIONAL_SCOPES.get(tool.name)
        if extra_scope and extra_scope not in scopes:
            continue
        properties = tool.parameters.get("properties", {})
        if tool.name in _AGENT_CONTROL:
            # No local/remote machine grant or shell OAuth scope is needed.
            pass
        elif tool.name in _CONTROLLER_MANAGEMENT:
            if not _agent_allows(policy, "local", "write") or not _can_authorize(
                owner, conversation_id, "local", "write", scopes, expires,
            ):
                continue
        elif tool.name == "remote_transfer":
            # Transfer requires a writable destination and a readable source;
            # no model-defined endpoint can bypass either machine's policy.
            if not any(level == "write" and _can_authorize(
                owner, conversation_id, machine, "write", scopes, expires,
            ) for machine, level in policy.items()):
                continue
        elif "machine" not in properties:
            if not _agent_allows(policy, "local", operation) or not _can_authorize(
                owner, conversation_id, "local", operation, scopes, expires,
            ):
                continue
        elif not any(_can_authorize(owner, conversation_id, machine, operation, scopes, expires)
                     for machine, level in policy.items()
                     if _agent_allows(policy, machine, operation)):
            continue
        params = copy.deepcopy(tool.parameters)
        # This internal context is controlled by LSM, never chosen by a model.
        params.get("properties", {}).pop("logical_session_id", None)
        params["required"] = [name for name in params.get("required", []) if name != "logical_session_id"]
        if not params["required"]:
            params.pop("required", None)
        description = (tool.description or "")[:2048]
        if tool.name == "plan_manage":
            description = (
                "Manage Goal mode for a Logical Session. In Chat, starting or resuming "
                "a plan binds it to the current generation. If the plan is still active "
                "when a model turn ends, Chat immediately continues the same generation. "
                "Update progress, finish completed plans, or block with a concrete reason. "
                "Actions: start, get, update, block, resume, finish, cancel. "
                "Start requires objective and steps; finish requires all steps completed or skipped. "
                "session_id must be returned by session_manage."
            )
        if tool.name == "browser_session":
            writable = any(level == "write" and _can_authorize(
                owner, conversation_id, machine, "write", scopes, expires,
            ) for machine, level in policy.items())
            if not writable:
                params["properties"]["action"] = {"type": "string", "enum": ["list"]}
                description = "List existing browser sessions on readable machines. Starting, closing, and cleanup require write access."
            else:
                description += " Only list is allowed on read-only machines; other actions require write access."
        definitions.append({"type": "function", "function": {
            "name": tool.name,
            "description": description,
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


def _validate_arguments(arguments: Any) -> None:
    """Apply the existing LSM transport budget, not a separate Agent limit.

    Internal dispatch skips HTTP, so enforce the same configured byte ceiling
    here. Tool-specific file/script limits and schemas remain in the native
    executor. SDK history/input previews are a different, non-execution concern.
    """
    from ..settings import get_settings

    if not isinstance(arguments, dict):
        raise ValueError("LSM tool arguments must be an object")
    if "logical_session_id" in arguments:
        raise PermissionError("Models cannot provide LSM internal session credentials")
    limit = max(1, get_settings().max_http_request_bytes)
    size = 0
    try:
        encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        for chunk in encoder.iterencode(arguments):
            size += len(chunk.encode("utf-8"))
            if size > limit:
                raise ValueError(f"LSM tool arguments exceed the configured {limit} byte request limit")
    except (TypeError, RecursionError, UnicodeError) as error:
        raise ValueError("LSM tool arguments must contain valid JSON") from error


async def call_tool(owner: str, conversation_id: str, call: ModelToolCall, *,
                    granted_scopes: set[str], grant_expires: int | None = None,
                    run_id: str | None = None,
                    authorization_conversation_id: str | None = None,
                    agent_id: str | None = None) -> str:
    """Dispatch through FastMCP's original validated, audited tool function.

    Detached child generations own native tasks in their actual child
    conversation while inheriting the verified original parent conversation's
    machine policy. Never bind a child's run_id to its parent's conversation:
    durable_tasks.reserve requires the run to belong to the owned task scope.
    """
    from . import durable_tasks

    tool = _tool(call.name)
    arguments = call.arguments
    _validate_arguments(arguments)
    intent = None
    permission_conversation_id = authorization_conversation_id or conversation_id

    def check_authorization():
        if run_id is not None and durable_tasks.is_run_cancelled(run_id):
            raise PermissionError("Agent generation has been cancelled")
        if intent is not None:
            durable_tasks.check_intent(intent)
        operation = _operation(tool, arguments)
        if agent_id and tool.name not in _AGENT_CONTROL:
            # Re-fetch each time a long-running native action is rechecked;
            # changing or deleting an Agent revokes its in-flight privileges.
            from .agents import AgentRepository
            from .routes import _repo

            agent = AgentRepository(_repo().database).get(owner, agent_id)
            if agent is None:
                raise PermissionError("Agent no longer exists")
            policy = agent_access_policy(agent)
            if policy is not None:
                agent_policy, default = resolve_agent_ceiling(owner, *policy)
                if tool.name == "remote_transfer":
                    requirements = [
                        (arguments.get("source_machine") or "local", "read"),
                        (arguments.get("destination_machine") or "local", "write"),
                    ]
                else:
                    requirements = [(machine, operation) for machine in _targets(tool, arguments)]
                if tool.name == "job_retry" and arguments.get("machine") in {None, "", "local"}:
                    from ..jobs import job_retry_machine_requirements

                    requirements.extend(job_retry_machine_requirements(arguments.get("job_id")))
                for machine, required in requirements:
                    if not _agent_allows(agent_policy, machine, required, default):
                        if required != "read" and agent_policy.get(machine, default) == "read":
                            raise MachineReadOnlyError(f"Machine {machine} is read-only for this Agent")
                        raise PermissionError(f"Agent has no {required} access to machine {machine}")
        if tool.name in _AGENT_CONTROL:
            # Session ownership is still checked; this bypasses machine ACLs only.
            from .routes import _repo

            if _repo().conversation(owner, conversation_id) is None:
                raise KeyError("Conversation not found")
            if grant_expires is not None:
                import time

                if float(grant_expires) <= time.time():
                    raise PermissionError("Authentication grant expired")
        elif tool.name == "remote_transfer":
            source = arguments.get("source_machine") or "local"
            destination = arguments.get("destination_machine") or "local"
            if not isinstance(source, str) or not isinstance(destination, str):
                raise ValueError("Invalid transfer machines")
            authorize_machine_action(owner, permission_conversation_id, source, "read",
                                     scopes=granted_scopes, expires=grant_expires)
            authorize_machine_action(owner, permission_conversation_id, destination, "write",
                                     scopes=granted_scopes, expires=grant_expires)
        else:
            for machine in _targets(tool, arguments):
                authorize_machine_action(owner, permission_conversation_id, machine, operation,
                                         scopes=granted_scopes, expires=grant_expires)
        if tool.name == "job_retry" and arguments.get("machine") in {None, "", "local"}:
            # Controller-managed transfer jobs retain remote endpoints in their
            # payload. Retrying by job ID must never bypass those endpoint ACLs.
            from ..jobs import job_retry_machine_requirements

            for machine, required in job_retry_machine_requirements(arguments.get("job_id")):
                authorize_machine_action(owner, permission_conversation_id, machine, required,
                                         scopes=granted_scopes, expires=grant_expires)
        extra_scope = _ADDITIONAL_SCOPES.get(tool.name)
        if extra_scope and extra_scope not in granted_scopes:
            raise PermissionError(f"{extra_scope} permission is required")
        if run_id is not None:
            durable_tasks.owned(owner, conversation_id, tool.name, arguments)

    try:
        check_authorization()
    except MachineReadOnlyError as error:
        # Only a denial before dispatch is recoverable. Live revocation still
        # interrupts the native task and propagates as a runtime safety error.
        raise ToolPermissionDenied("The target machine is read-only; this action requires write access.") from error
    # MCP uses None/omitted for the local controller. Passing the literal name
    # `local` would instead incorrectly route to a Worker called local.
    if run_id is not None and (tool.name in durable_tasks._STARTS or (
        tool.name in {"run_shell", "run_python"} and arguments.get("persist_on_timeout")
    )):
        intent = durable_tasks.reserve(owner, conversation_id, run_id, call.call_id,
                                      tool.name, arguments, granted_scopes, grant_expires,
                                      authorization_conversation_id=authorization_conversation_id,
                                      agent_id=agent_id)
        check_authorization()
    invocation = dict(arguments)
    if intent is not None and intent.key is not None:
        invocation["idempotency_key"] = intent.key
    for field in ("machine", "source_machine", "destination_machine"):
        if invocation.get(field) == "local":
            invocation[field] = None
    session_kwargs = {}
    if run_id is not None and tool.name not in _AGENT_CONTROL:
        from .chat_goal import active_plan
        from .routes import _repo

        active = active_plan(_repo().database, owner, run_id)
        if active:
            session_kwargs["logical_session_id"] = active[0]
    try:
        result = await _await_authorized(
            _invoke_registered(owner, conversation_id, tool.name, invocation,
                               scopes=granted_scopes, machines=_targets(tool, arguments),
                               intent=intent, **session_kwargs),
            check_authorization,
        )
        if run_id is not None and json.loads(result).get("ok", True) is not False:
            durable_tasks.mark_stopped(owner, conversation_id, tool.name, arguments)
        if tool.name == "remote_manage" and arguments.get("action", "").strip().lower() == "list":
            from .agents import AgentRepository
            from .machine_permissions import effective_machine_access
            from .routes import _repo

            payload = json.loads(result)
            if isinstance(payload, dict) and payload.get("ok", True):
                data = payload.get("data")
                if isinstance(data, dict) and isinstance(data.get("machines"), list):
                    repo = _repo()
                    agent = AgentRepository(repo.database).get(owner, agent_id) if agent_id else None
                    if agent_id and agent is None:
                        agent = {"machine_default_permission": "none"}
                    access, _ = effective_machine_access(
                        owner, permission_conversation_id, agent=agent,
                        scopes=granted_scopes, expires=grant_expires, repo=repo,
                    )
                    for row in data["machines"]:
                        if isinstance(row, dict):
                            row["effective_access"] = access.get(row.get("name"), "none")
                    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return result
    except PermissionError:
        audit("webui_agent_lsm_tool_revoked", owner=owner, conversation_id=conversation_id,
              tool=tool.name, machines=_targets(tool, arguments), ok=False)
        # Durable reconcilers run independently. Do not stall the provider
        # response on an offline Worker's cancellation timeout.
        raise


async def _await_authorized(invocation, check_authorization):
    """Recheck a live dispatch without bypassing native cancellation cleanup.

    Cancellation reaches the original tool executor. Its protected mutations
    still settle before returning; cancellable processes use native process
    group termination. Already-returned background jobs require a separate
    durable ownership lease and are deliberately not inferred from job lists.
    """
    task = asyncio.create_task(invocation)
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=_AUTHORIZATION_RECHECK_SECONDS)
            try:
                check_authorization()
            except KeyError as error:
                raise PermissionError("Agent authorization is no longer available") from error
            if task in done:
                return task.result()
    except BaseException:
        if not task.done():
            task.cancel()
        # Native non-cancellable writes/start operations may still be settling.
        # Keep ownership of the task until their cleanup has actually finished.
        await asyncio.gather(task, return_exceptions=True)
        raise



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
                             machines: list[str] | None = None,
                             intent=None, logical_session_id: str | None = None) -> str:
    """Call only an explicitly vetted tool using MCP's own validated executor."""
    from ..auth import _CURRENT_PRINCIPAL, Principal

    _validate_arguments(arguments)
    invocation = dict(arguments)
    invocation["logical_session_id"] = logical_session_id
    token = _CURRENT_PRINCIPAL.set(Principal(
        email=None, subject=owner,
        claims={"scope": " ".join(sorted(scopes)), "auth": "webui-agent"},
    ))
    try:
        data = await _registry()._tool_manager.call_tool(name, invocation, convert_result=True)
        if intent is not None:
            from .durable_tasks import bind

            bind(intent, data)
        result = _encode_result(data)
        succeeded = _result_succeeded(data)
    except Exception as exc:
        audit("webui_agent_lsm_tool", owner=owner, conversation_id=conversation_id,
              tool=name, machines=machines or [], ok=False, error_type=type(exc).__name__)
        raise
    finally:
        _CURRENT_PRINCIPAL.reset(token)
    audit("webui_agent_lsm_tool", owner=owner, conversation_id=conversation_id,
          tool=name, machines=machines or [], ok=succeeded)
    return result



def _result_succeeded(value: Any) -> bool:
    """Respect native MCP error envelopes without interpreting tool text."""
    from mcp.types import CallToolResult

    if isinstance(value, CallToolResult):
        return not value.isError and _result_succeeded(value.structuredContent)
    if isinstance(value, tuple) and len(value) == 2:
        return _result_succeeded(value[1])
    return not (isinstance(value, dict) and value.get("ok") is False)


def _encode_result(value: Any) -> str:
    if isinstance(value, tuple) and len(value) == 2:
        content, structured = value
        value = structured if structured is not None else list(content)
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", by_alias=True)
    # Keep the native structured result intact for audit/checkpoint replay.
    # Model-facing clipping belongs to the source ToolNode ingestion boundary.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                      default=lambda item: item.model_dump(mode="json", by_alias=True) if hasattr(item, "model_dump") else str(item))
