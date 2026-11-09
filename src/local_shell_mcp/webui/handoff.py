"""LibreChat SDK 4.0.1 handoff routing and edge-derived transfer tools.

Ported from graphs/handoff.ts and MultiAgentGraph.createHandoffToolsForEdge.
The graph host owns execution and checkpoints; this module never invokes a
model, grants machine access, or promotes a conversation's active Agent.
"""

from __future__ import annotations

import copy
import json
import secrets
from collections.abc import Callable
from typing import Any

from .graph_topology import is_direct_edge

PARENT = "__parent__"
TRANSFER_PREFIX = "transfer_to_"
_NANOID_ALPHABET = "_-0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _nanoid() -> str:
    return "".join(secrets.choice(_NANOID_ALPHABET) for _ in range(21))


class HandoffLimitError(ValueError):
    def __init__(self, limit: int):
        self.limit = limit
        super().__init__(f"Agent handoff limit ({limit}) reached")


def _transition_sort_key(transition: dict) -> tuple:
    # SDK identities are ASCII (nanoid/checkpoint/tool IDs). ICU's default
    # collation sorts punctuation before digits, then letters, lower first.
    # Preserve primary weights before case, as JS localeCompare does.
    punctuation = " _-,;:!?.'\"()[]{}@*/\\&#%`^+<=>|~$"
    value = transition["id"]
    ranks = {char: index for index, char in enumerate(punctuation + "0123456789abcdefghijklmnopqrstuvwxyz")}
    primary = tuple(ranks.get(char.lower(), 1000 + ord(char.lower()[0])) for char in value)
    return transition["depth"], primary, tuple(char.isupper() for char in value)


def merge_handoff_state(current: dict | None, update: dict | None) -> dict | None:
    """Identity union: checkpoint replay is idempotent and merges commute."""
    if update is None:
        return current
    if current is None:
        return update
    if current["executionId"] != update["executionId"]:
        raise ValueError("Cannot merge handoffs from different logical turns")
    if (current["entryAgentId"] != update["entryAgentId"] or
            current.get("maxHandoffs") != update.get("maxHandoffs")):
        raise ValueError("Conflicting handoff checkpoint configuration")
    transitions = {item["id"]: item for item in current["transitions"]}
    for transition in update["transitions"]:
        existing = transitions.get(transition["id"])
        if existing is not None and any(existing[key] != transition[key] for key in (
            "id", "sourceAgentId", "targetAgentId", "toolCallId", "scope", "depth",
        )):
            raise ValueError("Conflicting replayed handoff transition")
        transitions[transition["id"]] = transition
    return {
        **current,
        "parallel": current["parallel"] or update["parallel"],
        "historyComplete": current.get("historyComplete") is not False and update.get("historyComplete") is not False,
        "transitions": sorted(transitions.values(), key=_transition_sort_key),
    }


