"""JSON-facing port of LibreChat agents/validation.ts (e8f3be08).

This module validates persisted authoring configuration, independently from
machine access. Enabling a tool here never grants permission to execute it.
"""

from __future__ import annotations

import contextlib
import copy
import math
import re
from typing import Any

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_EMAIL = re.compile(r"^(?!\.)(?!.*\.\.)([A-Z0-9_'+\-\.]*)[A-Z0-9_+\-]@([A-Z0-9][A-Z0-9\-]*\.)+[A-Z]{2,}$", re.I)
_BOT_EMAIL = re.compile(r"^\d+\+[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?\[bot\]@users\.noreply\.github\.com$", re.I)
_NUMERIC = frozenset(["temperature", "top_p", "topP", "top_k", "topK", "frequency_penalty", "frequencyPenalty", "presence_penalty", "presencePenalty", "max_tokens", "maxTokens", "max_output_tokens", "maxOutputTokens", "max_context_tokens", "maxContextTokens", "fileTokenLimit", "thinking_budget", "thinkingBudget"])
_RESOURCE_KEYS = ("image_edit", "execute_code", "file_search", "context", "ocr")


def _require(value: Any, kind: type, path: str) -> Any:
    if type(value) is not kind:
        raise ValueError(f"{path} must be {kind.__name__}")
    return value


def _strings(value: Any, path: str) -> list[str]:
    return [_require(item, str, path) for item in _require(value, list, path)]


def _enum(value: Any, choices: tuple[str, ...], path: str) -> str:
    if type(value) is not str or value not in choices:
        raise ValueError(f"Invalid {path}")
    return value


def clean_edge(value: Any, *, graph: bool = False) -> dict:
    edge = _require(value, dict, "edge")
    allowed = {"from", "to", "description", "edgeType", "prompt", "excludeResults"}
    if not graph:
        allowed.add("promptKey")
    elif set(edge) - allowed:
        raise ValueError("Graph subagent edges contain unknown fields")
    result = {}
    for key in ("from", "to"):
        if key not in edge:
            raise ValueError(f"edge.{key} is required")
        item = edge[key]
        result[key] = item if type(item) is str else _strings(item, "edge." + key)
        if graph and type(item) is list and not item:
            raise ValueError("Graph subagent edge endpoints cannot be empty arrays")
    for key in ("description", "prompt", "promptKey"):
        if key not in allowed or key not in edge:
            continue
        item = _require(edge[key], str, "edge." + key)
        if graph or item != "":
            result[key] = item
    if "edgeType" in edge:
        result["edgeType"] = _enum(edge["edgeType"], ("direct",) if graph else ("handoff", "direct"), "edgeType")
    elif graph:
        raise ValueError("Graph subagent edgeType must be direct")
    if "excludeResults" in edge:
        result["excludeResults"] = _require(edge["excludeResults"], bool, "excludeResults")
    return result


def validate_graph_topology(graph: dict) -> None:
    """Original validateGraphSubagentTopology checks, in source order."""
    ids = graph["agent_ids"]
    members = set(ids)
    prefix = f'Graph subagent "{graph["type"]}"'
    def reject(message):
        raise ValueError(prefix + " " + message)
    if len(members) != len(ids):
        reject("contains duplicate member IDs.")
    reserved = {"__start__", "__end__", "messages", "agentMessages", "subagentResult"}
    for identity in ids:
        if identity in reserved or "|" in identity or ":" in identity:
            reject(f'member "{identity}" is reserved by the graph runtime.')
    if graph["entry_agent_id"] not in members or graph["result_agent_id"] not in members:
        reject("entry and result must reference configured members.")
    adjacency = {identity: set() for identity in ids}
    reverse = {identity: set() for identity in ids}
    incoming: dict[str, list[list[str]]] = {}
    directed = set()
    for edge in graph["edges"]:
        sources = edge["from"] if isinstance(edge["from"], list) else [edge["from"]]
        destinations = edge["to"] if isinstance(edge["to"], list) else [edge["to"]]
        if len(set(sources)) != len(sources) or len(set(destinations)) != len(destinations):
            reject("edge endpoints must be unique.")
        if edge.get("excludeResults") is True and not edge.get("prompt"):
            reject("cannot exclude results without an edge prompt.")
        if edge.get("prompt") and len(destinations) != 1:
            reject("prompted edges must have one destination.")
        for identity in sources + destinations:
            if identity not in members:
                reject(f'references unknown member "{identity}".')
        for destination in destinations:
            incoming.setdefault(destination, []).append(sources)
            for source in sources:
                if source == destination:
                    reject("cannot contain self-edges.")
                if (source, destination) in directed:
                    reject("contains duplicate edges.")
                directed.add((source, destination))
                adjacency[source].add(destination)
                reverse[destination].add(source)
    for destination, groups in incoming.items():
        if len(reverse[destination]) > 1 and (len(groups) != 1 or len(groups[0]) != len(reverse[destination])):
            reject(f'fan-in to "{destination}" must use one array-valued source edge.')
    roots = [identity for identity in ids if not reverse[identity]]
    sinks = [identity for identity in ids if not adjacency[identity]]
    if roots != [graph["entry_agent_id"]]:
        reject("must use entry_agent_id as its only root.")
    if sinks != [graph["result_agent_id"]]:
        reject("must use result_agent_id as its only sink.")
    remaining = {identity: len(reverse[identity]) for identity in ids}
    ready = list(roots)
    visited = 0
    while ready:
        source = ready.pop()
        visited += 1
        for destination in adjacency[source]:
            remaining[destination] -= 1
            if remaining[destination] == 0:
                ready.append(destination)
    if visited != len(members):
        reject("must be acyclic and fully connected.")
    chain = all(len(adjacency[identity]) <= 1 and len(reverse[identity]) <= 1 for identity in ids)
    if not chain and any(edge.get("prompt") and (edge["to"][0] if isinstance(edge["to"], list) else edge["to"]) != graph["result_agent_id"] for edge in graph["edges"]):
        reject("prompts in a branched graph must target result_agent_id.")


