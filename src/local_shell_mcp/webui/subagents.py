"""LibreChat 0.8.8 / agents 4.0.1 isolated subagent tool adapter.

Ports buildSubagentConfigs, buildSubagentToolParams, Graph's invocation wrapper
and filterSubagentResult. The shared runtime executes child graphs through an
injected callback; this module never creates a second provider/tool executor.
Detached tasks and child-thread continuation are not advertised without their
host store, matching the upstream capability-gated schema.
"""

from __future__ import annotations

import copy
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

SUBAGENT_TOOL_NAME = "subagent"
MAX_SUBAGENT_DEPTH = 5
MAX_SUBAGENT_RUN_CONFIGS = 100
SUBAGENT_DESCRIPTION = "Delegate a task to a specialized subagent or bounded agent team that runs in an isolated context window. The delegated execution returns only its designated final text result — all intermediate tool calls, reasoning, and context stay isolated.\n\nWHEN TO USE:\n- The task is self-contained and can be described in a single prompt.\n- You want to offload verbose or exploratory work without bloating your own context.\n- A specialized subagent is available for the task domain.\n\nWHAT HAPPENS:\n- A fresh agent or configured agent graph is created with the task description as its only input, unless the host enables child-thread continuation and you provide a saved thread id.\n- The delegated agent or team runs to completion using isolated tools and context.\n- Only the single agent's final response or the graph's designated result-agent response is returned to you.\n\nCONSTRAINTS:\n- subagent_type must match one of the available types listed below.\n- The subagent cannot see your conversation history."
_INTENT_DESCRIPTION = (
    'ALWAYS write this field FIRST, before any other argument. One present-progressive '
    'sentence saying what THIS call is about to do: "Searching for OAuth handling '
    'in the callback router". Shown to the user as this call\'s live status. '
    'Never name the tool. Sibling calls to one tool must differ.'
)
_DESCRIPTION = "Complete task description for the subagent. This is the ONLY information it receives — include all necessary context, requirements, and constraints."
_TYPE_DESCRIPTION = "Which subagent type to delegate to. Must be one of the available types."
_BACKGROUND_DESCRIPTION = "Set true to start the subagent as a detached process-local task and return a background_task_id immediately. Poll the host background-task tool to collect its result. The task can outlive this turn but does not survive a process restart."
_THREAD_DESCRIPTION = "Continue a host-owned child thread using a fresh execution lease. The saved thread must belong to this scope and subagent type. Only available with run_in_background."


@dataclass(frozen=True)
class SubagentConfig:
    type: str
    name: str
    description: str
    agent: dict
    max_turns: int
    owner: str
    self_spawn: bool = False
    allow_nested: bool = False
    children: tuple[SubagentConfig, ...] = ()


@dataclass(frozen=True)
class SubagentInvocation:
    agent: dict
    messages: list[dict]
    selected_tools: tuple[str, ...]
    max_turns: int
    recursion_limit: int
    remaining_depth: int
    scopes: frozenset[str]
    grant_expires: int | None
    owner: str
    conversation_id: str
    parent_run_id: str
    parent_tool_call_id: str
    subagent_type: str
    child_configs: tuple[SubagentConfig, ...]
    parent_agent_id: str | None = None


def resolve_subagent_max_turns(agent: dict, endpoint_config: dict | None = None) -> int:
    """agents/config.ts resolveRecursionLimit + resolveSubagentMaxTurns."""
    endpoint = endpoint_config or {}
    limit = endpoint.get("recursionLimit")
    if limit is None:
        limit = 50
    override = agent.get("recursion_limit")
    if type(override) in (int, float) and override > 0:
        limit = override
    cap = endpoint.get("maxRecursionLimit")
    if type(cap) in (int, float) and cap > 0 and limit > cap:
        limit = cap
    return math.floor(limit / 3)


