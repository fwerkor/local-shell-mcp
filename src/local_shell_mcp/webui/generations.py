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
              protocol_version: int = 2) -> tuple[Generation, bool]:
        client_request_id = payload.get("clientRequestId")
        if client_request_id is not None and (not isinstance(client_request_id, str) or
                                               not 1 <= len(client_request_id) <= 160):
            raise ValueError("Invalid client request id")
        manual_compaction = payload.get('compact') is True
        raw_conversation_id = payload.get("conversationId")
        new_conversation = raw_conversation_id in (None, "", "new", "new_conversation")
        if manual_compaction:
            anchor = payload.get('parentMessageId')
            if new_conversation or not isinstance(anchor, str) or not anchor or anchor == '00000000-0000-0000-0000-000000000000':
                raise ValueError('Compaction requires an existing conversation and a parent message')
            if any(payload.get(key) for key in ('isContinued', 'isRegenerate', 'editedContent', 'responseMessageId')):
                raise ValueError('Compaction cannot be combined with an edit, regenerate, or continue')
        if raw_conversation_id is not None and not isinstance(raw_conversation_id, str):
            raise ValueError("Invalid conversation id")
        project_id = payload.get("projectId", payload.get("chatProjectId")) if new_conversation else None
        if project_id is not None and (not isinstance(project_id, str) or not project_id):
            raise ValueError("Invalid project id")
        conversation_id = str(uuid.uuid4()) if new_conversation else raw_conversation_id
        prompt = payload.get("text")
        if manual_compaction:
            prompt = ''
        if not manual_compaction and (not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode("utf-8")) > _MAX_PROMPT_BYTES):
            raise ValueError("A non-empty text message is required (max 128 KiB)")
        user_message_id = str(payload.get('parentMessageId') if manual_compaction else (payload.get('messageId') or uuid.uuid4()))
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
            'manualCompaction': manual_compaction,
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
            if manual_compaction and not db.execute(
                'SELECT 1 FROM messages WHERE id=? AND conversation_id=?',
                (user_message_id, conversation_id),
            ).fetchone():
                raise KeyError('Compaction anchor not found')
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
            if not manual_compaction:
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
            if manual_compaction:
                created['message'] = {'messageId': user_message_id,
                    'conversationId': conversation_id, 'text': '', 'compact': True}
            db.execute("INSERT INTO generation_events(run_id,data) VALUES(?,?)", (run_id, _json(created)))
        return Generation(run_id, conversation_id, stamp_ms, response_message_id,
                          user_message_id, "running", (agent or {}).get("id") or payload.get("agent_id"), protocol_version), True

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

    def events(self, owner: str, run_id: str, after: int = 0, limit: int = 200) -> list[tuple[int, dict]]:
        with self.database.connect() as db:
            rows = db.execute(
                "SELECT ge.seq,ge.data FROM generation_events ge JOIN runs r ON r.id=ge.run_id "
                "JOIN conversations c ON c.id=r.conversation_id "
                "WHERE c.owner=? AND ge.run_id=? AND ge.seq>? ORDER BY ge.seq LIMIT ?",
                (owner, run_id, after, min(200, max(1, limit))),
            ).fetchall()
            return [(int(row[0]), json.loads(row[1])) for row in rows]

    def token_calibration(self, owner: str, run_id: str, provider: str, model: str):
        """Read source-style calibration by owner, model and active run.

        A new generation seeds from conversation metadata; a resumed
        generation always prefers its own run state, preserving the last
        confirmed token observation after controller restart.
        """
        import hashlib

        from .context_calibration import TokenCalibration

        key = hashlib.sha256((provider + '\x00' + model).encode()).hexdigest()
        with self.database.connect() as db:
            row = db.execute(
                'SELECT r.state,c.metadata FROM runs r JOIN conversations c ON c.id=r.conversation_id '
                'WHERE r.id=? AND c.owner=?', (run_id, owner),
            ).fetchone()
        if row is None:
            raise KeyError('Generation not found or unauthorized')
        state = json.loads(row['state'])
        conversation = json.loads(row['metadata'])
        for source in (state, conversation):
            entries = source.get('tokenCalibrations') if isinstance(source, dict) else None
            if isinstance(entries, dict) and key in entries:
                return TokenCalibration.from_dict(entries[key])
        return TokenCalibration()

    def record_token_calibration(self, owner: str, run_id: str, provider: str, model: str,
                                 calibration) -> None:
        """Atomically persist confirmed provider calibration with the conversation."""
        import hashlib

        from .context_calibration import TokenCalibration

        if not isinstance(calibration, TokenCalibration):
            raise TypeError('A token calibration snapshot is required')
        key = hashlib.sha256((provider + '\x00' + model).encode()).hexdigest()
        with self.database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute(
                'SELECT r.state,c.id AS conversation_id,c.metadata FROM runs r '
                'JOIN conversations c ON c.id=r.conversation_id '
                "WHERE r.id=? AND c.owner=? AND r.status='running'", (run_id, owner),
            ).fetchone()
            if row is None:
                raise KeyError('Generation not active or unauthorized')
            state = json.loads(row['state'])
            metadata = json.loads(row['metadata'])
            for record in (state, metadata):
                entries = record.get('tokenCalibrations')
                entries = dict(entries) if isinstance(entries, dict) else {}
                entries[key] = calibration.to_dict()
                if len(entries) > 32:
                    for expired in list(entries)[:-32]:
                        entries.pop(expired, None)
                record['tokenCalibrations'] = entries
            db.execute('UPDATE runs SET state=?,updated_at=? WHERE id=?',
                       (_json(state), _now(), run_id))
            db.execute('UPDATE conversations SET metadata=?,updated_at=? WHERE id=? AND owner=?',
                       (_json(metadata), _now(), row['conversation_id'], owner))

    def record_context_usage(self, owner: str, run_id: str, snapshot: dict) -> int:
        """Commit a visible context snapshot to run state and the SSE replay log.

        Like the upstream contextUsageSink, the last pre-invoke snapshot wins;
        the same transaction ensures process recovery can replay what users saw.
        """
        event = {'event': 'on_context_usage', 'data': snapshot}
        encoded = _json(event)
        if len(encoded.encode('utf-8')) > 256 * 1024:
            raise ValueError('Context usage event exceeds 256 KiB')
        with self.database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute(
                "SELECT r.state FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.id=? AND c.owner=? AND r.status='running'", (run_id, owner),
            ).fetchone()
            if row is None:
                raise KeyError('Generation not active or unauthorized')
            count = db.execute('SELECT count(*) FROM generation_events WHERE run_id=?',
                               (run_id,)).fetchone()[0]
            if count >= _EVENT_LIMIT:
                raise ValueError('Generation event retention limit reached')
            state = json.loads(row['state'])
            state['contextUsage'] = snapshot
            db.execute('UPDATE runs SET state=?,updated_at=? WHERE id=?',
                       (_json(state), _now(), run_id))
            event_row = db.execute('INSERT INTO generation_events(run_id,data) VALUES(?,?)',
                                   (run_id, encoded))
            return int(event_row.lastrowid)

    def stage_summary(self, owner: str, run_id: str, summary_text: str, token_count: int,
                      *, boundary: int = 0, manual: bool = False) -> None:
        """Atomic candidate checkpoint in the *existing run state*, no deletion.

        The final assistant content and terminal run status commit together in
        finish(). A crash before that commit leaves all original messages.
        """
        if not isinstance(summary_text, str) or not summary_text.strip():
            raise ValueError('A completed summary must contain text')
        if token_count < 0:
            raise ValueError('Invalid summary token count')
        with self.database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT r.state FROM runs r JOIN conversations c ON c.id=r.conversation_id '
                             "WHERE r.id=? AND c.owner=? AND r.status=\'running\'",
                             (run_id, owner)).fetchone()
            if row is None:
                raise KeyError('Generation no longer active')
            state = json.loads(row['state'])
            state['summaryCheckpoint'] = {'type': 'summary', 'content': [{'type': 'text', 'text': summary_text}],
                'boundary': {'messageIndex': boundary}, 'tokenCount': token_count,
                **({'initiatedBy': 'user'} if manual else {})}
            db.execute('UPDATE runs SET state=?,updated_at=? WHERE id=?', (_json(state), _now(), run_id))

    def manual_compaction(self, owner: str, run_id: str) -> bool:
        with self.database.connect() as db:
            row = db.execute('SELECT r.state FROM runs r JOIN conversations c ON c.id=r.conversation_id '
                             'WHERE r.id=? AND c.owner=?', (run_id, owner)).fetchone()
        return bool(row and json.loads(row['state']).get('manualCompaction'))

    def history(self, owner: str, conversation_id: str, max_messages: int | None = None,
                *, message_id: str | None = None) -> list[dict]:
        """Read the complete active branch until its last usable checkpoint.

        Failed, empty and partial summary blocks never bound history; this is
        exactly the distinction in LibreChat resolveCheckpointMessage().
        Raw messages remain immutable for replay, edits and error recovery.
        """
        from .compaction import (
            build_summary_carrier_text,
            find_checkpoint_summary_part,
            get_summary_part_text,
        )

        with self.database.connect() as db:
            if not db.execute('SELECT 1 FROM conversations WHERE id=? AND owner=?',
                              (conversation_id, owner)).fetchone():
                raise KeyError('Conversation not found')
            if message_id is None:
                latest = db.execute('SELECT id FROM messages WHERE conversation_id=? '
                                    'ORDER BY created_at DESC,id DESC LIMIT 1',
                                    (conversation_id,)).fetchone()
                message_id = latest['id'] if latest else None
            reversed_messages: list[dict] = []
            seen = set()
            while message_id and message_id != '00000000-0000-0000-0000-000000000000':
                if message_id in seen:
                    raise ValueError('Message graph contains a cycle')
                seen.add(message_id)
                row = db.execute('SELECT id,parent_id,role,text,content,metadata FROM messages '
                                 'WHERE id=? AND conversation_id=?', (message_id, conversation_id)).fetchone()
                if row is None:
                    raise KeyError('Message ancestor not found')
                role = row['role']
                parts = json.loads(row['content'])
                metadata = json.loads(row['metadata'])
                stop_at_checkpoint = False
                if role in {'user', 'assistant', 'system', 'tool'}:
                    text = row['text'] or ''
                    row_messages: list[dict] = []
                    if isinstance(parts, list):
                        summary = find_checkpoint_summary_part(parts) if role == 'assistant' else None
                        if summary is not None:
                            stop_at_checkpoint = True
                            parts = parts[parts.index(summary):]
                            row_messages.append({'role': 'system',
                                                 'content': build_summary_carrier_text(get_summary_part_text(summary))})
                        text_parts = [part['text'] for part in parts if isinstance(part, dict)
                                      and part.get('type') == 'text' and isinstance(part.get('text'), str)]
                        text = ''.join(text_parts) if text_parts else ('' if stop_at_checkpoint else text)
                        tool_parts = [part['tool_call'] for part in parts if isinstance(part, dict)
                                      and part.get('type') == 'tool_call'
                                      and isinstance(part.get('tool_call'), dict)]
                        calls = []
                        results = []
                        for call in tool_parts:
                            ident, name = call.get('id'), call.get('name')
                            if not isinstance(ident, str) or not isinstance(name, str) or 'output' not in call:
                                continue
                            calls.append({'id': ident, 'type': 'function', 'function': {
                                'name': name, 'arguments': _json(call.get('args', {}))}})
                            results.append({'role': 'tool', 'tool_call_id': ident,
                                            'content': str(call['output'])})
                        if calls:
                            row_messages.append({'role': 'assistant', 'content': None, 'tool_calls': calls})
                            row_messages.extend(results)
                        thinking = [part.get('text') or part.get('thinking') for part in parts
                                    if isinstance(part, dict) and part.get('type') in {'think', 'thinking', 'reasoning'}]
                        if text or (not calls and not stop_at_checkpoint):
                            item = {'role': role, 'content': text}
                            if thinking:
                                item['reasoning_content'] = '\n'.join(str(chunk) for chunk in thinking if chunk)
                            row_messages.append(item)
                    if not row_messages and not stop_at_checkpoint:
                        row_messages.append({'role': role, 'content': text})
                    files = metadata.get('files', [])
                    if role == 'user' and files and row_messages:
                        descriptors = []
                        for file in files:
                            attachment = db.execute('SELECT id,name,path FROM attachments WHERE id=? AND owner=?',
                                                    (file['file_id'], owner)).fetchone()
                            descriptors.append({'file_id': file['file_id'], 'machine': 'local',
                                **({'filename': attachment['name'], 'path': attachment['path']}
                                   if attachment else {'unavailable': True})})
                        row_messages[-1]['content'] = str(row_messages[-1].get('content') or '') + \
                            '\n\nController attachments (use authorized LSM file tools):\n' + _json(descriptors)
                    reversed_messages.extend(reversed(row_messages))
                if stop_at_checkpoint:
                    break
                if max_messages is not None and len(reversed_messages) >= max(1, max_messages):
                    break
                message_id = row['parent_id']
        return list(reversed(reversed_messages))

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
            # Preserve source React tool-call parts in history and final SSE,
            # rather than erasing them when the assistant text is committed.
            tool_parts = {}
            for event in db.execute("SELECT data FROM generation_events WHERE run_id=? ORDER BY seq", (run_id,)):
                value = json.loads(event["data"])
                if value.get("event") == "on_run_step_completed":
                    result = value.get("data", {}).get("result", {})
                    if isinstance(result.get("tool_call"), dict):
                        tool_parts[result["id"]] = {"type": "tool_call", "tool_call": {
                            **result["tool_call"], "stepId": result["id"],
                        }}
            run_state = json.loads(row['state'])
            staged = run_state.get('summaryCheckpoint')
            from .compaction import is_usable_summary_part, mark_compaction_outcome
            content = ([dict(staged)] if is_usable_summary_part(staged) else []) + (
                ([{"type": "text", "text": text, "phase": "final_answer"}] if text else [])
                + list(tool_parts.values())
            )
            # LibreChat agents/client.js emits ContentTypes.ERROR as a content
            # part. A top-level final.error alone is ignored by finalHandler.
            # Persist the same part so the error survives history reload too.
            if status in {"error", "interrupted"}:
                content.append({"type": "error", "error": error or "Generation failed"})
            if run_state.get('manualCompaction'):
                mark_compaction_outcome(content, aborted=False)
            response_metadata = {"sender": "Assistant", "isCreatedByUser": False,
                                 "unfinished": status != "complete"}
            if isinstance(run_state.get('contextUsage'), dict):
                response_metadata['metadata'] = {'contextUsage': run_state['contextUsage']}
            response_message = {
                **({'metadata': response_metadata['metadata']} if 'metadata' in response_metadata else {}),
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
                     _json(response_metadata), now, now),
                )
            db.execute("UPDATE runs SET status=?, updated_at=? WHERE id=?", (status, now, run_id))
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, generation.conversation_id))
            final = {
                "final": True,
                "generationProtocolVersion": generation.protocol_version,
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