class HandoffRouting:
    """One routing owner per graph, isolated from child Agent executions."""

    def __init__(self, entry_agent_id: str, max_handoffs: int | None = None,
                 parallel: bool = False):
        # The SDK MultiAgentGraph validates the shared cap before constructing
        # its HandoffRouting; the Python boundary performs the same check.
        if max_handoffs is not None and (
            type(max_handoffs) is not int or not 0 <= max_handoffs <= 9007199254740991
        ):
            raise ValueError("MultiAgentGraph: maxHandoffs must be a non-negative safe integer")
        self.entry_agent_id = entry_agent_id
        self.max_handoffs = max_handoffs
        self.parallel = parallel
        self._state = self._fresh_state()

    def _fresh_state(self) -> dict:
        return {"version": 1, "executionId": _nanoid(),
                "entryAgentId": self.entry_agent_id,
                **({"maxHandoffs": self.max_handoffs} if self.max_handoffs is not None else {}),
                "transitions": [], "parallel": self.parallel}

    def start(self) -> dict:
        self._state = self._fresh_state()
        return self.snapshot()

    def resume(self, state: dict | None) -> None:
        if state is not None:
            self.restore(state)
            return
        if self.max_handoffs is not None:
            raise ValueError("Cannot enforce a handoff budget on a legacy checkpoint without routing state")
        self._state = {**self._state, "historyComplete": False}

    def restore(self, state: dict | None) -> None:
        if state is None:
            return
        if type(state.get("version")) is not int or state["version"] != 1:
            raise ValueError("Unsupported handoff checkpoint version")
        if (state["entryAgentId"] != self.entry_agent_id or
                state.get("maxHandoffs") != self.max_handoffs):
            raise ValueError("Cannot resume with a different handoff entry or budget")
        if self._state["executionId"] != state["executionId"]:
            if self._state["transitions"]:
                raise ValueError("Cannot resume a different handoff execution")
            self._state = {**state, "transitions": [dict(item) for item in state["transitions"]]}
            return
        self._state = merge_handoff_state(self._state, state)

    def snapshot(self) -> dict:
        return {**self._state, "transitions": [dict(item) for item in self._state["transitions"]]}

    def finalize(self, commands: list[dict], input_state: dict,
                 config: dict | None = None) -> None:
        """Accept all settled transfer Commands atomically before recipients run."""
        self.restore(input_state.get("handoffState"))
        updates = []
        parallel = self._state["parallel"]
        for command in commands:
            if command.get("graph") != PARENT:
                continue
            sends = [item for item in command.get("goto", []) if _is_send(item)] if isinstance(command.get("goto"), list) else []
            parallel = parallel or len(sends) > 1
            if sends:
                updates.extend(send["args"] for send in sends)
            elif command.get("update") is not None:
                updates.append(command["update"])
        accepted = {item["id"]: item for item in self._state["transitions"]}
        requests = [update for update in updates if update.get("handoffRequest") is not None]
        if not requests:
            return
        input_handoffs = input_state.get("handoffState")
        depth = len(input_handoffs["transitions"]) if input_handoffs is not None else len(self._state["transitions"])
        messages = input_state["messages"]
        last_id = messages[-1].get("id") if messages else None
        checkpoint_ns = ((config or {}).get("configurable") or {}).get("checkpoint_ns", "")
        for update in requests:
            request = update["handoffRequest"]
            identity = json.dumps([self._state["executionId"], checkpoint_ns,
                                   request["sourceAgentId"], last_id if last_id is not None else len(messages),
                                   request["toolCallId"]], ensure_ascii=False, separators=(",", ":"))
            transition = {**request, "id": identity, "depth": depth}
            existing = accepted.get(identity)
            if existing is not None and (existing["targetAgentId"] != transition["targetAgentId"] or
                                         existing["scope"] != transition["scope"]):
                raise ValueError("Handoff replay changed its destination or scope")
            accepted[identity] = existing if existing is not None else transition
        if self.max_handoffs is not None and len(accepted) > self.max_handoffs:
            raise HandoffLimitError(self.max_handoffs)
        self._state = {**self._state, "transitions": list(accepted.values()), "parallel": parallel}
        for update in requests:
            update.pop("handoffRequest", None)
        for command in commands:
            if command.get("graph") != PARENT:
                continue
            command["update"] = {**(command.get("update") or {}), "handoffState": self.snapshot()}
            if isinstance(command.get("goto"), list):
                command["goto"] = [{**item, "args": {**item["args"], "handoffState": self.snapshot()}}
                                   if _is_send(item) else item for item in command["goto"]]

    def outcome(self, reason: str | None = None) -> dict:
        state = self.snapshot()
        base = {key: state[key] for key in ("executionId", "entryAgentId", "transitions")}
        if reason is not None:
            return {**base, "status": "incomplete", "reason": reason}
        if state.get("historyComplete") is False:
            return {**base, "status": "incomplete", "reason": "legacy_checkpoint"}
        persistent = [item for item in state["transitions"] if item["scope"] == "conversation"]
        if not persistent:
            return {**base, "status": "unchanged"}
        if state["parallel"]:
            return {**base, "status": "ambiguous"}
        last = persistent[0]
        for item in persistent[1:]:
            if last["depth"] <= item["depth"]:
                last = item
        return {**base, "status": "candidate", "agentId": last["targetAgentId"], "transitionId": last["id"]}


