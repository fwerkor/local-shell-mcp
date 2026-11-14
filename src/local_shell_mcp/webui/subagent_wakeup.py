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
import math
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
_LEASE_MS = 2 * 60_000  # original trigger engine DEFAULT_LEASE_MS
_MAX_ATTEMPTS = 8
_RETRY_BASE_MS = 1_000
_RETRY_CAP_MS = 5 * 60_000
_WORKERS: dict[str, asyncio.Task] = {}
_PROCESS = secrets.token_hex(12)
_OWNED_LEASES: dict[str, tuple[str, str]] = {}  # child task -> (root run, fresh claim token)


def waiting_retry_seconds(waiting_since_ms: int, now_ms: int) -> int:
    """Exact original triggers/backoff.ts:waitingRetryAfter default 5..60s.

    Defer not-ready parent/child deliveries without consuming an attempt.
    Readiness changes should clear next_attempt_at in the same SQLite commit.
    """
    elapsed = max(0, now_ms - waiting_since_ms)
    delay_ms = min(60_000, max(5_000, elapsed * .1))
    return math.ceil(delay_ms / 1_000)


def _defer_pending(db: Any, row: Any, now: int) -> None:
    db.execute("UPDATE subagent_wakeups SET next_attempt_at=?,updated_at=? "
               "WHERE task_id=? AND status='pending'",
               (now + waiting_retry_seconds(row["created_at"], now) * 1000,
                now, row["task_id"]))


def _retry_at(attempt: int, now: int, *, random_half: float | None = None) -> int:
    """Original triggers/engine.ts:retryAt half-to-full jitter, bounded 1s..5m.

    Time budgets are durable milliseconds; a retry never allocates a fresh
    root run or consumes a second manual child result claim.
    """
    if not isinstance(attempt, int) or attempt < 1:
        raise ValueError("A retry attempt number must be positive")
    delay = min(_RETRY_BASE_MS * (2 ** min(attempt - 1, 30)), _RETRY_CAP_MS)
    jitter = secrets.randbelow(max(1, delay // 2)) if random_half is None else int(
        max(0, min(0.999999, random_half)) * (delay / 2)
    )
    return now + delay // 2 + jitter


def _dispatch_failure(database: Any, task_id: str, run_id: str, lease_token: str,
                      error: Exception, *, at: int | None = None) -> bool:
    """Fenced original bounded retry; False means permanent dead letter.

    Source engine does not log provider exception strings into Agent history:
    records expose only a stable error type, never possible credentials.
    """
    current = _now() if at is None else at
    with database.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT attempts,failure_history FROM subagent_wakeups WHERE "
                         "task_id=? AND run_id=? AND lease_owner=? AND status='dispatched'",
                         (task_id, run_id, lease_token)).fetchone()
        if row is None:
            return True  # stale actor is not allowed to mutate the durable claim
        attempt = row["attempts"] + 1
        event = {"attempt": attempt, "code": "DELIVERY_FAILED",
                 "errorType": type(error).__name__, "at": current}
        prior = json.loads(row["failure_history"])
        history = _json((prior + [event])[-_MAX_ATTEMPTS:])
        if attempt >= _MAX_ATTEMPTS:
            db.execute("UPDATE subagent_wakeups SET status='dead',attempts=?,failure_history=?,"
                       "error=?,next_attempt_at=NULL,lease_owner=NULL,lease_until=NULL,"
                       "updated_at=? WHERE task_id=?",
                       (attempt, history, "Automatic delivery exhausted retry attempts", current, task_id))
            db.execute("UPDATE subagent_tasks SET result_claimed=0,result_claim_key=NULL "
                       "WHERE id=? AND result_claim_key=?", (task_id, "wakeup:" + task_id))
            return False
        db.execute("UPDATE subagent_wakeups SET attempts=?,failure_history=?,error=?,"
                   "next_attempt_at=?,lease_owner=NULL,lease_until=NULL,updated_at=? "
                   "WHERE task_id=?", (attempt, history, type(error).__name__,
                                       _retry_at(attempt, current), current, task_id))
        return True


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
        # A nested Subagent executes under its own child conversation while
        # retaining the root conversation's tool authority. A completion event
        # for that hidden child cannot be routed to the root conversation's
        # assistant branch. Keep its ordinary durable poll/claim path rather
        # than failing the child or inventing a false root Agent continuation.
        nested = db.execute(
            "SELECT 1 FROM runs r JOIN conversations c ON c.id=r.conversation_id "
            "JOIN subagent_tasks t ON t.child_run_id=r.id "
            "WHERE r.id=? AND c.owner=? AND t.owner=? "
            "AND t.parent_conversation_id=? AND t.status='running' LIMIT 1",
            (parent_run_id, owner, owner, conversation_id),
        ).fetchone()
        if nested is not None:
            return
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