def build_subagent_configs(owner: str, parent: dict | None, database: Any, *,
                           endpoint_config: dict | None = None,
                           ancestors: tuple[str, ...] = (), depth: int = 0,
                           _count: list[int] | None = None) -> list[SubagentConfig]:
    """Source run.ts self/default, explicit children, ancestry and expansion bounds."""
    from .agents import AgentRepository

    settings = (parent or {}).get("subagents")
    if not isinstance(settings, dict) or settings.get("enabled") is not True:
        return []
    if depth > MAX_SUBAGENT_DEPTH:
        raise ValueError(f"Subagent graph exceeds the maximum depth of {MAX_SUBAGENT_DEPTH} at agent {parent.get('id')}.")
    count = _count if _count is not None else [0]
    repository = AgentRepository(database)
    configs = []

    def append(agent: dict, kind: str, self_spawn: bool = False) -> None:
        count[0] += 1
        if count[0] > MAX_SUBAGENT_RUN_CONFIGS:
            raise ValueError(f"Subagent run configuration exceeds the maximum of {MAX_SUBAGENT_RUN_CONFIGS} expanded entries.")
        name = agent.get("name")
        if self_spawn:
            name = name if name is not None else "self"
            description = f"Spawn {name} in an isolated context to handle a focused subtask. Verbose tool output stays in the child's context; only a summary returns."
        else:
            name = name if name is not None else agent["id"]
            description = agent.get("description")
            if description is None:
                description = f"Delegate a subtask to the {name} agent in an isolated context."
        child = copy.deepcopy(agent)
        # run.ts buildAgentInput excludes Ask User in every child scope.
        child["tools"] = [tool for tool in child.get("tools", []) if tool != "ask_user_question"]
        for key in ("initialSummary", "discoveredTools", "initial_summary", "discovered_tools"):
            child.pop(key, None)
        children = []
        if self_spawn:
            child.pop("subagents", None)
        else:
            if depth + 1 > MAX_SUBAGENT_DEPTH:
                raise ValueError(f"Subagent graph exceeds the maximum depth of {MAX_SUBAGENT_DEPTH} at agent {agent['id']}.")
            children = build_subagent_configs(owner, child, database, endpoint_config=endpoint_config,
                                   ancestors=(*ancestors, str(parent.get("id") or "")),
                                   depth=depth + 1, _count=count)
        configs.append(SubagentConfig(kind, str(name), str(description), child,
                                      resolve_subagent_max_turns(agent, endpoint_config), owner,
                                      self_spawn=self_spawn, allow_nested=not self_spawn, children=tuple(children)))

    if settings.get("allowSelf") is not False:
        append(parent, "self", True)
    ids = settings.get("agent_ids") or []
    if not isinstance(ids, list) or any(not isinstance(identity, str) for identity in ids):
        raise ValueError("Subagent agent_ids must be an array of identifiers")
    seen = set()
    for identity in ids:
        if identity == parent.get("id") or identity in ancestors:
            continue
        if identity in seen:
            raise ValueError(f'Duplicate subagent type "{identity}". Each SubagentConfig must have a unique "type" field.')
        seen.add(identity)
        child = repository.get(owner, identity)
        if child is None:
            raise PermissionError("Subagent is not owned by the current principal")
        append(child, identity)
    # LibreChat packages/api/src/agents/run.ts buildSubagentConfigs: graph entries
    # are isolated StateGraphs with an explicitly designated result member.
    for definition in settings.get("graphs") or []:
        members = []
        for identity in definition["agent_ids"]:
            member = repository.get(owner, identity)
            if member is None:
                raise PermissionError("Graph subagent member is not owned by the current principal")
            members.append(member)
        if not members:
            continue
        count[0] += 1
        if count[0] > MAX_SUBAGENT_RUN_CONFIGS:
            raise ValueError(f"Subagent run configuration exceeds the maximum of {MAX_SUBAGENT_RUN_CONFIGS} expanded entries.")
        entry = next((member for member in members if member["id"] == definition["entry_agent_id"]), None)
        if entry is None:
            raise ValueError("Graph subagent entry is not a configured member")
        team = copy.deepcopy(entry)
        team["edges"] = [copy.deepcopy(edge) for edge in definition["edges"]]
        # The upstream graph receives every member, even a non-edge member.
        team["graphAgentIds"] = [member["id"] for member in members]
        team["entryAgentId"] = definition["entry_agent_id"]
        team["resultAgentId"] = definition["result_agent_id"]
        for edge in team["edges"]:
            if edge.get("excludeResults") is False and not edge.get("prompt"):
                edge.pop("excludeResults")
        configs.append(SubagentConfig(
            definition["type"], definition["name"], definition["description"], team,
            min(resolve_subagent_max_turns(member, endpoint_config) for member in members), owner,
        ))
    return configs


