"""Durable source-compatible child completion continuation on the existing AgentRunner.

Source: LibreChat v0.8.8 packages/api/src/agents/{subagentDelivery,
subagentCompletionWakeup,subagentThreads}.ts. SQLite owns pre-admission,
ordered parent branch arbitration and exactly one result claim. We do not
implement a second model executor or trust user/model-supplied event envelopes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
import uuid
from collections.abc import Callable
from typing import Any

from .generations import GenerationConflict, GenerationStore

log = logging.getLogger(__name__)
_SOURCE = "subagent-completion"
SOURCE_WAKEUP_GUIDANCE = (
    "Automatic completion delivery is enabled for this subagent task. Continue independent work "
    "if available; otherwise end this turn and the host will resume you when the task finishes. "
    "Do not repeatedly poll an unchanged running task. Use check_background_task only for "
    "explicit status or control, or as a fallback if automatic delivery is unavailable."
)
_DELAY_MS = 250
_LEASE_MS = 30_000
_WORKERS: dict[str, asyncio.Task] = {}
_PROCESS = secrets.token_hex(12)


def _now() -> int:
    return int(time.time() * 1000)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def register_wakeup(db: Any, *, task_id: str, owner: str, conversation_id: str,
                    parent_run_id: str, agent_id: str, thread_id: str,
                    subagent_type: str, created_at: int) -> None:
    """Called under the child task's INSERT transaction, before provider work."""
    setting = db.execute("SELECT value FROM settings WHERE owner=? AND key=?",
                         (owner, "backgroundTasks.completionWakeups")).fetchone()
    if setting is not None and json.loads(setting["value"]) is False:
        return
    parent = db.execute("SELECT state FROM runs WHERE id=? AND conversation_id=?",
                        (parent_run_id, conversation_id)).fetchone()
    if parent is None:
        raise PermissionError("A completion wakeup requires a trusted parent run")
    response_id = json.loads(parent["state"]).get("responseMessageId")
    if not isinstance(response_id, str) or not response_id:
        return
    envelope = {
        "version": 1, "mode": "continue", "requestId": str(uuid.uuid4()),
        "deliveryId": task_id, "receivedAt": created_at,
        "principal": {"userId": owner},
        "event": {"id": task_id, "type": "subagent.completion",
                  "occurredAt": created_at,
                  "source": {"id": _SOURCE, "type": "internal"},
                  "payload": {"taskId": task_id, "threadId": thread_id,
                              "subagentType": subagent_type}},
        "target": {"agentId": agent_id, "conversationId": conversation_id,
                   "parentMessageId": response_id},
        "input": "A detached subagent task is waiting to complete.",
    }
    db.execute(
        "INSERT INTO subagent_wakeups(task_id,owner,parent_conversation_id,parent_run_id,"
        "parent_agent_id,envelope,status,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,'pending',?,?)",
        (task_id, owner, conversation_id, parent_run_id, agent_id,
         _json(envelope), created_at, created_at),
    )


def _latest_branch(db: Any, conversation_id: str, anchor: str) -> str | None:
    """Find newest persisted assistant descendant of the source parent reply."""
    messages = db.execute(
        "SELECT id,parent_id,role,created_at FROM messages WHERE conversation_id=? "
        "ORDER BY created_at,id", (conversation_id,),
    ).fetchall()
    by_id = {row["id"]: row for row in messages}
    if anchor not in by_id or by_id[anchor]["role"] != "assistant":
        return None
    descendants: list[Any] = []
    for row in messages:
        if row["role"] != "assistant":
            continue
        seen = set()
        current = row
        while current is not None and current["id"] not in seen:
            if current["id"] == anchor:
                descendants.append(row)
                break
            seen.add(current["id"])
            current = by_id.get(current["parent_id"])
    return max(descendants, key=lambda row: (row["created_at"], row["id"]))["id"] if descendants else None