def get_dead_wakeups(database: Any, owner: str, *, limit: int = 50) -> list[dict]:
    """Original triggers service: trusted, owner-scoped in-process dead letters.

    This deliberately has no unverified public HTTP route or model tool.
    """
    with database.connect() as db:
        rows = db.execute(
            "SELECT task_id,run_id,error,attempts,failure_history,updated_at "
            "FROM subagent_wakeups WHERE owner=? AND status='dead' "
            "ORDER BY updated_at,task_id LIMIT ?", (owner, max(1, min(limit, 100))),
        ).fetchall()
    return [dict(row) for row in rows]


def requeue_dead_wakeup(database: Any, owner: str, task_id: str) -> bool:
    """Original trusted requeue: a dead delivery joins the lane tail anew.

    Incrementing a durable sequence is essential: replay must never adopt the
    old generation's persisted idempotency key after the previous root failed.
    Requeue is denied if a person already claimed the child result.
    """
    now = _now()
    with database.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT w.envelope FROM subagent_wakeups w JOIN subagent_tasks t "
            "ON t.id=w.task_id WHERE w.owner=? AND t.owner=? AND w.task_id=? "
            "AND w.status='dead' AND t.status!='running' AND t.result_claimed=0",
            (owner, owner, task_id),
        ).fetchone()
        if row is None:
            return False
        envelope = json.loads(row["envelope"])
        envelope["requestId"] = str(uuid.uuid4())
        envelope["receivedAt"] = now
        updated = db.execute(
            "UPDATE subagent_wakeups SET envelope=?,status='pending',run_id=NULL,"
            "lease_owner=NULL,lease_until=NULL,attempts=0,next_attempt_at=NULL,"
            "requeue_count=requeue_count+1,error=NULL,created_at=?,updated_at=? "
            "WHERE task_id=? AND owner=? AND status='dead'",
            (_json(envelope), now, now, task_id, owner),
        )
        return updated.rowcount == 1


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


