"""Durable, authenticated LibreChat generation-event stream on shared SQLite.

A user turn, its generation lease, event log, assistant message and terminal
outcome are stored in the one LSM database. HTTP SSE consumers can disconnect
and replay events without losing the source generation. Provider calls are
owned by the Controller's event loop, not by the browser connection.
"""

from __future__ import annotations

import contextlib
import copy
import json
import logging
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .approval_runtime import ApprovalBatch, prepare_approval_batch
from .artifact_prompts import artifact_mode
from .ask_user_tools import ask_user_requested
from .generation_protocol import job_generation_protocol
from .providers import selected_provider
from .sampling import validate_channel_sampling
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
    web_search_enabled: bool = True
    sampling: dict = field(default_factory=dict)


class GenerationConflict(Exception):
    def __init__(self, existing: Generation):
        self.existing = existing
        super().__init__("Conversation already has an active generation")


def _rewind_uncheckpointed_text(parts: list[dict], saved: str, *, preserve_slots: bool = False) -> None:
    """Remove incomplete provider text after the last durable human checkpoint.

    Preserve the placement of tool calls and steers; only assistant text is
    provisional while a model stream is in flight. The exact checkpointed
    prefix is retained even when it spans several independent text parts.
    Snapshot replay additionally keeps empty text placeholders: persisted
    step indexes must remain stable when a cached tool completes again.
    """
    if not isinstance(saved, str):
        raise ValueError('Invalid checkpoint text prefix')
    remaining = len(saved)
    retained = []
    for part in parts:
        if part.get('type') != 'text':
            retained.append(part)
            continue
        if remaining <= 0:
            if preserve_slots:
                retained.append({**part, 'text': ''})
            continue
        piece = part['text'][:remaining]
        if piece or preserve_slots:
            retained.append({**part, 'text': piece})
        remaining -= len(piece)
    parts[:] = retained


