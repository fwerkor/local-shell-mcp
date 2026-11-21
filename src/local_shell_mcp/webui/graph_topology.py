"""SDK MultiAgentGraph source construction, validating graph owner and edges.

Mirrors agents 4.0.1 MultiAgentGraph constructor; execution uses official Python
LangGraph StateGraph via graph_runtime, not an independently named scheduler.
"""
from __future__ import annotations

import copy
from typing import Any


def endpoints(edge: dict, key: str) -> list[str]:
    value = edge.get(key)
    return value if isinstance(value, list) else [value]


def is_direct_edge(edge: dict) -> bool:
    """Exact categorizeEdges default: only a single-source fan-out is direct."""
    return edge.get("edgeType") == "direct" or (
        edge.get("edgeType") is None and edge.get("condition") is None
        and len(endpoints(edge, "from")) == 1 and len(endpoints(edge, "to")) > 1
    )


def _safe_integer(value: Any) -> bool:
    # JSON has one numeric type in JS; integral floating-point values count too.
    return type(value) in {int, float} and abs(value) <= 9007199254740991 and value == int(value)


class GraphTopology:
    """Ordered source construction analysis; no model or machine side effects."""

    def __init__(self, agent_ids: list[str], edges: list[dict], *, entry_agent_id: str | None = None,
                 result_agent_id: str | None = None, member_recursion_limit: int | None = None,
                 max_handoffs: int | None = None):
        self.agent_ids = list(dict.fromkeys(agent_ids))
        if not self.agent_ids:
            raise ValueError("At least one agent configuration is required")
        self.edges = copy.deepcopy(edges)
        self.direct_edges: list[dict] = []
        self.handoff_edges: list[dict] = []
        self.handoff_sources: set[str] = set()
        self.parallel_groups: dict[str, int] = {}
        self.reachable_agent_ids: list[str] | None = None
        self.default_agent_id = self.agent_ids[0] if self.agent_ids else None
        if member_recursion_limit is not None and (
            not _safe_integer(member_recursion_limit) or member_recursion_limit <= 0
        ):
            raise ValueError("MultiAgentGraph: memberRecursionLimit must be a positive safe integer.")
        if result_agent_id is not None and result_agent_id not in self.agent_ids:
            raise ValueError(f'MultiAgentGraph: resultAgentId "{result_agent_id}" is not present in agents.')
        self._validate_edge_agents()
        for edge in self.edges:
            if is_direct_edge(edge):
                self.direct_edges.append(edge)
            else:
                self.handoff_edges.append(edge)
                self.handoff_sources.update(endpoints(edge, "from"))
        self._validate_command_routed_direct_edges()
        incoming = {ident for edge in self.edges for ident in endpoints(edge, "to")}
        self.starting_nodes = [ident for ident in self.agent_ids if ident not in incoming]
        if not self.starting_nodes and self.agent_ids:
            self.starting_nodes = self.agent_ids[:1]
        self._compute_parallel_capability()
        if entry_agent_id is not None:
            if entry_agent_id not in self.agent_ids:
                raise ValueError(f'MultiAgentGraph: unknown entryAgentId "{entry_agent_id}"')
            self.starting_nodes = [entry_agent_id]
            self.default_agent_id = entry_agent_id
            # Upstream keeps existing group entries on this second analysis.
            self._compute_parallel_capability()
            self.reachable_agent_ids = self._resolve_entry_reachability(entry_agent_id)
        if max_handoffs is not None and (
            not _safe_integer(max_handoffs) or max_handoffs < 0
        ):
            raise ValueError("MultiAgentGraph: maxHandoffs must be a non-negative safe integer")
        destinations: dict[str, set[str]] = {}
        for edge in self.direct_edges:
            if edge.get("handoffScope") is not None:
                raise ValueError("handoffScope is only valid on handoff edges")
            for source in endpoints(edge, "from"):
                destinations.setdefault(source, set()).update(endpoints(edge, "to"))
        self.routing_parallel = len(self.starting_nodes) > 1 or any(len(values) > 1 for values in destinations.values())
        self._validate_handoff_scopes()

    def _validate_edge_agents(self) -> None:
        unknown = list(dict.fromkeys(ident for edge in self.edges for key in ("from", "to")
                                    for ident in endpoints(edge, key) if isinstance(ident, str) and ident not in self.agent_ids))
        if unknown:
            missing = ", ".join('"' + ident + '"' for ident in unknown)
            raise ValueError("MultiAgentGraph: edges reference agent(s) not present in agents: [" + missing + "]. "
                             "Ensure every agent referenced by an edge is also included in the `agents` array, "
                             "or filter orphaned edges before constructing the graph.")

    def _validate_command_routed_direct_edges(self) -> None:
        groups: dict[str, dict] = {}
        for edge in self.direct_edges:
            sources = endpoints(edge, "from")
            command_source = next((source for source in sources if source in self.handoff_sources), None)
            if command_source is not None and len(sources) > 1:
                raise ValueError("MultiAgentGraph: grouped direct edge cannot include command-routed "
                                 f'source "{command_source}". Split handoff routing from all-of fan-in.')
            for destination in endpoints(edge, "to"):
                group = groups.setdefault(destination, {"has_prompt": False, "command_source": None})
                group["has_prompt"] |= edge.get("prompt") not in (None, "")
                if group["command_source"] is None:
                    group["command_source"] = command_source
        for group in groups.values():
            if group["has_prompt"] and group["command_source"] is not None:
                raise ValueError("MultiAgentGraph: prompted direct edge cannot include command-routed "
                                 f'source "{group["command_source"]}". Move the prompt into the routed node.')

    def _compute_parallel_capability(self) -> None:
        counter = 1
        if len(self.starting_nodes) > 1:
            for ident in self.starting_nodes:
                self.parallel_groups[ident] = counter
            counter += 1
        visited = set()
        queue = list(self.starting_nodes)
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            for edge in self.direct_edges:
                if current not in endpoints(edge, "from"):
                    continue
                targets = endpoints(edge, "to")
                if len(targets) > 1:
                    for target in targets:
                        self.parallel_groups.setdefault(target, counter)
                        if target not in visited:
                            queue.append(target)
                    counter += 1
                else:
                    queue.extend(target for target in targets if target not in visited)
            for edge in self.handoff_edges:
                if current in endpoints(edge, "from"):
                    queue.extend(target for target in endpoints(edge, "to") if target not in visited)

    def _resolve_entry_reachability(self, entry: str) -> list[str]:
        reached = [entry]
        direct_ids = {id(edge) for edge in self.direct_edges}
        outgoing: dict[str, list[int]] = {}
        remaining = {}
        for index, edge in enumerate(self.edges):
            sources = list(dict.fromkeys(endpoints(edge, "from")))
            remaining[index] = len(sources) if id(edge) in direct_ids else 1
            for source in sources:
                outgoing.setdefault(source, []).append(index)
        for current in reached:
            for index in outgoing.get(current, []):
                pending = remaining[index]
                if not pending:
                    continue
                remaining[index] = pending - 1
                if pending > 1:
                    continue
                for target in endpoints(self.edges[index], "to"):
                    if target not in reached:
                        reached.append(target)
        for edge in self.direct_edges:
            sources = endpoints(edge, "from")
            if any(source in reached for source in sources) and not all(source in reached for source in sources):
                raise ValueError("entryAgentId cannot satisfy a grouped direct edge prerequisite")
        return reached

    def _validate_handoff_scopes(self) -> None:
        scopes = {}
        for edge in self.handoff_edges:
            scope = "turn" if edge.get("handoffScope") is None else edge["handoffScope"]
            if scope not in {"turn", "conversation"}:
                raise ValueError("Invalid handoffScope")
            targets = ["conditional_transfer"] if edge.get("condition") is not None else endpoints(edge, "to")
            for source in endpoints(edge, "from"):
                for target in targets:
                    key = source, target
                    if key in scopes and scopes[key] != scope:
                        raise ValueError("Conflicting handoffScope for the same transfer tool")
                    scopes[key] = scope

    def summary(self) -> dict:
        return {"starts": self.starting_nodes, "default": self.default_agent_id,
                "direct": self.direct_edges, "handoff": self.handoff_edges,
                "parallelGroups": self.parallel_groups, "reachable": self.reachable_agent_ids,
                "parallel": self.routing_parallel}


def admit_agent_graph(owner: str, agent: dict | None, repository: Any) -> GraphTopology | None:
    """Validate all owned members before allowing a StateGraph execution."""
    if not agent or not agent.get("edges"):
        return None
    identities = list(dict.fromkeys([agent["id"], *(agent.get("graphAgentIds") or [])]))
    if any(not isinstance(identity, str) or not identity for identity in identities):
        raise ValueError("Graph Agent identifiers must be non-empty strings")
    for edge in agent["edges"]:
        for key in ("from", "to"):
            for ident in endpoints(edge, key):
                if ident not in identities:
                    identities.append(ident)
    for ident in identities:
        if repository.get(owner, ident) is None:
            raise PermissionError("Agent graph member is not owned by the current principal")
    topology = GraphTopology(identities, agent["edges"],
                             entry_agent_id=agent.get("entryAgentId"),
                             result_agent_id=agent.get("resultAgentId"),
                             max_handoffs=agent.get("maxHandoffs"))
    return topology
