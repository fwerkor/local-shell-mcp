from __future__ import annotations

import contextlib
import copy
import json
import secrets
import threading
import time
import uuid
from collections import deque
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .settings import get_settings
from .state_store import FileStateStore, get_state_store

PLAN_EXECUTION_LEASE_S = 15 * 60
PLAN_MAX_CONTINUATIONS = 10
PLAN_CONTINUATION_PENDING_TTL_S = 5 * 60
PLAN_CONTINUATION_FAILURE_BACKOFF_S = 5 * 60
PLAN_CONTINUATION_CLAIM_ID_LIMIT = 128
PLAN_MAX_STEPS = 100
PLAN_OBJECTIVE_LIMIT = 4_000
PLAN_STEP_ID_LIMIT = 128
PLAN_STEP_TEXT_LIMIT = 2_000
PLAN_NOTE_LIMIT = 2_000
PLAN_ACTIVITY_DETAIL_STEP_LIMIT = 12
PLAN_STEP_STATUSES = frozenset({"pending", "active", "completed", "skipped"})
# A normal tool call contributes a started and terminal event that the Live Workspace
# coalesces into one row, so 200 raw events yields roughly 100 visible tool rows.
SESSION_ACTIVITY_LIMIT = 200
SESSION_IN_FLIGHT_LEASE_S = 2 * 60 * 60
# Soft retention target: unfinished/resumable Sessions are never evicted to meet it.
SESSION_HISTORY_LIMIT_PER_PRINCIPAL = 100
SESSION_REPORT_LIST_LIMIT = 50
SESSION_TEXT_LIMIT = 20_000


class SessionToolLeaseStartPersistenceError(RuntimeError):
    """A tool-start write may have reached durable storage despite reporting failure."""

    def __init__(self, message: str, lease: dict[str, Any]) -> None:
        super().__init__(message)
        self.lease = lease


@dataclass(slots=True)
class PlanStep:
    id: str
    text: str
    status: str = "pending"
    note: str | None = None

    def public_state(self) -> dict[str, Any]:
        data: dict[str, Any] = {"id": self.id, "text": self.text, "status": self.status}
        if self.note:
            data["note"] = self.note
        return data


@dataclass(slots=True)
class PlanState:
    plan_id: str
    objective: str
    steps: list[PlanStep]
    created_at: float
    updated_at: float
    status: str = "active"
    revision: int = 1
    note: str | None = None
    continuation_count: int = 0
    continuation_pending: bool = False
    continuation_pending_since: float | None = None
    continuation_claim_id: str | None = None
    continuation_reserved: bool = False
    last_continuation_at: float | None = None
    continuation_retry_after: float | None = None
    last_agent_activity: float = 0.0

    def has_unfinished_steps(self) -> bool:
        return any(step.status in {"pending", "active"} for step in self.steps)

    def public_state(
        self, now: float | None = None, *, in_flight_calls: int = 0
    ) -> dict[str, Any]:
        current = time.time() if now is None else now
        due_at = self.last_agent_activity + PLAN_EXECUTION_LEASE_S
        retry_due = self.continuation_retry_after is None or current >= self.continuation_retry_after
        return {
            "plan_id": self.plan_id,
            "objective": self.objective,
            "status": self.status,
            "steps": [step.public_state() for step in self.steps],
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "note": self.note,
            "continuation_count": self.continuation_count,
            "continuation_pending": self.continuation_pending,
            "continuation_claim_id": self.continuation_claim_id,
            "continuation_reserved": self.continuation_reserved,
            "last_continuation_at": self.last_continuation_at,
            "continuation_retry_after": self.continuation_retry_after,
            "last_agent_activity": self.last_agent_activity,
            "in_flight_calls": in_flight_calls,
            "execution_lease_s": PLAN_EXECUTION_LEASE_S,
            "continuation_due_at": due_at,
            "continuation_due": (
                self.status == "active"
                and not self.continuation_pending
                and in_flight_calls == 0
                and self.continuation_count < PLAN_MAX_CONTINUATIONS
                and current >= due_at
                and retry_due
            ),
            "max_continuations": PLAN_MAX_CONTINUATIONS,
            "auto_continue_exhausted": self.continuation_count >= PLAN_MAX_CONTINUATIONS,
        }


@dataclass(slots=True)
class ProgressState:
    summary: str | None = None
    findings: list[str] = field(default_factory=list)
    next: str | None = None
    blockers: list[str] = field(default_factory=list)
    updated_at: float | None = None

    def public_state(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "findings": list(self.findings),
            "next": self.next,
            "blockers": list(self.blockers),
            "updated_at": self.updated_at,
        }




@dataclass(slots=True)
class LogicalSession:
    session_id: str
    subject: str
    created_at: float
    updated_at: float
    status: str = "active"
    label: str | None = None
    objective: str | None = None
    progress: ProgressState = field(default_factory=ProgressState)
    plan: PlanState | None = None
    in_flight_calls: dict[str, dict[str, Any]] = field(default_factory=dict)
    activity_seq: int = 0
    activity: deque[dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=SESSION_ACTIVITY_LIMIT)
    )

    def public_state(
        self, *, recent_activity: int = SESSION_ACTIVITY_LIMIT, in_flight_calls: int = 0
    ) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "label": self.label,
            "objective": self.objective,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "progress": self.progress.public_state(),
            "plan": (
                self.plan.public_state(in_flight_calls=in_flight_calls)
                if self.plan
                else None
            ),
            "recent_activity": (
                list(self.activity)[-min(recent_activity, SESSION_ACTIVITY_LIMIT) :]
                if recent_activity > 0
                else []
            ),
        }


