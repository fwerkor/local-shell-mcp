"""LibreChat agents 4.0.1 MultiAgentGraph compiled with official Python LangGraph.

Source: src/graphs/MultiAgentGraph.ts createWorkflow, src/graphs/handoff.ts.
Each graph member uses the existing AgentRunner (same provider, tool dispatch,
HITL and authorization); StateGraph owns supersteps, join barriers, Commands,
and Send fan-out. Python LangGraph remains an optional WebUI-only dependency.
"""
from __future__ import annotations

import copy
from typing import Annotated, Any, TypedDict

from .graph_topology import GraphTopology, endpoints
from .handoff import HandoffRouting, merge_handoff_state, receive_handoff
from .message_reducers import agent_messages_reducer, messages_state_reducer


class MultiAgentState(TypedDict, total=False):
    messages: Annotated[list[dict], messages_state_reducer]
    agentMessages: Annotated[list[dict], agent_messages_reducer]
    subagentResult: dict | None
    manualSummary: str | None
    handoffState: Annotated[dict | None, merge_handoff_state]


def _graph_imports():
    try:
        from langgraph.graph import END, START, StateGraph
        from langgraph.types import Command, Send
    except ImportError as exc:
        raise RuntimeError(
            "MultiAgentGraph needs the optional Controller-only webui-graph extra; "
            "install local-shell-mcp[webui-graph] (never on Worker)"
        ) from exc
    from .graph_checkpoint import OwnedGraphCheckpointer

    return START, END, StateGraph, Command, Send, OwnedGraphCheckpointer


def _route_prompt(message: str) -> dict:
    return {"role": "user", "content": message,
            "additional_kwargs": {"role": "user", "isMeta": True, "source": "routing"}}


def _content(message: dict) -> str:
    value = message.get("content")
    return value if isinstance(value, str) else str(value or "")


def _limit_prompt(value: str, size: int = 64_000) -> str:
    return value[:size]


def _as_goto(commands: list[dict], *, Send: Any) -> list[Any]:
    result = []
    for command in commands:
        goto = command.get("goto")
        for item in goto if isinstance(goto, list) else [goto]:
            if isinstance(item, dict) and item.get("lg_name") == "Send":
                result.append(Send(item["node"], item["args"]))
            elif isinstance(item, str):
                result.append(item)
            else:
                raise ValueError("Unknown source Command destination")
    return result