def clean_subagents(value: Any, *, max_subagents: int = 10) -> dict:
    obj = _require(value, dict, "subagents")
    result = {key: _require(obj[key], bool, "subagents." + key)
              for key in ("enabled", "allowSelf", "shareFiles") if key in obj}
    if "agent_ids" in obj:
        result["agent_ids"] = _strings(obj["agent_ids"], "subagents.agent_ids")
        if len(result["agent_ids"]) > max_subagents:
            raise ValueError(f"agent_ids must contain at most {max_subagents} item(s)")
    if "graphs" in obj:
        graphs = _require(obj["graphs"], list, "subagents.graphs")
        if len(graphs) > max_subagents:
            raise ValueError(f"graphs must contain at most {max_subagents} item(s)")
        result["graphs"] = []
        for item in graphs:
            item = _require(item, dict, "graph")
            graph = {}
            for key in ("type", "name", "description"):
                text = _require(item.get(key), str, "graph." + key).strip()
                if not text:
                    raise ValueError("Graph " + key + " cannot be empty")
                graph[key] = text
            graph["agent_ids"] = _strings(item.get("agent_ids"), "graph.agent_ids")
            if not 1 <= len(graph["agent_ids"]) <= 32:
                raise ValueError("Graph subagents require 1–32 members")
            graph["edges"] = [clean_edge(edge, graph=True) for edge in _require(item.get("edges"), list, "graph.edges")]
            for key in ("entry_agent_id", "result_agent_id"):
                graph[key] = _require(item.get(key), str, "graph." + key)
            validate_graph_topology(graph)
            result["graphs"].append(graph)
    types = set(result.get("agent_ids", []))
    configured = set(types)
    if result.get("allowSelf") is not False:
        types.add("self")
    for graph in result.get("graphs", []):
        if graph["type"] in types:
            raise ValueError("Graph subagent types must be unique across all spawn targets")
        types.add(graph["type"])
        configured.update(graph["agent_ids"])
    if len(configured) > 50:
        raise ValueError("Subagent configuration exceeds the maximum of 50 unique agents")
    return result


