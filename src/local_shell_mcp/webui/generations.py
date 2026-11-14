"""Durable, authenticated LibreChat generation-event stream on shared SQLite.

A user turn, its generation lease, event log, assistant message and terminal
outcome are stored in the one LSM database. HTTP SSE consumers can disconnect
and replay events without losing the source generation. Provider calls are
owned by the Controller's event loop, not by the browser connection.
"""

from __future__ import annotations

import contextlib
import json
import logging
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Any

from .approval_runtime import ApprovalBatch, prepare_approval_batch
from .ask_user_tools import ask_user_requested
from .generation_protocol import job_generation_protocol
from .providers import selected_provider
from .storage import _json, _now

log = logging.getLogger(__name__)
_TERMINAL = frozenset({"complete", "aborted", "error", "interrupted"})
_EVENT_LIMIT = 30000
_MAX_PROMPT_BYTES = 128 * 1024


@dataclass(frozen=True)
class Generation:
    run_id: str
    conversation_id: str
    generation_created_at: int
    response_message_id: str
    user_message_id: str
    status: str
    agent_id: str | None = None
    protocol_version: int = 2


class GenerationConflict(Exception):
    def __init__(self, existing: Generation):
        self.existing = existing
        super().__init__("Conversation already has an active generation")


class GenerationStore:
    def __init__(self, database: Any):
        self.database = database

    @staticmethod
    def _run(row: Any) -> Generation:
        state = json.loads(row["state"])
        return Generation(
            run_id=row["id"], conversation_id=row["conversation_id"],
            generation_created_at=state["generationCreatedAt"],
            response_message_id=state["responseMessageId"],
            user_message_id=state["userMessageId"], status=row["status"], agent_id=row["agent_id"],
            protocol_version=job_generation_protocol(state),
        )

    def latest(self, owner: str, conversation_id: str) -> Generation | None:
        with self.database.connect() as db:
            row = db.execute(
                "SELECT r.* FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE c.owner=? AND r.conversation_id=? ORDER BY r.created_at DESC,r.id DESC LIMIT 1",
                (owner, conversation_id),
            ).fetchone()
            return self._run(row) if row else None

    def get(self, owner: str, run_id: str) -> Generation | None:
        with self.database.connect() as db:
            row = db.execute("SELECT r.* FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                             "WHERE c.owner=? AND r.id=?", (owner, run_id)).fetchone()
            return self._run(row) if row else None

    def begin(self, owner: str, payload: dict, agent: dict | None = None, *,
              protocol_version: int = 2,
              trusted_new_conversation_id: str | None = None,
              _connection: Any | None = None) -> tuple[Generation, bool]:
        client_request_id = payload.get("clientRequestId")
        if client_request_id is not None and (not isinstance(client_request_id, str) or
                                               not 1 <= len(client_request_id) <= 160):
            raise ValueError("Invalid client request id")
        # These idempotency namespaces are host-generated only. A browser can
        # see a task handle and must not be able to preoccupy its continuation
        # key with an unrelated generation before the child settles.
        if isinstance(client_request_id, str):
            if client_request_id.startswith("subagent-wakeup:") and _connection is None:
                raise ValueError("Internal completion idempotency key cannot be submitted")
            if client_request_id.startswith("subagent:") and trusted_new_conversation_id is None:
                raise ValueError("Internal child idempotency key cannot be submitted")
        raw_conversation_id = payload.get("conversationId")
        new_conversation = raw_conversation_id in (None, "", "new", "new_conversation")
        if raw_conversation_id is not None and not isinstance(raw_conversation_id, str):
            raise ValueError("Invalid conversation id")
        project_id = payload.get("projectId", payload.get("chatProjectId")) if new_conversation else None
        if project_id is not None and (not isinstance(project_id, str) or not project_id):
            raise ValueError("Invalid project id")
        # Internal-only allocation for a host-reserved subagent child. No HTTP
        # field can select this value; the host registered its trusted lineage
        # before this conversation becomes externally observable.
        if trusted_new_conversation_id is not None:
            if not new_conversation or not isinstance(trusted_new_conversation_id, str):
                raise ValueError("A reserved child conversation must be a new conversation")
            try:
                if str(uuid.UUID(trusted_new_conversation_id)) != trusted_new_conversation_id:
                    raise ValueError("Invalid reserved child conversation identity")
            except ValueError as exc:
                raise ValueError("Invalid reserved child conversation identity") from exc
        conversation_id = (trusted_new_conversation_id or str(uuid.uuid4())) \
            if new_conversation else raw_conversation_id
        prompt = payload.get("text")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode("utf-8")) > _MAX_PROMPT_BYTES:
            raise ValueError("A non-empty text message is required (max 128 KiB)")
        user_message_id = str(payload.get("messageId") or uuid.uuid4())
        response_message_id = str(uuid.uuid4())
        run_id = "run_" + secrets.token_hex(16)
        now = _now()
        stamp_ms = now // 1000
        state = {
            "userMessageId": user_message_id,
            "responseMessageId": response_message_id,
            "generationCreatedAt": stamp_ms,
            "clientRequestId": client_request_id,
            "generationProtocolVersion": protocol_version,
            "provider": selected_provider(payload, agent),
            "model": str((agent or {}).get("model") or payload.get("model") or ""),
            "askUserEnabled": ask_user_requested(agent, payload),
        }
        # Internal trigger delivery supplies its already-locked SQLite
        # transaction. The generation and a one-shot child result claim must
        # commit or roll back together; ordinary HTTP admission is unchanged.
        with (contextlib.nullcontext(_connection) if _connection is not None
              else self.database.connect()) as db:
            if _connection is None:
                db.execute("BEGIN IMMEDIATE")
            if client_request_id:
                prior = db.execute(
                    "SELECT r.* FROM generation_requests gr JOIN runs r ON r.id=gr.run_id "
                    "WHERE gr.owner=? AND gr.client_request_id=?",
                    (owner, client_request_id),
                ).fetchone()
                if prior:
                    return self._run(prior), False
            if new_conversation:
                if project_id and not db.execute(
                    "SELECT 1 FROM projects WHERE id=? AND owner=?", (project_id, owner),
                ).fetchone():
                    raise KeyError("Project not found")
                db.execute(
                    "INSERT INTO conversations(id,owner,title,model,endpoint,project_id,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (conversation_id, owner, prompt.strip()[:80], state["model"],
                     payload.get("endpoint") or "agents", project_id, now, now),
                )
            elif not db.execute("SELECT 1 FROM conversations WHERE id=? AND owner=?",
                                (conversation_id, owner)).fetchone():
                raise KeyError("Conversation not found")
            active = db.execute(
                "SELECT * FROM runs WHERE conversation_id=? AND status IN ('running','requires_action') "
                "ORDER BY created_at DESC LIMIT 1", (conversation_id,),
            ).fetchone()
            if active:
                raise GenerationConflict(self._run(active))
            from .attachments import resolve_files

            files = resolve_files(db, owner, payload.get("files", []))
            user_metadata = {
                "sender": "User", "isCreatedByUser": True,
                "endpoint": str(payload.get("endpoint") or "agents"),
                "files": files,
            }
            db.execute(
                "INSERT INTO messages(id,conversation_id,parent_id,role,text,content,metadata,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (user_message_id, conversation_id, payload.get("parentMessageId"), "user", prompt,
                 _json(payload.get("content") or {}), _json(user_metadata), now, now),
            )
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id))
            db.execute("INSERT INTO runs(id,conversation_id,agent_id,status,state,created_at,updated_at) "
                       "VALUES(?,?,?,?,?,?,?)",
                       (run_id, conversation_id, (agent or {}).get("id") or payload.get("agent_id"),
                        "running", _json(state), now, now))
            if client_request_id:
                db.execute("INSERT INTO generation_requests(owner,client_request_id,run_id) VALUES(?,?,?)",
                           (owner, client_request_id, run_id))
            created = {
                "created": True,
                "conversation": {"conversationId": conversation_id, "title": prompt.strip()[:80]},
                "message": {
                    "messageId": user_message_id,
                    "conversationId": conversation_id,
                    "parentMessageId": payload.get("parentMessageId"),
                    "text": prompt,
                    "sender": "User",
                    "files": files,
                    "isCreatedByUser": True,
                },
            }
            db.execute("INSERT INTO generation_events(run_id,data) VALUES(?,?)", (run_id, _json(created)))
        return Generation(run_id, conversation_id, stamp_ms, response_message_id,
                          user_message_id, "running", (agent or {}).get("id") or payload.get("agent_id"), protocol_version), True

    @staticmethod
    def action_expired(pending: dict) -> bool:
        expires = pending.get("expiresAt")
        return type(expires) in (int, float) and expires <= time.time() * 1000

    def resume_claim(self, owner: str, run_id: str) -> dict | None:
        with self.database.connect() as db:
            row = db.execute(
                "SELECT r.state FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.id=? AND c.owner=? AND r.status IN ('running','requires_action')",
                (run_id, owner),
            ).fetchone()
        return json.loads(row["state"]).get("resumeClaim") if row is not None else None

    @staticmethod
    def client_pending_action(pending: dict | None) -> dict | None:
        """Source policy.ts:toClientPendingAction; server replay state stays private."""
        if pending is None:
            return None
        return {key: value for key, value in pending.items() if key not in {
            "requestFingerprint", "requestFingerprintV2",
            "resumeContext", "codeExecutionBinding",
        }}

    def pending_action(self, owner: str, run_id: str) -> dict | None:
        with self.database.connect() as db:
            row = db.execute(
                "SELECT r.state FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.id=? AND c.owner=? AND r.status='requires_action'", (run_id, owner),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["state"]).get("pendingAction")

    def pause_for_question(self, owner: str, run_id: str, pending: dict,
                           history: list[dict], partial_text: str) -> bool:
        if len(_json(history).encode("utf-8")) > 512 * 1024:
            raise ValueError("Agent continuation state is too large")
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT r.* FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.id=? AND c.owner=? AND r.status='running'", (run_id, owner),
            ).fetchone()
            if row is None:
                return False
            state = json.loads(row["state"])
            state["pendingAction"] = pending
            # An approved ask-user tool causes a second, question-shaped
            # interrupt. Retire the prior approval in the same transaction as
            # the new pause so a crash cannot replay the approval stage.
            state.pop("approvedToolBatch", None)
            state.pop("resumeClaim", None)
            state["resumeHistory"] = history
            state["partialText"] = partial_text
            db.execute("UPDATE runs SET state=?,status='requires_action',updated_at=? WHERE id=?",
                       (_json(state), _now(), run_id))
            db.execute("INSERT INTO generation_events(run_id,data) VALUES(?,?)",
                       (run_id, _json({"event": "on_pending_action",
                                        "data": self.client_pending_action(pending)})))
            return True

    def answer_question(self, owner: str, run_id: str, action_id: str,
                        answer: dict | str) -> tuple[Generation, list[dict], str]:
        from .ask_user_tools import resolve_ask_user_question_resume

        body = {"answer": answer} if isinstance(answer, str) else answer
        if not isinstance(body, dict):
            raise ValueError("An answer is required")
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT r.* FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.id=? AND c.owner=? AND r.status='requires_action'", (run_id, owner),
            ).fetchone()
            if row is None:
                raise KeyError("No pending generation action")
            state = json.loads(row["state"])
            pending = state.get("pendingAction")
            if not isinstance(pending, dict) or pending.get("actionId") != action_id:
                raise ValueError("Stale or mismatched human action")
            if self.action_expired(pending):
                raise ValueError("Human action expired")
            if pending.get("payload", {}).get("type") != "ask_user_question":
                raise ValueError("An Ask User answer is required")
            resolution = resolve_ask_user_question_resume(pending["payload"], body)
            if "error" in resolution:
                raise ValueError(resolution["error"])
            output = json.dumps(resolution["resumeValue"], ensure_ascii=False, separators=(",", ":"))
            history = state.get("resumeHistory")
            if not isinstance(history, list):
                raise ValueError("Missing saved model continuation")
            call_id = pending["payload"]["tool_call_id"]
            history.append({"role": "tool", "tool_call_id": call_id, "content": output})
            partial_text = state.get("partialText", "")
            state["resumeClaim"] = {
                "actionId": action_id, "pendingAction": pending, "kind": "ask",
                "submission": body,
            }
            state.pop("pendingAction", None)
            # Keep the resolved continuation until the model reaches a terminal
            # boundary. An ACK can be lost or the Controller can restart.
            state["resumeHistory"] = history
            state["partialText"] = partial_text
            db.execute("UPDATE runs SET state=?,status='running',updated_at=? WHERE id=?",
                       (_json(state), _now(), run_id))
            return self._run(row), history, partial_text

    def pause_for_approval(self, owner: str, run_id: str, pending: dict,
                           history: list[dict], partial_text: str) -> bool:
        return self.pause_for_question(owner, run_id, pending, history, partial_text)

    def claim_approval(self, owner: str, run_id: str, action_id: str,
                       decisions: list[dict]) -> tuple[Generation, list[dict], str, ApprovalBatch]:
        """Claim a whole reviewed batch without dropping its recovery evidence."""
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT r.* FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.id=? AND c.owner=? AND r.status='requires_action'", (run_id, owner),
            ).fetchone()
            if row is None:
                raise KeyError("No pending tool approval")
            state = json.loads(row["state"])
            pending = state.get("pendingAction")
            if not isinstance(pending, dict) or pending.get("actionId") != action_id:
                raise ValueError("Stale tool approval action")
            if self.action_expired(pending):
                raise ValueError("Human action expired")
            payload = pending.get("payload") or {}
            if payload.get("type") != "tool_approval":
                raise ValueError("Unexpected approval format")
            # Validation covers every request before the one-shot claim changes
            # state. The SDK review identity binds name, args and decisions;
            # a later execution still has to pass fresh native permissions.
            batch = prepare_approval_batch(payload, decisions)
            history = state.get("resumeHistory")
            if not isinstance(history, list):
                raise ValueError("Missing model continuation history")
            prior = state.get("partialText", "")
            state["resumeClaim"] = {
                "actionId": action_id, "pendingAction": pending, "kind": "approval",
                "submission": {"decisions": decisions},
            }
            state["approvedToolBatch"] = {
                "actionId": action_id,
                "namespace": pending.get("namespace", ""),
                "payload": payload,
                "resolutions": decisions,
            }
            state.pop("pendingAction", None)
            # Keep history/text until completion is durably recorded. A crash
            # after the claim must not erase the paused model continuation.
            db.execute("UPDATE runs SET state=?,status='running',updated_at=? WHERE id=?",
                       (_json(state), _now(), run_id))
            resumed = self._run({**dict(row), "status": "running"})
            return resumed, history, prior, batch

    def restart_claimed_resume(self, owner: str, run_id: str, action_id: str,
                               submission: dict) -> tuple[Generation, list[dict], str, ApprovalBatch | None, str]:
        """CAS-restart a previously accepted action; changed retries fail closed.

        A lost HTTP ACK and process restart must never authorize a DIFFERENT
        decision for the same action. SQLite stores the original answer/decision
        and the original interrupt identity in the same transaction.
        """
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT r.* FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.id=? AND c.owner=? AND r.status IN ('running','requires_action')",
                (run_id, owner),
            ).fetchone()
            if row is None:
                raise KeyError("No resumable generation")
            state = json.loads(row["state"])
            claim = state.get("resumeClaim")
            if not isinstance(claim, dict) or claim.get("actionId") != action_id:
                raise ValueError("Stale human action")
            if (not isinstance(submission, dict) or
                json.dumps(claim.get("submission"), sort_keys=True, ensure_ascii=False) !=
                json.dumps(submission, sort_keys=True, ensure_ascii=False)):
                raise ValueError("Conflicting human action retry")
            history = state.get("resumeHistory")
            if not isinstance(history, list):
                raise ValueError("Missing saved continuation history")
            batch = (prepare_approval_batch(state["approvedToolBatch"]["payload"],
                                            state["approvedToolBatch"]["resolutions"])
                     if state.get("approvedToolBatch") else None)
            if row["status"] == "requires_action":
                pending = state.get("pendingAction")
                if pending is None or pending.get("actionId") != action_id:
                    raise ValueError("Lost recovery action identity")
                state.pop("pendingAction")
                db.execute("UPDATE runs SET state=?,status='running',updated_at=? WHERE id=?",
                           (_json(state), _now(), run_id))
            return (self._run({**dict(row), "status": "running"}), history,
                    state.get("partialText", ""), batch,
                    claim["pendingAction"].get("namespace", ""))

    def recover_claimed_resumes(self, active_run_ids: set[str] | None = None) -> int:
        """Return crash-stranded claimed actions to the same client interrupt.

        Never execute tools at boot without an authenticated fresh request.
        The React client can re-submit the original answer, which matches the
        immutable SQLite claim and uses the graph's saved checkpoint.
        """
        active = active_run_ids or set()
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT r.id,r.state FROM runs r WHERE r.status='running'").fetchall()
            recovered = 0
            for row in rows:
                if row["id"] in active:
                    continue
                state = json.loads(row["state"])
                claim = state.get("resumeClaim")
                if not isinstance(claim, dict):
                    continue
                pending = claim.get("pendingAction")
                if not isinstance(pending, dict) or pending.get("actionId") != claim.get("actionId"):
                    continue
                state["pendingAction"] = pending
                db.execute("UPDATE runs SET state=?,status='requires_action',updated_at=? WHERE id=?",
                           (_json(state), _now(), row["id"]))
                db.execute("INSERT INTO generation_events(run_id,data) VALUES(?,?)",
                           (row["id"], _json({"event": "on_pending_action",
                                               "data": self.client_pending_action(pending)})))
                recovered += 1
            return recovered

    def approved_review(self, owner: str, run_id: str) -> dict | None:
        """Load owner-bound server review proof for crash/restart continuation."""
        with self.database.connect() as db:
            row = db.execute(
                "SELECT r.state,r.status FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.id=? AND c.owner=?", (run_id, owner),
            ).fetchone()
        if row is None or row["status"] not in {"running", "interrupted"}:
            return None
        state = json.loads(row["state"])
        review = state.get("approvedToolBatch")
        if review is None:
            return None
        if (not isinstance(review, dict) or not isinstance(review.get("actionId"), str) or
            not review["actionId"]):
            raise ValueError("Invalid retained tool approval review")
        prepare_approval_batch(review.get("payload"), review.get("resolutions"))
        return review

    def approved_batch(self, owner: str, run_id: str) -> ApprovalBatch | None:
        review = self.approved_review(owner, run_id)
        return prepare_approval_batch(review["payload"], review["resolutions"]) if review else None

    def complete_approval_batch(self, owner: str, run_id: str, action_id: str,
                                history: list[dict], partial_text: str) -> bool:
        """Retire approval proof only after checkpointed tool results are saved."""
        if len(_json(history).encode("utf-8")) > 512 * 1024:
            raise ValueError("Agent continuation state is too large")
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT r.state FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.id=? AND c.owner=? AND r.status='running'", (run_id, owner),
            ).fetchone()
            if row is None:
                return False
            state = json.loads(row["state"])
            review = state.get("approvedToolBatch")
            if not isinstance(review, dict) or review.get("actionId") != action_id:
                return False
            state.pop("approvedToolBatch")
            state["resumeHistory"] = history
            state["partialText"] = partial_text
            db.execute("UPDATE runs SET state=?,updated_at=? WHERE id=?",
                       (_json(state), _now(), run_id))
            return True

    def append(self, owner: str, run_id: str, event: dict) -> int:
        encoded = _json(event)
        if len(encoded.encode("utf-8")) > 256 * 1024:
            raise ValueError("Generation event exceeds 256 KiB")
        with self.database.connect() as db:
            if not db.execute(
                "SELECT 1 FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.id=? AND c.owner=? AND r.status='running'", (run_id, owner),
            ).fetchone():
                raise KeyError("Generation not active or unauthorized")
            count = db.execute("SELECT count(*) FROM generation_events WHERE run_id=?", (run_id,)).fetchone()[0]
            if count >= _EVENT_LIMIT:
                raise ValueError("Generation event retention limit reached")
            cursor = db.execute("INSERT INTO generation_events(run_id,data) VALUES(?,?)", (run_id, encoded))
            return int(cursor.lastrowid)

    def resume_snapshot(self, owner: str, run_id: str) -> tuple[dict, int]:
        """Source React SSE resumeState projection from one SQLite read view.

        The cursor and content are captured together; events added after this
        transaction are streamed by their seq and cannot be lost on reload.
        This is the existing generation event log, not a second runtime.
        """
        with self.database.connect() as db:
            db.execute("BEGIN")
            row = db.execute(
                "SELECT r.* FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.id=? AND c.owner=?", (run_id, owner),
            ).fetchone()
            if row is None:
                raise KeyError("Generation not found")
            generation = self._run(row)
            state = json.loads(row["state"])
            user = db.execute(
                "SELECT id,parent_id,text FROM messages WHERE id=? AND conversation_id=?",
                (generation.user_message_id, generation.conversation_id),
            ).fetchone()
            entries = db.execute(
                "SELECT seq,data FROM generation_events WHERE run_id=? ORDER BY seq",
                (run_id,),
            ).fetchall()
            max_seq = entries[-1]["seq"] if entries else 0
        steps = {}
        content_parts: list[dict] = []
        for entry in entries:
            item = json.loads(entry["data"])
            event, data = item.get("event"), item.get("data") or {}
            if event == "on_run_step" and isinstance(data, dict) and isinstance(data.get("id"), str):
                steps[data["id"]] = data
            elif event == "on_run_step_closed" and data.get("id") in steps:
                steps[data["id"]] = {**steps[data["id"]], **{
                    key: data[key] for key in ("status", "closed_at") if key in data}}
            elif event == "on_message_delta":
                content = (data.get("delta") or {}).get("content") or {}
                if content.get("type") == "text" and isinstance(content.get("text"), str) and content["text"]:
                    if content_parts and content_parts[-1].get("type") == "text":
                        content_parts[-1]["text"] += content["text"]
                    else:
                        content_parts.append({"type": "text", "text": content["text"],
                                              "phase": "final_answer"})
            elif event == "on_steer_applied" and isinstance(data.get("part"), dict):
                content_parts.append(data["part"])
        pending = state.get("pendingAction")
        initial = content_parts
        pending_steers = (state.get("steering") or {}).get("queue", [])
        from .steering import _public

        result = {
            "runSteps": list(steps.values()),
            "aggregatedContent": initial,
            "pendingSteers": [_public(item) for item in pending_steers],
            "userMessage": {
                "messageId": generation.user_message_id,
                "conversationId": generation.conversation_id,
                "text": user["text"] if user else "",
                **({"parentMessageId": user["parent_id"]} if user and user["parent_id"] else {}),
            },
            "responseMessageId": generation.response_message_id,
            "conversationId": generation.conversation_id,
            "sender": "Assistant",
            "model": state.get("model") or "",
            **({"pendingAction": self.client_pending_action(pending)} if pending else {}),
        }
        return result, max_seq

    def events(self, owner: str, run_id: str, after: int = 0, limit: int = 200) -> list[tuple[int, dict]]:
        with self.database.connect() as db:
            rows = db.execute(
                "SELECT ge.seq,ge.data FROM generation_events ge JOIN runs r ON r.id=ge.run_id "
                "JOIN conversations c ON c.id=r.conversation_id "
                "WHERE c.owner=? AND ge.run_id=? AND ge.seq>? ORDER BY ge.seq LIMIT ?",
                (owner, run_id, after, min(200, max(1, limit))),
            ).fetchall()
            return [(int(row[0]), json.loads(row[1])) for row in rows]

    def accumulated_text(self, owner: str, run_id: str) -> str:
        """Reassemble already-streamed deltas for a restarted owner-bound run.

        A resumed StateGraph must not lose previous assistant text, and must not
        reemit old SSE chunks. This uses the existing generation event contract.
        """
        with self.database.connect() as db:
            rows = db.execute(
                "SELECT ge.data FROM generation_events ge JOIN runs r ON r.id=ge.run_id "
                "JOIN conversations c ON c.id=r.conversation_id "
                "WHERE c.owner=? AND ge.run_id=? ORDER BY ge.seq", (owner, run_id),
            ).fetchall()
        chunks = []
        for row in rows:
            event = json.loads(row["data"])
            if event.get("event") == "on_message_delta":
                content = event.get("data", {}).get("delta", {}).get("content", {})
                value = content.get("text") if isinstance(content, dict) else None
                if isinstance(value, str):
                    chunks.append(value)
        return "".join(chunks)

    def history(self, owner: str, conversation_id: str, max_messages: int = 50,
                *, message_id: str | None = None) -> list[dict]:
        with self.database.connect() as db:
            if not db.execute("SELECT 1 FROM conversations WHERE id=? AND owner=?",
                              (conversation_id, owner)).fetchone():
                raise KeyError("Conversation not found")
            if message_id is None:
                latest = db.execute(
                    "SELECT id FROM messages WHERE conversation_id=? ORDER BY created_at DESC,id DESC LIMIT 1",
                    (conversation_id,),
                ).fetchone()
                message_id = latest["id"] if latest else None
            result = []
            seen = set()
            while message_id and message_id != "00000000-0000-0000-0000-000000000000":
                if message_id in seen:
                    raise ValueError("Message graph contains a cycle")
                seen.add(message_id)
                row = db.execute("SELECT id,parent_id,role,text,content,metadata FROM messages WHERE id=? AND conversation_id=?",
                                 (message_id, conversation_id)).fetchone()
                if row is None:
                    raise KeyError("Message ancestor not found")
                if row["role"] in {"user", "assistant"}:
                    content = row["text"]
                    # Original formatMessage/formatAgentMessages read persisted
                    # structured text before the top-level display snapshot.
                    # Keep this existing text-only history boundary; rich/tool
                    # message reconstruction is handled separately.
                    parts = json.loads(row["content"])
                    if isinstance(parts, list):
                        texts = [part["text"] for part in parts if isinstance(part, dict)
                                 and part.get("type") == "text" and isinstance(part.get("text"), str)]
                        if texts:
                            content = "".join(texts)
                        if row["role"] == "assistant":
                            # Upstream formatAgentMessages replays STEER parts
                            # as user instructions, not as assistant prose.
                            from .steering import merged_text

                            for part in reversed(parts):
                                if (isinstance(part, dict) and part.get("type") == "steer"
                                    and isinstance(part.get("steer"), str)):
                                    result.append({"role": "user", "content": merged_text(part),
                                                   "source": "steer", "files": part.get("files", [])})
                    files = json.loads(row["metadata"]).get("files", [])
                    if row["role"] == "user" and files:
                        descriptors = []
                        for file in files:
                            attachment = db.execute("SELECT id,name,path FROM attachments WHERE id=? AND owner=?",
                                                    (file["file_id"], owner)).fetchone()
                            descriptors.append({"file_id": file["file_id"], "machine": "local",
                                **({"filename": attachment["name"], "path": attachment["path"]}
                                   if attachment else {"unavailable": True})})
                        content += "\n\nController attachments (use authorized LSM file tools):\n" + _json(descriptors)
                    result.append({"role": row["role"], "content": content})
                if len(result) >= max(1, min(max_messages, 100)):
                    break
                message_id = row["parent_id"]
        return list(reversed(result))

    def finish(self, owner: str, run_id: str, *, status: str, text: str = "",
               error: str | None = None, expired_action_id: str | None = None) -> bool:
        if status not in _TERMINAL:
            raise ValueError("Only terminal statuses can finish a generation")
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT r.* FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.id=? AND c.owner=?", (run_id, owner),
            ).fetchone()
            if not row or row["status"] in _TERMINAL:
                return False
            if expired_action_id is not None:
                pending = json.loads(row["state"]).get("pendingAction")
                if (row["status"] != "requires_action" or
                    not isinstance(pending, dict) or
                    pending.get("actionId") != expired_action_id or
                    not self.action_expired(pending)):
                    return False
            generation = self._run(row)
            now = _now()
            # Preserve source React tool-call parts in history and final SSE,
            # rather than erasing them when the assistant text is committed.
            tool_parts = {}
            content = []
            for event in db.execute("SELECT data FROM generation_events WHERE run_id=? ORDER BY seq", (run_id,)):
                value = json.loads(event["data"])
                kind = value.get("event")
                data = value.get("data") or {}
                if kind == "on_run_step_completed":
                    result = data.get("result", {})
                    if isinstance(result.get("tool_call"), dict):
                        tool_parts[result["id"]] = {"type": "tool_call", "tool_call": {
                            **result["tool_call"], "stepId": result["id"],
                        }}
                elif kind == "on_message_delta":
                    delta = (data.get("delta") or {}).get("content") or {}
                    if delta.get("type") == "text" and isinstance(delta.get("text"), str) and delta["text"]:
                        if content and content[-1].get("type") == "text":
                            content[-1]["text"] += delta["text"]
                        else:
                            content.append({"type": "text", "text": delta["text"], "phase": "final_answer"})
                elif kind == "on_steer_applied" and isinstance(data.get("part"), dict):
                    content.append(data["part"])
            if not content and text:
                content.append({"type": "text", "text": text, "phase": "final_answer"})
            content += list(tool_parts.values())
            # LibreChat agents/client.js emits ContentTypes.ERROR as a content
            # part. A top-level final.error alone is ignored by finalHandler.
            # Persist the same part so the error survives history reload too.
            if status in {"error", "interrupted"}:
                content.append({"type": "error", "error": error or "Generation failed"})
            response_message = {
                "messageId": generation.response_message_id,
                "conversationId": generation.conversation_id,
                "parentMessageId": generation.user_message_id,
                "sender": "Assistant", "isCreatedByUser": False,
                "text": text,
                "content": content,
                "unfinished": status != "complete",
            }
            if content:
                db.execute(
                    "INSERT INTO messages(id,conversation_id,parent_id,role,text,content,metadata,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (generation.response_message_id, generation.conversation_id, generation.user_message_id,
                     "assistant", text, _json(response_message["content"]),
                     _json({"sender": "Assistant", "isCreatedByUser": False,
                            "unfinished": status != "complete"}), now, now),
                )
            run_state = json.loads(row["state"])
            from .steering import SteeringStore

            pending_steers = SteeringStore.settle_leftovers(run_state)
            if status != "interrupted":
                run_state.pop("resumeClaim", None)
                run_state.pop("approvedToolBatch", None)
            db.execute("UPDATE runs SET status=?,state=?,updated_at=? WHERE id=?",
                       (status, _json(run_state), now, run_id))
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, generation.conversation_id))
            final = {
                "final": True,
                "generationProtocolVersion": generation.protocol_version,
                "conversation": {"conversationId": generation.conversation_id},
                "responseMessage": response_message,
                **({"aborted": True} if status == "aborted" else {}),
                **({"error": error or "Generation failed"} if status in {"error", "interrupted"} else {}),
                **({"pendingSteers": pending_steers} if pending_steers else {}),
            }
            db.execute("INSERT INTO generation_events(run_id,data) VALUES(?,?)", (run_id, _json(final)))
            return True

    def recover_orphans(self, active_run_ids: set[str] | None = None) -> int:
        """Never leave a crashed owner-generation shown as live indefinitely."""
        active = active_run_ids or set()
        with self.database.connect() as db:
            rows = db.execute(
                "SELECT r.id,c.owner FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.status='running'",
            ).fetchall()
        recovered = 0
        for row in rows:
            if row["id"] not in active and self.finish(row["owner"], row["id"], status="interrupted"):
                recovered += 1
        return recovered