def assert_wakeup_lease(database: Any, owner: str, run_id: str,
                        wakeup_lease: tuple[str, str]) -> None:
    """A stale Controller can neither checkpoint nor invoke model tools.

    Claim tokens are fresh on each attempt, including a lease reacquired by
    the same process. The durable run remains unique across replays.
    """
    from .agent_runtime import RuntimeSafetyError

    task_id, token = wakeup_lease
    with database.connect() as db:
        valid = db.execute(
            "SELECT 1 FROM subagent_wakeups WHERE task_id=? AND run_id=? "
            "AND owner=? AND status='dispatched' AND lease_owner=? AND lease_until>?",
            (task_id, run_id, owner, token, _now()),
        ).fetchone()
    if valid is None:
        raise RuntimeSafetyError("Automatic completion actor lease was revoked")


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
            "WHERE (w.status='pending' "
            "AND (w.next_attempt_at IS NULL OR w.next_attempt_at<=?)) OR "
            "(w.status='dispatched' AND (w.next_attempt_at IS NULL OR w.next_attempt_at<=?) "
            "AND (w.lease_until IS NULL OR w.lease_until<=? "
            "OR r.status IN ('complete','requires_action','error','aborted','interrupted'))) "
            "ORDER BY w.created_at,w.task_id LIMIT 20", (now, now, now),
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
                "t.id,t.child_conversation_id,t.child_run_id,t.parent_tool_call_id "
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
                if now - row["created_at"] < _DELAY_MS:
                    continue
                if row["child_status"] == "running":
                    _defer_pending(db, row, now)
                    continue
                if row["child_status"] == "cancelled":
                    _retire(db, task_id, "Cancelled child has no automatic delivery")
                    continue
                if row["result_claimed"]:
                    _retire(db, task_id, "Child result already manually claimed")
                    continue
                # The original createSubagentCompletionWakeupResolver requires
                # the actual owned child conversation and terminal assistant
                # state. Deleting a child transcript must retire delivery, not
                # let a stale result be replayed into its parent conversation.
                child = db.execute(
                    "SELECT c.metadata,r.status FROM conversations c JOIN runs r "
                    "ON r.conversation_id=c.id WHERE c.id=? AND c.owner=? AND r.id=?",
                    (row["child_conversation_id"], owner, row["child_run_id"]),
                ).fetchone()
                if child is None:
                    _retire(db, task_id, "The owned child conversation is no longer available")
                    continue
                try:
                    lineage = json.loads(child["metadata"])
                except (ValueError, TypeError):
                    _retire(db, task_id, "The child transcript metadata is invalid")
                    continue
                if not isinstance(lineage, dict):
                    _retire(db, task_id, "The child transcript metadata is invalid")
                    continue
                if (lineage.get("subagentTask") != task_id or
                        lineage.get("parentConversationId") != row["parent_conversation_id"]):
                    _retire(db, task_id, "The child transcript lineage no longer matches its owner")
                    continue
                if child["status"] in {"running", "requires_action"}:
                    _defer_pending(db, row, now)
                    continue  # Child terminal messages are not durable yet.
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
                    _defer_pending(db, row, now)
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
                        "clientRequestId": "subagent-wakeup:" + task_id + (
                            ":requeue:" + str(row["requeue_count"])
                            if row["requeue_count"] else ""
                        ),
                        "endpoint": "agents",
                    }, agent, _connection=db)
                except GenerationConflict:
                    _defer_pending(db, row, now)
                    continue
                db.execute("UPDATE subagent_tasks SET result_claimed=1,result_claim_key=? "
                           "WHERE id=? AND result_claimed=0", ("wakeup:" + task_id, task_id))
                token = _PROCESS + ":" + secrets.token_hex(12)
                db.execute("UPDATE subagent_wakeups SET status='dispatched',run_id=?,"
                           "lease_owner=?,lease_until=?,updated_at=? WHERE task_id=? AND status='pending'",
                           (generation.run_id, token, now + _LEASE_MS, now, task_id))
                prepared = (generation, profile, agent, owner, scopes, expiry, policy, True, task_id, token)
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
                token = _PROCESS + ":" + secrets.token_hex(12)
                db.execute("UPDATE subagent_wakeups SET lease_owner=?,lease_until=?,"
                           "next_attempt_at=NULL,updated_at=? WHERE task_id=?",
                           (token, now + _LEASE_MS, now, task_id))
                prepared = (generation, profile, agent, owner, scopes, expiry, policy, False, task_id, token)
        if prepared is not None:
            generation, profile, agent, owner, scopes, expiry, policy, new_turn, task_id, token = prepared
            from . import generation_routes as runner
            # The existing scheduler owns provider streaming and tools. It is
            # the only task runner; the wakeup queue only admits trusted turns.
            current = runner._TASKS.get(generation.run_id)
            if current is None or current.done():
                flags = WorkspaceRepository(database).setting(
                    owner, "conversation.permissions." + generation.conversation_id, {})
                try:
                    await dispatch(owner, generation, profile, agent,
                                   native_file_tools=any(v in {"read", "write"} for v in policy.values()),
                                   write_tools=any(v == "write" for v in policy.values()),
                                   ask_user_enabled=ask_user_requested(agent, {}),
                                   mcp_enabled=isinstance(flags, dict) and flags.get("mcp") is True,
                                   resume_history=None if new_turn else store.history(
                                       owner, generation.conversation_id,
                                       message_id=generation.user_message_id),
                                   partial_text="" if new_turn else store.accumulated_text(owner, generation.run_id),
                                   granted_scopes=scopes, grant_expires=expiry,
                                   wakeup_lease=(task_id, token))
                except Exception as exc:
                    retry = _dispatch_failure(database, task_id, generation.run_id, token, exc)
                    if not retry:
                        store.finish(owner, generation.run_id, status="error",
                                     error="Automatic completion delivery exhausted retries")
                    log.warning("Subagent completion dispatch failed: %s", type(exc).__name__)
                    continue
                _OWNED_LEASES[task_id] = (generation.run_id, token)
                processed += 1
    # Keep live leases alive while the single existing scheduler is running.
    with database.connect() as db:
        from .generation_routes import _TASKS
        for key, (run_id, token) in list(_OWNED_LEASES.items()):
            current = _TASKS.get(run_id)
            if current is None or current.done():
                _OWNED_LEASES.pop(key, None)
                continue
            updated = db.execute(
                "UPDATE subagent_wakeups SET lease_until=?,updated_at=? WHERE task_id=? "
                "AND lease_owner=? AND status='dispatched' AND lease_until>?",
                (_now() + _LEASE_MS, _now(), key, token, _now()),
            )
            if updated.rowcount != 1:
                _OWNED_LEASES.pop(key, None)
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
    _OWNED_LEASES.clear()