def _input(db: Any, task: Any, anchor: str) -> str:
    # A bounded, host-authored snapshot is distinct from the child model's
    # untrusted text. Never expose the full private child transcript.
    siblings = db.execute(
        "SELECT id,thread_id,subagent_type,status,result_claimed FROM subagent_tasks "
        "WHERE owner=? AND parent_conversation_id=? AND parent_run_id=? "
        "ORDER BY created_at,id LIMIT 32",
        (task["owner"], task["parent_conversation_id"], task["parent_run_id"]),
    ).fetchall()
    known = [{"background_task_id": row["id"], "subagent_thread_id": row["thread_id"],
              "subagent_type": row["subagent_type"], "status": row["status"],
              "result_state": "claimed" if row["result_claimed"] else
                              "pending" if row["status"] == "running" else "available",
              "current_completion": row["id"] == task["id"]} for row in siblings]
    snapshot = {"scope": "current_parent_branch", "parent_message_id": anchor,
                "completeness": "bounded", "known_children": known,
                "additional_children_may_exist": len(siblings) == 32}
    status = task["child_status"]
    # The existing GenerationStore enforces a 128 KiB UTF-8 prompt limit.
    # Bound the UTF-8 payload itself, not Python characters (CJK text can use
    # three bytes per code point); leave room for the orchestration snapshot.
    raw = (task["result"] if status == "completed" else task["error"] or "")
    bounded = raw.encode("utf-8")[:48 * 1024].decode("utf-8", "ignore")
    return "\n".join([
        f"A detached subagent task has {status}. Continue the parent task using its durable result below.",
        _json({"background_task_id": task["id"], "subagent_thread_id": task["thread_id"],
               "subagent_type": task["subagent_type"], "status": status,
               "result": bounded}),
        "Host-authored bounded orchestration snapshot:", _json(snapshot),
    ])


def _retire(db: Any, task_id: str, reason: str) -> None:
    db.execute("UPDATE subagent_wakeups SET status='retired',error=?,updated_at=? "
               "WHERE task_id=? AND status='pending'", (reason, _now(), task_id))