def build_subagent_tool_params(configs: list[SubagentConfig], *, background: bool = False,
                               thread_continuation: bool = False) -> dict:
    """Exact agents/src/tools/SubagentTool.ts dynamic model-facing schema."""
    types = [config.type for config in configs]
    properties = {
        "intent": {"type": "string", "description": _INTENT_DESCRIPTION},
        "description": {"type": "string", "description": _DESCRIPTION},
        "subagent_type": {"type": "string", "enum": types,
                          "description": _TYPE_DESCRIPTION + " Available: " + ", ".join(types) + "."},
    }
    description = SUBAGENT_DESCRIPTION
    if background:
        properties["run_in_background"] = {"type": "boolean", "description": _BACKGROUND_DESCRIPTION}
        description += "\n\nBACKGROUND EXECUTION:\n- Set run_in_background to true when you do not need the result immediately. The call returns a background_task_id; use the host background-task tools to poll, steer, queue, interrupt, or cancel it."
        if thread_continuation:
            properties["subagent_thread_id"] = {"type": "string", "description": _THREAD_DESCRIPTION}
            description += "\n- To continue a completed child later, set run_in_background and pass its subagent_thread_id. The host starts a fresh execution from saved history; it does not restore a completed runtime."
    description += "\n\nAvailable types:\n" + "\n".join(
        f'- "{config.type}" ({config.name}): {config.description}' for config in configs)
    return {"name": SUBAGENT_TOOL_NAME,
            "schema": {"type": "object", "properties": properties,
                       "required": ["description", "subagent_type"]},
            "description": description}


def subagent_tools(configs: list[SubagentConfig], *, background: bool = False,
                   thread_continuation: bool = False) -> list[dict]:
    if not configs:
        return []
    params = build_subagent_tool_params(configs, background=background,
                                        thread_continuation=thread_continuation)
    return [{"type": "function", "function": {
        "name": params["name"], "description": params["description"],
        "parameters": params["schema"],
    }}]


def filter_subagent_result(messages: list[dict]) -> str:
    """Source SubagentExecutor.filterSubagentResult; final AI text only."""
    for message in reversed(messages):
        if message.get("role") not in {"assistant", "ai"}:
            continue
        content = message.get("content")
        if isinstance(content, str):
            if content:
                return content
            continue
        if not isinstance(content, list):
            continue
        parts, deltas = [], []
        delta_index = None

        def flush(parts=parts, deltas=deltas) -> None:
            nonlocal delta_index
            if deltas:
                parts.append("".join(deltas))
                deltas.clear()
                delta_index = None

        for block in content:
            if isinstance(block, str):
                flush()
                if block:
                    parts.append(block)
                continue
            if not isinstance(block, dict):
                flush()
                continue
            kind = block.get("type")
            text = block.get("text")
            text = text if kind in {"text", "text_delta"} and isinstance(text, str) else ""
            if kind == "text_delta":
                if not text:
                    continue
                index = block.get("index")
                index = index if type(index) in (str, int, float) else None
                if delta_index is not None and index is not None and index != delta_index:
                    flush()
                if delta_index is None:
                    delta_index = index
                deltas.append(text)
                continue
            if kind == "text" and not text:
                continue
            flush()
            if text:
                parts.append(text)
        flush()
        if parts:
            return "\n".join(parts)
    return "Task completed"