def _is_send(value: Any) -> bool:
    return isinstance(value, dict) and value.get("lg_name") == "Send"


def is_transfer_tool(name: str) -> bool:
    return name.startswith(TRANSFER_PREFIX) or name == "conditional_transfer"


def outgoing_handoff_edges(agent: dict, source_agent_id: str | None = None) -> list[dict]:
    """Select exactly the source's declared handoff graph edges."""
    source = source_agent_id or agent.get("id")
    result = []
    scopes = {}
    for edge in agent.get("edges") or []:
        if not isinstance(edge, dict):
            raise ValueError("Invalid Agent graph edge")
        if is_direct_edge(edge):
            if edge.get("handoffScope") is not None:
                raise ValueError("handoffScope is only valid on handoff edges")
            continue
        scope = "turn" if edge.get("handoffScope") is None else edge["handoffScope"]
        if scope not in {"turn", "conversation"}:
            raise ValueError("Invalid handoffScope")
        sources = edge.get("from") if isinstance(edge.get("from"), list) else [edge.get("from")]
        targets = edge.get("to") if isinstance(edge.get("to"), list) else [edge.get("to")]
        if not targets or any(not isinstance(item, str) or not item for item in targets):
            raise ValueError("Invalid handoff destination")
        for src in sources:
            for target in (["conditional_transfer"] if edge.get("condition") is not None else targets):
                key = (src, target)
                if key in scopes and scopes[key] != scope:
                    raise ValueError("Conflicting handoffScope for the same transfer tool")
                scopes[key] = scope
        if source in sources:
            result.append(edge)
    return result


def handoff_tools(owner: str, agent: dict, repository: Any, *,
                  source_agent_id: str | None = None) -> list[dict]:
    """Original tool definitions, admitted through LSM's Agent ownership boundary."""
    definitions = []
    for edge in outgoing_handoff_edges(agent, source_agent_id):
        targets = edge["to"] if isinstance(edge["to"], list) else [edge["to"]]
        for target in targets:
            if repository.get(owner, target) is None:
                raise PermissionError("Handoff destination is not owned by the current principal")
        conditional = edge.get("condition") is not None
        if conditional and not callable(edge["condition"]):
            raise ValueError("Conditional handoff requires a graph condition resolver")
        destinations = [None] if conditional else targets
        for target in destinations:
            has_input = isinstance(edge.get("prompt"), str)
            key = edge.get("promptKey", "instructions")
            schema = {"type": "object", "properties": {}, "required": []}
            if has_input:
                schema["properties"][key] = {"type": "string", "description": edge["prompt"]}
            definitions.append({"type": "function", "function": {
                "name": "conditional_transfer" if conditional else TRANSFER_PREFIX + target,
                "description": edge.get("description", "Conditionally transfer control based on state" if conditional
                                        else f"Transfer control to agent '{target}'"),
                "parameters": schema,
            }})
    return definitions


def handoff_edge_for_call(owner: str, agent: dict, repository: Any, tool_name: str, *,
                          source_agent_id: str | None = None) -> dict:
    """Recheck source configuration and destination ownership at execution."""
    allowed = {item["function"]["name"] for item in handoff_tools(
        owner, agent, repository, source_agent_id=source_agent_id)}
    if tool_name not in allowed:
        raise PermissionError("Handoff tool is not enabled for the current Agent")
    for edge in outgoing_handoff_edges(agent, source_agent_id):
        if edge.get("condition") is not None and tool_name == "conditional_transfer":
            return edge
        targets = edge["to"] if isinstance(edge["to"], list) else [edge["to"]]
        if edge.get("condition") is None and tool_name in [TRANSFER_PREFIX + target for target in targets]:
            return edge
    raise PermissionError("Handoff destination is not declared by the current Agent")


