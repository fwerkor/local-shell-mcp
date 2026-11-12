"""Original agents 4.0.1 SubagentTaskStore backed by the Controller SQLite DB.

The task ledger is inserted BEFORE any child generation or model/tool dispatch,
with immutable parent-run/tool-call lineage. Each detached child is an ordinary
AgentRunner/StateGraph running in a distinct GenerationStore conversation. The
host is a task *owner*, not a second graph or LSM tool executor.

Source: src/types/subagentTasks.ts, src/tools/subagent/SubagentExecutor.ts
(executeInBackground) and LibreChat api/src/agents/subagentThreads.ts.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import secrets
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from .agent_runtime import RuntimeSafetyError
from .agents import AgentRepository
from .generations import GenerationStore
from .subagents import SubagentInvocation, filter_subagent_result

log = logging.getLogger(__name__)
_RUNNING_PER_SCOPE = 10
_RUNNING_GLOBAL = 100
_MAX_RESULT = 100_000
_MAX_ERROR = 4_096
_MAX_THREAD_HISTORY = 512 * 1_024
_LEASE_SECONDS = 30
_TIMEOUT_SECONDS = 30 * 60

# Child task objects are process-owned; SQLite, never this dictionary, is
# authoritative for cross-turn identity, lineage, status and result claiming.
_TASKS: dict[str, asyncio.Task] = {}
_ACTIVE_LEASES: dict[str, str] = {}
_RECOVERY_TASKS: set[asyncio.Task] = set()
_PROCESS_ID = secrets.token_hex(16)


def _now() -> int:
    return int(time.time() * 1_000)


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _limited(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    marker = "\n…[truncated]…\n"
    keep = limit - len(marker)
    front = (keep + 1) // 2
    return value[:front] + marker + value[-(keep - front):]


def _snapshot(row: Any) -> dict:
    return {
        "taskId": row["id"], "threadId": row["thread_id"],
        "subagentType": row["subagent_type"], "status": row["status"],
        "createdAt": row["created_at"], "updatedAt": row["updated_at"],
        "resultAvailable": row["status"] == "completed" and not bool(row["result_claimed"]),
        "resultClaimed": bool(row["result_claimed"]),
        "pendingControls": int(row["pending_controls"]),
        **({"error": row["error"]} if row["error"] else {}),
    }


def _iso(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def _out(task: dict, *, status: str | None = None, result: str | None = None,
         error: str | None = None, control_id: str | None = None) -> dict:
    return {
        "background_task_id": task["taskId"],
        "subagent_thread_id": task["threadId"],
        "tool": "subagent", "subagent_type": task["subagentType"],
        "status": status or task["status"],
        "progress": 0 if task["status"] == "running" else 1,
        "started_at": _iso(task["createdAt"]),
        **({"settled_at": _iso(max(task["updatedAt"], task["createdAt"]))}
           if task["status"] != "running" else {}),
        "elapsed_ms": max(0, (max(task["updatedAt"], task["createdAt"])
                              if task["status"] != "running" else _now()) - task["createdAt"]),
        **({"result_available": True} if task["resultAvailable"] else {}),
        **({"result_claimed": True} if task["resultClaimed"] else {}),
        **({"result": result} if result is not None else {}),
        **({"error": error} if error is not None else {}),
        **({"control_id": control_id} if control_id else {}),
    }


class SQLiteSubagentTaskHost:
    """Trusted, owner-scoped host for one durable child generation per tool call."""

    def __init__(self, database: Any, owner: str, conversation_id: str,
                 *, stream_tools: Callable, stream_text: Callable):
        self.db, self.owner, self.conversation_id = database, owner, conversation_id
        self.stream_tools, self.stream_text = stream_tools, stream_text

    def _child_activity(self) -> Any | None:
        """Integration seam for the independent Artifacts PR #352 child guard.

        That PR owns `active_subagent_threads` and its authenticated mutation
        API. Import only when installed; do not create a competing marker table
        or rewrite its source-pinned guard.
        """
        try:
            from .child_thread_activity import ActiveChildThreads
        except ModuleNotFoundError as exc:
            if exc.name != "local_shell_mcp.webui.child_thread_activity":
                raise
            return None
        return ActiveChildThreads(self.db)

    def _settle_child_registration(self, task_id: str, *, before_terminal: bool = False,
                                   lease_token: str | None = None) -> None:
        """Persist the source child guard *before* exposing a terminal task.

        The Artifact guard uses a distinct SQLite connection. Call its original
        settle API before, never within, the terminal task transaction. If the
        process dies between these two commits the immutable marker remains
        read-only and the still-running task can safely retry settlement.
        """
        activity = self._child_activity()
        if activity is None:
            return
        with self.db.connect() as db:
            row = self._row(db, task_id)
        if not row or not row["child_registered"] or not row["child_conversation_id"]:
            return
        if row["status"] == "running":
            if not before_terminal:
                return
            if lease_token is not None:
                if row["lease_owner"] != lease_token:
                    return
            elif row["lease_owner"] and row["lease_until"] and row["lease_until"] > _now():
                return
        activity.settle(self.owner, row["child_conversation_id"], row["parent_run_id"])

    def _row(self, db: Any, task_id: str) -> Any:
        return db.execute(
            "SELECT t.*, (SELECT count(*) FROM subagent_task_controls q WHERE q.task_id=t.id "
            "AND q.status='accepted') AS pending_controls FROM subagent_tasks t "
            "JOIN conversations c ON c.id=t.parent_conversation_id "
            "WHERE t.id=? AND t.owner=? AND t.parent_conversation_id=? AND c.owner=?",
            (task_id, self.owner, self.conversation_id, self.owner),
        ).fetchone()

    def _get(self, task_id: str) -> Any:
        with self.db.connect() as db:
            return self._row(db, task_id)

    def list(self) -> list[dict]:
        with self.db.connect() as db:
            rows = db.execute("SELECT t.*, (SELECT count(*) FROM subagent_task_controls q "
                              "WHERE q.task_id=t.id AND q.status='accepted') AS pending_controls "
                              "FROM subagent_tasks t JOIN conversations c "
                              "ON c.id=t.parent_conversation_id "
                              "WHERE t.owner=? AND t.parent_conversation_id=? AND c.owner=? "
                              "ORDER BY t.created_at ASC", (self.owner, self.conversation_id, self.owner)).fetchall()
        return [_snapshot(row) for row in rows]

    def _sweep(self, db: Any, now: int) -> None:
        # Source store TTL: retire old terminal task handles but keep the
        # independently owned thread transcript for future continuation.
        db.execute("DELETE FROM subagent_tasks WHERE status!='running' AND updated_at<?",
                   (now - 60 * 60 * 1000,))

    def _existing(self, db: Any, key: str, fingerprint: str) -> dict | None:
        row = db.execute("SELECT t.*, (SELECT count(*) FROM subagent_task_controls q "
                         "WHERE q.task_id=t.id AND q.status='accepted') AS pending_controls "
                         "FROM subagent_tasks t WHERE t.owner=? AND t.parent_conversation_id=? "
                         "AND t.idempotency_key=?", (self.owner, self.conversation_id, key)).fetchone()
        if row is None:
            return None
        task = _snapshot(row)
        return {"accepted": row["fingerprint"] == fingerprint, "isNew": False,
                "reason": "conflict" if row["fingerprint"] != fingerprint else None,
                "task": task}

    async def start(self, invocation: SubagentInvocation, *, thread_id: str | None = None,
                    mcp_enabled: bool = False) -> str:
        """Persist immutable owner/parent/tool identity before launching any child run."""
        if not invocation.parent_tool_call_id or not invocation.parent_run_id:
            return _json({"status": "rejected", "tool": "subagent",
                          "message": "Background subagent execution requires a parent tool call ID."})
        if invocation.owner != self.owner or invocation.conversation_id != self.conversation_id:
            raise PermissionError("Background task scope is not authorized")
        if invocation.grant_expires is not None and invocation.grant_expires <= time.time():
            raise PermissionError("Authentication grant expired")
        source_agent = invocation.agent.get("id")
        parent_agent = invocation.parent_agent_id or source_agent
        repository = AgentRepository(self.db)
        if repository.get(self.owner, source_agent) is None or repository.get(self.owner, parent_agent) is None:
            raise PermissionError("Subagent or parent Agent is not owned by the current principal")
        key = _json([invocation.parent_run_id, parent_agent, invocation.parent_tool_call_id])
        task_text = invocation.messages[-1]["content"]
        fingerprint = hashlib.sha256(_json([task_text, invocation.subagent_type, thread_id or ""]).encode()).hexdigest()
        now = _now()
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._sweep(db, now)
            parent = db.execute(
                "SELECT 1 FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "LEFT JOIN subagent_tasks t ON t.child_run_id=r.id "
                "WHERE r.id=? AND c.owner=? AND (r.conversation_id=? OR "
                "(t.owner=? AND t.parent_conversation_id=? AND t.status='running'))",
                (invocation.parent_run_id, self.owner, self.conversation_id,
                 self.owner, self.conversation_id),
            ).fetchone()
            if parent is None:
                raise PermissionError("Parent run is not owned by this conversation")
            previous = self._existing(db, key, fingerprint)
            if previous is not None:
                if not previous["accepted"]:
                    return _json({"status": "rejected", "tool": "subagent",
                                  "message": "The same parent tool call ID was already used with different background subagent arguments."})
                task = previous["task"]
                is_new = False
            else:
                in_scope = db.execute("SELECT count(*) FROM subagent_tasks WHERE owner=? AND "
                                      "parent_conversation_id=? AND status='running'",
                                      (self.owner, self.conversation_id)).fetchone()[0]
                total = db.execute("SELECT count(*) FROM subagent_tasks WHERE status='running'").fetchone()[0]
                task_count = db.execute("SELECT count(*) FROM subagent_tasks WHERE owner=? AND "
                                        "parent_conversation_id=?", (self.owner, self.conversation_id)).fetchone()[0]
                global_count = db.execute("SELECT count(*) FROM subagent_tasks").fetchone()[0]
                if (in_scope >= _RUNNING_PER_SCOPE or total >= _RUNNING_GLOBAL
                        or task_count >= 200 or global_count >= 2000):
                    return _json({"status": "rejected", "tool": "subagent", "message":
                                  "Too many background subagent tasks are already running in this scope or process. Poll or cancel an existing task, or run this call in the foreground."})
                prior_messages = []
                if thread_id:
                    thread = db.execute("SELECT * FROM subagent_threads WHERE id=? AND owner=? "
                                        "AND parent_conversation_id=? AND subagent_type=?",
                                        (thread_id, self.owner, self.conversation_id,
                                         invocation.subagent_type)).fetchone()
                    if thread is None:
                        return _json({"status": "rejected", "tool": "subagent", "message":
                                      "The requested subagent thread is unavailable in this parent scope. Start a new subagent thread or choose one created by this parent for the same subagent type."})
                    prior_messages = json.loads(thread["messages"])
                task_id = "subtask_" + secrets.token_hex(16)
                reserved_child_id = str(uuid.uuid4())
                thread_id = thread_id or "subthread_" + secrets.token_hex(16)
                if not prior_messages:
                    db.execute("INSERT OR IGNORE INTO subagent_threads "
                               "(id,owner,parent_conversation_id,subagent_type,messages,created_at,updated_at) "
                               "VALUES(?,?,?,?,?,?,?)", (thread_id, self.owner, self.conversation_id,
                                                         invocation.subagent_type, "[]", now, now))
                history = prior_messages + invocation.messages
                db.execute("INSERT INTO subagent_tasks "
                           "(id,owner,parent_conversation_id,parent_run_id,parent_agent_id,parent_tool_call_id,"
                           "subagent_type,thread_id,idempotency_key,fingerprint,agent_config,execution_options,input,initial_messages,"
                           "granted_scopes,grant_expires,child_conversation_id,status,created_at,updated_at) "
                           "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (task_id, self.owner, self.conversation_id, invocation.parent_run_id,
                            parent_agent, invocation.parent_tool_call_id, invocation.subagent_type,
                            thread_id, key, fingerprint, _json(invocation.agent),
                            _json({"selected_tools": invocation.selected_tools,
                                   "recursion_limit": invocation.recursion_limit,
                                   "remaining_depth": invocation.remaining_depth,
                                   "child_types": [config.type for config in invocation.child_configs],
                                   "mcp_enabled": mcp_enabled}), task_text,
                            _json(history), _json(sorted(invocation.scopes)), invocation.grant_expires,
                            reserved_child_id, "running", now, now))
                task = _snapshot(self._row(db, task_id))
                is_new = True
        if is_new:
            activity = self._child_activity()
            if activity is not None:
                # Register the identity before the GeneratorStore creates the
                # child conversation or exposes its message to artifact routes.
                # The task is already owned by the parent invocation in SQLite.
                try:
                    activity.activate(self.owner, reserved_child_id, invocation.parent_run_id)
                except BaseException:
                    with self.db.connect() as db:
                        db.execute("UPDATE subagent_tasks SET status='error',error=?,updated_at=? "
                                   "WHERE id=? AND status='running'",
                                   ("Child-thread registration rejected", _now(), task["taskId"]))
                    raise
            # The durable admission bit prevents an idempotent second caller
            # from launching the same child between task insert and the Artifacts
            # guard's committed registration. Never infer it from a guessed ID.
            with self.db.connect() as db:
                db.execute("UPDATE subagent_tasks SET child_registered=1 WHERE id=? "
                           "AND status='running'", (task["taskId"],))
        await self._ensure_active(task["taskId"])
        return _json({"background_task_id": task["taskId"],
                      "subagent_thread_id": task["threadId"], "tool": "subagent",
                      "subagent_type": task["subagentType"], "status": task["status"],
                      "message": f"{'Started' if is_new else 'Reused'} subagent \"{task['subagentType']}\" background task. Poll the host background-task tool with background_task_id \"{task['taskId']}\" to check progress or collect its result."})

    async def _ensure_active(self, task_id: str) -> None:
        current = _TASKS.get(task_id)
        if current is not None and not current.done():
            return
        now = _now()
        # The callback may already have published a cancellation/expiration
        # intent. Settle the protected child marker before terminal status is
        # visible to any poller, including a different Controller replica.
        preliminary = self._get(task_id)
        pre_cancel = bool(preliminary and preliminary["cancel_requested"])
        pre_expired = bool(preliminary and preliminary["grant_expires"] is not None
                           and preliminary["grant_expires"] <= time.time())
        if preliminary and preliminary["status"] == "running" and (pre_cancel or pre_expired):
            self._settle_child_registration(task_id, before_terminal=True)
        terminal = False
        claimed = 0
        lease = ""
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, task_id)
            if row is None or row["status"] != "running":
                return
            if not row["child_registered"]:
                # Recovery from a crash after PR #352's registration commit but
                # before our admission bit. The exact authenticated marker is
                # durable and may now outlive the parent run.
                if self._child_activity() is None:
                    return
                registered = db.execute(
                    "SELECT 1 FROM active_subagent_threads WHERE owner=? AND thread_id=? "
                    "AND parent_run_id=?", (self.owner, row["child_conversation_id"],
                                              row["parent_run_id"]),
                ).fetchone()
                if registered is None:
                    return
                db.execute("UPDATE subagent_tasks SET child_registered=1 WHERE id=?",
                           (task_id,))
            if row["cancel_requested"] and (row["lease_owner"] is None or row["lease_until"] is None
                                              or row["lease_until"] <= now):
                if not pre_cancel:
                    # Cancellation arrived after our pre-terminal registration
                    # check. Leave it pending for the next guarded admission.
                    return
                db.execute("UPDATE subagent_tasks SET status='cancelled', error=?, updated_at=? "
                           "WHERE id=?", ("Detached subagent task cancelled by its parent.", now, task_id))
                terminal = True
            elif row["grant_expires"] is not None and row["grant_expires"] <= time.time():
                if not pre_expired:
                    return
                db.execute("UPDATE subagent_tasks SET status='error', error=?,updated_at=? WHERE id=?",
                           ("Authentication grant expired", now, task_id))
                terminal = True
            else:
                lease = _PROCESS_ID + ":" + secrets.token_hex(12)
                claimed = db.execute("UPDATE subagent_tasks SET lease_owner=?,lease_until=? "
                                     "WHERE id=? AND status='running' AND "
                                     "(lease_until IS NULL OR lease_until<=?)",
                                     (lease, now + _LEASE_SECONDS * 1000, task_id, now)).rowcount
        if terminal:
            return
        if claimed:
            _ACTIVE_LEASES[task_id] = lease
            runner = asyncio.create_task(self._execute(task_id, lease), name="webui-subagent-" + task_id)
            _TASKS[task_id] = runner
            runner.add_done_callback(lambda finished, key=task_id, token=lease: (
                self._task_done(key, token, finished)
            ))

    def _task_done(self, task_id: str, token: str, finished: asyncio.Task) -> None:
        if _TASKS.get(task_id) is finished:
            _TASKS.pop(task_id, None)
            if _ACTIVE_LEASES.get(task_id) == token:
                _ACTIVE_LEASES.pop(task_id, None)
        # A cancelled asyncio.Task may never enter its coroutine at all, so
        # its try/except/finally cannot release the SQLite lease. Reconcile the
        # original cancellation request from durable state, not a guessed ID.
        if not finished.cancelled():
            return
        preliminary = self._get(task_id)
        if preliminary and preliminary["cancel_requested"]:
            self._settle_child_registration(task_id, before_terminal=True,
                                            lease_token=token)
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, task_id)
            if row is None or row["status"] != "running" or row["lease_owner"] != token:
                return
            if row["cancel_requested"] and preliminary and preliminary["cancel_requested"]:
                db.execute("UPDATE subagent_tasks SET status='cancelled', error=?, updated_at=?, "
                           "lease_owner=NULL,lease_until=NULL WHERE id=?",
                           ("Detached subagent task cancelled by its parent.", _now(), task_id))
            else:
                db.execute("UPDATE subagent_tasks SET lease_owner=NULL,lease_until=NULL "
                           "WHERE id=?", (task_id,))

    async def _execute(self, task_id: str, token: str) -> None:
        from .agent_runner import AgentRunner
        from .graph_topology import admit_agent_graph

        row = self._get(task_id)
        if row is None:
            return
        store = GenerationStore(self.db)
        child_generation = None
        heartbeat = None
        try:
            agent = json.loads(row["agent_config"])
            if AgentRepository(self.db).get(self.owner, agent["id"]) is None:
                raise RuntimeSafetyError("Subagent was revoked")
            admit_agent_graph(self.owner, agent, AgentRepository(self.db))
            scopes = frozenset(json.loads(row["granted_scopes"]))
            options = json.loads(row["execution_options"])
            if row["grant_expires"] is not None and row["grant_expires"] <= time.time():
                raise RuntimeSafetyError("Authentication grant expired")
            child_generation, _ = store.begin(
                self.owner, {"text": row["input"], "clientRequestId": "subagent:" + task_id,
                             "endpoint": "agents"}, agent,
                trusted_new_conversation_id=row["child_conversation_id"],
            )
            with self.db.connect() as db:
                db.execute("UPDATE conversations SET archived=1,metadata=? WHERE id=?",
                           (_json({"subagentTask": task_id, "parentConversationId": self.conversation_id}),
                            child_generation.conversation_id))
                db.execute("UPDATE subagent_tasks SET child_run_id=? WHERE id=?",
                           (child_generation.run_id, task_id))
            async def pulse():
                while True:
                    await asyncio.sleep(5)
                    with self.db.connect() as db:
                        row = db.execute("SELECT cancel_requested FROM subagent_tasks WHERE id=? "
                                         "AND lease_owner=? AND status='running'",
                                         (task_id, token)).fetchone()
                        if row is None or row["cancel_requested"]:
                            executing = _TASKS.get(task_id)
                            if executing and not executing.done():
                                executing.cancel()
                            return
                        db.execute("UPDATE subagent_tasks SET lease_until=? WHERE id=? "
                                   "AND lease_owner=? AND status='running'",
                                   (_now() + _LEASE_SECONDS * 1000, task_id, token))
            heartbeat = asyncio.create_task(pulse())
            async def emit(_chunk: str) -> None:
                return None
            # The graph runner resolves only the pre-admitted child types; a
            # freshly modified nested catalog must not expand the delegated
            # authority or reset the parent recursion/depth budget.
            from .subagents import build_subagent_configs

            allowed = set(options.get("child_types") or [])
            nested = [config for config in build_subagent_configs(self.owner, agent, self.db)
                      if config.type in allowed] if allowed else []
            runner = AgentRunner(
                self.owner, child_generation, self.db, store, scopes=scopes,
                grant_expires=row["grant_expires"], stream_tools=self.stream_tools,
                stream_text=self.stream_text, on_text=emit,
                agent=agent, mcp_enabled=bool(options.get("mcp_enabled")), ask_user_enabled=False,
                background_deny=True, authorization_conversation_id=self.conversation_id,
                task_control_host=self, task_control_id=task_id,
                selected_tools=options.get("selected_tools"),
                child_configs=nested,
                subagent_depth=options.get("remaining_depth", 0),
            )
            initial = json.loads(row["initial_messages"])
            result = await asyncio.wait_for(runner.run(
                initial, recursion_limit=options.get("recursion_limit")
            ), timeout=_TIMEOUT_SECONDS)
            final_text = _limited(filter_subagent_result(result), _MAX_RESULT)
            # For graph teams the tool result is deliberately only the designated
            # sink. Their whole thread transcript remains inside graph checkpoint.
            canonical = result
            if agent.get("resultAgentId") and agent.get("edges"):
                from .graph_checkpoint import OwnedGraphCheckpointer

                checkpointer = OwnedGraphCheckpointer(self.db, self.owner)
                saved = checkpointer.get_tuple(checkpointer.storage.config(
                    child_generation.conversation_id, child_generation.run_id + ":graph:",
                    event_actor=True))
                if saved:
                    canonical = saved.checkpoint["channel_values"].get("messages", result)
            encoded = _json(canonical)
            if len(encoded.encode()) > _MAX_THREAD_HISTORY:
                raise ValueError("Subagent transcript exceeds durable thread limit")
            self._settle_child_registration(task_id, before_terminal=True, lease_token=token)
            disposition = None
            with self.db.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                task = self._row(db, task_id)
                if task and task["status"] == "running" and task["lease_owner"] == token:
                    now = _now()
                    if task["cancel_requested"]:
                        db.execute("UPDATE subagent_tasks SET status='cancelled',error=?,updated_at=?, "
                                   "lease_owner=NULL,lease_until=NULL WHERE id=?",
                                   ("Detached subagent task cancelled by its parent.", now, task_id))
                        disposition = "aborted"
                    else:
                        db.execute("UPDATE subagent_threads SET messages=?,updated_at=? WHERE id=?",
                                   (encoded, now, task["thread_id"]))
                        db.execute("UPDATE subagent_tasks SET status='completed',result=?,updated_at=?, "
                                   "lease_owner=NULL,lease_until=NULL WHERE id=?",
                                   (final_text, now, task_id))
                        disposition = "complete"
            # Never finish a shared child generation if a different Controller
            # stole this task's lease after its last model/tool safety check.
            if disposition:
                store.finish(self.owner, child_generation.run_id, status=disposition,
                             text=final_text if disposition == "complete" else "")
        except asyncio.CancelledError:
            # Complete only a parent-requested cancel. A cooperative Controller
            # shutdown retains the active child marker and resumable checkpoint.
            if (current := self._get(task_id)) and current["cancel_requested"]:
                self._settle_child_registration(task_id, before_terminal=True,
                                                lease_token=token)
            # Cooperative Controller shutdown only releases the execution lease;
            # a parent-driven cancel stores the requested terminal disposition.
            cancelled_by_parent = False
            with self.db.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                task = self._row(db, task_id)
                if task and task["status"] == "running" and task["lease_owner"] == token:
                    if task["cancel_requested"] and current and current["cancel_requested"]:
                        cancelled_by_parent = True
                        db.execute("UPDATE subagent_tasks SET status='cancelled',error=?,updated_at=?, "
                                   "lease_owner=NULL,lease_until=NULL WHERE id=?",
                                   ("Detached subagent task cancelled by its parent.", _now(), task_id))
                    else:
                        db.execute("UPDATE subagent_tasks SET lease_owner=NULL,lease_until=NULL "
                                   "WHERE id=?", (task_id,))
            if cancelled_by_parent and child_generation:
                store.finish(self.owner, child_generation.run_id, status="aborted")
            raise
        except Exception as exc:
            log.warning("Detached Subagent %s failed: %s", task_id, type(exc).__name__)
            self._settle_child_registration(task_id, before_terminal=True, lease_token=token)
            with self.db.connect() as db:
                changed = db.execute("UPDATE subagent_tasks SET status='error',error=?,updated_at=?,"
                                     "lease_owner=NULL,lease_until=NULL WHERE id=? "
                                     "AND status='running' AND lease_owner=?",
                                     ("Detached subagent task failed (" + type(exc).__name__ + ")",
                                      _now(), task_id, token)).rowcount
            if child_generation and changed:
                store.finish(self.owner, child_generation.run_id, status="error",
                             error="Detached subagent task failed")
        finally:
            if heartbeat:
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat

    def assert_execution_lease(self, task_id: str) -> None:
        """Fence model/tool actions against a replaced or revoked child owner."""
        with self.db.connect() as db:
            row = self._row(db, task_id)
            if row is None or row["status"] != "running" or row["lease_owner"] != _ACTIVE_LEASES.get(task_id) \
                    or row["lease_until"] is None or row["lease_until"] <= _now():
                raise RuntimeSafetyError("Subagent execution lease is no longer held")
            if row["cancel_requested"]:
                raise asyncio.CancelledError("Detached subagent cancellation requested")
            if row["grant_expires"] is not None and row["grant_expires"] <= time.time():
                raise RuntimeSafetyError("Authentication grant expired")

    def has_interrupt(self, task_id: str) -> bool:
        with self.db.connect() as db:
            row = self._row(db, task_id)
            if not row or row["status"] != "running":
                return False
            return db.execute(
                "SELECT 1 FROM subagent_task_controls WHERE task_id=? AND status='accepted' "
                "AND action='interrupt' LIMIT 1", (task_id,)
            ).fetchone() is not None

    def pending(self, task_id: str, boundary: str, existing_ids: set[str]) -> list[dict]:
        """Read unconsumed controls; never mark applied ahead of a checkpoint."""
        allowed = {"preempt": ("interrupt",),
                   "tool": ("steer", "interrupt"),
                   "turn": ("queue", "steer", "interrupt")}
        actions = allowed[boundary]
        with self.db.connect() as db:
            rows = db.execute(
                "SELECT c.* FROM subagent_task_controls c JOIN subagent_tasks t ON t.id=c.task_id "
                "WHERE c.task_id=? AND t.owner=? AND t.parent_conversation_id=? "
                "AND t.status='running' AND c.status='accepted' "
                "ORDER BY c.created_at,c.id", (task_id, self.owner, self.conversation_id),
            ).fetchall()
        return [{"id": row["id"], "role": "user", "content": row["message"],
                 "additional_kwargs": {"source": "steer", "control_id": row["id"]}}
                for row in rows if row["action"] in actions and row["id"] not in existing_ids]

    def acknowledge(self, task_id: str, boundary: str, message_ids: set[str]) -> None:
        """Only acknowledge persisted IDs after the AgentRunner save_state."""
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT id FROM subagent_task_controls WHERE task_id=? "
                              "AND status='accepted'", (task_id,)).fetchall()
            for row in rows:
                if row["id"] in message_ids:
                    db.execute("UPDATE subagent_task_controls SET status='applied',boundary=?, "
                               "updated_at=? WHERE id=? AND status='accepted'",
                               (boundary, _now(), row["id"]))

    async def check(self, args: dict, *, tool_call_id: str = "",
                    parent_run_id: str = "", parent_agent_id: str = "") -> str:
        """Durably fence one source check_background_task invocation before effects."""
        if not tool_call_id or not parent_run_id or not parent_agent_id:
            return await self._check_once(args)
        fingerprint = hashlib.sha256(_json(args).encode()).hexdigest()
        invocation_key = hashlib.sha256(_json([
            parent_run_id, parent_agent_id, tool_call_id,
        ]).encode()).hexdigest()
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM subagent_task_invocations WHERE owner=? AND "
                             "parent_conversation_id=? AND parent_run_id=? AND parent_agent_id=? "
                             "AND tool_call_id=?", (self.owner, self.conversation_id, parent_run_id,
                                                    parent_agent_id, tool_call_id)).fetchone()
            if row:
                if row["fingerprint"] != fingerprint:
                    return _json({"status": "invalid", "message":
                                  "This control invocation id was already used for a different command."})
                if row["status"] == "completed":
                    return row["result"]
                # Crash between the SQLite side effect and final response save:
                # reconstruct only when durable proof names THIS invocation.
                task_id = args.get("background_task_id")
                task = self._row(db, task_id) if isinstance(task_id, str) else None
                if task and args.get("action", "poll") == "poll" and task["result_claim_key"] == invocation_key:
                    return _json(_out(_snapshot(task), status=task["status"],
                                      result=task["result"] if task["status"] == "completed" else None,
                                      error=task["error"] if task["status"] != "completed" else None))
                if task:
                    receipt = db.execute("SELECT id FROM subagent_task_controls "
                                         "WHERE task_id=? AND invocation_key=?", (task_id, invocation_key)).fetchone()
                    if receipt:
                        return _json(_out(_snapshot(task), status="accepted",control_id=receipt["id"]))
                return _json({"status": "unavailable", "message":
                              "This prior control invocation has an uncertain result; poll with a new tool call ID."})
            parent = db.execute("SELECT 1 FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                                "LEFT JOIN subagent_tasks t ON t.child_run_id=r.id "
                                "WHERE r.id=? AND c.owner=? AND (r.conversation_id=? OR "
                                "(t.owner=? AND t.parent_conversation_id=? AND t.status='running'))",
                                (parent_run_id, self.owner, self.conversation_id,
                                 self.owner, self.conversation_id)).fetchone()
            if not parent:
                raise PermissionError("Background control run is not in the trusted parent scope")
            now = _now()
            db.execute("INSERT INTO subagent_task_invocations "
                       "(owner,parent_conversation_id,parent_run_id,parent_agent_id,tool_call_id,"
                       "fingerprint,status,created_at,updated_at) "
                       "VALUES(?,?,?,?,?,?,?,?,?)",
                       (self.owner, self.conversation_id,parent_run_id,parent_agent_id,
                        tool_call_id,fingerprint,"reserved",now,now))
        output = await self._check_once(args, invocation_key=invocation_key)
        with self.db.connect() as db:
            db.execute("UPDATE subagent_task_invocations SET status='completed',result=?,updated_at=? "
                       "WHERE owner=? AND parent_conversation_id=? AND parent_run_id=? "
                       "AND parent_agent_id=? AND tool_call_id=? AND status='reserved'",
                       (output,_now(),self.owner,self.conversation_id,parent_run_id,
                        parent_agent_id,tool_call_id))
        return output

    async def _check_once(self, args: dict, *, invocation_key: str | None = None) -> str:
        """Host check_background_task status, list, one-shot claim and cancel."""
        raw_id = args.get("background_task_id")
        if isinstance(raw_id, str) and len(raw_id.strip()) > 256:
            return _json({"status": "invalid", "message": "A background_task_id cannot exceed 256 characters."})
        task_id = raw_id.strip() if isinstance(raw_id, str) else ""
        action = args.get("action") or "poll"
        if not task_id:
            if action != "poll":
                return _json({"status": "invalid", "message": "A background_task_id is required for control actions."})
            listed = [_out(task) for task in self.list()]
            return _json({"tasks": listed,
                          "outstanding": sum(task["status"] == "running" for task in listed)})
        row = self._get(task_id)
        if row is None:
            return _json({"status": "not_found", "background_task_id": task_id})
        if action == "poll":
            await self._ensure_active(task_id)
            with self.db.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = self._row(db, task_id)
                task = _snapshot(row)
                if task["status"] == "running":
                    return _json(_out(task))
                if task["resultClaimed"]:
                    return _json(_out(task, status="claimed"))
                db.execute("UPDATE subagent_tasks SET result_claimed=1,result_claim_key=?,"
                           "updated_at=? WHERE id=?", (invocation_key, _now(), task_id))
                task = {**task, "resultAvailable": False, "resultClaimed": True}
                return _json(_out(task, result=row["result"] if task["status"] == "completed" else None,
                                  error=row["error"] if task["status"] != "completed" else None))
        if action in {"steer", "queue", "interrupt", "cancel_message"}:
            with self.db.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = self._row(db, task_id)
                if row["status"] != "running":
                    return _json(_out(_snapshot(row), status="not_running"))
                if action == "cancel_message":
                    control_id = args.get("control_id")
                    if not isinstance(control_id, str) or not 0 < len(control_id) <= 256:
                        return _json({"status": "invalid", "message": "A control_id is required."})
                    receipt = db.execute("SELECT * FROM subagent_task_controls WHERE id=? "
                                         "AND task_id=? AND status='accepted'",
                                         (control_id, task_id)).fetchone()
                    if receipt is None:
                        return _json(_out(_snapshot(row), status="control_not_found"))
                    db.execute("UPDATE subagent_task_controls SET status='rejected',reason='withdrawn',"
                               "updated_at=? WHERE id=?", (_now(), control_id))
                    return _json(_out(_snapshot(self._row(db, task_id)), status="accepted",
                                  control_id=control_id))
                message = args.get("message")
                if not isinstance(message, str) or not message.strip():
                    return _json({"status": "invalid", "message": "A non-empty message is required."})
                if len(message) > 64 * 1024:
                    return _json({"status": "invalid", "message": "Message exceeds 65536 characters."})
                count = db.execute("SELECT count(*) FROM subagent_task_controls WHERE "
                                   "task_id=? AND status='accepted'", (task_id,)).fetchone()[0]
                if count >= 32:
                    return _json({"status": "invalid", "message": "Task already has 32 pending messages."})
                control_id = "control_" + secrets.token_hex(16)
                now = _now()
                db.execute("INSERT INTO subagent_task_controls "
                           "(id,task_id,invocation_key,action,message,status,created_at,updated_at) "
                           "VALUES(?,?,?,?,?,?,?,?)",
                           (control_id, task_id, invocation_key, action, message.strip(), "accepted", now, now))
                return _json(_out(_snapshot(self._row(db, task_id)), status="accepted",
                                  control_id=control_id))
        if action == "cancel":
            with self.db.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = self._row(db, task_id)
                if row["status"] != "running":
                    return _json(_out(_snapshot(row), status="not_running"))
                db.execute("UPDATE subagent_tasks SET cancel_requested=1,updated_at=? WHERE id=?",
                           (_now(), task_id))
            active = _TASKS.get(task_id)
            if active and not active.done():
                active.cancel()
            else:
                # Another replica may still own the live executor. Never claim
                # cancellation completed while a remote lease is unexpired.
                await self._ensure_active(task_id)
            refreshed = self._get(task_id)
            return _json(_out(_snapshot(refreshed), status=(
                "cancelled" if refreshed["status"] == "cancelled" else "cancellation_requested"
            )))
        return _json({"status": "invalid", "background_task_id": task_id,
                      "message": "This control action is not available until the Subagent task boundary is enabled."})


async def shutdown_subagent_tasks() -> None:
    """Release Controller-owned execution leases while preserving running tasks."""
    tasks = list(_TASKS.values()) + list(_RECOVERY_TASKS)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def check_background_task_tools() -> list[dict]:
    """LibreChat background.ts CHECK_BACKGROUND_TASK_PARAMETERS (source schema)."""
    return [{"type": "function", "function": {
        "name": "check_background_task",
        "description": (
            "Provide a background_task_id to inspect one task; omit it to list every "
            "background task in this thread. Use action poll, steer, queue, "
            "interrupt, cancel or cancel_message to control a detached subagent. "
            "A result is claimable exactly once."
        ),
        "parameters": {"type": "object", "properties": {
            "background_task_id": {"type": "string", "maxLength": 256,
                                   "description": "The id returned when the tool or subagent was dispatched. Omit to list all background tasks in this thread."},
            "action": {"type": "string",
                       "enum": ["poll", "steer", "queue", "interrupt", "cancel", "cancel_message"],
                       "description": "Defaults to poll. Cancel applies to subagents and may apply to ordinary tools when enabled by the deployment; other controls apply only to subagents."},
            "message": {"type": "string", "maxLength": 64 * 1024,
                        "description": "Required for steer, queue, or interrupt."},
            "control_id": {"type": "string", "maxLength": 256,
                           "description": "Required for cancel_message; use the id returned by a prior control action."},
        }, "required": []},
    }}]


def active_child_generations(database: Any) -> set[str]:
    """Keep resumable detached children out of ordinary orphan-finalization."""
    with database.connect() as db:
        rows = db.execute("SELECT child_run_id FROM subagent_tasks "
                          "WHERE status='running' AND child_run_id IS NOT NULL").fetchall()
    return {row["child_run_id"] for row in rows}


async def recover_subagent_tasks(database: Any, *, stream_tools: Callable, stream_text: Callable) -> int:
    """Rejoin on-disk child leases on Controller startup without a new scheduler.

    The original JS host leases may still belong to a different live replica;
    do not steal them early. Retry at lease expiry, using the same AgentRunner
    and shared generation task executor as a freshly admitted child.
    """
    with database.connect() as db:
        rows = db.execute("SELECT owner,parent_conversation_id,id,lease_until FROM subagent_tasks "
                          "WHERE status='running' ORDER BY created_at").fetchall()
    count = 0
    for row in rows:
        host = SQLiteSubagentTaskHost(database, row["owner"], row["parent_conversation_id"],
                                      stream_tools=stream_tools, stream_text=stream_text)
        task_id = row["id"]
        lease_until = row["lease_until"] or 0
        if lease_until <= _now():
            await host._ensure_active(task_id)
            count += 1
        else:
            async def later(owner=host, key=task_id, expires=lease_until):
                await asyncio.sleep(max(0, (expires - _now()) / 1000) + .05)
                await owner._ensure_active(key)
            future = asyncio.create_task(later(), name="webui-subagent-recover-" + task_id)
            _RECOVERY_TASKS.add(future)
            future.add_done_callback(_RECOVERY_TASKS.discard)
            count += 1
    return count
