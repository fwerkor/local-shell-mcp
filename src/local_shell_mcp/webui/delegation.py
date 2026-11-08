"""Bounded, owner-scoped Agent delegation and handoff inside the Python runtime.

A parent Agent must explicitly allowlist subagent IDs in its configuration.
Subagents receive only a bounded task and their own instructions; they have
no native shell/MCP tools or inherited machine write permissions by default.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from typing import Any

from .providers import ModelToolCall, provider_config, stream_model
from .storage import _now


def _agent_ids(agent: dict | None) -> set[str]:
    if not agent:
        return set()
    raw = agent.get("subagents")
    if not isinstance(raw, list):
        return set()
    names: set[str] = set()
    for item in raw[:32]:
        identity = item if isinstance(item, str) else item.get("agent_id") if isinstance(item, dict) else None
        if isinstance(identity, str) and identity.startswith("agent_") and len(identity) <= 128:
            names.add(identity)
    return names


def delegation_tools(agent: dict | None) -> list[dict]:
    if not _agent_ids(agent):
        return []
    parameters = {
        "type": "object",
        "properties": {
            "agent_id": {"type": "string", "description": "ID of an explicitly configured subagent"},
            "task": {"type": "string", "description": "A focused task of at most 8 KiB"},
        },
        "required": ["agent_id", "task"],
        "additionalProperties": False,
    }
    return [
        {"type": "function", "function": {
            "name": "delegate_agent", "description": "Delegate one bounded task to a configured subagent.",
            "parameters": parameters,
        }},
        {"type": "function", "function": {
            "name": "handoff_agent", "description": "Transfer the current response to a configured subagent.",
            "parameters": parameters,
        }},
    ]


async def run_subagent(owner: str, generation: Any, parent: dict | None,
                       call: ModelToolCall, database: Any) -> str:
    from .agents import AgentRepository

    if call.name not in {"delegate_agent", "handoff_agent"}:
        raise ValueError("Unknown Agent delegation tool")
    args = call.arguments
    if set(args) != {"agent_id", "task"}:
        raise ValueError("Subagent identity and task are required")
    child_id = args["agent_id"]
    task = args["task"]
    if not isinstance(child_id, str) or child_id not in _agent_ids(parent):
        raise PermissionError("Subagent is not approved by the parent Agent")
    if not isinstance(task, str) or not task.strip() or len(task.encode("utf-8")) > 8192:
        raise ValueError("Subagent task must be 1–8192 UTF-8 bytes")
    child = AgentRepository(database).get(owner, child_id)
    if child is None:
        raise PermissionError("Subagent is not owned by the current principal")
    if parent is not None and child_id == parent.get("id"):
        raise PermissionError("Agent cannot delegate to itself")
    ident = "delegate_" + secrets.token_hex(12)
    kind = "handoff" if call.name == "handoff_agent" else "delegate"
    now = _now()
    with database.connect() as db:
        db.execute("INSERT INTO agent_delegations(id,run_id,agent_id,kind,task,status,created_at,updated_at) "
                   "VALUES(?,?,?,?,?,?,?,?)",
                   (ident, generation.run_id, child_id, kind, task, "running", now, now))
    try:
        profile = provider_config(child.get("provider") or "openai", child.get("model"))
        messages = []
        instructions = child.get("instructions")
        if instructions:
            messages.append({"role": "system", "content": str(instructions)[:80000]})
        messages.append({"role": "user", "content": task})
        responses: list[str] = []
        total = 0
        async def consume():
            nonlocal total
            async for chunk in stream_model(profile, messages, max_tokens=2048):
                if not isinstance(chunk, str):
                    continue
                total += len(chunk.encode("utf-8"))
                if total > 32768:
                    raise ValueError("Subagent output limit exceeded")
                responses.append(chunk)
        await asyncio.wait_for(consume(), timeout=90)
        output = "".join(responses)
        with database.connect() as db:
            db.execute("UPDATE agent_delegations SET status='complete',result=?,updated_at=? WHERE id=?",
                       (output, _now(), ident))
        return json.dumps({"agent_id": child_id, "task_id": ident, "output": output}, ensure_ascii=False)
    except asyncio.CancelledError:
        with database.connect() as db:
            db.execute("UPDATE agent_delegations SET status='interrupted',updated_at=? WHERE id=?",
                       (_now(), ident))
        raise
    except Exception:
        with database.connect() as db:
            db.execute("UPDATE agent_delegations SET status='error',updated_at=? WHERE id=?", (_now(), ident))
        raise