async def run_multi_agent_graph(parent: Any, history: list[dict], topology: GraphTopology,
                                *, recursion_limit: int | None = None) -> list[dict]:
    """Compile all declared edges, preserving the SDK's dynamic/static split."""
    START, END, StateGraph, Command, Send, OwnedGraphCheckpointer = _graph_imports()
    from .agent_runner import AgentRunner

    root = parent.graph_definition
    source_id = root["id"]
    if topology.reachable_agent_ids is not None:
        member_ids = topology.reachable_agent_ids
    else:
        member_ids = topology.agent_ids
    members = {}
    for ident in member_ids:
        member = parent.repository.get(parent.owner, ident)
        if member is None:
            raise PermissionError("Agent graph member is not owned by the current principal")
        members[ident] = member
    source_history = messages_state_reducer([], copy.deepcopy(history))
    initial_count = len(source_history)
    graph = StateGraph(MultiAgentState)
    handoff_sources = topology.handoff_sources
    destinations = {ident: set() for ident in member_ids}
    direct_destinations = {ident: set() for ident in member_ids}
    for edge in topology.edges:
        for src in endpoints(edge, "from"):
            for dest in endpoints(edge, "to"):
                if dest in members:
                    destinations[src].add(dest)
                    if edge in topology.direct_edges:
                        direct_destinations[src].add(dest)

    async def node(agent_id: str, state: MultiAgentState):
        parent._check_grant()
        member = parent.repository.get(parent.owner, agent_id)
        if member is None:
            raise PermissionError("Graph member Agent was revoked")
        current = copy.deepcopy(state["messages"])
        incoming = copy.deepcopy(state.get("agentMessages") or current)
        reception = receive_handoff(current, agent_id)
        if reception is not None:
            incoming = reception["filteredMessages"]
            prompt = reception.get("instructions")
            if prompt:
                if incoming and incoming[-1].get("role") == "tool":
                    incoming.append({"role": "assistant", "content":
                                     f"[Processed tool result and transferring to {agent_id}]"})
                incoming.append(_route_prompt(_limit_prompt(prompt)))
        elif state.get("agentMessages"):
            incoming = copy.deepcopy(state["agentMessages"])
        instructions = member.get("instructions") or ""
        if instructions:
            incoming.insert(0, {"role": "system", "content": instructions})

        async def emit(delta: str) -> None:
            # All nodes use one event stream and the existing generation actor.
            parent.partial_text += delta
            await parent.on_text(delta)

        child = AgentRunner(
            parent.owner, parent.generation, parent.database, parent.store,
            scopes=parent.scopes, grant_expires=parent.grant_expires,
            stream_tools=parent.stream_tools, stream_text=parent.stream_text,
            on_text=emit, agent=member, profile=parent.initial_profile if agent_id == source_id else None,
            parameters=parent.initial_parameters,
            ask_user_enabled=parent.ask_user_enabled, mcp_enabled=parent.mcp_enabled,
            namespace=parent.namespace + "/graph:" + agent_id,
            child_configs=parent.child_configs, selected_tools=parent.selected_tools if agent_id == source_id else None,
            resume_history=parent.resume_history, resume_namespace=parent.resume_namespace,
            partial_text=parent.partial_text, approved_batch=parent.approved_batch,
            graph_node=True, graph_definition=root, graph_entry_id=topology.default_agent_id,
            graph_parallel=topology.routing_parallel,
            graph_max_handoffs=root.get("maxHandoffs"),
            authorization_conversation_id=parent.authorization_conversation_id,
            background_deny=parent.background_deny,
            task_control_host=parent.task_control_host, task_control_id=parent.task_control_id,
            subagent_depth=parent.subagent_depth, on_injected=parent.on_injected,
            wakeup_lease=parent.wakeup_lease,
        )
        child.route.restore(state.get("handoffState"))
        # The existing loop appends in place: snapshot the pre-call boundary.
        incoming = messages_state_reducer([], incoming)
        before = copy.deepcopy(incoming)
        result = await child.run(incoming)
        # Stable IDs make full state returns and sibling superstep updates safe.
        result = messages_state_reducer([], result)
        diff = result[len(before):] if result[:len(before)] == before else result
        update = {"messages": diff, "agentMessages": []}
        if root.get("resultAgentId") == agent_id:
            replies = [m for m in diff if m.get("role") in {"assistant", "ai"}]
            update["subagentResult"] = {"agentId": agent_id, "message": replies[-1] if replies else None}
        if child.graph_commands:
            # ToolNode settled all commands and finalized the transition once.
            update["handoffState"] = child.route.snapshot()
            for command in child.graph_commands:
                command_update = command.get("update") or {}
                transfer_messages = command_update.get("messages") or []
                if transfer_messages:
                    transfer = transfer_messages[-1]
                    if transfer.get("role") == "tool":
                        update["messages"].append(transfer)
            goto = _as_goto(child.graph_commands, Send=Send)
            if len(goto) == 1 and not isinstance(goto[0], Send):
                return Command(update=update, goto=goto[0])
            return Command(update=update, goto=goto)
        if agent_id in handoff_sources and direct_destinations[agent_id]:
            direct = list(dict.fromkeys(dest for edge in topology.direct_edges
                                        if agent_id in endpoints(edge, "from")
                                        for dest in endpoints(edge, "to")))
            return Command(update=update, goto=direct)
        return update

    for agent_id in members:
        async def wrapper(state: MultiAgentState, _agent_id=agent_id):
            return await node(_agent_id, state)

        graph.add_node(agent_id, wrapper, destinations=tuple(destinations[agent_id]) + (END,))

    for agent_id in topology.starting_nodes:
        if agent_id in members:
            graph.add_edge(START, agent_id)

    groups: dict[str, list[dict]] = {}
    for edge in topology.direct_edges:
        for target in endpoints(edge, "to"):
            if target in members:
                groups.setdefault(target, []).append(edge)
    for target, edges in groups.items():
        prompted = [edge for edge in edges if edge.get("prompt")]
        to_node = target
        if prompted:
            to_node = f"fan_in_{target}_prompt"
            prompt, exclude = prompted[0].get("prompt"), prompted[0].get("excludeResults")

            async def fan_in(state: MultiAgentState, _prompt=prompt, _exclude=exclude):
                if not isinstance(_prompt, str):
                    raise ValueError("Persisted direct-edge prompt must be a string")
                use_results = "{results}" in _prompt
                rendered = _prompt.replace("{results}", _limit_prompt(
                    "\n".join(_content(message) for message in state["messages"][initial_count:])))
                if not rendered:
                    return {}
                prompt_msg = _route_prompt(_limit_prompt(rendered))
                if _exclude is True or (use_results and _exclude is not False):
                    return {"messages": [prompt_msg], "agentMessages":
                            messages_state_reducer(state["messages"][:initial_count], [prompt_msg])}
                return {"messages": [prompt_msg]}

            graph.add_node(to_node, fan_in)
            graph.add_edge(to_node, target)
        for edge in edges:
            sources = endpoints(edge, "from")
            if not prompted:
                sources = [source for source in sources if source not in handoff_sources]
            if sources:
                graph.add_edge(sources if len(sources) > 1 else sources[0], to_node)

    saver = OwnedGraphCheckpointer(parent.database, parent.owner)
    checkpoint_config = saver.storage.config(
        parent.generation.conversation_id, parent.generation.run_id + ":graph:" + parent.namespace,
        event_actor=True,
    )
    compiled = graph.compile(checkpointer=saver, name="multi_agent_graph")
    stored = saver.get_tuple(checkpoint_config)
    if stored is not None and stored.checkpoint["channel_values"].get("messages"):
        initial = None  # Replay pending work; never re-run a completed model step.
    else:
        initial = {"messages": source_history, "agentMessages": [],
                   "handoffState": HandoffRouting(topology.default_agent_id, root.get("maxHandoffs"),
                                                   topology.routing_parallel).snapshot()}
    limit = recursion_limit or root.get("recursion_limit") or 50
    config = {**checkpoint_config, "recursion_limit": int(limit)}
    outcome = await compiled.ainvoke(initial, config)
    # Source SubagentExecutor returns the designated resultAgentId, never the
    # last sibling to settle in a parallel team. Keep intermediate messages
    # only in the isolated child graph and its SQLite checkpoints.
    if parent.namespace and "/subagent:" in parent.namespace and root.get("resultAgentId"):
        result = outcome.get("subagentResult") or {}
        message = result.get("message") if result.get("agentId") == root["resultAgentId"] else None
        return [message] if isinstance(message, dict) else []
    return outcome["messages"]