class SessionRuntimeManager:
    """Durable logical task sessions addressed only by session_id."""

    def __init__(self, state_dir: Path | None = None) -> None:
        self._lock = threading.RLock()
        self._state_dir_override = state_dir
        self._loaded_storage: tuple[str, ...] | None = None
        self._sessions: dict[str, LogicalSession] = {}

    def _state_store(self):  # noqa: ANN202
        if self._state_dir_override is not None:
            return FileStateStore(Path(self._state_dir_override))
        return get_state_store()

    def _storage_signature(self) -> tuple[str, ...]:
        if self._state_dir_override is not None:
            return ("override", str(Path(self._state_dir_override).resolve()))
        settings = get_settings()
        return (
            settings.state_backend,
            settings.state_backend_url or "",
            settings.state_backend_prefix,
            str(settings.state_dir),
        )

    def _ensure_loaded_locked(self) -> None:
        signature = self._storage_signature()
        if self._loaded_storage == signature:
            return
        store = self._state_store()
        loaded_sessions: dict[str, LogicalSession] = {}
        for key in store.list_keys("sessions/"):
            if not key.endswith(".json"):
                continue
            try:
                raw = store.read_bytes(key)
                if raw is None:
                    continue
                payload = json.loads(raw.decode("utf-8"))
                session = self._session_from_payload(payload)
            except (
                OSError,
                UnicodeDecodeError,
                ValueError,
                TypeError,
                json.JSONDecodeError,
            ):
                continue
            loaded_sessions[session.session_id] = session
        self._sessions = loaded_sessions
        self._loaded_storage = signature

    def _uses_shared_state_backend(self) -> bool:
        return self._state_dir_override is None and get_settings().state_backend == "redis"

    def _load_session_from_store_locked(self, session_id: str) -> LogicalSession | None:
        raw = self._state_store().read_bytes(f"sessions/{session_id}.json")
        if raw is None:
            return None
        try:
            payload = json.loads(raw.decode("utf-8"))
            return self._session_from_payload(payload)
        except (
            OSError,
            UnicodeDecodeError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
        ):
            return None

    def _refresh_session_locked(self, session_id: str) -> None:
        if not self._uses_shared_state_backend():
            return
        refreshed = self._load_session_from_store_locked(session_id)
        if refreshed is None:
            self._sessions.pop(session_id, None)
        else:
            self._sessions[session_id] = refreshed

    def _refresh_all_sessions_locked(self) -> None:
        if not self._uses_shared_state_backend():
            return
        refreshed: dict[str, LogicalSession] = {}
        store = self._state_store()
        for key in store.list_keys("sessions/"):
            if not key.endswith(".json"):
                continue
            session_id = key.removeprefix("sessions/").removesuffix(".json")
            session = self._load_session_from_store_locked(session_id)
            if session is not None:
                refreshed[session.session_id] = session
        self._sessions = refreshed

    @contextlib.contextmanager
    def _shared_session_locks_locked(self, session_ids: list[str]) -> Iterator[None]:
        normalized = sorted({str(item) for item in session_ids if item})
        if not normalized or not self._uses_shared_state_backend():
            yield
            return
        store = self._state_store()
        with contextlib.ExitStack() as stack:
            for session_id in normalized:
                stack.enter_context(store.lock(f"sessions/{session_id}"))
            yield

    @staticmethod
    def _bounded_text(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        return normalized[:SESSION_TEXT_LIMIT]

    @classmethod
    def _bounded_list(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        normalized = [
            item
            for item in (cls._bounded_text(str(value)) for value in values)
            if item is not None
        ]
        return normalized[:SESSION_REPORT_LIST_LIMIT]

    @staticmethod
    def _plan_to_payload(plan: PlanState | None) -> dict[str, Any] | None:
        if plan is None:
            return None
        return {
            "plan_id": plan.plan_id,
            "objective": plan.objective,
            "steps": [asdict(step) for step in plan.steps],
            "created_at": plan.created_at,
            "updated_at": plan.updated_at,
            "status": plan.status,
            "revision": plan.revision,
            "note": plan.note,
            "continuation_count": plan.continuation_count,
            "continuation_pending": plan.continuation_pending,
            "continuation_pending_since": plan.continuation_pending_since,
            "continuation_claim_id": plan.continuation_claim_id,
            "continuation_reserved": plan.continuation_reserved,
            "last_continuation_at": plan.last_continuation_at,
            "continuation_retry_after": plan.continuation_retry_after,
            "last_agent_activity": plan.last_agent_activity,
        }

    @staticmethod
    def _bounded_plan_text(value: Any, limit: int) -> str:
        return str(value or "").strip()[:limit]

    @classmethod
    def _plan_from_payload(cls, payload: Any) -> PlanState | None:
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise ValueError("invalid plan state")
        steps_payload = payload.get("steps")
        if not isinstance(steps_payload, list):
            raise ValueError("invalid plan steps")
        return PlanState(
            plan_id=str(payload["plan_id"]),
            objective=cls._bounded_plan_text(payload["objective"], PLAN_OBJECTIVE_LIMIT),
            steps=[
                PlanStep(
                    id=cls._bounded_plan_text(step["id"], PLAN_STEP_ID_LIMIT),
                    text=cls._bounded_plan_text(step["text"], PLAN_STEP_TEXT_LIMIT),
                    status=str(step.get("status") or "pending"),
                    note=(
                        None
                        if step.get("note") is None
                        else cls._bounded_plan_text(step["note"], PLAN_NOTE_LIMIT) or None
                    ),
                )
                for step in steps_payload
                if isinstance(step, dict)
            ],
            created_at=float(payload["created_at"]),
            updated_at=float(payload["updated_at"]),
            status=str(payload.get("status") or "active"),
            revision=int(payload.get("revision") or 1),
            note=(
                None
                if payload.get("note") is None
                else cls._bounded_plan_text(payload["note"], PLAN_NOTE_LIMIT) or None
            ),
            continuation_count=int(payload.get("continuation_count") or 0),
            continuation_pending=bool(payload.get("continuation_pending")),
            continuation_pending_since=(
                None
                if payload.get("continuation_pending_since") is None
                else float(payload["continuation_pending_since"])
            ),
            continuation_claim_id=(
                None
                if payload.get("continuation_claim_id") is None
                else str(payload["continuation_claim_id"])
            ),
            continuation_reserved=bool(payload.get("continuation_reserved")),
            last_continuation_at=(
                None
                if payload.get("last_continuation_at") is None
                else float(payload["last_continuation_at"])
            ),
            continuation_retry_after=(
                None
                if payload.get("continuation_retry_after") is None
                else float(payload["continuation_retry_after"])
            ),
            last_agent_activity=float(payload.get("last_agent_activity") or 0.0),
        )

    @classmethod
    def _session_from_payload(cls, payload: Any) -> LogicalSession:
        if not isinstance(payload, dict):
            raise ValueError("session metadata must be an object")
        progress_payload = payload.get("progress") or {}
        if not isinstance(progress_payload, dict):
            raise ValueError("invalid progress state")
        activity_payload = payload.get("activity") or []
        if not isinstance(activity_payload, list):
            raise ValueError("invalid activity state")
        in_flight_payload = payload.get("in_flight_calls") or {}
        if not isinstance(in_flight_payload, dict):
            raise ValueError("invalid in-flight tool state")
        # v1 contained additional per-agent metadata. Ignore it while retaining the
        # durable task state keyed by session_id.
        return LogicalSession(
            session_id=str(payload["session_id"]),
            subject=str(payload["subject"]),
            created_at=float(payload["created_at"]),
            updated_at=float(payload["updated_at"]),
            status=str(payload.get("status") or "active"),
            label=cls._bounded_text(payload.get("label")),
            objective=cls._bounded_text(payload.get("objective")),
            progress=ProgressState(
                summary=cls._bounded_text(progress_payload.get("summary")),
                findings=cls._bounded_list(progress_payload.get("findings")) or [],
                next=cls._bounded_text(progress_payload.get("next")),
                blockers=cls._bounded_list(progress_payload.get("blockers")) or [],
                updated_at=(
                    None
                    if progress_payload.get("updated_at") is None
                    else float(progress_payload["updated_at"])
                ),
            ),
            plan=cls._plan_from_payload(payload.get("plan")),
            in_flight_calls={
                str(call_id): {
                    "started_at": float(value.get("started_at") or 0.0),
                    "heartbeat_at": float(
                        value.get("heartbeat_at") or value.get("started_at") or 0.0
                    ),
                }
                for call_id, value in in_flight_payload.items()
                if isinstance(value, dict)
            },
            activity_seq=int(payload.get("activity_seq") or 0),
            activity=deque(
                [item for item in activity_payload if isinstance(item, dict)],
                maxlen=SESSION_ACTIVITY_LIMIT,
            ),
        )

    @classmethod
    def _session_to_payload(cls, session: LogicalSession) -> dict[str, Any]:
        return {
            "version": 2,
            "session_id": session.session_id,
            "subject": session.subject,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "status": session.status,
            "label": session.label,
            "objective": session.objective,
            "progress": asdict(session.progress),
            "plan": cls._plan_to_payload(session.plan),
            "in_flight_calls": session.in_flight_calls,
            "activity_seq": session.activity_seq,
            "activity": list(session.activity),
        }

    def _save_locked(self, session: LogicalSession) -> None:
        data = json.dumps(
            self._session_to_payload(session),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        self._state_store().write_bytes(f"sessions/{session.session_id}.json", data)

    def _restore_snapshot_locked(
        self, snapshot: LogicalSession, exc: Exception, *, context: str
    ) -> None:
        self._sessions[snapshot.session_id] = snapshot
        try:
            self._save_locked(snapshot)
        except Exception as rollback_exc:  # noqa: BLE001 - preserve original error.
            exc.add_note(
                f"{context} rollback warning: {type(rollback_exc).__name__}: {rollback_exc}"
            )

    @staticmethod
    def _new_session_id() -> str:
        return f"s_{secrets.token_hex(12)}"

    def _require_session_locked(
        self, session_id: str, subject: str | None = None
    ) -> LogicalSession:
        self._ensure_loaded_locked()
        normalized_id = str(session_id)
        self._refresh_session_locked(normalized_id)
        session = self._sessions.get(normalized_id)
        if session is None:
            raise ValueError(f"Unknown logical session: {session_id}")
        if subject is not None and session.subject != subject:
            raise PermissionError("Logical session belongs to a different principal")
        return session

    def _append_activity_locked(
        self,
        session: LogicalSession,
        event_type: str,
        *,
        actor: str,
        data: dict[str, Any] | None = None,
        touch_plan: bool = False,
    ) -> dict[str, Any]:
        now = time.time()
        session.activity_seq += 1
        event = {
            "seq": session.activity_seq,
            "ts": now,
            "type": event_type,
            "actor": actor,
            "data": data or {},
        }
        session.activity.append(event)
        session.updated_at = now
        if touch_plan and session.plan is not None and session.plan.status == "active":
            session.plan.last_agent_activity = now
            session.plan.updated_at = max(session.plan.updated_at, now)
        self._save_locked(session)
        return event

    @staticmethod
    def _prune_in_flight_locked(session: LogicalSession, now: float | None = None) -> None:
        current = time.time() if now is None else now
        expired = [
            call_id
            for call_id, lease in session.in_flight_calls.items()
            if current
            - float(lease.get("heartbeat_at") or lease.get("started_at") or 0.0)
            >= SESSION_IN_FLIGHT_LEASE_S
        ]
        for call_id in expired:
            session.in_flight_calls.pop(call_id, None)

    def _in_flight_count_locked(self, session_id: str) -> int:
        session = self._sessions.get(session_id)
        if session is None:
            return 0
        self._prune_in_flight_locked(session)
        return len(session.in_flight_calls)

    def _public_state_locked(
        self, session: LogicalSession, *, recent_activity: int = SESSION_ACTIVITY_LIMIT
    ) -> dict[str, Any]:
        return session.public_state(
            recent_activity=recent_activity,
            in_flight_calls=self._in_flight_count_locked(session.session_id),
        )

    def _prune_session_history_locked(self, subject: str) -> None:
        """Trim old terminal Sessions without deleting resumable work."""
        retained = [item for item in self._sessions.values() if item.subject == subject]
        excess = len(retained) - SESSION_HISTORY_LIMIT_PER_PRINCIPAL
        if excess <= 0:
            return

        candidates = []
        for item in retained:
            if item.status not in {"completed", "cancelled"}:
                continue
            if self._in_flight_count_locked(item.session_id):
                continue
            candidates.append(item)
        candidates.sort(key=lambda item: (item.updated_at, item.created_at))

        for candidate in candidates:
            if excess <= 0:
                break
            session_id = candidate.session_id
            if self._uses_shared_state_backend():
                with self._shared_session_locks_locked([session_id]):
                    self._refresh_session_locked(session_id)
                    current = self._sessions.get(session_id)
                    if current is None or current.subject != subject:
                        continue
                    if current.status not in {"completed", "cancelled"}:
                        continue
                    if self._in_flight_count_locked(session_id):
                        continue
                    self._state_store().delete(f"sessions/{session_id}.json")
                    self._sessions.pop(session_id, None)
            else:
                self._state_store().delete(f"sessions/{session_id}.json")
                self._sessions.pop(session_id, None)
            excess -= 1

    def manage(
        self,
        subject: str | None,
        *,
        action: str,
        session_id: str | None = None,
        label: str | None = None,
        objective: str | None = None,
        summary: str | None = None,
        findings: list[str] | None = None,
        next: str | None = None,
        blockers: list[str] | None = None,
        actor: str = "agent",
        _state_lock_held: bool = False,
    ) -> dict[str, Any]:
        normalized_action = str(action).strip().lower()
        allowed = {"start", "resume", "get", "report", "finish", "cancel", "delete"}
        if normalized_action not in allowed:
            raise ValueError(
                "action must be one of: start, resume, get, report, finish, cancel, delete"
            )

        with self._lock:
            self._ensure_loaded_locked()
            if normalized_action == "start":
                if not _state_lock_held and self._uses_shared_state_backend():
                    with self._state_store().lock("sessions/history"):
                        return self.manage(
                            subject,
                            action=action,
                            session_id=session_id,
                            label=label,
                            objective=objective,
                            summary=summary,
                            findings=findings,
                            next=next,
                            blockers=blockers,
                            actor=actor,
                            _state_lock_held=True,
                        )
                if self._uses_shared_state_backend():
                    self._refresh_all_sessions_locked()
                now = time.time()
                normalized_subject = str(subject or "").strip()
                if not normalized_subject:
                    raise ValueError("subject is required for action=start")
                logical = LogicalSession(
                    session_id=self._new_session_id(),
                    subject=normalized_subject,
                    created_at=now,
                    updated_at=now,
                    label=self._bounded_text(label),
                    objective=self._bounded_text(objective),
                )
                self._sessions[logical.session_id] = logical
                try:
                    self._append_activity_locked(
                        logical,
                        "session.started",
                        actor=actor,
                    )
                except Exception as exc:
                    self._sessions.pop(logical.session_id, None)
                    with contextlib.suppress(Exception):
                        self._state_store().delete(f"sessions/{logical.session_id}.json")
                    raise exc
                with contextlib.suppress(Exception):
                    self._prune_session_history_locked(normalized_subject)
                return self._public_state_locked(logical)

            if not session_id:
                raise ValueError(f"session_id is required for action={normalized_action}")

            if (
                not _state_lock_held
                and normalized_action not in {"get"}
                and self._uses_shared_state_backend()
            ):
                with self._shared_session_locks_locked([session_id]):
                    return self.manage(
                        subject,
                        action=action,
                        session_id=session_id,
                        label=label,
                        objective=objective,
                        summary=summary,
                        findings=findings,
                        next=next,
                        blockers=blockers,
                        actor=actor,
                        _state_lock_held=True,
                    )

            logical = self._require_session_locked(session_id, subject)

            if normalized_action == "get":
                return self._public_state_locked(logical)

            if normalized_action == "delete":
                if self._in_flight_count_locked(logical.session_id):
                    raise ValueError("Cannot delete a logical session while tool calls are in flight")
                if logical.status == "active":
                    raise ValueError(
                        "Cannot delete an active logical session; finish or cancel it first"
                    )
                self._state_store().delete(f"sessions/{logical.session_id}.json")
                self._sessions.pop(logical.session_id, None)
                return {"session_id": logical.session_id, "deleted": True}

            if normalized_action == "resume":
                if logical.status not in {"active", "completed"}:
                    raise ValueError(f"Cannot resume a {logical.status} session")
                snapshot = copy.deepcopy(logical)
                try:
                    logical.status = "active"
                    self._append_activity_locked(
                        logical,
                        "session.resumed",
                        actor=actor,
                        touch_plan=True,
                    )
                except Exception as exc:
                    self._restore_snapshot_locked(snapshot, exc, context="Session resume")
                    raise
                return self._public_state_locked(logical)

            if logical.status != "active":
                raise ValueError(f"Logical session is {logical.status}")

            if normalized_action == "report":
                snapshot = copy.deepcopy(logical)
                try:
                    changed = False
                    if summary is not None:
                        logical.progress.summary = self._bounded_text(summary)
                        changed = True
                    if findings is not None:
                        logical.progress.findings = self._bounded_list(findings) or []
                        changed = True
                    if next is not None:
                        logical.progress.next = self._bounded_text(next)
                        changed = True
                    if blockers is not None:
                        logical.progress.blockers = self._bounded_list(blockers) or []
                        changed = True
                    if objective is not None:
                        logical.objective = self._bounded_text(objective)
                        changed = True
                    if label is not None:
                        logical.label = self._bounded_text(label)
                        changed = True
                    if not changed:
                        raise ValueError(
                            "action=report requires summary, findings, next, blockers, objective, or label"
                        )
                    logical.progress.updated_at = time.time()
                    self._append_activity_locked(
                        logical,
                        "session.reported",
                        actor=actor,
                        data={
                            "summary": logical.progress.summary,
                            "next": logical.progress.next,
                            "blocker_count": len(logical.progress.blockers),
                        },
                        touch_plan=True,
                    )
                except Exception as exc:
                    if logical != snapshot:
                        self._restore_snapshot_locked(snapshot, exc, context="Session report")
                    raise
                return self._public_state_locked(logical)

            if normalized_action in {"finish", "cancel"} and self._in_flight_count_locked(
                logical.session_id
            ):
                raise ValueError(
                    f"Cannot {normalized_action} a logical session while tool calls are in flight"
                )

            if normalized_action in {"finish", "cancel"}:
                if (
                    normalized_action == "finish"
                    and logical.plan is not None
                    and logical.plan.status in {"active", "blocked"}
                ):
                    raise ValueError(
                        "Cannot finish a session while its plan is active or blocked; finish or cancel the plan first"
                    )
                snapshot = copy.deepcopy(logical)
                try:
                    now = time.time()
                    logical.status = "completed" if normalized_action == "finish" else "cancelled"
                    if (
                        normalized_action == "cancel"
                        and logical.plan is not None
                        and logical.plan.status not in {"completed", "cancelled"}
                    ):
                        logical.plan.status = "cancelled"
                        logical.plan.updated_at = now
                        logical.plan.continuation_pending = False
                        logical.plan.continuation_pending_since = None
                        logical.plan.continuation_claim_id = None
                        logical.plan.continuation_reserved = False
                    self._append_activity_locked(
                        logical,
                        "session.completed" if normalized_action == "finish" else "session.cancelled",
                        actor=actor,
                    )
                except Exception as exc:
                    self._restore_snapshot_locked(snapshot, exc, context="Session terminal")
                    raise
                return self._public_state_locked(logical)

            raise AssertionError("unreachable")

    def get(self, session_id: str, *, subject: str | None = None) -> dict[str, Any]:
        with self._lock:
            logical = self._require_session_locked(session_id, subject)
            return self._public_state_locked(logical)

    def owner_subject(self, session_id: str, *, subject: str | None = None) -> str:
        """Return the canonical Session owner after applying the requested access check."""
        with self._lock:
            return self._require_session_locked(session_id, subject).subject

    def list_sessions(self, *, subject: str | None) -> list[dict[str, Any]]:
        """Return Logical Session summaries, optionally scoped to one principal."""
        normalized_subject = str(subject).strip() if subject is not None else None
        if subject is not None and not normalized_subject:
            raise ValueError("subject is required")
        with self._lock:
            self._ensure_loaded_locked()
            if self._uses_shared_state_backend():
                self._refresh_all_sessions_locked()
            logical_sessions = [
                session
                for session in self._sessions.values()
                if normalized_subject is None or session.subject == normalized_subject
            ]
            logical_sessions.sort(
                key=lambda session: (session.updated_at, session.created_at), reverse=True
            )
            return [
                self._public_state_locked(session, recent_activity=0)
                for session in logical_sessions
            ]

    def plan_state(
        self, session_id: str | None, *, subject: str | None = None
    ) -> dict[str, Any] | None:
        if not session_id:
            return None
        with self._lock:
            logical = self._require_session_locked(session_id, subject)
            return (
                logical.plan.public_state(
                    in_flight_calls=self._in_flight_count_locked(logical.session_id)
                )
                if logical.plan
                else None
            )

    def begin_tool_call(
        self,
        session_id: str | None,
        call_id: str,
        *,
        subject: str | None = None,
        data: dict[str, Any] | None = None,
        _state_lock_held: bool = False,
    ) -> dict[str, Any] | None:
        """Persist a tool call under an explicitly supplied Logical Session."""
        if not session_id:
            return None
        with self._lock:
            self._ensure_loaded_locked()
            if not _state_lock_held and self._uses_shared_state_backend():
                with self._shared_session_locks_locked([session_id]):
                    return self.begin_tool_call(
                        session_id,
                        call_id,
                        subject=subject,
                        data=data,
                        _state_lock_held=True,
                    )
            logical = self._require_session_locked(session_id, subject)
            if logical.status != "active":
                raise RuntimeError(
                    f"Logical session is {logical.status}; start or resume another session"
                )
            before_start = copy.deepcopy(logical)
            now = time.time()
            logical.in_flight_calls[call_id] = {
                "started_at": now,
                "heartbeat_at": now,
            }
            try:
                self._append_activity_locked(
                    logical,
                    "tool.started",
                    actor="agent",
                    data={"call_id": call_id, **(data or {})},
                    touch_plan=True,
                )
            except Exception as exc:
                ambiguous_lease = {
                    "session_id": logical.session_id,
                    "call_id": call_id,
                }
                self._sessions[logical.session_id] = before_start
                raise SessionToolLeaseStartPersistenceError(
                    "Failed to persist the tool-call state; refusing to execute the tool untracked",
                    ambiguous_lease,
                ) from exc
            return {
                "session_id": logical.session_id,
                "call_id": call_id,
                "persistence_error": None,
            }

    def finish_tool_call(
        self,
        lease: dict[str, Any] | None,
        event_type: str,
        *,
        data: dict[str, Any] | None = None,
        _state_lock_held: bool = False,
    ) -> str | None:
        if lease is None:
            return None
        with self._lock:
            self._ensure_loaded_locked()
            session_id = str(lease.get("session_id") or "")
            call_id = str(lease.get("call_id") or "")
            if not _state_lock_held and self._uses_shared_state_backend():
                with self._shared_session_locks_locked([session_id]):
                    return self.finish_tool_call(
                        lease,
                        event_type,
                        data=data,
                        _state_lock_held=True,
                    )
            self._refresh_session_locked(session_id)
            logical = self._sessions.get(session_id)
            if logical is None:
                return None
            logical.in_flight_calls.pop(call_id, None)
            lease_persistence_error = None
            try:
                self._save_locked(logical)
            except Exception as exc:  # noqa: BLE001 - completion must not mask tool results.
                lease_persistence_error = f"{type(exc).__name__}: {exc}"
            try:
                self._append_activity_locked(
                    logical,
                    event_type,
                    actor="agent",
                    data={"call_id": call_id, **(data or {})},
                    touch_plan=logical.status == "active",
                )
            except Exception as exc:  # noqa: BLE001 - never mask the tool result.
                activity_error = f"{type(exc).__name__}: {exc}"
                return "; ".join(
                    item for item in (lease_persistence_error, activity_error) if item
                )
            return lease_persistence_error

    def retry_tool_call_cleanup(
        self,
        lease: dict[str, Any] | None,
        *,
        _state_lock_held: bool = False,
    ) -> bool:
        if lease is None:
            return True
        session_id = str(lease.get("session_id") or "")
        call_id = str(lease.get("call_id") or "")
        if not session_id or not call_id:
            return True
        with self._lock:
            self._ensure_loaded_locked()
            if not _state_lock_held and self._uses_shared_state_backend():
                with self._shared_session_locks_locked([session_id]):
                    return self.retry_tool_call_cleanup(lease, _state_lock_held=True)
            durable = self._load_session_from_store_locked(session_id)
            if durable is not None:
                self._sessions[session_id] = durable
            logical = self._sessions.get(session_id)
            if logical is None or call_id not in logical.in_flight_calls:
                return True
            snapshot = copy.deepcopy(logical)
            logical.in_flight_calls.pop(call_id, None)
            try:
                self._save_locked(logical)
            except Exception:
                self._sessions[session_id] = snapshot
                raise
            return True

    def renew_tool_call(
        self,
        lease: dict[str, Any] | None,
        *,
        _state_lock_held: bool = False,
    ) -> bool:
        if lease is None:
            return False
        session_id = str(lease.get("session_id") or "")
        call_id = str(lease.get("call_id") or "")
        if not session_id or not call_id:
            return False
        with self._lock:
            self._ensure_loaded_locked()
            if not _state_lock_held and self._uses_shared_state_backend():
                with self._shared_session_locks_locked([session_id]):
                    return self.renew_tool_call(lease, _state_lock_held=True)
            self._refresh_session_locked(session_id)
            logical = self._sessions.get(session_id)
            if logical is None:
                return False
            current = logical.in_flight_calls.get(call_id)
            if current is None:
                return False
            previous = current.get("heartbeat_at")
            current["heartbeat_at"] = time.time()
            try:
                self._save_locked(logical)
            except Exception:
                if previous is None:
                    current.pop("heartbeat_at", None)
                else:
                    current["heartbeat_at"] = previous
                raise
            return True

    @classmethod
    def _normalize_plan_steps(cls, steps: list[dict[str, Any]]) -> list[PlanStep]:
        if not steps:
            raise ValueError("A plan requires at least one step")
        if len(steps) > PLAN_MAX_STEPS:
            raise ValueError(f"A plan may contain at most {PLAN_MAX_STEPS} steps")
        normalized: list[PlanStep] = []
        seen: set[str] = set()
        for index, raw in enumerate(steps):
            step_id = cls._bounded_plan_text(
                raw.get("id") or f"step-{index + 1}", PLAN_STEP_ID_LIMIT
            )
            text = cls._bounded_plan_text(
                raw.get("text") or raw.get("content") or raw.get("title") or "",
                PLAN_STEP_TEXT_LIMIT,
            )
            status = str(raw.get("status") or "pending").strip().lower()
            note = cls._bounded_plan_text(raw.get("note"), PLAN_NOTE_LIMIT) or None
            if not step_id or step_id in seen:
                raise ValueError(f"Plan step ids must be unique; invalid id at index {index}")
            if not text:
                raise ValueError(f"Plan step {step_id!r} has no text")
            if status not in PLAN_STEP_STATUSES:
                raise ValueError(f"Unsupported plan step status: {status}")
            seen.add(step_id)
            normalized.append(PlanStep(step_id, text, status, note))
        active = [step for step in normalized if step.status == "active"]
        if len(active) > 1:
            raise ValueError("A plan may have at most one active step")
        if not active:
            next_step = next((step for step in normalized if step.status == "pending"), None)
            if next_step is not None:
                next_step.status = "active"
        return normalized

    @staticmethod
    def _promote_next_step(plan: PlanState) -> None:
        if any(step.status == "active" for step in plan.steps):
            return
        next_step = next((step for step in plan.steps if step.status == "pending"), None)
        if next_step is not None:
            next_step.status = "active"

    @staticmethod
    def _plan_activity_snapshot(plan: PlanState) -> dict[str, Any]:
        completed = sum(
            1 for step in plan.steps if step.status in {"completed", "skipped"}
        )
        active = next((step for step in plan.steps if step.status == "active"), None)
        data: dict[str, Any] = {
            "plan_id": plan.plan_id,
            "revision": plan.revision,
            "objective": plan.objective,
            "status": plan.status,
            "completed_steps": completed,
            "total_steps": len(plan.steps),
        }
        if active is not None:
            data["active_step"] = active.public_state()
        if plan.note:
            data["note"] = plan.note
        return data

    @staticmethod
    def _plan_activity_steps(plan: PlanState) -> dict[str, Any]:
        visible = plan.steps[:PLAN_ACTIVITY_DETAIL_STEP_LIMIT]
        return {
            "steps": [step.public_state() for step in visible],
            "steps_total": len(plan.steps),
            "steps_truncated": len(plan.steps) > len(visible),
        }

    def manage_plan(
        self,
        session_id: str,
        *,
        action: str,
        objective: str | None = None,
        steps: list[dict[str, Any]] | None = None,
        step_id: str | None = None,
        status: str | None = None,
        text: str | None = None,
        note: str | None = None,
        actor: str = "agent",
        subject: str | None = None,
        _state_lock_held: bool = False,
    ) -> dict[str, Any]:
        normalized_action = action.strip().lower()
        with self._lock:
            self._ensure_loaded_locked()
            if (
                not _state_lock_held
                and normalized_action != "get"
                and self._uses_shared_state_backend()
            ):
                with self._shared_session_locks_locked([session_id]):
                    return self.manage_plan(
                        session_id,
                        action=action,
                        objective=objective,
                        steps=steps,
                        step_id=step_id,
                        status=status,
                        text=text,
                        note=note,
                        actor=actor,
                        subject=subject,
                        _state_lock_held=True,
                    )
            logical = self._require_session_locked(session_id, subject)
            if normalized_action != "get" and logical.status != "active":
                raise ValueError(f"Logical session is {logical.status}")
            return self._manage_plan_transaction_locked(
                logical,
                action=action,
                objective=objective,
                steps=steps,
                step_id=step_id,
                status=status,
                text=text,
                note=note,
                actor=actor,
            )

    def _manage_plan_transaction_locked(
        self,
        logical: LogicalSession,
        *,
        action: str,
        objective: str | None = None,
        steps: list[dict[str, Any]] | None = None,
        step_id: str | None = None,
        status: str | None = None,
        text: str | None = None,
        note: str | None = None,
        actor: str,
    ) -> dict[str, Any]:
        if action.strip().lower() == "get":
            return self._manage_plan_locked(
                logical,
                action=action,
                objective=objective,
                steps=steps,
                step_id=step_id,
                status=status,
                text=text,
                note=note,
                actor=actor,
            )
        snapshot = copy.deepcopy(logical)
        try:
            return self._manage_plan_locked(
                logical,
                action=action,
                objective=objective,
                steps=steps,
                step_id=step_id,
                status=status,
                text=text,
                note=note,
                actor=actor,
            )
        except Exception as exc:
            if logical != snapshot:
                self._restore_snapshot_locked(snapshot, exc, context="Plan mutation")
            raise

    def _manage_plan_locked(
        self,
        logical: LogicalSession,
        *,
        action: str,
        objective: str | None = None,
        steps: list[dict[str, Any]] | None = None,
        step_id: str | None = None,
        status: str | None = None,
        text: str | None = None,
        note: str | None = None,
        actor: str,
    ) -> dict[str, Any]:
        normalized_action = action.strip().lower()
        plan = logical.plan
        if normalized_action == "get":
            return {
                "session_id": logical.session_id,
                "goal_mode": bool(plan and plan.status in {"active", "blocked"}),
                "plan": (
                    plan.public_state(
                        in_flight_calls=self._in_flight_count_locked(logical.session_id)
                    )
                    if plan
                    else None
                ),
            }
        now = time.time()
        event_type = ""
        event_data: dict[str, Any] = {}
        if normalized_action == "start":
            if plan is not None and plan.status in {"active", "blocked"}:
                raise ValueError("A plan is already active; finish or cancel it before starting another")
            objective_text = self._bounded_plan_text(objective, PLAN_OBJECTIVE_LIMIT)
            if not objective_text:
                raise ValueError("objective is required for action=start")
            plan = PlanState(
                plan_id=uuid.uuid4().hex,
                objective=objective_text,
                steps=self._normalize_plan_steps(list(steps or [])),
                created_at=now,
                updated_at=now,
                last_agent_activity=now,
            )
            logical.plan = plan
            if logical.objective is None:
                logical.objective = objective_text[:SESSION_TEXT_LIMIT]
            event_type = "plan.started"
            event_data = {
                **self._plan_activity_snapshot(plan),
                **self._plan_activity_steps(plan),
            }
        else:
            if plan is None:
                raise ValueError("No plan exists in this logical session")
            if normalized_action == "update":
                if plan.status not in {"active", "blocked"}:
                    raise ValueError(f"Cannot update a {plan.status} plan")
                changed = False
                changes: dict[str, Any] = {}
                if objective is not None:
                    objective_text = self._bounded_plan_text(objective, PLAN_OBJECTIVE_LIMIT)
                    if not objective_text:
                        raise ValueError("objective cannot be empty")
                    plan.objective = objective_text
                    changed = True
                    changes["objective"] = plan.objective
                if steps is not None:
                    plan.steps = self._normalize_plan_steps(list(steps))
                    changed = True
                    changes.update(self._plan_activity_steps(plan))
                if step_id is not None:
                    normalized_step_id = self._bounded_plan_text(step_id, PLAN_STEP_ID_LIMIT)
                    target = next(
                        (step for step in plan.steps if step.id == normalized_step_id), None
                    )
                    if target is None:
                        raise ValueError(f"Unknown plan step: {normalized_step_id}")
                    updated_fields: list[str] = []
                    if status is not None:
                        normalized_status = status.strip().lower()
                        if normalized_status not in PLAN_STEP_STATUSES:
                            raise ValueError(f"Unsupported plan step status: {normalized_status}")
                        if normalized_status == "active":
                            for item in plan.steps:
                                if item is not target and item.status == "active":
                                    item.status = "pending"
                        target.status = normalized_status
                        changed = True
                        updated_fields.append("status")
                    if text is not None:
                        normalized_text = self._bounded_plan_text(text, PLAN_STEP_TEXT_LIMIT)
                        if not normalized_text:
                            raise ValueError("step text cannot be empty")
                        target.text = normalized_text
                        changed = True
                        updated_fields.append("text")
                    if note is not None:
                        target.note = self._bounded_plan_text(note, PLAN_NOTE_LIMIT) or None
                        changed = True
                        updated_fields.append("note")
                    if updated_fields:
                        changes["step"] = target.public_state()
                        changes["updated_fields"] = updated_fields
                elif status is not None or text is not None:
                    raise ValueError("step_id is required when updating step status or text")
                if note is not None and step_id is None:
                    plan.note = self._bounded_plan_text(note, PLAN_NOTE_LIMIT) or None
                    changed = True
                    changes["note"] = plan.note
                if not changed:
                    raise ValueError("action=update requires objective, steps, step_id, or note")
                self._promote_next_step(plan)
                plan.revision += 1
                plan.updated_at = now
                plan.last_agent_activity = now
                plan.continuation_pending = False
                plan.continuation_pending_since = None
                plan.continuation_claim_id = None
                plan.continuation_reserved = False
                plan.continuation_retry_after = None
                event_type = "plan.updated"
                event_data = self._plan_activity_snapshot(plan)
                event_data["changes"] = changes
            elif normalized_action == "block":
                if plan.status != "active":
                    raise ValueError(f"Cannot block a {plan.status} plan")
                reason = self._bounded_plan_text(note, PLAN_NOTE_LIMIT)
                if not reason:
                    raise ValueError("note is required for action=block")
                plan.status = "blocked"
                plan.note = reason
                plan.revision += 1
                plan.updated_at = now
                plan.continuation_pending = False
                plan.continuation_pending_since = None
                plan.continuation_claim_id = None
                plan.continuation_reserved = False
                event_type = "plan.blocked"
                event_data = {**self._plan_activity_snapshot(plan), "reason": reason}
            elif normalized_action == "resume":
                if plan.status != "blocked":
                    raise ValueError("Only a blocked plan can be resumed")
                plan.status = "active"
                plan.note = None
                plan.revision += 1
                plan.updated_at = now
                if actor == "agent":
                    plan.last_agent_activity = now
                plan.continuation_retry_after = None
                event_type = "plan.resumed"
                event_data = self._plan_activity_snapshot(plan)
            elif normalized_action == "finish":
                if plan.status not in {"active", "blocked"}:
                    raise ValueError(f"Cannot finish a {plan.status} plan")
                unfinished = [step.id for step in plan.steps if step.status in {"pending", "active"}]
                if unfinished:
                    raise ValueError(
                        "Cannot finish plan while unfinished steps remain: " + ", ".join(unfinished)
                    )
                plan.status = "completed"
                plan.note = self._bounded_plan_text(note, PLAN_NOTE_LIMIT) or plan.note
                plan.revision += 1
                plan.updated_at = now
                plan.continuation_pending = False
                plan.continuation_pending_since = None
                plan.continuation_claim_id = None
                plan.continuation_reserved = False
                plan.continuation_retry_after = None
                event_type = "plan.completed"
                event_data = {
                    **self._plan_activity_snapshot(plan),
                    **self._plan_activity_steps(plan),
                }
            elif normalized_action == "cancel":
                if plan.status in {"completed", "cancelled"}:
                    raise ValueError(f"Plan is already {plan.status}")
                plan.status = "cancelled"
                plan.note = self._bounded_plan_text(note, PLAN_NOTE_LIMIT) or plan.note
                plan.revision += 1
                plan.updated_at = now
                plan.continuation_pending = False
                plan.continuation_pending_since = None
                plan.continuation_claim_id = None
                plan.continuation_reserved = False
                plan.continuation_retry_after = None
                event_type = "plan.cancelled"
                event_data = {
                    **self._plan_activity_snapshot(plan),
                    **self._plan_activity_steps(plan),
                }
            else:
                raise ValueError(
                    "action must be one of: start, get, update, block, resume, finish, cancel"
                )
        self._append_activity_locked(
            logical,
            event_type,
            actor=actor,
            data=event_data,
            touch_plan=actor == "agent" and normalized_action not in {"block", "finish", "cancel"},
        )
        return {
            "session_id": logical.session_id,
            "goal_mode": plan.status in {"active", "blocked"},
            "plan": plan.public_state(
                now, in_flight_calls=self._in_flight_count_locked(logical.session_id)
            ),
        }

    def claim_plan_continuation(
        self,
        session_id: str,
        *,
        claim_id: str | None = None,
        subject: str | None = None,
        _state_lock_held: bool = False,
    ) -> dict[str, Any] | None:
        with self._lock:
            if not _state_lock_held and self._uses_shared_state_backend():
                with self._shared_session_locks_locked([session_id]):
                    return self.claim_plan_continuation(
                        session_id,
                        claim_id=claim_id,
                        subject=subject,
                        _state_lock_held=True,
                    )
            logical = self._require_session_locked(session_id, subject)
            plan = logical.plan
            if plan is None or plan.status != "active":
                return None
            now = time.time()
            requested_claim_id = str(claim_id or "").strip() or None
            if requested_claim_id is not None and len(requested_claim_id) > PLAN_CONTINUATION_CLAIM_ID_LIMIT:
                raise ValueError(
                    f"continuation claim_id must be <= {PLAN_CONTINUATION_CLAIM_ID_LIMIT} characters"
                )

            def claim_state() -> dict[str, Any]:
                return {
                    "session_id": logical.session_id,
                    "plan": plan.public_state(
                        now, in_flight_calls=self._in_flight_count_locked(logical.session_id)
                    ),
                    "recent_events": list(logical.activity)[-20:],
                    "continuation_count": (
                        plan.continuation_count
                        if plan.continuation_reserved
                        else plan.continuation_count + 1
                    ),
                    "claim_id": plan.continuation_claim_id,
                }

            if self._in_flight_count_locked(logical.session_id):
                return None
            if plan.continuation_pending:
                pending_since = plan.continuation_pending_since or now
                if now - pending_since < PLAN_CONTINUATION_PENDING_TTL_S:
                    if (
                        requested_claim_id
                        and plan.continuation_claim_id == requested_claim_id
                    ):
                        return claim_state()
                    return None
                snapshot = copy.deepcopy(logical)
                try:
                    plan.continuation_pending = False
                    plan.continuation_pending_since = None
                    plan.continuation_claim_id = None
                    plan.continuation_reserved = False
                    plan.updated_at = now
                    self._save_locked(logical)
                except Exception as exc:
                    self._restore_snapshot_locked(
                        snapshot, exc, context="Expired continuation cleanup"
                    )
                    raise
            if plan.continuation_count >= PLAN_MAX_CONTINUATIONS:
                return None
            if plan.continuation_retry_after is not None and now < plan.continuation_retry_after:
                return None
            if now < plan.last_agent_activity + PLAN_EXECUTION_LEASE_S:
                return None
            snapshot = copy.deepcopy(logical)
            try:
                plan.continuation_pending = True
                plan.continuation_pending_since = now
                plan.continuation_claim_id = requested_claim_id or f"c_{secrets.token_hex(8)}"
                plan.continuation_reserved = False
                plan.updated_at = now
                self._append_activity_locked(
                    logical,
                    "plan.continuation_requested",
                    actor="system",
                    data={"plan_id": plan.plan_id, "attempt": plan.continuation_count + 1},
                )
            except Exception as exc:
                self._restore_snapshot_locked(snapshot, exc, context="Continuation claim")
                raise
            return claim_state()

    def validate_plan_continuation(
        self,
        session_id: str,
        claim_id: str,
        *,
        subject: str | None = None,
        _state_lock_held: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            if not _state_lock_held and self._uses_shared_state_backend():
                with self._shared_session_locks_locked([session_id]):
                    return self.validate_plan_continuation(
                        session_id,
                        claim_id,
                        subject=subject,
                        _state_lock_held=True,
                    )
            logical = self._require_session_locked(session_id, subject)
            plan = logical.plan
            now = time.time()
            in_flight_calls = self._in_flight_count_locked(logical.session_id)
            pending_fresh = bool(
                plan is not None
                and plan.continuation_pending_since is not None
                and now - plan.continuation_pending_since < PLAN_CONTINUATION_PENDING_TTL_S
            )
            valid = bool(
                plan is not None
                and plan.status == "active"
                and plan.continuation_pending
                and plan.continuation_claim_id == claim_id
                and pending_fresh
                and in_flight_calls == 0
                and now >= plan.last_agent_activity + PLAN_EXECUTION_LEASE_S
            )
            if valid and plan is not None and not plan.continuation_reserved:
                snapshot = copy.deepcopy(logical)
                try:
                    plan.continuation_count += 1
                    plan.continuation_reserved = True
                    plan.last_continuation_at = now
                    plan.updated_at = now
                    self._save_locked(logical)
                except Exception as exc:
                    self._restore_snapshot_locked(
                        snapshot, exc, context="Continuation reservation"
                    )
                    raise
            if (
                plan is not None
                and plan.continuation_pending
                and plan.continuation_claim_id == claim_id
                and not valid
            ):
                snapshot = copy.deepcopy(logical)
                try:
                    plan.continuation_pending = False
                    plan.continuation_pending_since = None
                    plan.continuation_claim_id = None
                    plan.continuation_reserved = False
                    plan.updated_at = now
                    self._save_locked(logical)
                except Exception as exc:
                    self._restore_snapshot_locked(
                        snapshot, exc, context="Continuation invalidation"
                    )
                    raise
            return {
                "valid": valid,
                "session_id": logical.session_id,
                "plan": (
                    plan.public_state(now, in_flight_calls=in_flight_calls)
                    if plan is not None
                    else None
                ),
            }

    def report_plan_continuation(
        self,
        session_id: str,
        *,
        accepted: bool,
        error: str | None = None,
        claim_id: str | None = None,
        subject: str | None = None,
        _state_lock_held: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            if not _state_lock_held and self._uses_shared_state_backend():
                with self._shared_session_locks_locked([session_id]):
                    return self.report_plan_continuation(
                        session_id,
                        accepted=accepted,
                        error=error,
                        claim_id=claim_id,
                        subject=subject,
                        _state_lock_held=True,
                    )
            logical = self._require_session_locked(session_id, subject)
            plan = logical.plan
            if plan is None:
                raise ValueError("No plan exists in this logical session")
            if not plan.continuation_pending:
                raise ValueError("No plan continuation is pending")
            if claim_id is not None and plan.continuation_claim_id != claim_id:
                raise ValueError("Plan continuation claim is stale")
            if not plan.continuation_reserved and accepted:
                raise ValueError("Plan continuation was not reserved for dispatch")
            now = time.time()
            snapshot = copy.deepcopy(logical)
            try:
                plan.continuation_pending = False
                plan.continuation_pending_since = None
                plan.continuation_claim_id = None
                plan.continuation_reserved = False
                if accepted:
                    plan.last_agent_activity = now
                    plan.continuation_retry_after = None
                else:
                    plan.continuation_retry_after = now + PLAN_CONTINUATION_FAILURE_BACKOFF_S
                plan.updated_at = now
                self._append_activity_locked(
                    logical,
                    "plan.continuation_sent" if accepted else "plan.continuation_failed",
                    actor="system",
                    data={
                        "plan_id": plan.plan_id,
                        "count": plan.continuation_count,
                        **({"error": error[:500]} if error else {}),
                    },
                )
            except Exception as exc:
                self._restore_snapshot_locked(snapshot, exc, context="Continuation report")
                raise
            return plan.public_state(
                now, in_flight_calls=self._in_flight_count_locked(logical.session_id)
            )

    def abandon_plan_continuation(
        self,
        session_id: str,
        claim_id: str | None,
        *,
        subject: str | None = None,
        _state_lock_held: bool = False,
    ) -> bool:
        """Clear one matching continuation claim when its Workspace binding is lost.

        This is an internal recovery path used before the host is allowed to act
        on a claim. If validation already reserved an attempt, the conservative
        attempt count is retained; only the pending/reserved claim is released.
        """
        normalized_claim = str(claim_id or "").strip()
        if not normalized_claim:
            return False
        with self._lock:
            if not _state_lock_held and self._uses_shared_state_backend():
                with self._shared_session_locks_locked([session_id]):
                    return self.abandon_plan_continuation(
                        session_id,
                        normalized_claim,
                        subject=subject,
                        _state_lock_held=True,
                    )
            logical = self._require_session_locked(session_id, subject)
            plan = logical.plan
            if (
                plan is None
                or not plan.continuation_pending
                or plan.continuation_claim_id != normalized_claim
            ):
                return False
            snapshot = copy.deepcopy(logical)
            now = time.time()
            try:
                plan.continuation_pending = False
                plan.continuation_pending_since = None
                plan.continuation_claim_id = None
                plan.continuation_reserved = False
                plan.updated_at = now
                self._save_locked(logical)
            except Exception as exc:
                self._restore_snapshot_locked(
                    snapshot, exc, context="Continuation abandonment"
                )
                raise
            return True


_MANAGER = SessionRuntimeManager()


def get_session_runtime_manager() -> SessionRuntimeManager:
    return _MANAGER