def build_handoff_command(edge: dict, source_agent_id: str, source_agent_name: str,
                          tool_name: str, arguments: dict, tool_call_id: str,
                          messages: list[dict], *, condition: Callable | None = None,
                          input_state: dict | None = None) -> dict | None:
    """Execute the original graph-managed transfer tool (no nested model call)."""
    targets = edge["to"] if isinstance(edge["to"], list) else [edge["to"]]
    conditional = edge.get("condition") is not None
    if conditional:
        resolver = condition or edge.get("condition")
        if not callable(resolver):
            raise ValueError("Conditional handoff requires a graph condition resolver")
        result = resolver(input_state if input_state is not None else {"messages": messages})
        if result is False:
            return None
        destination = (targets[0] if isinstance(result, bool) else result if isinstance(result, str)
                       else result[0] if isinstance(result, list) and result else targets[0])
        if destination not in targets:
            raise ValueError(f'Conditional handoff selected undeclared destination "{destination}"')
        expected_name = "conditional_transfer"
    else:
        expected_name = tool_name
        destination = tool_name.removeprefix(TRANSFER_PREFIX)
        if not tool_name.startswith(TRANSFER_PREFIX) or destination not in targets:
            raise PermissionError("Handoff destination is not declared by the current Agent")
    if tool_name != expected_name:
        raise ValueError("Handoff tool names must match exactly")
    has_input = isinstance(edge.get("prompt"), str)
    key = edge.get("promptKey", "instructions")
    instructions = arguments.get(key) if has_input else None
    if instructions is not None and not isinstance(instructions, str):
        raise ValueError("Handoff instructions must be a string")
    content = ("Conditionally" if conditional else "Successfully") + f" transferred to {destination}"
    if instructions is not None:
        content += "\n\n" + key[:1].upper() + key[1:] + ": " + instructions
    extra = {"handoff_source_name": source_agent_name}
    if conditional:
        extra["handoff_destination"] = destination
    if instructions is not None:
        extra["handoff_instructions"] = instructions
    tool_message = {"role": "tool", "name": tool_name, "tool_call_id": tool_call_id,
                    "content": content, "additional_kwargs": extra}
    filtered = copy.deepcopy(messages)
    if not conditional:
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if message.get("role") not in {"assistant", "ai"}:
                continue
            calls = message.get("tool_calls") or []
            matching = [item for item in calls if item.get("id") == tool_call_id]
            if matching:
                if len(calls) > 1:
                    retained = copy.deepcopy(message)
                    retained["tool_calls"] = copy.deepcopy(matching)
                    filtered = copy.deepcopy(messages[:index]) + [retained]
                break
    return {"graph": PARENT, "goto": destination, "update": {
        "messages": filtered + [tool_message], "handoffRequest": {
            "sourceAgentId": source_agent_id, "targetAgentId": destination,
            "toolCallId": tool_call_id, "scope": edge.get("handoffScope", "turn"),
        },
    }}


def combine_handoff_commands(commands: list[dict], *, parallel_batch: str | None = None) -> list[dict]:
    """Port ToolNode's transfer-to-Send aggregation before routing finalize."""
    transfers = []
    combined = []
    parent_sends = []
    for command in commands:
        goto = command.get("goto")
        if command.get("graph") == PARENT and isinstance(goto, list) and all(_is_send(item) for item in goto):
            parent_sends.extend(goto)
        elif command.get("graph") == PARENT and (isinstance(goto, str) or (
                isinstance(goto, list) and len(goto) == 1 and isinstance(goto[0], str))):
            transfers.append(command)
        else:
            combined.append(command)
    if len(transfers) > 1:
        destinations = [command["goto"] if isinstance(command["goto"], str) else command["goto"][0]
                        for command in transfers]
        batch = parallel_batch if parallel_batch is not None else _nanoid()
        alphabet = _NANOID_ALPHABET
        group = 0
        for char in batch[:8]:
            group = group * 64 + max(alphabet.find(char), 0)
        group += 2 ** 48
        sends = []
        for command, destination in zip(transfers, destinations, strict=True):
            update = command.get("update") or {}
            for message in reversed(update.get("messages") or []):
                extra = message.setdefault("additional_kwargs", {}) if message.get("role") == "tool" else {}
                if (message.get("name") == TRANSFER_PREFIX + destination or (
                        message.get("name") == "conditional_transfer" and extra.get("handoff_destination") == destination)):
                    extra["handoff_parallel_siblings"] = [item for item in destinations if item != destination]
                    extra["__handoff_parallel_batch"] = batch
                    extra["__handoff_group_id"] = group
                    break
            sends.append({"lg_name": "Send", "node": destination, "args": update})
        combined.append({"graph": PARENT, "goto": sends})
    elif transfers:
        combined.append(transfers[0])
    if parent_sends:
        combined.append({"graph": PARENT, "goto": parent_sends})
    return combined


