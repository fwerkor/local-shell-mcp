"""Controller-owned durable native Job/Shell leases.

The intent is committed before native execution. Native IDs are observed from
structured results or a read-only idempotency lookup; never guessed from names
or fetched from unfiltered listings. Cancellation uses the original executor.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any

from ..audit import audit
from .machine_permissions import authorize_machine_action

log = logging.getLogger(__name__)
_STARTS = frozenset({"job_start", "shell_start", "job_retry", "remote_transfer"})
_TRACKED = _STARTS | {"run_shell", "run_python"}
_CONTROL = {"job_stop": ("job", "job_id"), "job_retry": ("job", "job_id"),
            "shell_stop": ("shell", "session_id"), "shell_send": ("shell", "session_id")}
_POLL = 2.0


def _database():
    from ..settings import get_settings
    from ..sqlite_store import shared_database

    return shared_database(get_settings().state_dir.resolve())


def _stamp() -> int:
    return time.time_ns() // 1000


def _kind(name: str) -> str:
    return "shell" if name == "shell_start" else ("retry" if name == "job_retry" else "job")


def _requirements(name: str, arguments: dict) -> dict[str, str]:
    if name == "job_retry" and arguments.get("machine") in (None, "", "local"):
        from ..jobs import job_retry_machine_requirements

        requirements = {"local": "write"}
        for machine, level in job_retry_machine_requirements(arguments.get("job_id")):
            machine = machine or "local"
            if level == "write" or requirements.get(machine) != "write":
                requirements[machine] = level
        return requirements
    if name == "remote_transfer":
        source = arguments.get("source_machine") or "local"
        destination = arguments.get("destination_machine") or "local"
        return {source: "write" if source == destination else "read", destination: "write"}
    return {arguments.get("machine") or "local": "write"}


def _fingerprint(name: str, arguments: dict) -> str:
    # The request identity excludes only a caller-visible, optional dedup key.
    payload = {k: v for k, v in arguments.items() if k != "idempotency_key"}
    return hashlib.sha256(json.dumps([name, payload], sort_keys=True,
                                     ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class Intent:
    id: str
    name: str
    key: str | None


def reserve(owner: str, conversation_id: str, run_id: str | None, call_id: str,
            name: str, arguments: dict, scopes: set[str], expires: int | None) -> Intent:
    """Atomic ownership reservation prior to *any* native creation RPC."""
    import sqlite3

    if name not in _TRACKED or (name in {"run_shell", "run_python"} and not arguments.get("persist_on_timeout")):
        raise ValueError("Not a durable creation")
    machine = "local" if name == "remote_transfer" else arguments.get("machine") or "local"
    # A user-provided native key could already belong to a public MCP client
    # (or be claimed concurrently after a read-only lookup). Never adopt it.
    # Native MCP clients continue to support explicit idempotency keys; Agent
    # creation uses only a high-entropy key allocated by this Controller.
    if arguments.get("idempotency_key") is not None:
        raise PermissionError("Agent durable creation does not accept caller-supplied idempotency keys")
    key = "agent-" + secrets.token_hex(24)
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    # Separate native mutation namespaces: job start and job retry differ.
    identity = hashlib.sha256(json.dumps([owner, conversation_id, run_id, call_id, name],
                                      separators=(",", ":")).encode()).hexdigest()
    fingerprint = _fingerprint(name, arguments)
    required = _requirements(name, arguments)
    with _database().connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM agent_durable_tasks WHERE id=?", (identity,)).fetchone()
        if row:
            if row["fingerprint"] != fingerprint:
                raise PermissionError("A replayed tool call cannot change a durable task request")
            if row["state"] not in ("reserved", "active"):
                raise PermissionError("Durable task request was cancelled or cannot be replayed")
            return Intent(identity, name, row["idempotency_key"])
        conversation = db.execute("SELECT owner FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if conversation is None or conversation["owner"] != owner:
            raise PermissionError("Conversation ownership is no longer valid")
        if run_id:
            run = db.execute("SELECT status FROM runs WHERE id=? AND conversation_id=?", (run_id, conversation_id)).fetchone()
            if run is None or run["status"] in {"aborted", "error", "interrupted"}:
                raise PermissionError("Generation can no longer start tasks")
            if db.execute("SELECT 1 FROM agent_run_cancellations WHERE run_id=?", (run_id,)).fetchone():
                raise PermissionError("Generation was cancelled")
        # Native key ownership is exclusive for each operation and machine.
        try:
            db.execute(
                "INSERT INTO agent_durable_tasks(id,owner,conversation_id,run_id,call_id,tool,kind,machine,"
                "requirements,fingerprint,idempotency_key,key_hash,scopes,grant_expires,state,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (identity, owner, conversation_id, run_id, call_id, name, _kind(name), machine,
                 json.dumps(required), fingerprint, key, key_hash, json.dumps(sorted(scopes)), expires,
                 "reserved", _stamp(), _stamp()),
            )
        except sqlite3.IntegrityError as exc:
            raise PermissionError("Native idempotency key is already owned by another Agent call") from exc
    audit("agent_durable_intent", owner=owner, conversation_id=conversation_id,
          tool=name, machine=machine, ok=True)
    return Intent(identity, name, key)


def check_intent(intent: Intent) -> None:
    with _database().connect() as db:
        row = db.execute("SELECT state,run_id FROM agent_durable_tasks WHERE id=?", (intent.id,)).fetchone()
        if row is not None and row["run_id"]:
            run = db.execute("SELECT status FROM runs WHERE id=?", (row["run_id"],)).fetchone()
            if run is None or run["status"] in {"aborted", "error", "interrupted"}:
                raise PermissionError("The generation that created this task has ended")
    if row is None or row["state"] not in {"reserved", "active"}:
        raise PermissionError("Durable task authorization was revoked")


def owned(owner: str, conversation_id: str, name: str, arguments: dict) -> None:
    """An Agent cannot mutate a foreign/manual native task through an ID."""
    spec = _CONTROL.get(name)
    if spec is None:
        return
    kind, field = spec
    native_id = arguments.get(field)
    machine = arguments.get("machine") or "local"
    if not isinstance(native_id, str) or not native_id:
        raise PermissionError("A tracked native task ID is required")
    with _database().connect() as db:
        # Native job_retry reuses the original job_id. A stopped own job may
        # be retried; subsequent stop must also recognize that retry lease.
        if name == "job_retry":
            row = db.execute("SELECT 1 FROM agent_durable_tasks WHERE owner=? AND conversation_id=? "
                             "AND kind IN ('job','retry') AND machine=? AND native_id=? "
                             "AND state IN ('active','stopped') LIMIT 1",
                             (owner, conversation_id, machine, native_id)).fetchone()
        elif kind == "job":
            row = db.execute("SELECT 1 FROM agent_durable_tasks WHERE owner=? AND conversation_id=? "
                             "AND kind IN ('job','retry') AND machine=? AND native_id=? AND state='active' LIMIT 1",
                             (owner, conversation_id, machine, native_id)).fetchone()
        else:
            row = db.execute("SELECT 1 FROM agent_durable_tasks WHERE owner=? AND conversation_id=? "
                             "AND kind=? AND machine=? AND native_id=? AND state='active' LIMIT 1",
                             (owner, conversation_id, kind, machine, native_id)).fetchone()
    if not row:
        raise PermissionError("Native task does not belong to this conversation")


def _payload(result: Any) -> dict:
    if isinstance(result, tuple) and len(result) == 2:
        result = result[1] if result[1] is not None else result[0]
    if hasattr(result, "model_dump"):
        result = result.model_dump(mode="json")
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except (ValueError, TypeError):
            return {}
    if not isinstance(result, dict):
        return {}
    if "structuredContent" in result and isinstance(result["structuredContent"], dict):
        result = result["structuredContent"]
    if "structured_content" in result and isinstance(result["structured_content"], dict):
        result = result["structured_content"]
    if "data" in result and isinstance(result["data"], dict):
        result = result["data"]
    if "job" in result and isinstance(result["job"], dict):
        result = result["job"]
    return result


def bind(intent: Intent, result: Any) -> bool:
    """Bind only a genuine executor-returned ID; global uniqueness forbids aliasing."""
    data = _payload(result)
    ident = data.get("session_id" if intent.name == "shell_start" else "job_id")
    if not isinstance(ident, str) or not ident:
        return False
    with _database().connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT native_id,state FROM agent_durable_tasks WHERE id=?", (intent.id,)).fetchone()
        if row is None or row["native_id"] not in (None, ident):
            raise PermissionError("Native task identity changed after reservation")
        try:
            db.execute("UPDATE agent_durable_tasks SET native_id=?,state=CASE WHEN state='reserved' "
                       "THEN 'active' ELSE state END, updated_at=? WHERE id=?", (ident, _stamp(), intent.id))
        except Exception as exc:
            raise PermissionError("Native task identity already belongs to another Agent call") from exc
    return True


def mark_stopped(owner: str, conversation_id: str, name: str, arguments: dict) -> None:
    spec = _CONTROL.get(name)
    if spec is None or name not in ("job_stop", "shell_stop"):
        return
    kind, field = spec
    with _database().connect() as db:
        if kind == "job":
            db.execute("UPDATE agent_durable_tasks SET state='stopped',updated_at=? WHERE owner=? AND "
                       "conversation_id=? AND kind IN ('job','retry') AND machine=? AND native_id=? "
                       "AND state='active'",
                       (_stamp(), owner, conversation_id, arguments.get("machine") or "local", arguments[field]))
        else:
            db.execute("UPDATE agent_durable_tasks SET state='stopped',updated_at=? WHERE owner=? AND "
                       "conversation_id=? AND kind=? AND machine=? AND native_id=? AND state='active'",
                       (_stamp(), owner, conversation_id, kind, arguments.get("machine") or "local", arguments[field]))


def is_run_cancelled(run_id: str) -> bool:
    with _database().connect() as db:
        return db.execute("SELECT 1 FROM agent_run_cancellations WHERE run_id=?", (run_id,)).fetchone() is not None



def cancel_run(owner: str, run_id: str) -> None:
    """Persist explicit abort before cancelling provider/tool coroutine."""
    with _database().connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT c.owner FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                         "WHERE r.id=?", (run_id,)).fetchone()
        if not row or row["owner"] != owner:
            raise PermissionError("Generation owner mismatch")
        db.execute("INSERT OR IGNORE INTO agent_run_cancellations(run_id,created_at) VALUES(?,?)",
                   (run_id, _stamp()))
        db.execute("UPDATE agent_durable_tasks SET state='cancel_pending',updated_at=? "
                   "WHERE run_id=? AND state IN ('reserved','active','unknown')", (_stamp(), run_id))


def _revoked(row: Any) -> bool:
    from .routes import _repo

    try:
        if _repo().conversation(row["owner"], row["conversation_id"]) is None:
            return True
        if row["run_id"]:
            with _repo().database.connect() as db:
                if db.execute("SELECT 1 FROM agent_run_cancellations WHERE run_id=?", (row["run_id"],)).fetchone():
                    return True
                run = db.execute("SELECT status FROM runs WHERE id=?", (row["run_id"],)).fetchone()
                # A Controller restart marks in-flight generations interrupted,
                # but native background jobs must survive that restart. Only an
                # explicit abort revokes an otherwise still-authorized lease.
                if run is not None and run["status"] == "aborted":
                    return True
        for machine, operation in json.loads(row["requirements"]).items():
            authorize_machine_action(row["owner"], row["conversation_id"], machine, operation,
                                     scopes=set(json.loads(row["scopes"])), expires=row["grant_expires"])
        return False
    except (PermissionError, KeyError, ValueError):
        return True


def mark_revoked(owner: str) -> int:
    """Latch revocation using the same repository as the WebUI permission write."""
    from .routes import _repo

    repository = _repo()
    with repository.database.connect() as db:
        rows = [dict(row) for row in db.execute(
            "SELECT * FROM agent_durable_tasks WHERE owner=? "
            "AND state IN ('reserved','active','unknown')", (owner,))]
    revoked = [row["id"] for row in rows if _revoked(row)]
    if revoked:
        with repository.database.connect() as db:
            db.executemany("UPDATE agent_durable_tasks SET state='cancel_pending',updated_at=?,"
                           "next_attempt_at=NULL WHERE id=? AND state IN ('reserved','active','unknown')",
                           [(_stamp(), ident) for ident in revoked])
    return len(revoked)


async def _lookup(row: Any) -> str | None:
    """Read only native idempotency records; never replay creation after revoke."""
    from .. import jobs, shell_ops, tools
    from ..settings import get_settings

    name = row["tool"]
    if name == "shell_start":
        request = "shell_lookup_idempotency"
        params = {"idempotency_key": row["idempotency_key"], "operation": "start"}
    else:
        request = "job_lookup_idempotency"
        action = "retry" if name == "job_retry" else "start"
        params = {"idempotency_key": row["idempotency_key"], "action": action}
    if row["machine"] == "local":
        result = (shell_ops.lookup_shell_idempotency(**params) if name == "shell_start"
                  else jobs.lookup_job_idempotency(**params))
    else:
        result = await tools._remote_call(get_settings(), row["machine"], request, params, timeout_s=15)
    if getattr(result, "isError", False) or (hasattr(result, "ok") and not result.ok) or (
        isinstance(result, dict) and result.get("ok") is False
    ):
        raise RuntimeError("Native idempotency lookup is unavailable")
    data = _payload(result)
    return data.get("session_id" if name == "shell_start" else "job_id")


async def _stop(row: Any) -> bool:
    from .. import jobs, shell_ops, tools
    from ..settings import get_settings

    native_id = row["native_id"]
    if not native_id:
        return False
    if row["machine"] == "local":
        result = await (shell_ops.kill_shell(native_id) if row["kind"] == "shell" else jobs.stop_job(native_id))
    else:
        command = "shell_kill" if row["kind"] == "shell" else "job_stop"
        field = "session_id" if row["kind"] == "shell" else "job_id"
        result = await tools._remote_call(get_settings(), row["machine"], command, {field: native_id}, timeout_s=30)
    if (getattr(result, "isError", False) or getattr(result, "ok", True) is False
            or (isinstance(result, dict) and result.get("ok") is False)):
        return False
    data = _payload(result)
    if row["kind"] == "shell":
        # An RPC delivered successfully is not proof that tmux/ConPTY killed
        # the session; the native tool reports the actual outcome separately.
        return data.get("killed") is True
    return data.get("status") in jobs.TERMINAL_STATUSES


async def _reconcile_one(row: dict) -> int:
    if row["state"] != "cancel_pending" and not _revoked(row):
        return 0
    try:
        native_id = row["native_id"] or await _lookup(row)
        if native_id:
            with _database().connect() as db:
                try:
                    db.execute("UPDATE agent_durable_tasks SET native_id=?,state='cancel_pending',updated_at=? "
                               "WHERE id=? AND state IN ('reserved','active','cancel_pending','unknown')",
                               (native_id, _stamp(), row["id"]))
                except Exception:
                    log.warning("Native ID ownership conflict for durable Agent task %s", row["id"])
                    return 0
            row["native_id"] = native_id
            if await _stop(row):
                with _database().connect() as db:
                    db.execute("UPDATE agent_durable_tasks SET state='stopped',updated_at=? WHERE id=? "
                               "AND state='cancel_pending'", (_stamp(), row["id"]))
                audit("agent_durable_cancel", owner=row["owner"], conversation_id=row["conversation_id"],
                      tool=row["tool"], machine=row["machine"], native_id=native_id, ok=True)
                return 1
        # No identity means no safe cancellation target; retain intent for reconciliation.
        error = "native ID not yet confirmed" if not native_id else "native cancellation not confirmed"
    except Exception as exc:
        error = type(exc).__name__
    with _database().connect() as db:
        db.execute("UPDATE agent_durable_tasks SET state='cancel_pending',last_error=?,"
                   "next_attempt_at=?,updated_at=? WHERE id=? AND state!='stopped'",
                   (error, _stamp() + 5_000_000, _stamp(), row["id"]))
    return 0


async def sweep() -> int:
    """Bounded-concurrency native cancellation across all pending machines."""
    with _database().connect() as db:
        rows = [dict(row) for row in db.execute(
            "SELECT * FROM agent_durable_tasks WHERE state IN ('reserved','active','cancel_pending','unknown') "
            "AND (next_attempt_at IS NULL OR next_attempt_at<=?) "
            "ORDER BY CASE WHEN state='cancel_pending' THEN 0 ELSE 1 END, created_at", (_stamp(),))]
    semaphore = asyncio.Semaphore(8)

    async def limited(row: dict) -> int:
        async with semaphore:
            return await _reconcile_one(row)

    return sum(await asyncio.gather(*(limited(row) for row in rows)))


async def serve() -> None:
    """One Controller reconciler; Worker has no WebUI scheduler dependencies."""
    while True:
        try:
            await sweep()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Durable Agent task reconciliation failed")
        await asyncio.sleep(_POLL)
