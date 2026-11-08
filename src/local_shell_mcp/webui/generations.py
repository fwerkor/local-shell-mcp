"""Durable, authenticated LibreChat generation-event stream on shared SQLite.

A user turn, its generation lease, event log, assistant message and terminal
outcome are stored in the one LSM database. HTTP SSE consumers can disconnect
and replay events without losing the source generation. Provider calls are
owned by the Controller's event loop, not by the browser connection.
"""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from dataclasses import dataclass
from typing import Any

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

    def begin(self, owner: str, payload: dict, agent: dict | None = None) -> tuple[Generation, bool]:
        client_request_id = payload.get("clientRequestId")
        if client_request_id is not None and (not isinstance(client_request_id, str) or
                                               not 1 <= len(client_request_id) <= 160):
            raise ValueError("Invalid client request id")
        raw_conversation_id = payload.get("conversationId")
        new_conversation = raw_conversation_id in (None, "", "new", "new_conversation")
        if raw_conversation_id is not None and not isinstance(raw_conversation_id, str):
            raise ValueError("Invalid conversation id")
        project_id = payload.get("projectId", payload.get("chatProjectId")) if new_conversation else None
        if project_id is not None and (not isinstance(project_id, str) or not project_id):
            raise ValueError("Invalid project id")
        conversation_id = str(uuid.uuid4()) if new_conversation else raw_conversation_id
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
            "provider": selected_provider(payload, agent),
            "model": str((agent or {}).get("model") or payload.get("model") or ""),
            "askUserEnabled": bool(agent and "ask_user_question" in (agent.get("tools") or [])),
        }
        with self.database.connect() as db:
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
            user_metadata = {
                "sender": "User", "isCreatedByUser": True,
                "endpoint": str(payload.get("endpoint") or "agents"),
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
                    "isCreatedByUser": True,
                },
            }
            db.execute("INSERT INTO generation_events(run_id,data) VALUES(?,?)", (run_id, _json(created)))
        return Generation(run_id, conversation_id, stamp_ms, response_message_id,
                          user_message_id, "running", (agent or {}).get("id") or payload.get("agent_id")), True

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
            state["resumeHistory"] = history
            state["partialText"] = partial_text
            db.execute("UPDATE runs SET state=?,status='requires_action',updated_at=? WHERE id=?",
                       (_json(state), _now(), run_id))
            db.execute("INSERT INTO generation_events(run_id,data) VALUES(?,?)",
                       (run_id, _json({"event": "on_pending_action", "data": pending})))
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
            state.pop("pendingAction", None)
            state.pop("resumeHistory", None)
            state.pop("partialText", None)
            db.execute("UPDATE runs SET state=?,status='running',updated_at=? WHERE id=?",
                       (_json(state), _now(), run_id))
            return self._run(row), history, partial_text

    def pause_for_approval(self, owner: str, run_id: str, pending: dict,
                           history: list[dict], partial_text: str) -> bool:
        return self.pause_for_question(owner, run_id, pending, history, partial_text)

    def claim_approval(self, owner: str, run_id: str, action_id: str,
                       decisions: list[dict]) -> tuple[Generation, list[dict], str, dict, str]:
        if not isinstance(decisions, list) or len(decisions) != 1 or not isinstance(decisions[0], dict):
            raise ValueError("Exactly one external MCP decision is required")
        decision = decisions[0]
        kind = decision.get("decision")
        if kind not in {"approve", "reject"}:
            raise ValueError("MCP tool calls can only be approved or rejected")
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
            payload = pending.get("payload") or {}
            calls = payload.get("action_requests") or []
            if payload.get("type") != "tool_approval" or len(calls) != 1:
                raise ValueError("Unexpected approval format")
            requested = calls[0]
            if decision.get("tool_call_id") != requested.get("tool_call_id"):
                raise ValueError("Mismatched tool call decision")
            history = state.get("resumeHistory")
            if not isinstance(history, list):
                raise ValueError("Missing model continuation history")
            prior = state.get("partialText", "")
            state.pop("pendingAction", None)
            state.pop("resumeHistory", None)
            state.pop("partialText", None)
            db.execute("UPDATE runs SET state=?,status='running',updated_at=? WHERE id=?",
                       (_json(state), _now(), run_id))
            return self._run(row), history, prior, requested, kind

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

    def events(self, owner: str, run_id: str, after: int = 0, limit: int = 200) -> list[tuple[int, dict]]:
        with self.database.connect() as db:
            rows = db.execute(
                "SELECT ge.seq,ge.data FROM generation_events ge JOIN runs r ON r.id=ge.run_id "
                "JOIN conversations c ON c.id=r.conversation_id "
                "WHERE c.owner=? AND ge.run_id=? AND ge.seq>? ORDER BY ge.seq LIMIT ?",
                (owner, run_id, after, min(200, max(1, limit))),
            ).fetchall()
            return [(int(row[0]), json.loads(row[1])) for row in rows]

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
                row = db.execute("SELECT id,parent_id,role,text FROM messages WHERE id=? AND conversation_id=?",
                                 (message_id, conversation_id)).fetchone()
                if row is None:
                    raise KeyError("Message ancestor not found")
                if row["role"] in {"user", "assistant"}:
                    result.append({"role": row["role"], "content": row["text"]})
                if len(result) >= max(1, min(max_messages, 100)):
                    break
                message_id = row["parent_id"]
        return list(reversed(result))

    def finish(self, owner: str, run_id: str, *, status: str, text: str = "",
               error: str | None = None) -> bool:
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
            generation = self._run(row)
            now = _now()
            response_message = {
                "messageId": generation.response_message_id,
                "conversationId": generation.conversation_id,
                "parentMessageId": generation.user_message_id,
                "sender": "Assistant", "isCreatedByUser": False,
                "text": text,
                "content": [{"type": "text", "text": text, "phase": "final_answer"}] if text else [],
                "unfinished": status != "complete",
            }
            if text:
                db.execute(
                    "INSERT INTO messages(id,conversation_id,parent_id,role,text,content,metadata,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (generation.response_message_id, generation.conversation_id, generation.user_message_id,
                     "assistant", text, _json(response_message["content"]),
                     _json({"sender": "Assistant", "isCreatedByUser": False,
                            "unfinished": status != "complete"}), now, now),
                )
            db.execute("UPDATE runs SET status=?, updated_at=? WHERE id=?", (status, now, run_id))
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, generation.conversation_id))
            final = {
                "final": True,
                "generationProtocolVersion": 2,
                "conversation": {"conversationId": generation.conversation_id},
                "responseMessage": response_message,
                **({"aborted": True} if status == "aborted" else {}),
                **({"error": error or "Generation failed"} if status in {"error", "interrupted"} else {}),
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
