"""Original LibreChat Agent Trigger remote source identity and SQLite delivery lane.

Source: LibreChat v0.8.8 packages/api/src/agents/triggers/{envelope,
 delivery,engine,ingress,bindings}.ts. API-key identity is intentionally
 distinct from Controller OAuth and the trusted subagent completion channel.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from .subagent_wakeup import _retry_at

log = logging.getLogger(__name__)
_TOKEN = re.compile(r"^[A-Za-z0-9._~:/+=-]{1,256}$")
_EVENT_KEY_PREFIX = "lsm_evt_"
_PROCESS = secrets.token_hex(16)
_WORKERS: dict[str, asyncio.Task] = {}
_OWNED: dict[str, tuple[str, str]] = {}
_MAX_RETRIES = 8
_LEASE_MS = 120_000


def _now() -> int:
    return int(time.time() * 1000)


def _iso(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat(
        timespec="milliseconds",
    ).replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _js(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def mint_source_key(database: Any, owner: str, *, label: str = "event-source",
                    permissions: tuple[str, ...] = ("fire", "continue", "steer"),
                    expires_at: int | None = None) -> dict:
    if not owner or len(label) > 128 or not label.strip():
        raise ValueError("A nonempty event source owner and label are required")
    allowed = {"fire", "continue", "steer"}
    if not permissions or any(mode not in allowed for mode in permissions):
        raise ValueError("Invalid event source permissions")
    if expires_at is not None and (type(expires_at) is not int or expires_at <= _now()):
        raise ValueError("Event source expiration must be in the future")
    token = _EVENT_KEY_PREFIX + secrets.token_urlsafe(48)
    key_id = "eventkey_" + secrets.token_hex(16)
    with database.connect() as db:
        db.execute("INSERT INTO agent_event_source_keys(id,owner,label,token_hash,permissions,"
                   "expires_at,created_at) VALUES(?,?,?,?,?,?,?)",
                   (key_id, owner, label, hashlib.sha256(token.encode()).hexdigest(),
                    _json(sorted(set(permissions))), expires_at, _now()))
    return {"id": key_id, "label": label, "token": token,
            "permissions": sorted(set(permissions)), "expiresAt": expires_at}


def validate_source_key(database: Any, token: str) -> dict | None:
    if not isinstance(token, str) or not token.startswith(_EVENT_KEY_PREFIX) or len(token) > 256:
        return None
    digest = hashlib.sha256(token.encode()).hexdigest()
    with database.connect() as db:
        row = db.execute("SELECT id,owner,permissions,expires_at FROM agent_event_source_keys "
                         "WHERE token_hash=? AND revoked_at IS NULL AND "
                         "(expires_at IS NULL OR expires_at>?)",
                         (digest, _now())).fetchone()
    return ({"id": row["id"], "owner": row["owner"],
             "permissions": json.loads(row["permissions"])} if row else None)


def revoke_source_key(database: Any, owner: str, key_id: str) -> bool:
    with database.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        now = _now()
        updated = db.execute("UPDATE agent_event_source_keys SET revoked_at=? "
                             "WHERE id=? AND owner=? AND revoked_at IS NULL",
                             (now, key_id, owner)).rowcount
        if updated:
            # The credential is the trusted owner of *all* already admitted
            # event actors, not just future ingress. Revoke in the same
            # transaction so another Controller cannot renew a leased actor.
            db.execute("UPDATE agent_event_deliveries SET status='dead',error_code=?,"
                       "error_type=?,lease_owner=NULL,lease_until=NULL,updated_at=? "
                       "WHERE owner=? AND source_key_id=? AND status IN ('pending','leased')",
                       ("SOURCE_REVOKED", "PermissionError", now, owner, key_id))
        return updated == 1


def source_keys(database: Any, owner: str) -> list[dict]:
    with database.connect() as db:
        rows = db.execute("SELECT id,label,permissions,expires_at,revoked_at,created_at "
                          "FROM agent_event_source_keys WHERE owner=? ORDER BY created_at DESC,id",
                          (owner,)).fetchall()
    return [{"id": row["id"], "label": row["label"],
             "permissions": json.loads(row["permissions"]), "expiresAt": row["expires_at"],
             "revokedAt": row["revoked_at"], "createdAt": row["created_at"]}
            for row in rows]


_NO_PARENT = "00000000-0000-0000-0000-000000000000"  # LibreChat Constants.NO_PARENT


def binding_key(owner: str, source_key_id: str, registration_key: str) -> str:
    """Exact bindings.ts:bindingId for the single-user (no tenant) scope."""
    return "evtbind_" + hashlib.sha256(("librechat:agent-event-binding:v1\0" +
                                       owner + "\0\0" + source_key_id + "\0" +
                                       registration_key).encode()).hexdigest()[:48]


def bound_child(database: Any, owner: str, source_key_id: str, binding_id: str) -> dict | None:
    if not re.fullmatch(r"evtbind_[a-f0-9]{48}", binding_id):
        raise ValueError("Event binding is invalid")
    with database.connect() as db:
        binding = db.execute("SELECT * FROM agent_event_bindings WHERE id=? AND owner=? "
                             "AND source_key_id=?", (binding_id, owner, source_key_id)).fetchone()
        if binding is None:
            return None
        if not db.execute("SELECT 1 FROM conversations WHERE id=? AND owner=?",
                          (binding["parent_conversation_id"], owner)).fetchone():
            return None
    return dict(binding)


def register_bound_child(database: Any, owner: str, source_key_id: str,
                         registration_key: str, *, actor_id: str,
                         parent_conversation_id: str, parent_message_id: str,
                         target_agent_id: str) -> dict:
    """Source bindings.ts direct-child-only reservation; fail closed without guard.

    A durable registration is not visible until the PR352 child-thread write
    protector commits its owner+parent run marker. We never infer the root
    conversation from an untrusted external payload after that enrollment.
    """
    from .agents import AgentRepository

    _string(actor_id, "actorId", 128)
    _string(parent_conversation_id, "parentConversationId", 256)
    _string(parent_message_id, "parentMessageId", 256)
    _string(target_agent_id, "target.agentId", 256)
    if not _TOKEN.fullmatch(registration_key):
        raise ValueError("Idempotency-Key contains invalid characters")
    identifier = binding_key(owner, source_key_id, registration_key)
    with database.connect() as db:
        parent = db.execute("SELECT id,agent_id,metadata FROM conversations "
                            "WHERE id=? AND owner=?", (parent_conversation_id, owner)).fetchone()
        message = db.execute("SELECT role FROM messages WHERE id=? AND conversation_id=?",
                             (parent_message_id, parent_conversation_id)).fetchone()
        if not parent or not message or message["role"] != "assistant":
            raise KeyError("Parent Agent conversation or reply was not found")
        try:
            parent_meta = json.loads(parent["metadata"])
        except (ValueError, TypeError) as exc:
            raise PermissionError("Parent Agent lineage is invalid") from exc
        if not isinstance(parent_meta, dict) or parent_meta.get("subagentThread"):
            raise PermissionError("An event actor parent must be an ordinary conversation")
        runs = db.execute("SELECT id,agent_id,state,status FROM runs WHERE conversation_id=? "
                          "ORDER BY created_at DESC", (parent_conversation_id,)).fetchall()
        parent_run = next((run for run in runs
                           if json.loads(run["state"]).get("responseMessageId") == parent_message_id
                           and run["status"] == "complete"), None)
        if parent_run is None or not parent_run["agent_id"]:
            raise PermissionError("Parent Agent reply is not an authoritative completed run")
        parent_agent_id = parent_run["agent_id"]
        old = db.execute("SELECT * FROM agent_event_bindings WHERE id=?", (identifier,)).fetchone()
        if old:
            if (old["owner"], old["source_key_id"], old["actor_id"],
                    old["parent_conversation_id"], old["parent_message_id"],
                    old["parent_agent_id"], old["agent_id"]) != (
                        owner, source_key_id, actor_id, parent_conversation_id,
                        parent_message_id, parent_agent_id, target_agent_id):
                raise ValueError("Idempotency-Key was already used for a different event binding")
            return {"id": identifier, "actorId": actor_id,
                    "agentId": target_agent_id, "threadId": old["conversation_id"]}
    config = AgentRepository(database).get(owner, parent_agent_id)
    child = AgentRepository(database).get(owner, target_agent_id)
    if config is None or child is None:
        raise PermissionError("Parent or child Agent is no longer available")
    subagents = config.get("subagents")
    allowed = (isinstance(subagents, dict) and subagents.get("enabled") is True and
               ((parent_agent_id == target_agent_id and subagents.get("allowSelf") is not False)
                or target_agent_id in subagents.get("agent_ids", [])))
    if not allowed:
        raise PermissionError("Target Agent is not a configured direct child")
    # With PR352 absent, accepting a bound actor could bypass its editable
    # Artifact/HTTP child guard. Reject rather than create a writable child.
    try:
        from .child_thread_activity import ActiveChildThreads
    except ImportError as exc:
        raise RuntimeError("Child conversation write guard must be integrated before bindings") from exc
    thread_id = str(uuid.uuid4())
    ActiveChildThreads(database).activate(owner, thread_id, parent_run["id"])
    now = _now()
    child_meta = {"agentEventBinding": {"bindingId": identifier,
                                       "sourceKeyId": source_key_id, "actorId": actor_id},
                  "subagentThread": {"rootConversationId": parent_conversation_id,
                                     "parentConversationId": parent_conversation_id,
                                     "parentMessageId": parent_message_id,
                                     "parentToolCallId": "event-binding:" + identifier,
                                     "parentAgentId": parent_agent_id,
                                     "subagentType": target_agent_id,
                                     "subagentKind": "agent", "depth": 1}}
    with database.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute("SELECT * FROM agent_event_bindings WHERE id=?", (identifier,)).fetchone()
        if prior:
            return {"id": identifier, "actorId": actor_id,
                    "agentId": target_agent_id, "threadId": prior["conversation_id"]}
        db.execute("INSERT INTO conversations(id,owner,title,agent_id,endpoint,archived,"
                   "metadata,created_at,updated_at) VALUES(?,?,?,?,?,1,?,?,?)",
                   (thread_id, owner, ("Agent actor: " + actor_id)[:120], target_agent_id,
                    "agents", _json(child_meta), now, now))
        db.execute("INSERT INTO agent_event_bindings(id,owner,source_key_id,actor_id,"
                   "parent_conversation_id,parent_message_id,parent_agent_id,agent_id,"
                   "conversation_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (identifier, owner, source_key_id, actor_id, parent_conversation_id,
                    parent_message_id, parent_agent_id, target_agent_id, thread_id, now))
    return {"id": identifier, "actorId": actor_id, "agentId": target_agent_id,
            "threadId": thread_id}


def delivery_key(envelope: dict) -> str:
    """Direct port of original envelope.ts:getAgentTriggerIdempotencyKey."""
    target = envelope["target"]
    principal = envelope["principal"]
    source = envelope["event"]["source"]
    values = [envelope["version"], principal.get("tenantId", ""), principal["userId"],
              source["type"], source["id"], envelope["event"]["type"],
              envelope["event"]["id"], envelope["deliveryId"], envelope["mode"],
              target["agentId"], "" if envelope["mode"] == "fire" else target["conversationId"],
              target["parentMessageId"] if envelope["mode"] == "continue" else "",
              target.get("bindingId", "") if envelope["mode"] == "continue" else "",
              target.get("sourceKeyId", "") if envelope["mode"] == "continue" else ""]
    return "trigger_" + hashlib.sha256(_js(values).encode()).hexdigest()


def _lane(envelope: dict, ordering_key: str | None) -> str:
    source = envelope["event"]["source"]
    if ordering_key is not None:
        if not isinstance(ordering_key, str) or not 1 <= len(ordering_key.strip()) <= 256:
            raise ValueError("orderingKey must contain 1-256 characters")
        lane = ["explicit", ordering_key.strip()]
    else:
        lane = ["default", source["type"], source["id"], envelope["mode"],
                envelope["target"]["agentId"],
                "" if envelope["mode"] == "fire" else envelope["target"]["conversationId"]]
    return "trigger_lane_" + _digest([envelope["principal"].get("tenantId", ""),
                                      envelope["principal"]["userId"], lane])


def _string(value: Any, label: str, limit: int = 131_072) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > limit:
        raise ValueError(f"{label} must be a nonempty string of at most {limit} bytes")
    return value


def prepare_source_event(owner: str, source_key_id: str, identity: str, body: dict,
                         *, received_at: int | None = None) -> tuple[dict, str]:
    """Source ingress.ts overwrites caller-controlled source, principal and receive time."""
    if not isinstance(body, dict) or not _TOKEN.fullmatch(identity):
        raise ValueError("Exactly one valid Idempotency-Key header is required")
    mode = body.get("mode")
    if mode not in {"fire", "continue", "steer"}:
        raise ValueError("Unsupported original Agent Trigger mode")
    event = body.get("event")
    target = body.get("target")
    if not isinstance(event, dict) or not isinstance(target, dict):
        raise ValueError("An event and target object are required")
    moment = event.get("occurredAt")
    if type(moment) is not int or moment < 0 or moment > 2**53 - 1:
        raise ValueError("event.occurredAt must be a nonnegative safe integer")
    agent_id = _string(target.get("agentId"), "target.agentId", 256)
    resolved = {"agentId": agent_id}
    if mode != "fire":
        resolved["conversationId"] = _string(target.get("conversationId"),
                                              "target.conversationId", 256)
    if mode == "continue":
        resolved["parentMessageId"] = _string(target.get("parentMessageId"),
                                               "target.parentMessageId", 256)
        resolved["bindingId"] = _string(target.get("bindingId"), "target.bindingId", 256)
        resolved["sourceKeyId"] = source_key_id
    if mode == "steer":
        stamp = target.get("generationCreatedAt")
        if type(stamp) is not int or stamp < 0:
            raise ValueError("target.generationCreatedAt must be a nonnegative integer")
        resolved["generationCreatedAt"] = stamp
        if target.get("preempt") is not None:
            if type(target["preempt"]) is not bool:
                raise ValueError("target.preempt must be a boolean")
            resolved["preempt"] = target["preempt"]
    if body.get("expectedAction") is not None or body.get("coalesce") is not None:
        raise ValueError("Action fencing and coalescing require the source event-actor implementation")
    received_at = _now() if received_at is None else received_at
    envelope = {"version": 1, "mode": mode, "requestId": str(uuid.uuid4()),
                "deliveryId": identity, "receivedAt": received_at,
                "principal": {"userId": owner},
                "event": {"id": _string(event.get("id"), "event.id", 256),
                          "type": _string(event.get("type"), "event.type", 256),
                          "occurredAt": moment,
                          "source": {"id": source_key_id, "type": "remote_api_key"}},
                "target": resolved,
                "input": _string(body.get("input"), "input")}
    if "payload" in event:
        envelope["event"]["payload"] = event["payload"]
    if len(_json(envelope).encode()) > 1024 * 1024:
        raise ValueError("Agent Trigger envelope exceeds 1048576 bytes")
    return envelope, _lane(envelope, body.get("orderingKey"))


def enqueue_event(database: Any, owner: str, source_key_id: str, identity: str,
                  body: dict) -> dict:
    from .agents import AgentRepository

    envelope, lane = prepare_source_event(owner, source_key_id, identity, body)
    key = delivery_key(envelope)
    source = AgentRepository(database).get(owner, envelope["target"]["agentId"])
    if source is None:
        raise PermissionError("Event target Agent is not owned by the authenticated source principal")
    if envelope["mode"] == "continue":
        with database.connect() as db:
            binding = db.execute("SELECT 1 FROM agent_event_bindings WHERE id=? AND owner=? "
                                 "AND source_key_id=? AND agent_id=? AND conversation_id=?",
                                 (envelope["target"]["bindingId"], owner, source_key_id,
                                  envelope["target"]["agentId"],
                                  envelope["target"]["conversationId"])).fetchone()
        if binding is None:
            raise PermissionError("An authenticated event binding is required for continue")
    if envelope["mode"] == "steer":
        raise ValueError("Steer requires the pending Graph/HITL transport integration")
    stable = dict(envelope)
    stable.pop("requestId")
    stable.pop("receivedAt")
    fingerprint = _digest(stable)
    now = _now()
    with database.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        source = db.execute("SELECT permissions,revoked_at,expires_at FROM agent_event_source_keys "
                            "WHERE id=? AND owner=?", (source_key_id, owner)).fetchone()
        if source is None or source["revoked_at"] is not None or (
            source["expires_at"] is not None and source["expires_at"] <= now
        ):
            raise PermissionError("Event source authentication was revoked")
        if envelope["mode"] not in json.loads(source["permissions"]):
            raise PermissionError("Event source is not allowed to use this mode")
        prior = db.execute("SELECT fingerprint,status,available_at FROM agent_event_deliveries "
                           "WHERE id=? AND owner=? AND source_key_id=?",
                           (key, owner, source_key_id)).fetchone()
        if prior:
            if not hmac.compare_digest(prior["fingerprint"], fingerprint):
                raise ValueError("Idempotency-Key was already used for different event content")
            return {"id": key, "status": prior["status"],
                    "availableAt": prior["available_at"], "replayed": True}
        db.execute("INSERT INTO agent_event_deliveries "
                   "(id,owner,source_key_id,fingerprint,envelope,mode,ordering_key,status,"
                   "available_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'pending',?,?,?)",
                   (key, owner, source_key_id, fingerprint, _json(envelope),
                    envelope["mode"], lane, now, now, now))
    return {"id": key, "status": "pending", "availableAt": now, "replayed": False}


def get_event(database: Any, owner: str, source_key_id: str, delivery_id: str) -> dict | None:
    if not re.fullmatch(r"trigger_[a-f0-9]{64}", delivery_id):
        raise ValueError("Event delivery id is invalid")
    with database.connect() as db:
        row = db.execute("SELECT id,status,attempts,available_at,created_at,updated_at,"
                         "run_id,error_code,error_type,result FROM agent_event_deliveries "
                         "WHERE id=? AND owner=? AND source_key_id=?",
                         (delivery_id, owner, source_key_id)).fetchone()
    if row is None:
        return None
    payload = {"id": row["id"], "status": row["status"], "attempts": row["attempts"],
               "availableAt": _iso(row["available_at"]), "createdAt": _iso(row["created_at"])}
    if row["status"] in {"succeeded", "dead"}:
        payload["settledAt"] = _iso(row["updated_at"])
    if row["result"]:
        payload["result"] = json.loads(row["result"])
    if row["error_code"]:
        payload["error"] = {"code": row["error_code"], "message": row["error_type"]}
    return payload


def assert_event_lease(database: Any, owner: str, run_id: str,
                       lease: tuple[str, str]) -> None:
    from .agent_runtime import RuntimeSafetyError

    delivery_id, token = lease
    with database.connect() as db:
        valid = db.execute("SELECT 1 FROM agent_event_deliveries WHERE id=? AND owner=? "
                           "AND run_id=? AND status='leased' AND lease_owner=? AND lease_until>?",
                           (delivery_id, owner, run_id, token, _now())).fetchone()
    if valid is None:
        raise RuntimeSafetyError("Remote Agent Trigger actor lease was revoked")


def active_event_generations(database: Any) -> set[str]:
    """Keep externally admitted root turns resumable after Controller restart."""
    with database.connect() as db:
        rows = db.execute("SELECT run_id FROM agent_event_deliveries WHERE "
                          "status='leased' AND run_id IS NOT NULL").fetchall()
    return {row["run_id"] for row in rows}


def _failure(database: Any, db: Any, row: Any, *, code: str, error: Exception,
             attempted_at: int) -> None:
    count = row["attempts"] + 1
    permanent = isinstance(error, (ValueError, PermissionError)) or count >= _MAX_RETRIES
    db.execute(
        "UPDATE agent_event_deliveries SET status=?,attempts=?,error_code=?,error_type=?,"
        "available_at=?,lease_owner=NULL,lease_until=NULL,updated_at=? WHERE id=? "
        "AND status='leased' AND lease_owner=?",
        ("dead" if permanent else "pending", count, code, type(error).__name__,
         _retry_at(count, attempted_at), attempted_at, row["id"], row["lease_owner"]),
    )
    if permanent:
        # Source settleSourceBeforeDeadLetter: the generation can already be
        # durably admitted even if provider lookup or scheduling failed.
        # Settle it and its original SSE in the exact same fenced transaction
        # before exposing a dead letter or freeing the actor's ordered lane.
        from .generations import GenerationStore

        run_id = row["run_id"]
        if run_id is None:
            replay = db.execute("SELECT run_id FROM generation_requests WHERE owner=? "
                                "AND client_request_id=?", (row["owner"], row["id"])).fetchone()
            run_id = replay["run_id"] if replay else None
        if run_id:
            GenerationStore(database).finish(
                row["owner"], run_id, status="error",
                error="Agent event delivery failed (retry budget exhausted)",
                _connection=db,
            )


def _source_valid(db: Any, row: Any, at: int) -> bool:
    source = db.execute("SELECT permissions,expires_at,revoked_at FROM agent_event_source_keys "
                        "WHERE id=? AND owner=?", (row["source_key_id"], row["owner"])).fetchone()
    return (source is not None and source["revoked_at"] is None and
            (source["expires_at"] is None or source["expires_at"] > at) and
            row["mode"] in json.loads(source["permissions"]))


async def process_event_deliveries(database: Any, *, dispatch: Any = None,
                                   max_items: int = 8) -> int:
    """Fence one ordered queue claim + admission in the same SQLite transaction.

    The existing GenerationStore/AgentRunner are the only model executors.
    Source event retries reuse exactly one run; a different Controller may
    recover a lease only after the old generation's capability has expired.
    """
    from .agents import AgentRepository
    from .generations import GenerationConflict, GenerationStore
    from .providers import provider_config, selected_provider

    if dispatch is None:
        from .generation_routes import _start_task as dispatch

    store = GenerationStore(database)
    now = _now()
    completed = 0
    # Source handling completion is authoritative even after the admitting
    # worker exits: a different Controller must release the ordered lane from
    # persisted root terminal state, not depend on its in-memory _OWNED map.
    with database.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "UPDATE agent_event_deliveries SET status='succeeded',lease_owner=NULL,"
            "lease_until=NULL,updated_at=? WHERE status='leased' AND run_id IS NOT NULL "
            "AND EXISTS(SELECT 1 FROM runs r WHERE r.id=agent_event_deliveries.run_id "
            "AND r.status IN ('complete','error','aborted','interrupted','requires_action'))",
            (now,),
        )
    with database.connect() as db:
        rows = db.execute(
            "SELECT id FROM agent_event_deliveries d WHERE "
            "((d.status='pending' AND d.available_at<=?) "
            "OR (d.status='leased' AND d.lease_until<=?)) "
            "AND NOT EXISTS(SELECT 1 FROM agent_event_deliveries ahead "
            "WHERE ahead.owner=d.owner AND ahead.ordering_key=d.ordering_key "
            "AND ahead.seq<d.seq AND ahead.status IN ('pending','leased')) "
            "ORDER BY d.seq LIMIT ?", (now, now, max_items),
        ).fetchall()
    for candidate in rows:
        ready = None
        with database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM agent_event_deliveries WHERE id=?",
                             (candidate["id"],)).fetchone()
            if row is None or row["status"] not in {"pending", "leased"}:
                continue
            if row["status"] == "pending" and row["available_at"] > now:
                continue
            if row["status"] == "leased" and row["lease_until"] > now:
                continue
            ahead = db.execute("SELECT 1 FROM agent_event_deliveries WHERE owner=? "
                               "AND ordering_key=? AND seq<? AND status IN ('pending','leased') "
                               "LIMIT 1", (row["owner"], row["ordering_key"], row["seq"])).fetchone()
            if ahead is not None:
                continue
            if not _source_valid(db, row, now):
                db.execute("UPDATE agent_event_deliveries SET status='dead',error_code=?,"
                           "error_type=?,lease_owner=NULL,lease_until=NULL,updated_at=? WHERE id=?",
                           ("SOURCE_REVOKED", "PermissionError", now, row["id"]))
                continue
            envelope = json.loads(row["envelope"])
            agent = AgentRepository(database).get(row["owner"], envelope["target"]["agentId"])
            if agent is None:
                db.execute("UPDATE agent_event_deliveries SET status='dead',error_code=?,"
                           "error_type=?,updated_at=? WHERE id=?",
                           ("AGENT_NOT_FOUND", "KeyError", now, row["id"]))
                continue
            token = _PROCESS + ":" + secrets.token_hex(12)
            # Refresh persisted epoch and token before any external model call.
            db.execute("UPDATE agent_event_deliveries SET status='leased',"
                       "lease_owner=?,lease_until=?,updated_at=? WHERE id=?",
                       (token, now + _LEASE_MS, now, row["id"]))
            try:
                if row["run_id"]:
                    generation = store.get(row["owner"], row["run_id"])
                    if generation is None:
                        raise PermissionError("Previously admitted root generation no longer exists")
                    fresh = False
                else:
                    if envelope["mode"] == "fire":
                        payload = {"text": envelope["input"], "endpoint": "agents",
                                   "clientRequestId": row["id"]}
                    elif envelope["mode"] == "continue":
                        # Parent child-conversation guard/binding verified at the
                        # original enqueue. Recheck here to fence later deletion.
                        binding = db.execute("SELECT conversation_id FROM agent_event_bindings "
                                             "WHERE id=? AND owner=? AND source_key_id=? "
                                             "AND agent_id=? AND conversation_id=?",
                                             (envelope["target"]["bindingId"], row["owner"],
                                              row["source_key_id"], agent["id"],
                                              envelope["target"]["conversationId"])).fetchone()
                        if binding is None:
                            raise PermissionError("Original direct child binding was revoked")
                        ancestor = db.execute("SELECT id FROM messages WHERE conversation_id=? "
                                              "AND role='assistant' ORDER BY created_at DESC,id DESC LIMIT 1",
                                              (binding["conversation_id"],)).fetchone()
                        payload = {"text": envelope["input"], "endpoint": "agents",
                                   "conversationId": binding["conversation_id"],
                                   "parentMessageId": ancestor["id"] if ancestor else _NO_PARENT,
                                   "clientRequestId": row["id"]}
                    else:
                        raise ValueError("Unknown trusted Agent Trigger mode")
                    generation, fresh = store.begin(row["owner"], payload, agent, _connection=db)
                profile = provider_config(selected_provider({}, agent), agent.get("model"))
                db.execute("UPDATE agent_event_deliveries SET run_id=?,"
                           "result=?,updated_at=? WHERE id=? AND lease_owner=?",
                           (generation.run_id, _json({"mode": envelope["mode"],
                                "status": "started", "conversationId": generation.conversation_id,
                                "generationCreatedAt": generation.generation_created_at}),
                            now, row["id"], token))
                ready = (row["id"], token, row["owner"], generation, profile, agent, fresh)
            except GenerationConflict:
                # A different actor currently owns the conversation. This is a
                # readiness deferral, not a provider failure and not an attempt.
                db.execute("UPDATE agent_event_deliveries SET status='pending',"
                           "available_at=?,lease_owner=NULL,lease_until=NULL WHERE id=?",
                           (now + 5_000, row["id"]))
            except Exception as exc:
                current = db.execute("SELECT * FROM agent_event_deliveries WHERE id=?",
                                     (row["id"],)).fetchone()
                _failure(database, db, current, code="DELIVERY_REJECTED", error=exc, attempted_at=now)
        if ready is not None:
            delivery_id, token, owner, generation, profile, agent, fresh = ready
            from . import generation_routes as runner
            running = runner._TASKS.get(generation.run_id)
            if running is None or running.done():
                try:
                    await dispatch(owner, generation, profile, agent,
                                   native_file_tools=False, write_tools=False,
                                   ask_user_enabled=False, mcp_enabled=False,
                                   resume_history=None if fresh else store.history(
                                       owner, generation.conversation_id,
                                       message_id=generation.user_message_id),
                                   partial_text="" if fresh else store.accumulated_text(
                                       owner, generation.run_id),
                                   granted_scopes=frozenset(), event_delivery_lease=(delivery_id, token))
                except Exception as exc:
                    with database.connect() as db:
                        db.execute("BEGIN IMMEDIATE")
                        current = db.execute("SELECT * FROM agent_event_deliveries WHERE id=? "
                                             "AND lease_owner=?", (delivery_id, token)).fetchone()
                        if current is not None:
                            _failure(database, db, current, code="DELIVERY_FAILED", error=exc, attempted_at=_now())
                    continue
            _OWNED[delivery_id] = (generation.run_id, token)
            completed += 1
    # Source triggers/engine.ts lease reclamation: CAS renewal only from the
    # worker that still runs the exactly-fenced accepted generation.
    from .generation_routes import _TASKS
    for key, (run_id, token) in list(_OWNED.items()):
        task = _TASKS.get(run_id)
        if task is not None and not task.done():
            with database.connect() as db:
                if db.execute("UPDATE agent_event_deliveries SET lease_until=?,updated_at=? "
                              "WHERE id=? AND lease_owner=? AND status='leased' AND lease_until>?",
                              (_now() + _LEASE_MS, _now(), key, token, _now())).rowcount == 0:
                    _OWNED.pop(key, None)
            continue
        _OWNED.pop(key, None)
        with database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status,run_id,owner,lease_owner,result FROM "
                             "agent_event_deliveries WHERE id=?", (key,)).fetchone()
            if row and row["status"] == "leased" and row["lease_owner"] == token:
                generation = store.get(row["owner"], run_id)
                if generation and generation.status in {"complete", "error", "interrupted", "aborted", "requires_action"}:
                    db.execute("UPDATE agent_event_deliveries SET status='succeeded',"
                               "lease_owner=NULL,lease_until=NULL,updated_at=? WHERE id=?",
                               (_now(), key))
    return completed


async def start_event_worker(database: Any) -> None:
    key = str(database.path)
    worker = _WORKERS.get(key)
    if worker and not worker.done():
        return

    async def serve():
        while True:
            try:
                await process_event_deliveries(database)
            except Exception:
                log.exception("Agent Trigger source queue scan failed")
            await asyncio.sleep(1)

    _WORKERS[key] = asyncio.create_task(serve(), name="webui-agent-event-trigger")


async def shutdown_event_workers() -> None:
    for task in _WORKERS.values():
        task.cancel()
    if _WORKERS:
        await asyncio.gather(*_WORKERS.values(), return_exceptions=True)
    _WORKERS.clear()
    _OWNED.clear()
