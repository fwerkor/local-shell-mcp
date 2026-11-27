"""Chat-owned continuation of an explicitly started logical plan.

The running generation owns the continuation, not a timer or a browser tab.
A synthetic instruction is checkpointed with the model history before the
next provider request. A stopped generation never schedules another run.
"""
from __future__ import annotations

import hashlib
import json
import logging

from ..session_runtime import get_session_runtime_manager

log = logging.getLogger(__name__)
_MAX_UNCHANGED_BOUNDARIES = 3


def _binding(database, owner: str, run_id: str, *, running_only: bool = True) -> tuple[str, str] | None:
    with database.connect() as db:
        row = db.execute(
            "SELECT json_extract(r.state, '$.chatGoalSessionId'), "
            "json_extract(r.state, '$.chatGoalPlanId') FROM runs r "
            "JOIN conversations c ON c.id=r.conversation_id WHERE r.id=? AND c.owner=?"
            + (" AND r.status='running'" if running_only else ""),
            (run_id, owner),
        ).fetchone()
    return (row[0], row[1]) if row and all(isinstance(value, str) for value in row) else None


def bound_session(database, owner: str, run_id: str) -> str | None:
    binding = _binding(database, owner, run_id)
    return binding[0] if binding else None


def bind(database, owner: str, run_id: str, session_id: str, plan_id: str) -> bool:
    with database.connect() as db:
        if not db.execute(
            "SELECT 1 FROM runs r JOIN conversations c ON c.id=r.conversation_id "
            "WHERE r.id=? AND c.owner=? AND r.status='running'", (run_id, owner),
        ).fetchone():
            return False
    manager = get_session_runtime_manager()
    if not manager.adopt_chat_plan(session_id, plan_id, run_id, subject=owner):
        return False
    with database.connect() as db:
        updated = db.execute(
            "UPDATE runs SET state=json_set(state, '$.chatGoalSessionId', ?, '$.chatGoalPlanId', ?) "
            "WHERE id=? AND status='running' AND conversation_id IN "
            "(SELECT id FROM conversations WHERE owner=?)",
            (session_id, plan_id, run_id, owner),
        ).rowcount
    if not updated:
        manager.pause_chat_plan(session_id, run_id, subject=owner,
                                note="Chat generation ended before Goal activation.")
    return bool(updated)


def active_plan(database, owner: str, run_id: str) -> tuple[str, dict] | None:
    binding = _binding(database, owner, run_id)
    if not binding:
        return None
    session_id, plan_id = binding
    try:
        plan = get_session_runtime_manager().chat_plan_state(session_id, run_id, subject=owner)
    except (KeyError, ValueError, PermissionError):
        return None
    if not plan or plan["plan_id"] != plan_id:
        return None
    return session_id, plan


def pause(database, owner: str, run_id: str, note: str) -> None:
    binding = _binding(database, owner, run_id, running_only=False)
    if not binding:
        return
    try:
        get_session_runtime_manager().pause_chat_plan(binding[0], run_id, subject=owner, note=note)
    except (KeyError, ValueError, PermissionError):
        # A separately finished/deleted session is already not runnable.
        return
    except Exception:
        log.exception("Could not pause Chat Goal for %s", run_id)


def observe_result(database, owner: str, run_id: str, name: str,
                   arguments: dict, result: str) -> str:
    if name != "plan_manage" or str(arguments.get("action", "")).strip().lower() not in {"start", "resume"}:
        return result
    payload = json.loads(result)
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return result
    data = payload.get("data")
    if not isinstance(data, dict) or not data.get("goal_mode"):
        return result
    plan_id = (data.get("plan") or {}).get("plan_id")
    session_id = data.get("session_id")
    if not isinstance(session_id, str) or not isinstance(plan_id, str):
        return result
    if not bind(database, owner, run_id, session_id, plan_id):
        return json.dumps({"ok": False, "message": "Chat Goal could not be activated"})
    data["plan"] = get_session_runtime_manager().plan_state(session_id, subject=owner)
    return json.dumps(payload, ensure_ascii=False)


def continuation(database, owner: str, run_id: str, messages: list[dict]) -> dict | None:
    active = active_plan(database, owner, run_id)
    if not active:
        return None
    session_id, plan = active
    # Do not count genuine tool work as a stalled text-only loop even when
    # it has not reached the next milestone. Ignore incidental plan revisions.
    snapshot = {key: plan.get(key) for key in ("plan_id", "objective", "steps", "note")}
    snapshot["answer"] = str(messages[-1].get("content") or "").strip() if messages else ""
    signature = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    previous = []
    for message in reversed(messages):
        if message.get("role") == "tool" or message.get("tool_calls"):
            break
        if message.get("source") == "chat_goal":
            previous.append(message)
    previous.reverse()
    unchanged = 0
    for message in reversed(previous):
        if message.get("goalSignature") != signature:
            break
        unchanged += 1
    if unchanged >= _MAX_UNCHANGED_BOUNDARIES:
        pause(database, owner, run_id,
              "Repeated identical replies without plan progress or tool work. Resume after addressing the blocker.")
        return None
    steps = [{key: step.get(key) for key in ("id", "text", "status", "note")} for step in plan["steps"]]
    return {
        "role": "user",
        "source": "chat_goal",
        "goalSignature": signature,
        "content": (
            "Automatic Goal continuation (not a new user request). Continue working now, "
            "without waiting for another user message. Do not repeat completed work. "
            "Update the plan as work progresses; finish it when all steps are done, "
            "or block it with a concrete reason if further progress is impossible. "
            "Use the same logical session: " + session_id + "\n"
            + json.dumps({"objective": plan["objective"], "steps": steps, "note": plan.get("note")},
                         ensure_ascii=False)
        ),
    }