async def process_wakeups(database: Any, *, dispatch: Callable | None = None) -> int:
    """Prepare an owned internal turn atomically; dispatch via existing scheduler.

    Safe to call from multiple Controllers: every claim, branch admission and
    GenerationStore.begin share one BEGIN IMMEDIATE transaction. A replay sees
    its deterministic generation id instead of creating another turn.
    """
    from .agents import AgentRepository
    from .ask_user_tools import ask_user_requested
    from .machine_permissions import require_machine_scope, resolve_access
    from .providers import provider_config, selected_provider
    from .storage import WorkspaceRepository

    if dispatch is None:
        from .generation_routes import _start_task as dispatch

    store = GenerationStore(database)
    now = _now()
    with database.connect() as db:
        candidates = db.execute(
            "SELECT w.task_id FROM subagent_wakeups w JOIN subagent_tasks t ON t.id=w.task_id "
            "LEFT JOIN runs r ON r.id=w.run_id "
            "WHERE (w.status='pending' AND t.status!='running') OR "
            "(w.status='dispatched' AND (w.lease_until IS NULL OR w.lease_until<=? "
            "OR r.status IN ('complete','requires_action','error','aborted','interrupted'))) "
            "ORDER BY w.created_at,w.task_id LIMIT 20", (now,),
        ).fetchall()
    processed = 0
    for candidate in candidates:
        task_id = candidate["task_id"]
        prepared = None
        with database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT w.*,t.status AS child_status,t.result_claimed,t.result_claim_key,"
                "t.granted_scopes,t.grant_expires,t.thread_id,t.subagent_type,t.result,t.error,"
                "t.id,t.child_conversation_id,t.parent_tool_call_id "
                "FROM subagent_wakeups w JOIN subagent_tasks t ON t.id=w.task_id "
                "WHERE w.task_id=? AND w.owner=t.owner AND w.parent_conversation_id=t.parent_conversation_id "
                "AND w.parent_run_id=t.parent_run_id AND w.parent_agent_id=t.parent_agent_id",
                (task_id,),
            ).fetchone()
            if row is None or row["status"] not in {"pending", "dispatched"}:
                continue
            owner = row["owner"]
            scopes = frozenset(json.loads(row["granted_scopes"]))
            expiry = row["grant_expires"]
            if row["status"] == "pending":
                if row["child_status"] == "running" or now - row["created_at"] < _DELAY_MS:
                    continue
                if row["child_status"] == "cancelled":
                    _retire(db, task_id, "Cancelled child has no automatic delivery")
                    continue
                if row["result_claimed"]:
                    _retire(db, task_id, "Child result already manually claimed")
                    continue
                if expiry is not None and expiry <= time.time():
                    _retire(db, task_id, "Parent authorization grant expired")
                    continue
                parent = db.execute("SELECT r.* FROM runs r JOIN conversations c "
                                    "ON r.conversation_id=c.id WHERE r.id=? AND c.owner=? "
                                    "AND r.conversation_id=?", (row["parent_run_id"], owner,
                                                                  row["parent_conversation_id"])).fetchone()
                if parent is None:
                    _retire(db, task_id, "Parent lineage no longer exists")
                    continue
                if parent["status"] in {"running", "requires_action"}:
                    continue
                if parent["status"] != "complete":
                    _retire(db, task_id, "Parent generation did not complete")
                    continue
                envelope = json.loads(row["envelope"])
                target = envelope["target"]
                original = json.loads(parent["state"]).get("responseMessageId")
                if (target.get("conversationId") != row["parent_conversation_id"] or
                        target.get("agentId") != row["parent_agent_id"] or
                        target.get("parentMessageId") != original):
                    _retire(db, task_id, "Wakeup target lineage mismatch")
                    continue
                agent = AgentRepository(database).get(owner, row["parent_agent_id"])
                if agent is None:
                    _retire(db, task_id, "Original parent Agent was removed")
                    continue
                branch = _latest_branch(db, row["parent_conversation_id"], original)
                if branch is None:
                    _retire(db, task_id, "Original parent reply was not persisted")
                    continue
                policy = resolve_access(owner, row["parent_conversation_id"],
                                        repo=WorkspaceRepository(database))
                try:
                    for machine, level in policy.items():
                        if level in {"read", "write"}:
                            require_machine_scope(set(scopes), machine, level, expires=expiry)
                    profile = provider_config(selected_provider({}, agent), agent.get("model"))
                except (PermissionError, ValueError):
                    _retire(db, task_id, "Parent provider or delegated permission unavailable")
                    continue
                try:
                    generation, _ = store.begin(owner, {
                        "conversationId": row["parent_conversation_id"],
                        "parentMessageId": branch,
                        "text": _input(db, row, original),
                        "clientRequestId": "subagent-wakeup:" + task_id,
                        "endpoint": "agents",
                    }, agent, _connection=db)
                except GenerationConflict:
                    continue
                db.execute("UPDATE subagent_tasks SET result_claimed=1,result_claim_key=? "
                           "WHERE id=? AND result_claimed=0", ("wakeup:" + task_id, task_id))
                db.execute("UPDATE subagent_wakeups SET status='dispatched',run_id=?,"
                           "lease_owner=?,lease_until=?,updated_at=? WHERE task_id=? AND status='pending'",
                           (generation.run_id, _PROCESS, now + _LEASE_MS, now, task_id))
                prepared = (generation, profile, agent, owner, scopes, expiry, policy, True)
            else:
                generation = store.get(owner, row["run_id"]) if row["run_id"] else None
                if generation is None:
                    db.execute("UPDATE subagent_wakeups SET status='dead',error=?,updated_at=? WHERE task_id=?",
                               ("Internal continuation was deleted", now, task_id))
                    db.execute("UPDATE subagent_tasks SET result_claimed=0,result_claim_key=NULL "
                               "WHERE id=? AND result_claim_key=?", (task_id, "wakeup:" + task_id))
                    continue
                if generation.status in {"complete", "requires_action"}:
                    db.execute("UPDATE subagent_wakeups SET status='done',lease_owner=NULL,"
                               "lease_until=NULL,updated_at=? WHERE task_id=?", (now, task_id))
                    continue
                if generation.status in {"aborted", "error", "interrupted"}:
                    db.execute("UPDATE subagent_wakeups SET status='dead',lease_owner=NULL,"
                               "lease_until=NULL,error=?,updated_at=? WHERE task_id=?",
                               ("Automatic continuation failed; use manual poll", now, task_id))
                    db.execute("UPDATE subagent_tasks SET result_claimed=0,result_claim_key=NULL "
                               "WHERE id=? AND result_claim_key=?", (task_id, "wakeup:" + task_id))
                    continue
                if expiry is not None and expiry <= time.time():
                    db.execute("UPDATE subagent_wakeups SET status='dead',error=?,updated_at=? WHERE task_id=?",
                               ("Parent authorization expired during wakeup", now, task_id))
                    db.execute("UPDATE subagent_tasks SET result_claimed=0,result_claim_key=NULL "
                               "WHERE id=? AND result_claim_key=?", (task_id, "wakeup:" + task_id))
                    continue
                agent = AgentRepository(database).get(owner, row["parent_agent_id"])
                if agent is None:
                    db.execute("UPDATE subagent_wakeups SET status='dead',error=?,updated_at=? WHERE task_id=?",
                               ("Parent Agent removed during continuation", now, task_id))
                    db.execute("UPDATE subagent_tasks SET result_claimed=0,result_claim_key=NULL "
                               "WHERE id=? AND result_claim_key=?", (task_id, "wakeup:" + task_id))
                    continue
                policy = resolve_access(owner, row["parent_conversation_id"],
                                        repo=WorkspaceRepository(database))
                try:
                    for machine, level in policy.items():
                        if level in {"read", "write"}:
                            require_machine_scope(set(scopes), machine, level, expires=expiry)
                    profile = provider_config(selected_provider({}, agent), agent.get("model"))
                except (ValueError, PermissionError):
                    db.execute("UPDATE subagent_wakeups SET status='dead',error=?,updated_at=? WHERE task_id=?",
                               ("Parent provider or delegated permission unavailable", now, task_id))
                    db.execute("UPDATE subagent_tasks SET result_claimed=0,result_claim_key=NULL "
                               "WHERE id=? AND result_claim_key=?", (task_id, "wakeup:" + task_id))
                    continue
                db.execute("UPDATE subagent_wakeups SET lease_owner=?,lease_until=?,updated_at=? "
                           "WHERE task_id=?", (_PROCESS, now + _LEASE_MS, now, task_id))
                prepared = (generation, profile, agent, owner, scopes, expiry, policy, False)
        if prepared is not None:
            generation, profile, agent, owner, scopes, expiry, policy, new_turn = prepared
            from . import generation_routes as runner
            # The existing scheduler owns provider streaming and tools. It is
            # the only task runner; the wakeup queue only admits trusted turns.
            current = runner._TASKS.get(generation.run_id)
            if current is None or current.done():
                flags = WorkspaceRepository(database).setting(
                    owner, "conversation.permissions." + generation.conversation_id, {})
                await dispatch(owner, generation, profile, agent,
                               native_file_tools=any(v in {"read", "write"} for v in policy.values()),
                               write_tools=any(v == "write" for v in policy.values()),
                               ask_user_enabled=ask_user_requested(agent, {}),
                               mcp_enabled=isinstance(flags, dict) and flags.get("mcp") is True,
                               resume_history=None if new_turn else store.history(
                                   owner, generation.conversation_id,
                                   message_id=generation.user_message_id),
                               partial_text="" if new_turn else store.accumulated_text(owner, generation.run_id),
                               granted_scopes=scopes, grant_expires=expiry)
                processed += 1
    # Keep live leases alive while the single existing scheduler is running.
    with database.connect() as db:
        rows = db.execute("SELECT task_id,run_id FROM subagent_wakeups WHERE status='dispatched' "
                          "AND lease_owner=?", (_PROCESS,)).fetchall()
        for row in rows:
            from .generation_routes import _TASKS
            current = _TASKS.get(row["run_id"])
            if current is not None and not current.done():
                db.execute("UPDATE subagent_wakeups SET lease_until=?,updated_at=? WHERE task_id=? "
                           "AND lease_owner=?", (_now() + _LEASE_MS, _now(), row["task_id"], _PROCESS))
    return processed


async def start_wakeup_worker(database: Any) -> None:
    """Resume the same SQLite queue on server startup; no second provider runner."""
    key = str(database.path)
    prior = _WORKERS.get(key)
    if prior and not prior.done():
        return

    async def run():
        while True:
            try:
                await process_wakeups(database)
            except Exception:
                log.exception("Subagent completion queue scan failed; retrying")
            await asyncio.sleep(1)

    _WORKERS[key] = asyncio.create_task(run(), name="webui-subagent-completion-recover")


async def shutdown_wakeup_workers() -> None:
    current = list(_WORKERS.values())
    for task in current:
        task.cancel()
    if current:
        await asyncio.gather(*current, return_exceptions=True)
    _WORKERS.clear()
