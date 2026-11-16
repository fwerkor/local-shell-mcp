"""Source-pinned LibreChat Agent Trigger detached-action evidence and recovery.

Source: packages/api/src/agents/triggers/{detachedAction,expectedAction}.ts.
Reservation is atomic with an existing native background task. The executor is
always the existing audited LSM tool path, never a second event worker.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

_MAX_JS_SAFE = 2**53 - 1
_HEX_64 = re.compile(r"^[a-f0-9]{64}$")
_RECOVERY_RESERVED_MS = 60_000
_RECOVERY_RUNNING_MS = 30 * 60_000
_EVENT_TYPE = "librechat.event_actor.detached_completion"
_EVENT_SOURCE = "librechat-event-actor"
_INPUT = "Resume the suspended event actor with the detached tool completion supplied by the host."


def _safe_integer(value: Any) -> bool:
    # JSON is IEEE-754 on the original Node runtime: integral floats are safe.
    return (type(value) in (int, float) and math.isfinite(value) and
            0 <= value <= _MAX_JS_SAFE and int(value) == value)


def _utf16_length(value: str) -> int:
    # JS String.length counts UTF-16 code units, not Python code points.
    return len(value.encode("utf-16-le", errors="surrogatepass")) // 2


def parse_terminal_evidence(value: Any) -> dict | None:
    """Exact field bounds from detachedAction.ts:parseAgentEventDetachedTerminalEvidence."""
    if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
        return None
    for name, maximum in (("deliveryKey", 128), ("taskId", 128)):
        if not isinstance(value.get(name), str) or not 1 <= _utf16_length(value[name]) <= maximum:
            return None
    if not isinstance(value.get("idempotencyKey"), str) or not _HEX_64.fullmatch(value["idempotencyKey"]):
        return None
    for name in ("generationCreatedAt", "observedAt"):
        if not _safe_integer(value.get(name)):
            return None
    status = value.get("status")
    if status not in {"succeeded", "failed", "cancelled"}:
        return None
    result, error = value.get("result"), value.get("error")
    if status == "succeeded":
        if not isinstance(result, str) or error is not None or _utf16_length(result) > 32768:
            return None
    elif not isinstance(error, str) or result is not None or _utf16_length(error) > 2048:
        return None
    return {name: value[name] for name in
            ("version", "deliveryKey", "generationCreatedAt", "taskId", "idempotencyKey",
             "status", "observedAt", "result" if status == "succeeded" else "error")}


def parse_completion_projection(value: Any) -> dict | None:
    """Exact source detachedAction.ts:parseAgentEventActorDetachedCompletion."""
    if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
        return None
    for name in ("invocationId", "taskId"):
        if not isinstance(value.get(name), str) or not 1 <= _utf16_length(value[name]) <= 128:
            return None
    for name in ("generationCreatedAt", "wakeGenerationCreatedAt"):
        if not _safe_integer(value.get(name)):
            return None
    if not isinstance(value.get("idempotencyKey"), str) or not _HEX_64.fullmatch(value["idempotencyKey"]):
        return None
    return {name: value[name] for name in ("version", "invocationId", "generationCreatedAt",
                                            "wakeGenerationCreatedAt", "taskId", "idempotencyKey")}


def reserve(db: Any, *, owner: str, run_id: str, lease: tuple[str, str],
            task_id: str, tool_name: str, tool_call_id: str,
            arguments: dict, argument_hash: str, at: int) -> bool:
    """Reserve source-matching expectedAction before an irreversible native launch.

    Caller MUST already hold BEGIN IMMEDIATE and inserts the generic native
    task into the same SQLite transaction. All event/worker/source bindings
    are independently rechecked here, not inferred from model arguments.
    """
    from .event_triggers import matches_expected_action
    delivery_id, token = lease
    row = db.execute(
        "SELECT e.envelope,e.mode,e.owner FROM agent_event_deliveries e "
        "JOIN agent_event_source_keys k ON k.id=e.source_key_id AND k.owner=e.owner "
        "WHERE e.id=? AND e.owner=? AND e.run_id=? AND e.mode='continue' "
        "AND e.status='leased' AND e.lease_owner=? AND e.lease_until>? "
        "AND k.revoked_at IS NULL AND (k.expires_at IS NULL OR k.expires_at>?)",
        (delivery_id, owner, run_id, token, at, at),
    ).fetchone()
    if row is None:
        raise PermissionError("Detached Event Actor source lease was revoked")
    envelope = json.loads(row["envelope"])
    expected = envelope.get("expectedAction")
    if expected is None or not matches_expected_action(
        {"toolName": tool_name, "toolCallId": tool_call_id, "arguments": arguments}, expected
    ):
        return False
    action_idempotency = hashlib.sha256(
        ("librechat:event-actor-detached:v1\0" + delivery_id + "\0" + tool_call_id).encode()
    ).hexdigest()
    previous = db.execute("SELECT * FROM agent_event_detached_actions WHERE delivery_id=?",
                          (delivery_id,)).fetchone()
    if previous is not None:
        if (previous["owner"] != owner or previous["run_id"] != run_id or
                previous["task_id"] != task_id or previous["tool_name"] != tool_name or
                previous["tool_call_id"] != tool_call_id or previous["argument_hash"] != argument_hash):
            raise PermissionError("A different detached action already owns this Event Actor invocation")
        return True
    db.execute("INSERT INTO agent_event_detached_actions "
               "(delivery_id,owner,run_id,task_id,tool_name,tool_call_id,argument_hash,"
               "idempotency_key,status,recovery_after,created_at,updated_at) "
               "VALUES(?,?,?,?,?,?,?,?,'reserved',?,?,?)",
               (delivery_id, owner, run_id, task_id, tool_name, tool_call_id,
                argument_hash, action_idempotency, at + _RECOVERY_RESERVED_MS, at, at))
    return True


def renew_source_lease(db: Any, owner: str, run_id: str, lease: tuple[str, str], at: int) -> bool:
    """A detached tool keeps its original source lease alive only while valid."""
    delivery_id, token = lease
    return db.execute(
        "UPDATE agent_event_deliveries SET lease_until=?,updated_at=? WHERE id=? "
        "AND owner=? AND run_id=? AND status='leased' AND lease_owner=? "
        "AND lease_until>? AND EXISTS(SELECT 1 FROM agent_event_source_keys k "
        "WHERE k.id=agent_event_deliveries.source_key_id AND k.owner=? "
        "AND k.revoked_at IS NULL AND (k.expires_at IS NULL OR k.expires_at>?))",
        (at + 120_000, at, delivery_id, owner, run_id, token, at, owner, at),
    ).rowcount == 1


def mark_running(db: Any, task_id: str, owner: str, at: int) -> bool:
    """A detached action cannot be launched again after an uncertain handoff."""
    return db.execute(
        "UPDATE agent_event_detached_actions SET status='running',recovery_after=?,updated_at=? "
        "WHERE task_id=? AND owner=? AND status='reserved'",
        (at + _RECOVERY_RUNNING_MS, at, task_id, owner),
    ).rowcount == 1


def settle(db: Any, task_id: str, owner: str, status: str,
           result: str | None, error: str | None, at: int) -> None:
    """Commit terminal tool outcome and evidence together; safe under retries."""
    row = db.execute("SELECT a.*,r.state FROM agent_event_detached_actions a "
                     "JOIN runs r ON r.id=a.run_id WHERE a.task_id=? AND a.owner=?",
                     (task_id, owner)).fetchone()
    if row is None:
        return
    if status == "completed":
        outcome = "succeeded"
    elif status == "error":
        outcome = "failed"
    elif status == "cancelled":
        outcome = "cancelled"
    else:
        db.execute("UPDATE agent_event_detached_actions SET status='launch_indeterminate',"
                   "recovery_after=?,updated_at=? WHERE task_id=? AND status IN ('reserved','running')",
                   (at, at, task_id))
        return
    evidence = {"version": 1, "deliveryKey": row["delivery_id"],
                "generationCreatedAt": json.loads(row["state"]).get("generationCreatedAt"),
                "taskId": task_id, "idempotencyKey": row["idempotency_key"],
                "status": outcome, "observedAt": at}
    if outcome == "succeeded":
        evidence["result"] = (result or "")[:32768]
    else:
        evidence["error"] = (error or "Detached action failed")[:2048]
    if parse_terminal_evidence(evidence) is None:
        raise ValueError("Detached Event Actor host terminal evidence has an invalid shape")
    db.execute("UPDATE agent_event_detached_actions SET status=?,evidence=?,observed_at=?,"
               "updated_at=? WHERE task_id=? AND owner=? AND status IN ('reserved','running')",
               (outcome, json.dumps(evidence, separators=(",", ":"), sort_keys=True),
                at, at, task_id, owner))


def recover_expired(db: Any, at: int) -> int:
    """Fail closed on unknown launch; never resubmit the external tool."""
    result = db.execute(
        "UPDATE agent_event_detached_actions SET status='launch_indeterminate',"
        "updated_at=? WHERE status IN ('reserved','running') AND recovery_after<=?",
        (at, at),
    )
    return result.rowcount