async def invoke_subagent(call: Any, configs: list[SubagentConfig], *,
                          execute_child: Callable[[SubagentInvocation], Awaitable[list[dict] | str]],
                          start_background: Callable[[SubagentInvocation, str | None], Awaitable[str]] | None = None,
                          owner: str, conversation_id: str, parent_run_id: str, database: Any,
                          parent_agent_id: str | None = None,
                          scopes: frozenset[str], grant_expires: int | None,
                          max_depth: int = MAX_SUBAGENT_DEPTH,
                          propagate_error: Callable[[Exception], bool] | None = None) -> str:
    """Use the shared child graph, isolated input, original final text semantics."""
    if call.name != SUBAGENT_TOOL_NAME:
        raise ValueError("Unknown subagent tool")
    args = call.arguments
    if not isinstance(args, dict):
        raise ValueError("Subagent arguments must be an object")
    kind = args.get("subagent_type") if isinstance(args.get("subagent_type"), str) else ""
    config = next((config for config in configs if config.type == kind), None)
    if config is None:
        return f'Error: Unknown subagent type "{kind}". Available types: {", ".join(config.type for config in configs)}'
    if max_depth <= 0:
        return "Error: Maximum subagent nesting depth exceeded."
    if config.owner != owner:
        raise PermissionError("Subagent is not owned by the current principal")
    from .agents import AgentRepository

    if not config.self_spawn and AgentRepository(database).get(owner, config.agent["id"]) is None:
        raise PermissionError("Subagent is not owned by the current principal")
    if grant_expires is not None and grant_expires <= time.time():
        raise PermissionError("Authentication grant expired")
    background = args.get("run_in_background") is True
    thread = args.get("subagent_thread_id")
    if isinstance(thread, str) and thread.strip() and not background:
        return '{"status":"rejected","tool":"subagent","message":"Child-thread continuation requires run_in_background."}'
    if background and start_background is None:
        raise ValueError("Background subagent execution is not available without a host task store")
    task = args.get("description")
    description = task if isinstance(task, str) and task.strip() else "No task description provided"
    messages = []
    instructions = config.agent.get("instructions")
    additional = config.agent.get("additional_instructions")
    system = "\n\n".join(value for value in (instructions, additional) if isinstance(value, str) and value)
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": description})
    invocation = SubagentInvocation(
        agent=copy.deepcopy(config.agent), messages=messages,
        selected_tools=tuple(config.agent.get("tools") or []),
        max_turns=config.max_turns, recursion_limit=config.max_turns * 3,
        remaining_depth=max(0, max_depth - 1) if config.allow_nested else 0,
        scopes=frozenset(scopes), grant_expires=grant_expires, owner=owner,
        conversation_id=conversation_id, parent_run_id=parent_run_id,
        parent_tool_call_id=call.call_id, subagent_type=kind,
        parent_agent_id=parent_agent_id,
        child_configs=config.children if max_depth > 1 else (),
    )
    if background:
        assert start_background is not None
        return await start_background(invocation, thread.strip() if isinstance(thread, str) and thread.strip() else None)
    try:
        result = await execute_child(invocation)
    except Exception as error:
        # Graph interrupts and circuit-breaker failures are control flow, not
        # recoverable tool errors. The shared graph supplies its own classes.
        if propagate_error is not None and propagate_error(error):
            raise
        message = str(error)
        encoded = message.encode("utf-16-le", errors="surrogatepass")
        if len(encoded) > 400:
            message = encoded[:400].decode("utf-16-le", errors="surrogatepass") + "..."
        return "Subagent error: " + message
    return result if isinstance(result, str) else filter_subagent_result(result)