def _web_search_requested(agent: dict | None, payload: dict) -> bool:
    """Web search defaults on; explicit chat/Agent toggles take precedence."""
    ephemeral = payload.get('ephemeralAgent')
    if isinstance(ephemeral, dict) and type(ephemeral.get('web_search')) is bool:
        return ephemeral['web_search']
    if type(payload.get('web_search')) is bool:
        return payload['web_search']
    options = (agent or {}).get('model_parameters') or {}
    if isinstance(options, dict) and type(options.get('web_search')) is bool:
        return options['web_search']
    return True


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
            web_search_enabled=state.get("webSearchEnabled", True),
            sampling=state.get("sampling", {}),
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
        manual_compaction = payload.get('compact') is True
        # These idempotency namespaces are host-generated only. A browser can
        # see a task handle and must not be able to preoccupy its continuation
        # key with an unrelated generation before the child settles.
        if isinstance(client_request_id, str):
            if client_request_id.startswith("subagent-wakeup:") and _connection is None:
                raise ValueError("Internal completion idempotency key cannot be submitted")
            if client_request_id.startswith("subagent:") and trusted_new_conversation_id is None:
                raise ValueError("Internal child idempotency key cannot be submitted")
            if client_request_id.startswith("trigger_") and _connection is None:
                raise ValueError("Internal Agent Trigger idempotency key cannot be submitted")
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
        if manual_compaction:
            prompt = ''
        if not manual_compaction and (not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode("utf-8")) > _MAX_PROMPT_BYTES):
            raise ValueError("A non-empty text message is required (max 128 KiB)")
        manual_skill_ids = payload.get('manualSkills')
        if manual_skill_ids is not None:
            from .skill_runtime import resolve_manual_skills

            resolve_manual_skills(self.database, owner, agent, manual_skill_ids)
        else:
            manual_skill_ids = []
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
            "webSearchEnabled": _web_search_requested(agent, payload),
            'manualCompaction': manual_compaction,
            "artifactsMode": artifact_mode(payload, agent),
            "sampling": validate_channel_sampling(payload.get("lsmSampling", {}), selected_provider(payload, agent)) if not agent else {},
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
                    "INSERT INTO conversations(id,owner,title,model,endpoint,project_id,metadata,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (conversation_id, owner, prompt.strip()[:80], state["model"],
                     payload.get("endpoint") or "agents", project_id,
                     _json({"lsmSampling": state["sampling"]} if "lsmSampling" in payload and not agent else {}), now, now),
                )
            elif not db.execute("SELECT 1 FROM conversations WHERE id=? AND owner=?",
                                (conversation_id, owner)).fetchone():
                raise KeyError("Conversation not found")
            elif state["model"] or payload.get("endpoint"):
                # A later turn can switch model without recreating the chat. Keep
                # the conversation's saved selection in sync with the actual
                # request, including when the frontend did not send /convos/update.
                db.execute(
                    "UPDATE conversations SET model=CASE WHEN ? THEN ? ELSE model END, "
                    "endpoint=COALESCE(?,endpoint),updated_at=? WHERE id=? AND owner=?",
                    (bool(state["model"]), state["model"], payload.get("endpoint"),
                     now, conversation_id, owner),
                )
            if not new_conversation and not agent:
                if "lsmSampling" in payload:
                    db.execute("UPDATE conversations SET metadata=json_set(metadata, '$.lsmSampling', json(?)) "
                               "WHERE id=? AND owner=?", (_json(state["sampling"]), conversation_id, owner))
                else:
                    saved = db.execute("SELECT json_extract(metadata, '$.lsmSampling') FROM conversations "
                                       "WHERE id=? AND owner=?", (conversation_id, owner)).fetchone()[0]
                    if saved is not None:
                        state["sampling"] = validate_channel_sampling(json.loads(saved), state["provider"])
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
            # A successive user turn without an explicit branch pointer follows
            # the last committed assistant, otherwise only its own prompt was
            # visible to the model on the next request.
            parent_id = payload.get("parentMessageId")
            if "parentMessageId" not in payload and not new_conversation:
                parent = db.execute(
                    "SELECT id FROM messages WHERE conversation_id=? ORDER BY created_at DESC,id DESC LIMIT 1",
                    (conversation_id,),
                ).fetchone()
                parent_id = parent["id"] if parent else None
            from .attachments import resolve_files

            files = resolve_files(db, owner, payload.get("files", []))
            user_metadata = {
                "sender": "User", "isCreatedByUser": True,
                "endpoint": str(payload.get("endpoint") or "agents"),
                "files": files,
                **({"manualSkills": manual_skill_ids} if manual_skill_ids else {}),
            }
            if not manual_compaction:
                db.execute(
                    "INSERT INTO messages(id,conversation_id,parent_id,role,text,content,metadata,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (user_message_id, conversation_id, parent_id, "user", prompt,
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
                    "parentMessageId": parent_id,
                    "text": prompt,
                    "sender": "User",
                    "files": files,
                    "isCreatedByUser": True,
                    **({"manualSkills": manual_skill_ids} if manual_skill_ids else {}),
                },
            }
            if manual_compaction:
                created['message'] = {'messageId': user_message_id,
                    'conversationId': conversation_id, 'text': '', 'compact': True}
            db.execute("INSERT INTO generation_events(run_id,data) VALUES(?,?)", (run_id, _json(created)))
        return Generation(run_id, conversation_id, stamp_ms, response_message_id,
                          user_message_id, "running", (agent or {}).get("id") or payload.get("agent_id"),
                          protocol_version, state["webSearchEnabled"], state["sampling"]), True

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
                           history: list[dict], partial_text: str, *, actor_lease=None) -> bool:
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if actor_lease is not None:
                actor_lease.assert_current(db)
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

    def pause_for_oauth(self, owner: str, run_id: str, pending: dict,
                        history: list[dict], partial_text: str, auth_delta: dict, *, actor_lease=None) -> bool:
        """Park a model-selected OAuth tool without any live Python waiter.

        The original React sign-in delta and the durable interrupt are written
        together. A crash can never show a login link without a resumable run.
        """
        payload = pending.get("payload", {})
        action_id, call_id = payload.get("action_id"), payload.get("tool_call_id")
        version = payload.get("action_version")
        if (payload.get("type") != "action_oauth" or not isinstance(action_id, str)
                or not isinstance(call_id, str) or type(version) is not int):
            raise ValueError("Invalid Action OAuth interrupt")
        # Canonical tool messages may retain identical content/raw_result for
        # exact audit replay. The provider-facing context budget counts such
        # bytes once; also bound the physical checkpoint to 1 MiB.
        budget_history = []
        for message in history:
            if (isinstance(message, dict) and message.get("role") == "tool" and
                    message.get("raw_result") == message.get("content")):
                budget_history.append({key: value for key, value in message.items()
                                       if key != "raw_result"})
            else:
                budget_history.append(message)
        if (len(_json(budget_history).encode("utf-8")) > 512 * 1024 or
                len(_json(history).encode("utf-8")) > 1024 * 1024 or
                len(_json(auth_delta).encode("utf-8")) > 256 * 1024):
            raise ValueError("Action OAuth continuation too large")
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if actor_lease is not None:
                actor_lease.assert_current(db)
            row = db.execute(
                "SELECT r.* FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.id=? AND c.owner=? AND r.status='running'", (run_id, owner),
            ).fetchone()
            if row is None:
                return False
            flow = db.execute(
                "SELECT 1 FROM action_oauth_flows WHERE run_id=? AND owner=? AND action_id=? "
                "AND call_id=? AND action_version=? AND expires_at>=?",
                (run_id, owner, action_id, call_id, version, _now() // 1_000_000),
            ).fetchone()
            if flow is None:
                raise ValueError("OAuth authorization attempt expired before checkpoint")
            state = json.loads(row["state"])
            if state.get("pendingAction") is not None:
                raise ValueError("Generation already has a pending human action")
            state["pendingAction"] = pending
            state["resumeHistory"] = history
            state["partialText"] = partial_text
            db.execute("UPDATE runs SET state=?,status='requires_action',updated_at=? WHERE id=?",
                       (_json(state), _now(), run_id))
            # OAuth is presented by the retained React ToolCall component;
            # do not inject the Ask User/Approval pending-action UI here.
            db.execute("INSERT INTO generation_events(run_id,data) VALUES(?,?)", (run_id, _json(auth_delta)))
            return True

    def claim_oauth(self, owner: str, run_id: str, action_id: str, call_id: str,
                    version: int, *, lone_call: bool = True) -> tuple[Generation, list[dict], str] | None:
        """Claim a finished browser login, retaining proof across restart.

        'claimed' can be replayed after a crash because HTTP has not started.
        'dispatching' cannot be replayed without proof of the remote result.
        """
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT r.* FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.id=? AND c.owner=? AND r.status='requires_action'", (run_id, owner),
            ).fetchone()
            if row is None:
                return None
            state = json.loads(row["state"])
            pending = state.get("pendingAction")
            payload = pending.get("payload", {}) if isinstance(pending, dict) else {}
            if (payload.get("type") != "action_oauth" or payload.get("action_id") != action_id
                    or payload.get("tool_call_id") != call_id or payload.get("action_version") != version):
                return None
            history = state.get("resumeHistory")
            if not isinstance(history, list):
                raise ValueError("Missing OAuth model checkpoint continuation")
            state["oauthResume"] = {"stage": "claimed", "action_id": action_id,
                                    "tool_call_id": call_id, "action_version": version,
                                    "lone_call": lone_call, "pendingAction": pending}
            state.pop("pendingAction")
            db.execute("UPDATE runs SET state=?,status='running',updated_at=? WHERE id=?",
                       (_json(state), _now(), run_id))
            # Clear the sign-in button using the retained React delta shape.
            # The prior URL remains in the immutable SSE log for audit/replay.
            step_id = payload.get("step_id")
            if isinstance(step_id, str):
                db.execute("INSERT INTO generation_events(run_id,data) VALUES(?,?)", (run_id, _json({
                    "event": "on_run_step_delta", "data": {"id": step_id, "delta": {
                        "type": "tool_calls", "tool_calls": [{"id": call_id,
                            "name": payload.get("tool_name", ""), "args": ""}],
                        "auth": "", "expires_at": None,
                    }},
                })))
            return self._run({**dict(row), "status": "running"}), history, state.get("partialText", "")

    def oauth_dispatch(self, owner: str, run_id: str, call_id: str, stage: str) -> None:
        """Fence OAuth replay before HTTP, after checkpointed output and after batching."""
        if stage not in {"dispatching", "completed", "cleared"}:
            raise ValueError("Invalid OAuth replay stage")
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT r.state FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.id=? AND c.owner=? AND r.status='running'", (run_id, owner),
            ).fetchone()
            if row is None:
                raise PermissionError("OAuth run no longer active")
            state = json.loads(row["state"])
            marker = state.get("oauthResume")
            if marker is None:
                return
            if marker.get("tool_call_id") != call_id:
                return
            previous = marker.get("stage")
            if stage == "dispatching" and previous != "claimed":
                raise PermissionError("OAuth Action was already dispatched")
            if stage == "completed" and previous == "completed":
                # A resumed, already-authorized approval may replay the cached
                # ToolNode result after a crash. Re-acknowledging that result is
                # safe ONLY if the authoritative host completion survived in
                # the same run; the HTTP dispatch fence stays closed.
                recorded = db.execute(
                    "SELECT 1 FROM generation_events WHERE run_id=? AND "
                    "json_extract(data,'$.event')='on_run_step_completed' AND "
                    "json_extract(data,'$.data.result.tool_call.id')=? LIMIT 1",
                    (run_id, call_id),
                ).fetchone()
                if recorded is not None:
                    return
            if stage == "completed" and previous != "dispatching":
                raise PermissionError("OAuth Action HTTP completion has no dispatch record")
            if stage == "cleared" and previous not in {"completed", "claimed"}:
                raise PermissionError("OAuth Action cannot clear unverified dispatch")
            if stage == "cleared":
                state.pop("oauthResume", None)
                # A human resume claim may still need this exact approved
                # continuation after a crash. OAuth's tool replay fence and
                # human approval replay evidence have different lifetimes.
                if not isinstance(state.get("resumeClaim"), dict):
                    state.pop("resumeHistory", None)
                    state.pop("partialText", None)
            else:
                marker["stage"] = stage
            db.execute("UPDATE runs SET state=?,updated_at=? WHERE id=?", (_json(state), _now(), run_id))

    def clear_oauth_checkpoint(self, owner: str, run_id: str) -> bool:
        """Drop the replay fence after the post-tool graph checkpoint commits."""
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT r.state FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.id=? AND c.owner=? AND r.status='running'", (run_id, owner),
            ).fetchone()
            if row is None:
                return False
            state = json.loads(row["state"])
            marker = state.get("oauthResume")
            if not isinstance(marker, dict) or marker.get("stage") not in {"claimed", "completed"}:
                return False
            state.pop("oauthResume")
            if not isinstance(state.get("resumeClaim"), dict):
                state.pop("resumeHistory", None)
                state.pop("partialText", None)
            db.execute("UPDATE runs SET state=?,updated_at=? WHERE id=?", (_json(state), _now(), run_id))
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
                           history: list[dict], partial_text: str, *, actor_lease=None) -> bool:
        return self.pause_for_question(owner, run_id, pending, history, partial_text,
                                       actor_lease=actor_lease)

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
            rows = db.execute("SELECT r.id,r.state,r.conversation_id,c.owner FROM runs r "
                              "JOIN conversations c ON c.id=r.conversation_id "
                              "WHERE r.status='running'").fetchall()
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
                # Rewind to the text prefix in the *latest durable model
                # checkpoint*, not the older human-pause state. A continuation
                # can complete more model/tool turns before crashing, and those
                # saved turns must remain visible on reconnect.
                preserved = state.get('partialText', '')
                namespace = pending.get('namespace', '')
                checkpoint_ns = row['id'] + ('|' + namespace if namespace else '')
                latest = None
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                              "AND name='agent_checkpoints'").fetchone():
                    latest = db.execute(
                        "SELECT checkpoint FROM agent_checkpoints WHERE owner=? "
                        "AND thread_id=? AND checkpoint_ns=? AND checkpoint IS NOT NULL "
                        "AND expires_at>? ORDER BY checkpoint_id DESC LIMIT 1",
                        (row['owner'], row['conversation_id'], checkpoint_ns, time.time()),
                    ).fetchone()
                if latest is not None:
                    saved = json.loads(latest['checkpoint']).get('channel_values') or {}
                    checkpoint_text = saved.get('partial_text')
                    if (isinstance(preserved, str) and isinstance(checkpoint_text, str)
                            and checkpoint_text.startswith(preserved)):
                        preserved = checkpoint_text
                db.execute("INSERT INTO generation_events(run_id,data) VALUES(?,?)",
                           (row['id'], _json({'event': 'on_content_rewind', 'data': {
                               'preserveText': preserved}})))
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
                                history: list[dict], partial_text: str, *, actor_lease=None) -> bool:
        """Retire approval proof only after checkpointed tool results are saved."""
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if actor_lease is not None:
                actor_lease.assert_current(db)
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

    @staticmethod
    def _record_completed_arguments(db, run_id: str, event: dict, full_arguments: dict | None):
        """Owner-verified, durable tool evidence outside truncated SSE previews."""
        if full_arguments is None:
            return
        tool = ((event.get('data') or {}).get('result') or {}).get('tool_call') or {}
        if (event.get('event') != 'on_run_step_completed' or not isinstance(tool.get('id'), str)
                or not isinstance(tool.get('name'), str) or not isinstance(full_arguments, dict)):
            raise ValueError('Invalid completed tool evidence')
        row = db.execute('SELECT state FROM runs WHERE id=?', (run_id,)).fetchone()
        state = json.loads(row['state'])
        proofs = state.setdefault('completedToolArguments', {})
        proof = {'name': tool['name'], 'arguments': full_arguments}
        if tool['id'] in proofs and proofs[tool['id']] != proof:
            raise ValueError('Cannot change completed tool arguments')
        proofs[tool['id']] = proof
        db.execute('UPDATE runs SET state=?,updated_at=? WHERE id=?', (_json(state), _now(), run_id))

    def append(self, owner: str, run_id: str, event: dict, *, actor_lease=None,
               full_arguments: dict | None = None) -> int:
        encoded = _json(event)
        if len(encoded.encode("utf-8")) > 256 * 1024:
            raise ValueError("Generation event exceeds 256 KiB")
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if actor_lease is not None:
                actor_lease.assert_current(db)
            if not db.execute(
                "SELECT 1 FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.id=? AND c.owner=? AND r.status='running'", (run_id, owner),
            ).fetchone():
                raise KeyError("Generation not active or unauthorized")
            count = db.execute("SELECT count(*) FROM generation_events WHERE run_id=?", (run_id,)).fetchone()[0]
            if count >= _EVENT_LIMIT:
                raise ValueError("Generation event retention limit reached")
            cursor = db.execute("INSERT INTO generation_events(run_id,data) VALUES(?,?)", (run_id, encoded))
            self._record_completed_arguments(db, run_id, event, full_arguments)
            return int(cursor.lastrowid)

    def append_tool_completion(self, owner: str, run_id: str, event: dict,
                               tool_call_id: str, file_ids: list[str],
                               *, actor_lease=None, full_arguments: dict | None = None) -> int:
        """Commit a tool completion and its file attachments atomically."""
        from .tool_attachments import link_tool_attachment

        encoded = _json(event)
        if len(encoded.encode("utf-8")) > 256 * 1024:
            raise ValueError("Generation event exceeds 256 KiB")
        if len(file_ids) > 16:
            raise ValueError("Tool attachment count exceeds limit")
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if actor_lease is not None:
                actor_lease.assert_current(db)
            if not db.execute(
                "SELECT 1 FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.id=? AND c.owner=? AND r.status='running'", (run_id, owner),
            ).fetchone():
                raise KeyError("Generation not active or unauthorized")
            step_id = (event.get("data") or {}).get("result", {}).get("id")
            if not isinstance(step_id, str) or not step_id:
                raise ValueError("Tool completion requires a run step identifier")
            prior = db.execute(
                "SELECT seq,data FROM generation_events WHERE run_id=? "
                "AND json_extract(data,'$.event')='on_run_step_completed' "
                "AND json_extract(data,'$.data.result.id')=? LIMIT 1",
                (run_id, step_id),
            ).fetchone()
            if prior:
                persisted = json.loads(prior["data"])
                # ``completed_at`` is the wall-clock acknowledgement time,
                # not part of the immutable tool result. Approval recovery
                # calls _completed again after restart with a fresh timestamp.
                # Compare every other field, including output, arguments and
                # call identity, so a genuinely changed result still fails.
                earlier = copy.deepcopy(persisted)
                replayed = copy.deepcopy(event)
                for value in (earlier, replayed):
                    value.get("data", {}).get("result", {}).pop("completed_at", None)
                if earlier != replayed:
                    raise ValueError("Cannot change a persisted tool completion")
                return int(prior["seq"])
            count = db.execute(
                "SELECT count(*) FROM generation_events WHERE run_id=?", (run_id,),
            ).fetchone()[0]
            if count + 1 + len(file_ids) > _EVENT_LIMIT:
                raise ValueError("Generation event retention limit reached")
            cursor = db.execute("INSERT INTO generation_events(run_id,data) VALUES(?,?)",
                                (run_id, encoded))
            self._record_completed_arguments(db, run_id, event, full_arguments)
            for ident in file_ids:
                try:
                    link_tool_attachment(
                        self.database, owner, run_id, tool_call_id, ident, db=db,
                    )
                except (OSError, PermissionError, KeyError, ValueError):
                    # Remote file IDs are not Controller-published blobs.
                    continue
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
        tool_slot_by_step: dict[str, int] = {}
        text_slot_by_step: dict[str, int] = {}
        for entry in entries:
            item = json.loads(entry["data"])
            event, data = item.get("event"), item.get("data") or {}
            if event == "on_run_step" and isinstance(data, dict) and isinstance(data.get("id"), str):
                steps[data["id"]] = data
                if (data.get("type") == "message_creation" and
                        data.get("id") not in text_slot_by_step and
                        data.get("index") == len(content_parts)):
                    # React allocates a content slot at the opening step, even
                    # if its first text chunk arrives after a completed tool.
                    text_slot_by_step[data["id"]] = len(content_parts)
                    creation = (data.get("stepDetails") or {}).get("message_creation") or {}
                    if creation.get("content_type") == "think":
                        content_parts.append({"type": "think", "think": ""})
                    else:
                        content_parts.append({"type": "text", "text": "", "phase": "final_answer"})
                elif data.get("type") == "tool_calls" and data["id"] not in tool_slot_by_step:
                    calls = (data.get("stepDetails") or {}).get("tool_calls") or []
                    if calls and isinstance(calls[0], dict):
                        call = calls[0]
                        part = {"type": "tool_call", "tool_call": {
                            "id": call.get("id", ""), "name": call.get("name", ""),
                            "args": call.get("args", {}), "stepId": data["id"],
                        }}
                        index = data.get("index")
                        if type(index) is not int or index < 0:
                            index = len(content_parts)
                        # React reserves this index at ON_RUN_STEP, not when
                        # the tool finishes. A later tool can complete first;
                        # its result must never occupy the earlier tool's slot.
                        while len(content_parts) < index:
                            content_parts.append({"type": "text", "text": "", "phase": "final_answer"})
                        if index == len(content_parts):
                            content_parts.append(part)
                        else:
                            content_parts[index] = part
                        tool_slot_by_step[data["id"]] = index
            elif event == "on_run_step_closed" and data.get("id") in steps:
                steps[data["id"]] = {**steps[data["id"]], **{
                    key: data[key] for key in ("status", "closed_at") if key in data}}
            elif event == "on_run_step_completed":
                result = data.get("result") or {}
                tool_call = result.get("tool_call")
                if isinstance(tool_call, dict):
                    step_id = result.get('id')
                    part = {'type': 'tool_call', 'tool_call': {
                        **tool_call, 'stepId': step_id}}
                    if isinstance(step_id, str) and step_id in tool_slot_by_step:
                        # Crash recovery can replay the same cached completion.
                        # React updates by step ID, so the snapshot must update
                        # that slot instead of adding another content element.
                        content_parts[tool_slot_by_step[step_id]] = part
                    else:
                        if isinstance(step_id, str):
                            tool_slot_by_step[step_id] = len(content_parts)
                        content_parts.append(part)
            elif event == "on_message_delta":
                content = (data.get("delta") or {}).get("content") or {}
                if content.get("type") == "text" and isinstance(content.get("text"), str) and content["text"]:
                    slot = text_slot_by_step.get(data.get("id"))
                    if slot is not None and slot < len(content_parts):
                        content_parts[slot]["text"] += content["text"]
                    elif content_parts and content_parts[-1].get("type") == "text":
                        content_parts[-1]["text"] += content["text"]
                    else:
                        content_parts.append({"type": "text", "text": content["text"],
                                              "phase": "final_answer"})
            elif event == 'on_reasoning_delta':
                part = (data.get('delta') or {}).get('content') or {}
                if part.get('type') == 'think' and isinstance(part.get('think'), str) and part['think']:
                    slot = text_slot_by_step.get(data.get('id'))
                    if slot is not None and slot < len(content_parts):
                        existing = content_parts[slot]
                        if existing.get('type') == 'text' and not existing.get('text'):
                            content_parts[slot] = {'type': 'think', 'think': part['think']}
                        elif existing.get('type') == 'think':
                            existing['think'] += part['think']
                    elif content_parts and content_parts[-1].get('type') == 'think':
                        content_parts[-1]['think'] += part['think']
                    else:
                        content_parts.append({'type': 'think', 'think': part['think']})
            elif event == "on_steer_applied" and isinstance(data.get("part"), dict):
                content_parts.append(data["part"])
            elif event == 'on_content_rewind':
                _rewind_uncheckpointed_text(content_parts, data.get('preserveText', ''),
                                           preserve_slots=True)
                # Retain live content indices for React RunStep events, while
                # validating recovered mappings before cached tool replay.
                tool_slot_by_step = {
                    part["tool_call"]["stepId"]: index for index, part in enumerate(content_parts)
                    if part.get("type") == "tool_call" and isinstance(part.get("tool_call"), dict)
                    and isinstance(part["tool_call"].get("stepId"), str)
                }
                text_slot_by_step = {step_id: index for step_id, index in text_slot_by_step.items()
                                     if index < len(content_parts) and content_parts[index].get("type") == "text"}
        pending = state.get("pendingAction")
        oauth_prompts = []
        if isinstance(pending, dict) and (pending.get('payload') or {}).get('type') == 'action_oauth':
            payload = pending['payload']
            step_id = payload.get('step_id')
            tool_call_id = payload.get('tool_call_id')
            for entry in reversed(entries):
                event = json.loads(entry['data'])
                data = event.get('data') or {}
                delta = data.get('delta') or {}
                if (event.get('event') == 'on_run_step_delta' and data.get('id') == step_id
                        and isinstance(delta.get('auth'), str) and delta['auth']
                        and any(call.get('id') == tool_call_id for call in delta.get('tool_calls') or [])):
                    step = steps.get(step_id) or {}
                    oauth_prompts.append({'stepId': step_id,
                                          'runId': step.get('runId', generation.response_message_id),
                                          'index': step.get('index', 0),
                                          'toolCallId': tool_call_id,
                                          'toolName': payload.get('tool_name', ''),
                                          'authURL': delta['auth'],
                                          'expiresAt': delta.get('expires_at')})
                    break
        initial = content_parts
        steering = state.get("steering") or {}
        pending_steers = steering.get("queue", []) or (steering.get("leftovers", [])
                                                           if generation.status in _TERMINAL else [])
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
            **({"pendingOAuthPrompts": oauth_prompts} if oauth_prompts else {}),
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

    def message_step_events(self, owner: str, run_id: str) -> list[dict]:
        """Read only step boundaries, avoiding deserializing every streamed delta."""
        with self.database.connect() as db:
            rows = db.execute(
                "SELECT ge.data FROM generation_events ge JOIN runs r ON r.id=ge.run_id "
                "JOIN conversations c ON c.id=r.conversation_id "
                "WHERE c.owner=? AND ge.run_id=? AND json_extract(ge.data,'$.event') "
                "IN ('on_run_step','on_run_step_closed') ORDER BY ge.seq",
                (owner, run_id),
            )
            return [json.loads(row[0]) for row in rows]

    def fading_tier(self, owner: str, run_id: str, agent_id: str,
                    provider: str, model: str) -> dict | None:
        """Read the source v2 hysteresis tier, owned and scoped by Agent/model."""
        import hashlib

        from .fading import is_fading_tier

        key = hashlib.sha256((agent_id + '\x00' + provider + '\x00' + model).encode()).hexdigest()
        with self.database.connect() as db:
            row = db.execute('SELECT r.state,c.metadata FROM runs r '
                             'JOIN conversations c ON c.id=r.conversation_id '
                             'WHERE r.id=? AND c.owner=?', (run_id, owner)).fetchone()
        if row is None:
            raise KeyError('Generation not found or unauthorized')
        state = json.loads(row['state'])
        metadata = json.loads(row['metadata'])
        for source in (state, metadata):
            values = source.get('fadingTiers') if isinstance(source, dict) else None
            if isinstance(values, dict) and key in values:
                value = values[key]
                return dict(value) if is_fading_tier(value) else None
        return None

    def record_fading_tier(self, owner: str, run_id: str, agent_id: str,
                           provider: str, model: str, tier: dict) -> None:
        """Save a bounded tier in the run and conversation in one transaction."""
        import hashlib

        from .fading import is_fading_tier

        if not is_fading_tier(tier):
            raise ValueError('Expected a valid source fading tier')
        key = hashlib.sha256((agent_id + '\x00' + provider + '\x00' + model).encode()).hexdigest()
        with self.database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT r.state,c.id AS conversation_id,c.metadata '
                             'FROM runs r JOIN conversations c ON c.id=r.conversation_id '
                             "WHERE r.id=? AND c.owner=? AND r.status='running'", (run_id, owner)).fetchone()
            if row is None:
                raise KeyError('Generation not active or unauthorized')
            run_state = json.loads(row['state'])
            conversation = json.loads(row['metadata'])
            for state in (run_state, conversation):
                entries = state.get('fadingTiers')
                entries = dict(entries) if isinstance(entries, dict) else {}
                entries[key] = dict(tier)
                if len(entries) > 32:
                    for stale in list(entries)[:-32]:
                        entries.pop(stale, None)
                state['fadingTiers'] = entries
            db.execute('UPDATE runs SET state=?,updated_at=? WHERE id=?',
                       (_json(run_state), _now(), run_id))
            db.execute('UPDATE conversations SET metadata=?,updated_at=? WHERE id=? AND owner=?',
                       (_json(conversation), _now(), row['conversation_id'], owner))

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
                      *, boundary: int = 0, manual: bool = False,
                      retained_tail: list[dict] | None = None,
                      covered_tool_call_ids: list[str] | None = None,
                      covered_steer_ids: list[str] | None = None,
                      visible_text_boundary: int | None = None,
                      model_history_start: int | None = None) -> None:
        """Atomic candidate checkpoint in the *existing run state*, no deletion.

        The final assistant content and terminal run status commit together in
        finish(). A crash before that commit leaves all original messages.
        """
        if not isinstance(summary_text, str) or not summary_text.strip():
            raise ValueError('A completed summary must contain text')
        if token_count < 0:
            raise ValueError('Invalid summary token count')
        if visible_text_boundary is not None and (
                type(visible_text_boundary) is not int or visible_text_boundary < 0):
            raise ValueError('Invalid visible summary text boundary')
        if model_history_start is not None and (
                type(model_history_start) is not int or model_history_start < 0):
            raise ValueError('Invalid post-compaction model-history boundary')
        with self.database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT r.state FROM runs r JOIN conversations c ON c.id=r.conversation_id '
                             "WHERE r.id=? AND c.owner=? AND r.status=\'running\'",
                             (run_id, owner)).fetchone()
            if row is None:
                raise KeyError('Generation no longer active')
            state = json.loads(row['state'])
            previous = state.get('summaryCheckpoint') or {}
            prior_ids = previous.get('coveredToolCallIds') if isinstance(previous, dict) else None
            if covered_tool_call_ids is not None or isinstance(prior_ids, list):
                covered_tool_call_ids = sorted({
                    call_id for call_id in [*(prior_ids or []), *(covered_tool_call_ids or [])]
                    if isinstance(call_id, str) and call_id
                })
            prior_steers = previous.get('coveredSteerIds') if isinstance(previous, dict) else None
            if covered_steer_ids is not None or isinstance(prior_steers, list):
                covered_steer_ids = sorted({
                    ident for ident in [*(prior_steers or []), *(covered_steer_ids or [])]
                    if isinstance(ident, str) and ident
                })
            state['summaryCheckpoint'] = {'type': 'summary', 'content': [{'type': 'text', 'text': summary_text}],
                'boundary': {'messageIndex': boundary}, 'tokenCount': token_count,
                **({'initiatedBy': 'user'} if manual else {}),
                **({'retainedTail': retained_tail} if retained_tail is not None else {}),
                **({'coveredToolCallIds': covered_tool_call_ids} if covered_tool_call_ids is not None else {}),
                **({'coveredSteerIds': covered_steer_ids} if covered_steer_ids is not None else {}),
                **({'visibleTextBoundary': visible_text_boundary} if visible_text_boundary is not None else {})}
            if model_history_start is not None:
                # The original user prompt may no longer exist in the live
                # model history after compaction. Persist the replacement
                # boundary atomically with the summary checkpoint.
                state['modelHistoryStart'] = model_history_start
                state['postCompactionHistoryStart'] = model_history_start
            db.execute('UPDATE runs SET state=?,updated_at=? WHERE id=?', (_json(state), _now(), run_id))

    def compacted_model_history_boundary(self, owner: str, run_id: str) -> int | None:
        with self.database.connect() as db:
            row = db.execute('SELECT r.state FROM runs r JOIN conversations c '
                             'ON c.id=r.conversation_id WHERE r.id=? AND c.owner=?',
                             (run_id, owner)).fetchone()
        if row is None:
            raise KeyError('Generation not found')
        value = json.loads(row['state']).get('postCompactionHistoryStart')
        return value if type(value) is int and value >= 0 else None

    def manual_compaction(self, owner: str, run_id: str) -> bool:
        with self.database.connect() as db:
            row = db.execute('SELECT r.state FROM runs r JOIN conversations c ON c.id=r.conversation_id '
                             'WHERE r.id=? AND c.owner=?', (run_id, owner)).fetchone()
        return bool(row and json.loads(row['state']).get('manualCompaction'))

    @staticmethod
    def _text_from_events(rows) -> str:
        chunks = []
        for row in rows:
            event = json.loads(row["data"])
            if event.get("event") == "on_message_delta":
                content = event.get("data", {}).get("delta", {}).get("content", {})
                value = content.get("text") if isinstance(content, dict) else None
                if isinstance(value, str):
                    chunks.append(value)
            elif event.get("event") == "on_content_rewind":
                chunks = [event["data"]["preserveText"]]
        return "".join(chunks)

    def accumulated_text(self, owner: str, run_id: str) -> str:
        """Reassemble visible text, including crash-recovery rewinds."""
        with self.database.connect() as db:
            rows = db.execute(
                "SELECT ge.data FROM generation_events ge JOIN runs r ON r.id=ge.run_id "
                "JOIN conversations c ON c.id=r.conversation_id "
                "WHERE c.owner=? AND ge.run_id=? ORDER BY ge.seq", (owner, run_id),
            ).fetchall()
        return self._text_from_events(rows)

    def rewind_running_to_checkpoint(self, owner: str, run_id: str, preserved: str,
                                     *, actor_lease) -> bool:
        """Discard abandoned SSE text before restarting a checkpointed actor.

        The newly claimed actor lease fences this transaction against another
        Controller. Repeated reconnects must not add redundant rewind events.
        """
        if not isinstance(preserved, str):
            raise ValueError("Invalid checkpoint text prefix")
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            actor_lease.assert_current(db)
            rows = db.execute("SELECT data FROM generation_events WHERE run_id=? ORDER BY seq",
                              (run_id,)).fetchall()
            visible = self._text_from_events(rows)
            if visible == preserved:
                return False
            if not visible.startswith(preserved):
                raise ValueError("Streamed text does not match durable checkpoint prefix")
            db.execute("INSERT INTO generation_events(run_id,data) VALUES(?,?)",
                       (run_id, _json({"event": "on_content_rewind",
                                        "data": {"preserveText": preserved}})))
            return True

    def history(self, owner: str, conversation_id: str, max_messages: int | None = None,
                *, message_id: str | None = None) -> list[dict]:
        """Walk the conversation branch and replay exact saved model steps.

        A finished run stores its ordered assistant/tool/steer messages in the
        server-only runs.state; UI `tool_call.output` is *never* model history.
        Earlier LibreChat-format rows use the source-format fallback.
        """
        from .compaction import (
            build_summary_carrier_text,
            find_checkpoint_summary_part,
            get_summary_part_text,
        )
        from .message_dto import format_agent_messages

        def legacy_steps(content, display_text, metadata):
            """Backwards-compatible reconstruction for pre-canonical turns.

            Their only durable tool results were in the old UI content parts.
            New runs with modelSteps use exact canonical model history above.
            """
            if not isinstance(content, list):
                return [{'role': 'assistant', 'content': display_text}]
            tools = [part.get('tool_call') for part in content if isinstance(part, dict)
                     and part.get('type') == 'tool_call' and isinstance(part.get('tool_call'), dict)]
            pairs = [call for call in tools if isinstance(call.get('id'), str)
                     and isinstance(call.get('name'), str) and 'output' in call]
            text_chunks = [part['text'] for part in content if isinstance(part, dict)
                           and part.get('type') == 'text' and isinstance(part.get('text'), str)]
            thinking = [part.get('text') or part.get('thinking') for part in content
                        if isinstance(part, dict) and part.get('type') in {'think', 'thinking', 'reasoning'}]
            result = []
            if pairs:
                result.append({'role': 'assistant', 'content': None, 'tool_calls': [
                    {'id': call['id'], 'type': 'function', 'function': {
                        'name': call['name'], 'arguments': _json(call.get('args', {}))}}
                    for call in pairs]})
                result.extend({'role': 'tool', 'tool_call_id': call['id'],
                               'content': str(call['output'])} for call in pairs)
            nontext = [part for part in content if isinstance(part, dict)
                       and part.get('type') in {'image', 'image_url', 'file'}]
            if not pairs and nontext:
                try:
                    result.extend(format_agent_messages([{'role': 'assistant',
                        'content': content, 'metadata': metadata}]))
                except ValueError:
                    result.append({'role': 'assistant', 'content': display_text})
            elif text_chunks or not pairs:
                message = {'role': 'assistant', 'content': ''.join(text_chunks) if text_chunks else display_text}
                if thinking:
                    message['reasoning_content'] = '\n'.join(str(chunk) for chunk in thinking if chunk)
                result.append(message)
            return result

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
            groups = []
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
                    metadata = json.loads(row["metadata"])
                    content = json.loads(row["content"])
                    if row["role"] == "assistant":
                        summary = find_checkpoint_summary_part(content) if isinstance(content, list) else None
                        if summary is not None:
                            # Model context is cut at the most recent complete
                            # compaction. Keep the original UI transcript but
                            # never replay summarized tool output into the next
                            # model request.
                            prefix = {'role': 'system', 'content': build_summary_carrier_text(
                                get_summary_part_text(summary))}
                            recent = summary.get('retainedTail')
                            recent = [message for message in recent if isinstance(message, dict)
                                      and message.get('role') in {'user', 'assistant', 'tool'}] \
                                if isinstance(recent, list) else []
                            boundary = summary.get('visibleTextBoundary')
                            text = row['text'] or ''
                            if type(boundary) is int and boundary >= 0:
                                text = text[boundary:]
                            # This response may have a short unsummarized tail
                            # after the saved text boundary.
                            group = [prefix, *recent]
                            previous = db.execute(
                                "SELECT state FROM runs WHERE conversation_id=? "
                                "AND json_extract(state,'$.responseMessageId')=? "
                                "ORDER BY created_at DESC LIMIT 1",
                                (conversation_id, row['id']),
                            ).fetchone()
                            state = json.loads(previous['state']) if previous else {}
                            steps = state.get('modelSteps')
                            consumed_text = 0
                            if isinstance(steps, list):
                                # Summary coverage is cumulative across
                                # checkpoints. Only new canonical tool exchanges
                                # belong after the summary, never the already
                                # summarized or retained-tail exchanges.
                                covered = set(summary.get('coveredToolCallIds') or [])
                                retained_calls = {call.get('id') for message in recent
                                    for call in (message.get('tool_calls') or []) if isinstance(call, dict)}
                                retained_results = {message.get('tool_call_id') for message in recent
                                                    if message.get('role') == 'tool'}
                                covered_steers = set(summary.get('coveredSteerIds') or [])
                                retained_steers = {message.get('steerId') for message in recent
                                                   if message.get('role') == 'user'
                                                   and message.get('source') == 'steer'}
                                replayed_steers = set(retained_steers)
                                new_calls: set[str] = set()
                                # The saved visible text has the checkpointed
                                # prefix removed. Match canonical assistant
                                # segments against that suffix in stream order
                                # instead of appending them after later steers.
                                for message in steps:
                                    if not isinstance(message, dict):
                                        continue
                                    role = message.get('role')
                                    if role == 'user' and message.get('source') == 'steer':
                                        ident = message.get('steerId')
                                        if (isinstance(ident, str) and ident not in covered_steers
                                                and ident not in replayed_steers):
                                            group.append(message)
                                            replayed_steers.add(ident)
                                    elif role == 'assistant':
                                        candidate = message.get('content')
                                        visible = (isinstance(candidate, str) and bool(candidate)
                                                   and text.startswith(candidate, consumed_text))
                                        if isinstance(message.get('tool_calls'), list):
                                            calls = [call for call in message['tool_calls']
                                                     if isinstance(call, dict) and isinstance(call.get('id'), str)
                                                     and call['id'] not in covered and call['id'] not in retained_calls]
                                            if calls:
                                                new_calls.update(call['id'] for call in calls)
                                                group.append({**message,
                                                              'content': candidate if visible else None,
                                                              'tool_calls': calls})
                                                if visible:
                                                    consumed_text += len(candidate)
                                        elif visible:
                                            group.append(message)
                                            consumed_text += len(candidate)
                                    elif role == 'tool' and isinstance(message.get('tool_call_id'), str):
                                        ident = message['tool_call_id']
                                        if (ident not in covered and ident not in retained_results
                                                and ident in (new_calls | retained_calls)):
                                            group.append(message)
                                            retained_results.add(ident)
                            if consumed_text < len(text):
                                group.append({'role': 'assistant', 'content': text[consumed_text:]})
                            groups.append(group)
                            break
                        previous = db.execute(
                            "SELECT state FROM runs WHERE conversation_id=? AND json_extract(state,'$.responseMessageId')=? "
                            "ORDER BY created_at DESC LIMIT 1", (conversation_id, row["id"]),
                        ).fetchone()
                        persisted = json.loads(previous["state"]) if previous else {}
                        if persisted.get('modelSteps') or (
                                'modelSteps' in persisted and not row['text'] and not content):
                            # A canonical run never reads preview-truncated UI
                            # outputs as tool evidence. Empty cancelled runs
                            # remain empty; old runs and empty tool-less stubs
                            # still reconstruct from their display text.
                            groups.append(persisted['modelSteps'])
                        else:
                            legacy = {"role": "assistant", "content": content if isinstance(content, list) else row["text"],
                                      "metadata": metadata}
                            try:
                                if (isinstance(content, list) and
                                        any(isinstance(part, dict) and part.get('type') == 'tool_call'
                                            for part in content)):
                                    formatted_steps = legacy_steps(content, row['text'], metadata)
                                else:
                                    formatted_steps = format_agent_messages([legacy])
                                # Source legacy DTO only carries the plain steer
                                # string. On model replay retain quoted context
                                # from the durable steer part without modifying
                                # the upstream display-formatting contract.
                                if isinstance(content, list):
                                    from .steering import merged_text

                                    steers = iter(part for part in content if isinstance(part, dict)
                                                  and part.get('type') == 'steer')
                                    for step in formatted_steps:
                                        if step.get('source') == 'steer':
                                            part = next(steers, None)
                                            if part is not None:
                                                step['content'] = merged_text(part)
                                                step['files'] = part.get('files', [])
                                                step['quotes'] = part.get('quotes', [])
                                                step['steerId'] = part.get('steerId')
                                # Legacy React artifact edits store a text block
                                # while history API originally exposed its text.
                                # Keep the scalar-text contract when no media or
                                # tool anchors exist, without losing rich blocks.
                                for step in formatted_steps:
                                    parts = step.get("content")
                                    if (step.get("role") == "assistant" and isinstance(parts, list)
                                            and all(isinstance(p, dict) and p.get("type") == "text" for p in parts)):
                                        step["content"] = "".join(p.get("text", "") for p in parts)
                                if isinstance(content, list):
                                    reasoning = [part.get('text') or part.get('thinking') for part in content
                                                 if isinstance(part, dict) and
                                                 part.get('type') in {'think', 'thinking', 'reasoning'}]
                                    if reasoning:
                                        last_assistant = next((step for step in reversed(formatted_steps)
                                                               if step.get('role') == 'assistant'), None)
                                        if last_assistant is not None:
                                            last_assistant['reasoning_content'] = '\n'.join(
                                                str(chunk) for chunk in reasoning if chunk)
                                groups.append(formatted_steps)
                            except ValueError:
                                groups.append([{"role": "assistant", "content": row["text"]}])
                    else:
                        value = row["text"]
                        if isinstance(content, list):
                            # Legacy UI structured content takes precedence over
                            # the display string; retain non-text media intact.
                            relevant = [part for part in content if isinstance(part, dict)
                                        and part.get("type") in {"text", "image", "image_url", "file"}]
                            if relevant:
                                value = relevant
                                if all(part["type"] == "text" for part in relevant):
                                    value = "".join(part.get("text", "") for part in relevant)
                        files = metadata.get("files") or []
                        if files:
                            descriptors = []
                            for item in files:
                                attachment = db.execute("SELECT id,name,path FROM attachments WHERE id=? AND owner=?",
                                                        (item["file_id"], owner)).fetchone()
                                descriptors.append({"file_id": item["file_id"], "machine": "local",
                                    **({"filename": attachment["name"], "path": attachment["path"]}
                                       if attachment else {"unavailable": True})})
                            note = "Controller attachments (use authorized LSM file tools):\n" + _json(descriptors)
                            if isinstance(value, list):
                                value = [*value, {"type": "text", "text": note}]
                            else:
                                value += "\n\n" + note
                        groups.append([{"role": "user", "content": value}])
                if max_messages is not None and len(groups) >= max(1, max_messages):
                    break
                message_id = row["parent_id"]
        return [step for group in reversed(groups) for step in group]

    def model_history_boundary(self, owner: str, run_id: str, *, initial: int | None = None) -> int:
        """Retain the original prompt boundary through Ask User/approval checkpoints.

        A resumed snapshot contains this run's prior assistant/tool/steer steps.
        Its current length cannot be used to select newly generated steps.
        """
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT r.state FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.id=? AND c.owner=?", (run_id, owner),
            ).fetchone()
            if row is None:
                raise KeyError("Generation not found")
            state = json.loads(row["state"])
            if "modelHistoryStart" not in state:
                if initial is None or initial < 0:
                    raise ValueError("Missing initial model-history boundary")
                state["modelHistoryStart"] = initial
                db.execute("UPDATE runs SET state=? WHERE id=?", (_json(state), run_id))
            return int(state["modelHistoryStart"])

    def checkpoint_model_steps(self, owner: str, run_id: str) -> list[dict] | None:
        """Recover canonical, complete steps from a durable owned checkpoint.

        This is used only for interrupted/error/aborted runs. The checkpoint is
        server-owned and scoped to this generation, not the latest conversation
        step or the short run-step preview emitted to the browser.
        """
        from .checkpoints import SQLiteCheckpointSaver
        from .message_dto import completed_model_steps

        with self.database.connect() as db:
            row = db.execute(
                "SELECT r.conversation_id,r.state FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.id=? AND c.owner=?", (run_id, owner),
            ).fetchone()
            if row is None:
                return None
            boundary = json.loads(row["state"]).get("modelHistoryStart")
            if type(boundary) is not int or boundary < 0:
                return None
            cid = row["conversation_id"]
        saver = SQLiteCheckpointSaver(self.database, owner)
        checkpoint = saver.get_tuple(saver.config(cid, run_id, event_actor=True))
        if checkpoint is None:
            return None
        values = checkpoint["checkpoint"].get("channel_values") or {}
        messages = values.get("messages")
        if not isinstance(messages, list) or boundary > len(messages):
            return None
        return completed_model_steps(messages, boundary)

    def finish(self, owner: str, run_id: str, *, status: str, text: str = "",
               error: str | None = None, expired_action_id: str | None = None,
               actor_lease=None, _connection: Any | None = None,
               model_steps: list[dict] | None = None) -> bool:
        if status not in _TERMINAL:
            raise ValueError("Only terminal statuses can finish a generation")
        with (contextlib.nullcontext(_connection) if _connection is not None
              else self.database.connect()) as db:
            if _connection is None:
                db.execute("BEGIN IMMEDIATE")
            if actor_lease is not None:
                actor_lease.assert_current(db)
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
            run_state = json.loads(row['state'])
            staged = run_state.get('summaryCheckpoint')
            from .compaction import is_usable_summary_part, mark_compaction_outcome

            # Preserve source React tool-call parts in history and final SSE,
            # rather than erasing them when the assistant text is committed.
            tool_positions = {}
            content = []
            attachments = {}
            for event in db.execute("SELECT data FROM generation_events WHERE run_id=? ORDER BY seq", (run_id,)):
                value = json.loads(event["data"])
                kind = value.get("event")
                data = value.get("data") or {}
                if kind == "attachment":
                    attachment = data
                    if (isinstance(attachment, dict) and isinstance(attachment.get("file_id"), str)
                            and attachment.get("messageId") == generation.response_message_id):
                        attachments[attachment["file_id"]] = attachment
                if kind == "on_run_step_completed":
                    result = data.get("result", {})
                    if isinstance(result.get("tool_call"), dict):
                        part = {"type": "tool_call", "tool_call": {
                            **result["tool_call"], "stepId": result["id"],
                        }}
                        if result['id'] in tool_positions:
                            content[tool_positions[result['id']]] = part
                        else:
                            tool_positions[result['id']] = len(content)
                            content.append(part)
                elif kind == "on_message_delta":
                    delta = (data.get("delta") or {}).get("content") or {}
                    if delta.get("type") == "text" and isinstance(delta.get("text"), str) and delta["text"]:
                        if content and content[-1].get("type") == "text":
                            content[-1]["text"] += delta["text"]
                        else:
                            content.append({"type": "text", "text": delta["text"], "phase": "final_answer"})
                elif kind == 'on_reasoning_delta':
                    delta = (data.get('delta') or {}).get('content') or {}
                    if delta.get('type') == 'think' and isinstance(delta.get('think'), str) and delta['think']:
                        if content and content[-1].get('type') == 'think':
                            content[-1]['think'] += delta['think']
                        else:
                            content.append({'type': 'think', 'think': delta['think']})
                elif kind == "on_steer_applied" and isinstance(data.get("part"), dict):
                    content.append(data["part"])
                elif kind == 'on_content_rewind':
                    _rewind_uncheckpointed_text(content, data.get('preserveText', ''))
                    # Compacting abandoned text shifts surviving tool cards;
                    # rebuild their positions before replaying completions or
                    # applying final RunStep closure metadata.
                    tool_positions = {
                        part['tool_call']['stepId']: index
                        for index, part in enumerate(content)
                        if part.get('type') == 'tool_call'
                        and isinstance(part.get('tool_call'), dict)
                        and isinstance(part['tool_call'].get('stepId'), str)
                    }
            if text and not any(isinstance(part, dict) and part.get('type') == 'text'
                                for part in content):
                content.append({"type": "text", "text": text, "phase": "final_answer"})
            # The source ON_RUN_STEP_CLOSED event is the authoritative status
            # and duration even after reconnect; never infer a stop from the
            # absence of a live streaming task or the event's unstable index.
            for event in db.execute("SELECT data FROM generation_events WHERE run_id=? ORDER BY seq",
                                    (run_id,)):
                value = json.loads(event["data"])
                if value.get("event") != "on_run_step_closed":
                    continue
                closed = value.get("data") or {}
                part = (content[tool_positions[closed["id"]]] if closed.get("id") in tool_positions else None)
                if not part or closed.get("status") not in {"completed", "failed", "cancelled"}:
                    continue
                tool = part["tool_call"]
                tool["runStepStatus"] = closed["status"]
                opened_at, closed_at = closed.get("created_at"), closed.get("closed_at")
                if (type(closed_at) in (int, float) and closed_at > 0 and
                    (type(opened_at) not in (int, float) or opened_at <= closed_at)):
                    tool["runStepClosedAt"] = closed_at
                    if type(opened_at) in (int, float):
                        tool["runStepDurationMs"] = closed_at - opened_at
            # LibreChat agents/client.js emits ContentTypes.ERROR as a content
            # part. A top-level final.error alone is ignored by finalHandler.
            # Persist the same part so the error survives history reload too.
            if status in {"error", "interrupted"}:
                content.append({"type": "error", "error": error or "Generation failed"})
            attachments: list[dict] = []
            attachment_positions: dict[tuple, int] = {}
            for event_row in db.execute("SELECT data FROM generation_events WHERE run_id=? ORDER BY seq", (run_id,)):
                event = json.loads(event_row["data"])
                if event.get("event") != "attachment" or not isinstance(event.get("data"), dict):
                    continue
                attachment = event["data"]
                # Native file previews can emit pending then ready/failed for a
                # single file. Keep the final owned representation, not copies.
                if attachment.get("file_id"):
                    key = ("file", attachment["file_id"], attachment.get("toolCallId"))
                elif attachment.get("type") == "ui_resources" and isinstance(attachment.get("ui_resources"), list):
                    key = ("ui_resources", attachment.get("toolCallId"), tuple(
                        resource.get("resourceId") for resource in attachment["ui_resources"]
                        if isinstance(resource, dict)
                    ))
                else:
                    key = None
                if key is not None and key in attachment_positions:
                    attachments[attachment_positions[key]] = attachment
                else:
                    if key is not None:
                        attachment_positions[key] = len(attachments)
                    attachments.append(attachment)
            if is_usable_summary_part(staged):
                content.insert(0, dict(staged))
            if run_state.get('manualCompaction'):
                mark_compaction_outcome(content, aborted=False)
            from .tool_attachments import response_attachments, visible_response_attachments
            verified = response_attachments(db, owner, [generation.response_message_id])[
                generation.response_message_id]
            attachments = visible_response_attachments(verified, attachments)
            response_metadata = {"sender": "Assistant", "isCreatedByUser": False,
                                 "unfinished": status != "complete",
                                 **({"attachments": attachments} if attachments else {})}
            if isinstance(run_state.get('contextUsage'), dict):
                response_metadata['metadata'] = {'contextUsage': run_state['contextUsage']}
            response_message = {
                **({'metadata': response_metadata['metadata']} if 'metadata' in response_metadata else {}),
                **({"attachments": attachments} if attachments else {}),
                "messageId": generation.response_message_id,
                "conversationId": generation.conversation_id,
                "parentMessageId": generation.user_message_id,
                "sender": "Assistant", "isCreatedByUser": False,
                "text": text,
                "content": content,
                **({"attachments": attachments} if attachments else {}),
                "unfinished": status != "complete",
            }
            if content or attachments or model_steps:
                db.execute(
                    "INSERT INTO messages(id,conversation_id,parent_id,role,text,content,metadata,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (generation.response_message_id, generation.conversation_id, generation.user_message_id,
                     "assistant", text, _json(response_message["content"]),
                     _json(response_metadata), now, now),
                )
            run_state = json.loads(row["state"])
            if model_steps is not None:
                run_state['modelSteps'] = model_steps
            from .steering import SteeringStore

            pending_steers = SteeringStore.settle_leftovers(run_state)
            if status != "interrupted":
                run_state.pop("resumeClaim", None)
                run_state.pop("approvedToolBatch", None)
            db.execute("UPDATE runs SET status=?,state=?,updated_at=? WHERE id=?",
                       (status, _json(run_state), now, run_id))
            unread = db.execute(
                "UPDATE conversations SET updated_at=?,unread_marker="
                "CASE WHEN unread_marker LIKE 'manual:%' THEN ? ELSE ? END "
                "WHERE id=? RETURNING unread_marker",
                (now, "manual:" + run_id, "run:" + run_id, generation.conversation_id),
            ).fetchone()["unread_marker"]
            final = {
                "final": True,
                "unreadMarker": unread,
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
                "SELECT r.id,r.conversation_id,c.owner FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.status='running'",
            ).fetchall()
        recovered = 0
        for row in rows:
            if row["id"] in active:
                continue
            with self.database.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                current = db.execute("SELECT state,status FROM runs WHERE id=?", (row["id"],)).fetchone()
                if current is not None and current["status"] == "running":
                    state = json.loads(current["state"])
                    resume = state.get("oauthResume")
                    # 'claimed': login completed but remote HTTP was never sent.
                    # 'completed': the HTTP result has already been durably saved
                    # by the checkpoint saver, so replay uses that result.
                    if (isinstance(resume, dict) and resume.get("stage") in {"claimed", "completed"}
                            and resume.get("lone_call") is True
                            and isinstance(resume.get("pendingAction"), dict)):
                        pending = resume["pendingAction"]
                        if resume["stage"] == "completed":
                            from .checkpoints import SQLiteCheckpointSaver

                            saver = SQLiteCheckpointSaver(self.database, row["owner"])
                            checkpoint = saver.get_tuple(saver.config(
                                row["conversation_id"], row["id"],
                                checkpoint_ns=pending.get("namespace", ""), event_actor=True,
                            ))
                            snapshot = (checkpoint or {}).get("checkpoint", {}).get("channel_values", {})
                            calls = snapshot.get("pending_calls")
                            # A completed HTTP request is replayable only when
                            # the graph has its tool result in durable writes
                            # or has already advanced past that tool node.
                            has_result = db.execute(
                                "SELECT 1 FROM generation_events WHERE run_id=? AND "
                                "json_extract(data,'$.event')='on_run_step_completed' AND "
                                "json_extract(data,'$.data.result.tool_call.id')=? LIMIT 1",
                                (row["id"], resume["tool_call_id"]),
                            ).fetchone()
                            replay_safe = checkpoint is not None and has_result is not None and isinstance(calls, list)
                            if replay_safe and calls == []:
                                pending = {**pending, "payload": {**pending["payload"],
                                           "checkpoint_completed": True}}
                        else:
                            replay_safe = True
                        if replay_safe:
                            state["pendingAction"] = pending
                            state.pop("oauthResume")
                            db.execute("UPDATE runs SET state=?,status='requires_action',updated_at=? WHERE id=?",
                                       (_json(state), _now(), row["id"]))
                            recovered += 1
                            continue
            if self.finish(row["owner"], row["id"], status="interrupted",
                           model_steps=self.checkpoint_model_steps(row["owner"], row["id"])):
                recovered += 1
        return recovered