def receive_handoff(messages: list[dict], agent_id: str, *,
                    agent_names: dict[str, str] | None = None) -> dict | None:
    """Port current-round transfer reception without replaying obsolete transfers.

    Current tool messages carry structured handoff_instructions. The pre-release
    Python host deliberately does not parse legacy free-text routing payloads.
    """
    active_ids = set()
    start = len(messages)
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get("role") == "tool":
            continue
        if message.get("role") in {"assistant", "ai"}:
            for call in message.get("tool_calls") or []:
                name = call.get("name") or (call.get("function") or {}).get("name")
                if isinstance(name, str) and is_transfer_tool(name) and call.get("id") is not None:
                    active_ids.add(call["id"])
            start = index + 1
        break
    if not active_ids:
        return None
    tool_message = None
    for message in reversed(messages[start:]):
        name = message.get("name")
        if message.get("role") != "tool" or not isinstance(name, str) or message.get("tool_call_id") not in active_ids:
            continue
        extra = message.get("additional_kwargs") or {}
        destination = name.removeprefix(TRANSFER_PREFIX) if name.startswith(TRANSFER_PREFIX) else (
            extra.get("handoff_destination") if name == "conditional_transfer" else None)
        if destination == agent_id:
            tool_message = message
            break
    if tool_message is None:
        return None
    transfer_ids = {tool_message["tool_call_id"]}
    for message in messages:
        if message.get("role") == "tool" and isinstance(message.get("name"), str) and is_transfer_tool(message["name"]):
            transfer_ids.add(message.get("tool_call_id"))
        elif message.get("role") in {"assistant", "ai"}:
            for call in message.get("tool_calls") or []:
                name = call.get("name") or (call.get("function") or {}).get("name")
                if isinstance(name, str) and is_transfer_tool(name) and call.get("id") is not None:
                    transfer_ids.add(call["id"])
    filtered = []
    for message in messages:
        if message.get("role") == "tool" and message.get("tool_call_id") in transfer_ids:
            continue
        if message.get("role") in {"assistant", "ai"} and message.get("tool_calls"):
            calls = message["tool_calls"]
            retained = [call for call in calls if call.get("id") is None or call["id"] not in transfer_ids]
            if len(retained) < len(calls):
                content = message.get("content")
                if retained or (isinstance(content, str) and content.strip()):
                    copy_message = copy.deepcopy(message)
                    copy_message["tool_calls"] = copy.deepcopy(retained)
                    if isinstance(content, list):
                        copy_message["content"] = [block for block in content if not (
                            isinstance(block, dict) and block.get("type") == "tool_use" and (
                                block.get("id") in transfer_ids or (
                                    isinstance(block.get("name"), str) and is_transfer_tool(block["name"]))))]
                    filtered.append(copy_message)
                continue
        filtered.append(copy.deepcopy(message))
    extra = tool_message.get("additional_kwargs") or {}
    instructions = extra.get("handoff_instructions")
    source = extra.get("handoff_source_name")
    siblings = extra.get("handoff_parallel_siblings")
    names = agent_names or {}
    group = extra.get("__handoff_group_id")
    result = {"filteredMessages": filtered,
              "instructions": instructions.strip() if isinstance(instructions, str) else None,
              "sourceAgentName": source if isinstance(source, str) else None,
              "parallelSiblings": [names.get(item, item) for item in siblings if isinstance(item, str)]
                                  if isinstance(siblings, list) else []}
    if type(group) is int and 0 <= group <= 9007199254740991:
        result["parallelGroupId"] = group
    return result
