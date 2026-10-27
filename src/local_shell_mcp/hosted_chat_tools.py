"""Budget-aware tool discovery for OpenAI-compatible Hosted Chat models."""

from __future__ import annotations

import re
from typing import Any

from .hosted_chat_context import CONTEXT_RATIO, estimate_tokens

TOOL_SEARCH_NAME = "hosted_chat_search_tools"
TOOL_SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": TOOL_SEARCH_NAME,
        "description": (
            "Find available LSM tools by purpose or name when the context window "
            "cannot fit all tool definitions. Search before calling a tool that "
            "is not listed; matching tools become callable in the next step."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Task or tool name to search for, e.g. 'run shell command'",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}


def choose_tool_schemas(
    available: list[dict], messages: list[dict], context_size: int,
    preferred: list[str],
) -> list[dict]:
    """Advertise all tools when affordable, otherwise discovery and selected tools.

    Leave a substantial portion of the context for conversation and output.
    Each candidate is checked against the exact estimator used by compaction.
    """
    budget = int(context_size * CONTEXT_RATIO)
    if estimate_tokens({"messages": messages, "tools": available}) <= budget:
        return available
    selected = [TOOL_SEARCH_SCHEMA]
    schema_budget = int(budget * 0.70)
    by_name = {s["function"]["name"]: s for s in available}
    for name in dict.fromkeys(preferred):
        schema = by_name.get(name)
        if schema is None:
            continue
        candidate = [*selected, schema]
        if (estimate_tokens({"tools": candidate}) <= schema_budget
                and estimate_tokens({"messages": messages, "tools": candidate}) <= budget):
            selected = candidate
    return selected


def discover_tools(
    query: str, available: list[dict], context_size: int,
    previous: list[str] | None = None, messages: list[dict] | None = None,
) -> tuple[dict, list[str]]:
    """Accumulate only authorized discoveries fitting a shared schema and message budget."""
    if not isinstance(query, str) or not query.strip() or len(query) > 256:
        raise ValueError("Tool search requires a query of at most 256 characters")
    terms = set(re.findall(r"[a-z0-9]+", query.lower())) - {
        "the", "and", "for", "with", "tool", "tools", "please", "find", "use", "to",
    }
    # A query for a full tool name also matches underscores in its name.
    def rank(schema: dict) -> tuple[int, str]:
        fn = schema["function"]
        name = fn["name"].lower()
        description = fn.get("description", "").lower()
        words = set(re.findall(r"[a-z0-9]+", name))
        score = sum(5 if term in words else 2 if term in name else 1 if term in description else 0
                    for term in terms)
        if query.lower().strip() == name:
            score += 100
        return score, name

    matches = sorted((s for s in available if rank(s)[0] > 0),
                     key=lambda s: (-rank(s)[0], rank(s)[1]))
    selected = [TOOL_SEARCH_SCHEMA]
    retained: list[str] = []
    by_name = {s["function"]["name"]: s for s in available}
    schema_budget = int(context_size * CONTEXT_RATIO * 0.70)
    total_budget = int(context_size * CONTEXT_RATIO)
    for name in dict.fromkeys(previous or []):
        schema = by_name.get(name)
        if schema is None:
            continue
        candidate = [*selected, schema]
        if estimate_tokens({"tools": candidate}) <= schema_budget:
            selected = candidate
            retained.append(name)
    found: list[dict[str, Any]] = []
    for schema in matches:
        if len(found) >= 4:
            break
        fn = schema["function"]
        if fn["name"] in retained:
            continue
        item = {"name": fn["name"], "description": fn.get("description", "")[:160]}
        candidate = [*selected, schema]
        if estimate_tokens({"tools": candidate}) > schema_budget:
            continue
        if messages is not None:
            preview = {"role": "tool", "tool_call_id": "discovery", "content":
                       str({"matches": [*found, item]})}
            if estimate_tokens({"messages": [*messages, preview], "tools": candidate}) > total_budget:
                continue
        selected = candidate
        found.append(item)
    return {
        "matches": found,
        "note": ("These tools are available in the next model step. "
                 "Search again for other capabilities if needed." if found else
                 "No matching tool fits the available schema budget; try a narrower query or larger context window."),
    }, [*retained, *(item["name"] for item in found)]