def clean_agent_config(payload: Any, *, create: bool = False) -> dict:
    obj = _require(payload, dict, "Agent configuration")
    result = {}
    nullable_strings = {"name", "description", "instructions", "model"}
    strings = {"provider", "artifacts", "category", "code_environment_id", "code_workspace_id"}
    arrays = {"tools", "skills", "agent_ids", "conversation_starters"}
    booleans = {"skills_enabled", "skill_authoring_enabled", "end_after_tools", "hide_sequential_outputs", "stateful_code_sessions"}
    enums = {"skills_scope": ("all", "selected", "none"), "memory_scope": ("user", "agent"),
             "stateful_code_environment": ("user", "agent-user", "conversation"),
             "repositoryInstructions": ("prefer", "defer", "off")}
    for key in nullable_strings | strings | arrays | booleans | set(enums):
        if key not in obj:
            continue
        value = obj[key]
        if value is None and (key in nullable_strings or key == "code_environment_id" and not create):
            result[key] = None
        elif key in nullable_strings | strings:
            result[key] = _require(value, str, key)
        elif key in arrays:
            result[key] = _strings(value, key)
        elif key in booleans:
            result[key] = _require(value, bool, key)
        else:
            result[key] = _enum(value, enums[key], key)
    for key in ("code_environment_id", "code_workspace_id"):
        if key in result and result[key] is not None and not (key == "code_workspace_id" and result[key] == "") and not _ID.fullmatch(result[key]):
            raise ValueError("Invalid " + key)
    if "recursion_limit" in obj:
        number = obj["recursion_limit"]
        if type(number) not in (int, float) or not math.isfinite(number):
            raise ValueError("recursion_limit must be a number")
        result["recursion_limit"] = number
    if "avatar" in obj:
        avatar = obj["avatar"]
        result["avatar"] = None if avatar is None else {key: _require(_require(avatar, dict, "avatar").get(key), str, "avatar." + key) for key in ("filepath", "source")}
    if "model_parameters" in obj:
        result["model_parameters"] = copy.deepcopy(_require(obj["model_parameters"], dict, "model_parameters"))
    if "edges" in obj:
        result["edges"] = [clean_edge(edge) for edge in _require(obj["edges"], list, "edges")]
    if "subagents" in obj:
        result["subagents"] = clean_subagents(obj["subagents"])
    if "tool_options" in obj:
        result["tool_options"] = {}
        for tool, options in _require(obj["tool_options"], dict, "tool_options").items():
            _require(options, dict, "tool_options." + tool)
            cleaned = {key: _require(options[key], bool, key) for key in ("defer_loading", "run_in_background", "describe_intent") if key in options}
            if "allowed_callers" in options:
                cleaned["allowed_callers"] = [_enum(item, ("direct", "code_execution"), "allowed_callers") for item in _require(options["allowed_callers"], list, "allowed_callers")]
            result["tool_options"][tool] = cleaned
    if "tool_resources" in obj:
        resources = _require(obj["tool_resources"], dict, "tool_resources")
        result["tool_resources"] = {}
        for key in _RESOURCE_KEYS:
            if key in resources:
                resource = _require(resources[key], dict, "tool_resources." + key)
                result["tool_resources"][key] = {field: _strings(resource[field], field) for field in ("file_ids", "vector_store_ids") if field in resource and (field == "file_ids" or key == "file_search")}
    if "support_contact" in obj:
        contact = _require(obj["support_contact"], dict, "support_contact")
        result["support_contact"] = {key: _require(contact[key], str, "support_contact." + key) for key in ("name", "email") if key in contact}
        email = result["support_contact"].get("email")
        if email and not _EMAIL.fullmatch(email):
            raise ValueError("Invalid support contact email")
    if "git_identity" in obj:
        identity = obj["git_identity"]
        if identity is None and not create:
            result["git_identity"] = None
        else:
            identity = _require(identity, dict, "git_identity")
            cleaned = {key: _require(identity.get(key), str, "git_identity." + key).strip() for key in ("name", "email")}
            if not 1 <= len(cleaned["name"].encode("utf-16-le")) // 2 <= 128 or len(cleaned["email"].encode("utf-16-le")) // 2 > 254 or any(char in cleaned["name"] + cleaned["email"] for char in "\0\r\n") or not (_EMAIL.fullmatch(cleaned["email"]) or _BOT_EMAIL.fullmatch(cleaned["email"])):
                raise ValueError("Invalid git identity")
            result["git_identity"] = cleaned
    if create:
        if "provider" not in result or "model" not in result:
            raise ValueError("Agent provider and model are required")
        result.setdefault("tools", [])
    return result


def sanitize_model_parameters(params: dict) -> dict:
    """Port of agents/parameters.ts; numeric placeholders never reach models."""
    result = {}
    for key, value in params.items():
        if key not in _NUMERIC:
            result[key] = value
            continue
        number = None
        if type(value) in (int, float):
            number = value
        elif type(value) is str and value.strip():
            text = value.strip()
            with contextlib.suppress(ValueError):
                number = int(text, 0) if text.lower().startswith(("0x", "0o", "0b")) else float(text)
        if number is not None and math.isfinite(number):
            result[key] = number
    return result


def replace_agent_references(config: dict, previous: str, next_id: str) -> dict:
    """Creation/duplicate rewrites from edges.ts and v1.js graph helpers."""
    result = copy.deepcopy(config)
    def replace_endpoint(value):
        return [next_id if item == previous else item for item in value] if isinstance(value, list) else next_id if value == previous else value
    for edge in result.get("edges", []):
        edge["from"] = replace_endpoint(edge["from"])
    for graph in result.get("subagents", {}).get("graphs", []):
        graph["agent_ids"] = replace_endpoint(graph["agent_ids"])
        graph["entry_agent_id"] = replace_endpoint(graph["entry_agent_id"])
        graph["result_agent_id"] = replace_endpoint(graph["result_agent_id"])
        for edge in graph["edges"]:
            edge["from"] = replace_endpoint(edge["from"])
            edge["to"] = replace_endpoint(edge["to"])
        validate_graph_topology(graph)
    return result
