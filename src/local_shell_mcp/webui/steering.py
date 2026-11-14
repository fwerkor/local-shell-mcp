"""LibreChat-steering wire contract and durable, owner-fenced SQLite queue.

Source: packages/api/src/agents/steering/{request,runtime}.ts and
packages/api/src/stream/interfaces/IJobStore.ts. Every queue mutation is a
BEGIN IMMEDIATE transaction against the originating run; no browser-held
state or best-effort in-process queue can authorize a steer.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass

from .storage import _json, _now

QUEUE_LIMIT = 10
RECEIPT_LIMIT = 100
RECEIPT_TTL_MS = 20 * 60 * 1000
MAX_TEXT_LENGTH = 16000
MAX_FILES = 10
CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class SteerRejection(Exception):
    def __init__(self, status: int, code: str, **fields):
        self.status = status
        self.body = {"code": code, **fields}
        super().__init__(code)


def _quotes(raw) -> list[str]:
    """Bound excerpts in the same structural shape as source quote normalization."""
    if not isinstance(raw, list):
        return []
    result: list[str] = []
    for value in raw:
        if isinstance(value, str) and value.strip():
            result.append(value.strip()[:1500])
            if len(result) == 10:
                break
    return result


def merged_text(item: dict) -> str:
    blocks = ["\n".join("> " + line for line in quote.split("\n")) for quote in item.get("quotes", [])]
    text = item.get("text", item.get("steer", ""))
    return "\n\n".join([*blocks, text]) if blocks else text


def _public(item: dict) -> dict:
    return {key: item[key] for key in (
        "steerId", "clientSteerId", "text", "createdAt", "files",
        "quotes", "preempt", "preemptRevision",
    ) if key in item}


def _fingerprint(text: str, files: list, preempt: bool, quotes: list[str]) -> str:
    normalized = _json({"text": text, "files": files, "preempt": preempt, "quotes": quotes})
    return hashlib.sha256(normalized.encode()).hexdigest()


def _sanitized_files(value) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SteerRejection(400, "INVALID_FILES")
    if len(value) > MAX_FILES:
        raise SteerRejection(400, "TOO_MANY_FILES")
    result = []
    allowed = {"type", "filepath", "filename", "height", "width", "bytes"}
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("file_id"), str) or not item["file_id"]:
            raise SteerRejection(400, "INVALID_FILES")
        sanitized = {"file_id": item["file_id"]}
        for key in allowed:
            if key in item and (
                (key in {"type", "filepath", "filename"} and isinstance(item[key], str))
                or (key in {"height", "width", "bytes"} and type(item[key]) in (int, float))
            ):
                sanitized[key] = item[key]
        if item.get("llmDeliveryPath") in {"text", "provider", "none"}:
            sanitized["llmDeliveryPath"] = item["llmDeliveryPath"]
        result.append(sanitized)
    if len(_json(result).encode("utf-8")) > 64 * 1024:
        raise SteerRejection(400, "INVALID_FILES")
    return result


@dataclass
class SteeringStore:
    database: object

    @staticmethod
    def _state(row) -> dict:
        return json.loads(row["state"])

    def _latest(self, db, owner: str, conversation_id: str):
        return db.execute(
            "SELECT r.* FROM runs r JOIN conversations c ON r.conversation_id=c.id "
            "WHERE c.owner=? AND c.id=? ORDER BY r.created_at DESC,r.id DESC LIMIT 1",
            (owner, conversation_id),
        ).fetchone()

    @staticmethod
    def _ensure_epoch(row, expected):
        if expected is None:
            return
        if type(expected) is not int or expected < 0:
            raise SteerRejection(400, "INVALID_GENERATION_IDENTITY")
        if not row or json.loads(row["state"]).get("generationCreatedAt") != expected:
            raise SteerRejection(409, "RUN_REPLACED")

    @staticmethod
    def _active_steers(state):
        return state.setdefault("steering", {"queue": [], "receipts": {}})

    def enqueue(self, owner: str, body: dict, *, preempt_capable: bool,
                strict_delivery: bool = False) -> dict:
        cid = body.get("conversationId")
        if not isinstance(cid, str) or not cid or cid == "new":
            raise SteerRejection(400, "INVALID_CONVERSATION")
        raw_text = body.get("text")
        if not isinstance(raw_text, str) or not raw_text.replace("\x00", "").strip():
            raise SteerRejection(400, "EMPTY_TEXT")
        text = raw_text.replace("\x00", "").strip()
        if len(text) > MAX_TEXT_LENGTH:
            raise SteerRejection(413, "STEER_TOO_LONG", maxLength=MAX_TEXT_LENGTH)
        client_id = body.get("clientSteerId")
        if client_id is not None and (not isinstance(client_id, str) or not CLIENT_ID_PATTERN.fullmatch(client_id)):
            raise SteerRejection(400, "INVALID_CLIENT_STEER_ID")
        files = _sanitized_files(body.get("files"))
        quotes = _quotes(body.get("quotes"))
        desired_preempt = body.get("preempt") is True
        fingerprint = _fingerprint(text, files, desired_preempt, quotes)
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._latest(db, owner, cid)
            # Receipt must be read BEFORE current-run epoch fencing: a lost
            # ACK from a previous run must replay even if this chat moved on.
            if row is None:
                self._ensure_epoch(row, body.get("generationCreatedAt"))
                raise SteerRejection(404, "NO_ACTIVE_RUN")
            state = self._state(row)
            steer = self._active_steers(state)
            if client_id:
                # Replay includes terminal runs and survives a newly created run.
                past = db.execute(
                    "SELECT r.state FROM runs r WHERE r.conversation_id=? "
                    "ORDER BY r.created_at DESC,r.id DESC LIMIT 200", (cid,),
                ).fetchall()
                for previous in past:
                    previous_state = json.loads(previous["state"])
                    receipt = (previous_state.get("steering") or {}).get("receipts", {}).get(client_id)
                    if receipt is None or (
                        receipt["state"] not in {"queued", "claimed"}
                        and receipt.get("expiresAt", 0) <= int(time.time() * 1000)
                    ):
                        continue
                    if receipt["fingerprint"] != fingerprint:
                        raise SteerRejection(409, "STEER_IDEMPOTENCY_CONFLICT")
                    if body.get("generationCreatedAt") is not None and (
                        previous_state.get("generationCreatedAt") != body["generationCreatedAt"]
                    ):
                        raise SteerRejection(409, "RUN_REPLACED")
                    item = receipt["item"]
                    replay = self._ack(cid, item, receipt["state"], receipt.get("position", 1))
                    replay["replayed"] = True
                    return replay
            self._ensure_epoch(row, body.get("generationCreatedAt"))
            if row["status"] not in {"running", "requires_action"}:
                raise SteerRejection(404, "NO_ACTIVE_RUN")
            if row["status"] == "requires_action":
                raise SteerRejection(409, "RUN_PAUSED")
            if len(steer["queue"]) >= QUEUE_LIMIT:
                raise SteerRejection(429, "STEER_QUEUE_FULL")
            # Applied/cancelled receipts expire after the upstream 20-minute
            # replay window; a queued item never loses its idempotency proof.
            now = int(time.time() * 1000)
            for receipt_id, receipt in list(steer["receipts"].items()):
                if receipt["state"] not in {"queued", "claimed"} and receipt.get("expiresAt", 0) <= now:
                    del steer["receipts"][receipt_id]
            if client_id and len(steer["receipts"]) >= RECEIPT_LIMIT:
                raise SteerRejection(429, "STEER_RECEIPT_LIMIT")
            if strict_delivery and not client_id:
                raise SteerRejection(400, "CLIENT_STEER_ID_REQUIRED")
            if files:
                from .attachments import resolve_files
                try:
                    files = resolve_files(db, owner, files)
                except (KeyError, ValueError) as exc:
                    raise SteerRejection(400, "INVALID_FILES") from exc
            item = {"steerId": "steer_" + uuid.uuid4().hex, "text": text, "files": files, "quotes": quotes, "createdAt": now,
                    "preempt": desired_preempt and preempt_capable,
                    "preemptRevision": 1}
            if client_id:
                item["clientSteerId"] = client_id
            steer["queue"].append(item)
            if client_id:
                steer["receipts"][client_id] = {
                    "item": item.copy(), "fingerprint": fingerprint,
                    "position": len(steer["queue"]), "state": "queued",
                    "expiresAt": now + RECEIPT_TTL_MS,
                }
            db.execute("UPDATE runs SET state=?,updated_at=? WHERE id=?",
                       (_json(state), _now(), row["id"]))
            db.execute("INSERT INTO generation_events(run_id,data) VALUES(?,?)",
                       (row["id"], _json({"event": "on_steer_updated", "data": {
                           "conversationId": cid,
                           "steers": [{k: item[k] for k in ("steerId", "clientSteerId", "preempt", "preemptRevision")
                                       if k in item}],
                       }})))
            return self._ack(cid, item, "queued", len(steer["queue"]))

    @staticmethod
    def _ack(cid, item, state, position):
        return {"status": "queued", "steerId": item["steerId"],
                **({"clientSteerId": item["clientSteerId"]} if item.get("clientSteerId") else {}),
                "position": position, "conversationId": cid,
                "preempt": item["preempt"], "preemptRevision": item.get("preemptRevision", 0),
                "settled": state not in {"queued", "claimed"}, "leftover": state == "leftover",
                **({"quotesAccepted": True} if item.get("quotes") else {})}

    def mutate(self, owner, body, *, arm: bool, preempt_capable: bool):
        cid = body.get("conversationId")
        sid = body.get("steerId")
        if not isinstance(cid, str) or not cid or cid == "new":
            raise SteerRejection(400, "INVALID_CONVERSATION")
        if not isinstance(sid, str) or not sid:
            raise SteerRejection(400, "INVALID_STEER_ID")
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._latest(db, owner, cid)
            client_id = body.get("clientSteerId")
            if not arm and isinstance(client_id, str) and client_id:
                # Source cancel accepts a known leftover/cancelled receipt even
                # after a successor run has taken the conversation stream.
                prior = db.execute(
                    "SELECT r.* FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                    "WHERE c.owner=? AND c.id=? ORDER BY r.created_at DESC,r.id DESC LIMIT 200",
                    (owner, cid),
                ).fetchall()
                for previous in prior:
                    previous_state = self._state(previous)
                    receipt = (previous_state.get("steering") or {}).get("receipts", {}).get(client_id)
                    if not receipt or receipt["item"]["steerId"] != sid:
                        continue
                    self._ensure_epoch(previous, body.get("generationCreatedAt"))
                    if receipt["state"] == "cancelled":
                        return {"removed": True, "replayed": True}
                    if receipt["state"] == "leftover":
                        receipt["state"] = "cancelled"
                        db.execute("UPDATE runs SET state=?,updated_at=? WHERE id=?",
                                   (_json(previous_state), _now(), previous["id"]))
                        return {"removed": True, "replayed": True}
                    break
            self._ensure_epoch(row, body.get("generationCreatedAt"))
            if row is None:
                return {"armed" if arm else "removed": False}
            state = self._state(row)
            steer = self._active_steers(state)
            result = {"armed" if arm else "removed": False}
            if arm and (not preempt_capable or row["status"] != "running"):
                result["code"] = "PREEMPT_UNSUPPORTED"
                return result
            for index, item in enumerate(steer["queue"]):
                if item["steerId"] != sid:
                    continue
                receipt = steer["receipts"].get(item.get("clientSteerId"))
                if arm:
                    if item["preempt"]:
                        return result
                    item["preempt"] = True
                    item["preemptRevision"] += 1
                    if receipt:
                        receipt["item"] = item.copy()
                    result = {"armed": True, "preemptRevision": item["preemptRevision"]}
                    db.execute("INSERT INTO generation_events(run_id,data) VALUES(?,?)",
                               (row["id"], _json({"event": "on_steer_updated", "data": {
                                   "conversationId": cid, "steers": [{
                                       k: item[k] for k in ("steerId", "clientSteerId", "preempt", "preemptRevision")
                                       if k in item
                                   }],
                               }})))
                else:
                    steer["queue"].pop(index)
                    if receipt:
                        receipt["state"] = "cancelled"
                    result = {"removed": True}
                db.execute("UPDATE runs SET state=?,updated_at=? WHERE id=?",
                           (_json(state), _now(), row["id"]))
                return result
            if not arm:
                client_id = body.get("clientSteerId")
                receipt = steer["receipts"].get(client_id) if isinstance(client_id, str) else None
                if receipt and receipt["item"]["steerId"] == sid and receipt["state"] == "cancelled":
                    return {"removed": True, "replayed": True}
                if receipt and receipt["item"]["steerId"] == sid and receipt["state"] == "leftover":
                    receipt["state"] = "cancelled"
                    db.execute("UPDATE runs SET state=?,updated_at=? WHERE id=?",
                               (_json(state), _now(), row["id"]))
                    return {"removed": True, "replayed": True}
            return result

    def has_preempt(self, owner, run_id):
        with self.database.connect() as db:
            row = db.execute("SELECT state FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                             "WHERE r.id=? AND c.owner=? AND r.status='running'", (run_id, owner)).fetchone()
            return bool(row and any(item.get("preempt") for item in
                                    (self._state(row).get("steering") or {}).get("queue", [])))

    def drain(self, owner, run_id, *, boundary, actor_lease=None, recipient_namespace=""):
        """Atomic FIFO dequeue and SSE publication; never inject a newer run's items."""
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if actor_lease is not None:
                actor_lease.assert_current(db)
            row = db.execute("SELECT r.* FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                             "WHERE r.id=? AND c.owner=? AND r.status='running'",
                             (run_id, owner)).fetchone()
            if row is None:
                return []
            state = self._state(row)
            steer = self._active_steers(state)
            queue = steer["queue"]
            if not queue:
                return []
            if boundary == "stream" and not any(item["preempt"] for item in queue):
                return []
            # Preempt seals the stream at a safe boundary, then drains FIFO,
            # including unarmed items before the interrupting item.
            applied = list(queue)
            steer["queue"] = []
            index = 0
            previous_was_text = False
            for entry in db.execute(
                "SELECT data FROM generation_events WHERE run_id=? ORDER BY seq", (run_id,),
            ):
                event = json.loads(entry["data"])
                kind = event.get("event")
                if kind == "on_steer_applied":
                    index += 1
                    previous_was_text = False
                elif kind == "on_message_delta":
                    content = ((event.get("data") or {}).get("delta") or {}).get("content") or {}
                    if content.get("type") == "text" and content.get("text"):
                        if not previous_was_text:
                            index += 1
                        previous_was_text = True
            for item in applied:
                receipt = steer["receipts"].get(item.get("clientSteerId"))
                if receipt is not None:
                    receipt["state"] = "applied"
                part = {"type": "steer", "steer": item["text"], "steerId": item["steerId"],
                        **({"clientSteerId": item["clientSteerId"]} if item.get("clientSteerId") else {}),
                        "createdAt": item["createdAt"], "files": item["files"], "quotes": item["quotes"]}
                state.setdefault("steerParts", []).append(part)
                # Only the winning Graph node may replay this claimed Steer
                # after the event write but before its own model checkpoint.
                # Keep this routing private in run state, not React parts.
                state.setdefault("steerDelivery", {})[item["steerId"]] = recipient_namespace
                db.execute("INSERT INTO generation_events(run_id,data) VALUES(?,?)",
                           (run_id, _json({"event": "on_steer_applied", "data": {
                               "steerId": item["steerId"],
                               **({"clientSteerId": item["clientSteerId"]} if item.get("clientSteerId") else {}),
                               "index": index, "part": part,
                               "responseMessageId": state["responseMessageId"],
                               "conversationId": row["conversation_id"],
                           }})))
                index += 1
            db.execute("UPDATE runs SET state=?,updated_at=? WHERE id=?",
                       (_json(state), _now(), run_id))
            return applied

    def applied_parts(self, owner: str, run_id: str, *, namespace: str | None = None) -> list[dict]:
        """One source of durable delivery truth across a failed graph checkpoint.

        The queue is atomically consumed with the on_steer_applied receipt, but
        the later agent/graph checkpoint can be lost in a crash. Replaying only
        missing deterministic steer IDs repairs that crash window.
        """
        with self.database.connect() as db:
            row = db.execute(
                "SELECT r.state FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.id=? AND c.owner=? AND r.status='running'", (run_id, owner),
            ).fetchone()
        if row is None:
            return []
        state = self._state(row)
        parts = state.get("steerParts") or []
        if namespace is None:
            return list(parts)
        routes = state.get("steerDelivery") or {}
        return [part for part in parts if routes.get(part.get("steerId"), "") == namespace]

    def pending(self, owner, run_id):
        with self.database.connect() as db:
            row = db.execute(
                "SELECT r.state FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.id=? AND c.owner=?", (run_id, owner),
            ).fetchone()
            return ([_public(item) for item in
                     (self._state(row).get("steering") or {}).get("queue", [])] if row else [])

    @staticmethod
    def settle_leftovers(state):
        steer = state.get("steering")
        if not steer:
            return []
        leftover = [_public(item) for item in steer["queue"]]
        for item in steer["queue"]:
            receipt = steer["receipts"].get(item.get("clientSteerId"))
            if receipt:
                receipt["state"] = "leftover"
        steer["queue"] = []
        return leftover
