"""Durable, principal-scoped Hosted Chat data backed by LSM's state store."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import secrets
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .settings import get_settings
from .state_store import get_state_store


def _encryption_key() -> bytes:
    """Keep the KEK outside the chat state backend and require stable secrets on clustered installs."""
    configured = os.environ.get("LOCAL_SHELL_MCP_HOSTED_CHAT_ENCRYPTION_KEY")
    if configured:
        key = base64.urlsafe_b64decode(configured)
        if len(key) != 32:
            raise ValueError("Hosted Chat encryption key must decode to 32 bytes")
        return key
    settings = get_settings()
    if settings.state_backend != "file":
        raise RuntimeError(
            "Configure LOCAL_SHELL_MCP_HOSTED_CHAT_ENCRYPTION_KEY for non-file state storage"
        )
    path = Path(settings.state_dir) / "hosted-chat-encryption-key"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_path = tempfile.mkstemp(prefix=".hosted-chat-key-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            generated = secrets.token_bytes(32)
            handle.write(generated)
            handle.flush()
            os.fsync(handle.fileno())
        # Hard-link publication is atomic and create-if-absent: no reader can
        # observe a partially written key, and competing writers never replace it.
        try:
            os.link(temp_path, path)
        except FileExistsError:
            key = path.read_bytes()
        else:
            key = generated
    finally:
        Path(temp_path).unlink(missing_ok=True)
    if len(key) != 32:
        raise RuntimeError("Invalid Hosted Chat encryption key; cannot decrypt existing profiles")
    return key


def _owner_key(subject: str) -> str:
    if not subject:
        raise PermissionError("A principal is required for Hosted Chat storage")
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()


def _encrypt(key: str, aad: str) -> str:
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(_encryption_key()).encrypt(nonce, key.encode("utf-8"), aad.encode("utf-8"))
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def _decrypt(ciphertext: str, aad: str) -> str:
    value = base64.urlsafe_b64decode(ciphertext)
    return (
        AESGCM(_encryption_key())
        .decrypt(value[:12], value[12:], aad.encode("utf-8"))
        .decode("utf-8")
    )


class HostedChatStore:
    """Operations serialize by owner; store locks also serialize Redis writers."""

    def __init__(self, *, prefix: str = "hosted-chat") -> None:
        self.prefix = prefix
        self._guard = threading.RLock()

    @contextmanager
    def _record_lock(self, key: str):
        # Redis provides a distributed lock. File state must also serialize
        # separate server processes sharing the same state directory.
        with self._guard, get_state_store().lock(key):
            if get_settings().state_backend != "file":
                yield
                return
            lock_dir = Path(get_settings().state_dir) / ".hosted-chat-locks"
            lock_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            lock_path = lock_dir / (hashlib.sha256(key.encode()).hexdigest() + ".lock")
            with lock_path.open("a+b") as handle:
                if os.name == "nt":  # pragma: no cover - exercised in Windows matrix
                    import msvcrt

                    handle.seek(0, os.SEEK_END)
                    if handle.tell() == 0:
                        handle.write(b"\x00")
                        handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                    try:
                        yield
                    finally:
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _key(self, subject: str, kind: str, uid: str) -> str:
        return f"{self.prefix}/{_owner_key(subject)}/{kind}/{uid}.json"

    def _read(self, key: str) -> dict[str, Any]:
        value = get_state_store().read_bytes(key)
        if value is None:
            raise ValueError("Unknown Hosted Chat record")
        return json.loads(value)

    def _save(self, key: str, data: dict) -> None:
        get_state_store().write_bytes(
            key, json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )

    def _records(self, subject: str, kind: str) -> list[dict]:
        prefix = f"{self.prefix}/{_owner_key(subject)}/{kind}/"
        store = get_state_store()
        result = []
        for key in store.list_keys(prefix):
            if key.endswith(".json"):
                value = store.read_bytes(key)
                if value is not None:
                    result.append(json.loads(value))
        return sorted(result, key=lambda r: r["updated_at"], reverse=True)

    def profiles(self, subject: str) -> list[dict]:
        return [self._public_profile(p) for p in self._records(subject, "profiles")]

    @staticmethod
    def _public_profile(record: dict) -> dict:
        return {k: v for k, v in record.items() if k != "encrypted_key"}

    def profile(self, subject: str, profile_id: str, *, with_secret: bool = False) -> dict:
        p = self._read(self._key(subject, "profiles", _identifier(profile_id)))
        if with_secret:
            return {
                **self._public_profile(p),
                "api_key": _decrypt(p["encrypted_key"], f"{subject}:{profile_id}"),
            }
        return self._public_profile(p)

    def put_profile(self, subject: str, values: dict) -> dict:
        from .hosted_chat import validate_api_key, validate_endpoint
        from .hosted_chat_context import DEFAULT_CONTEXT_WINDOW, context_window

        profile_id = _identifier(str(values.get("id") or f"p_{uuid.uuid4().hex}"))
        key = self._key(subject, "profiles", profile_id)
        now = time.time()
        with self._record_lock(key):
            try:
                previous = self._read(key)
            except ValueError:
                previous = None
            name = str(values.get("name") or "").strip()
            model = str(values.get("model") or "").strip()
            endpoint = validate_endpoint(str(values.get("endpoint") or ""))
            if not 0 < len(name) <= 120 or not 0 < len(model) <= 256:
                raise ValueError("A profile name and model are required")
            secret = str(values.get("api_key") or "")
            if secret or not previous:
                validate_api_key(secret)
                encrypted = _encrypt(secret, f"{subject}:{profile_id}")
            else:
                encrypted = previous["encrypted_key"]
            window = context_window(values.get("context_window", previous.get("context_window", DEFAULT_CONTEXT_WINDOW) if previous else DEFAULT_CONTEXT_WINDOW))
            item = {
                "id": profile_id,
                "name": name,
                "model": model,
                "endpoint": endpoint,
                "context_window": window,
                "encrypted_key": encrypted,
                "created_at": previous["created_at"] if previous else now,
                "updated_at": now,
                "has_key": bool(secret)
                if secret
                else bool(previous["has_key"])
                if previous
                else False,
            }
            self._save(key, item)
            return self._public_profile(item)

    def delete_profile(self, subject: str, profile_id: str) -> None:
        key = self._key(subject, "profiles", _identifier(profile_id))
        with self._record_lock(key):
            self._read(key)
            get_state_store().delete(key)

    def _archive_key(self, subject: str, conversation_id: str) -> str:
        return self._key(subject, "archives", _identifier(conversation_id)).removesuffix(".json") + ".json.zst"

    def _archive_metadata_key(self, subject: str, conversation_id: str) -> str:
        return self._key(subject, "archive-metadata", _identifier(conversation_id))

    def _archive_ids(self, subject: str) -> set[str]:
        prefix = f"{self.prefix}/{_owner_key(subject)}/archives/"
        return {
            key.removeprefix(prefix).removesuffix(".json.zst")
            for key in get_state_store().list_keys(prefix)
            if key.endswith(".json.zst")
        }

    def conversations(self, subject: str) -> list[dict]:
        # A partially completed archive move can leave both copies. Archive
        # existence wins, so such conversations stay out of the normal index.
        archived = self._archive_ids(subject)
        return [
            self._summary(record) for record in self._records(subject, "conversations")
            if record["id"] not in archived
        ]

    @staticmethod
    def _summary(record: dict) -> dict:
        return {k: v for k, v in record.items() if k not in {"messages", "events", "context"}}

    def archived_conversations(self, subject: str) -> list[dict]:
        result = []
        store = get_state_store()
        for cid in self._archive_ids(subject):
            key = self._archive_metadata_key(subject, cid)
            metadata = store.read_bytes(key)
            if metadata is not None:
                result.append(json.loads(metadata))
            else:
                # An orphaned archive payload must remain discoverable and
                # recoverable even if the metadata write was interrupted.
                result.append(self._summary(self.archived_conversation(subject, cid)))
        return sorted(result, key=lambda r: r["archived_at"], reverse=True)

    def archived_conversation(self, subject: str, conversation_id: str) -> dict:
        from .audit_archive_codec import decompress_bytes

        content = get_state_store().read_bytes(self._archive_key(subject, conversation_id))
        if content is None:
            raise ValueError("Unknown archived conversation")
        return json.loads(decompress_bytes(content))

    def archive_conversation(self, subject: str, conversation_id: str) -> dict:
        from .audit_archive_codec import compress_bytes

        cid = _identifier(conversation_id)
        key = self._key(subject, "conversations", cid)
        archive_key = self._archive_key(subject, cid)
        metadata_key = self._archive_metadata_key(subject, cid)
        with self._record_lock(key):
            store = get_state_store()
            if store.read_bytes(archive_key) is not None:
                raise ValueError("Conversation is already archived")
            record = self._read(key)
            if record["status"] == "running":
                raise ValueError("Stop the active turn before archiving this conversation")
            archived = {**record, "archived_at": time.time()}
            payload = json.dumps(archived, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            # Publish compressed data first; never delete the only durable copy.
            store.write_bytes(archive_key, compress_bytes(payload))
            try:
                store.write_bytes(
                    metadata_key,
                    json.dumps(self._summary(archived), ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                )
            except Exception:
                # Data is already safe as a compressed archive. Keep it available
                # for recovery rather than risk data loss on failed rollback.
                raise
            store.delete(key)
            return self._summary(archived)

    def restore_conversation(self, subject: str, conversation_id: str) -> dict:
        cid = _identifier(conversation_id)
        key = self._key(subject, "conversations", cid)
        archive_key = self._archive_key(subject, cid)
        with self._record_lock(key):
            archived = self.archived_conversation(subject, cid)
            restored = {k: v for k, v in archived.items() if k != "archived_at"}
            store = get_state_store()
            existing = store.read_bytes(key)
            if existing is not None and json.loads(existing) != restored:
                raise ValueError("A conflicting live conversation already exists")
            if existing is None:
                self._save(key, restored)
            # Archive data is deleted only after the restored record is written.
            store.delete(archive_key)
            store.delete(self._archive_metadata_key(subject, cid))
            return restored

    def conversation(self, subject: str, conversation_id: str) -> dict:
        cid = _identifier(conversation_id)
        if get_state_store().read_bytes(self._archive_key(subject, cid)) is not None:
            raise ValueError("Archived conversation must be restored before use")
        return self._read(self._key(subject, "conversations", cid))

    def create_conversation(
        self,
        subject: str,
        *,
        profile_id: str,
        title: str = "New chat",
        session_id: str | None = None,
    ) -> dict:
        self.profile(subject, profile_id)
        now = time.time()
        cid = f"c_{uuid.uuid4().hex}"
        entry = {
            "id": cid,
            "title": title[:180],
            "profile_id": profile_id,
            "session_id": session_id,
            "messages": [],
            "events": [],
            "context": {"summary": "", "through": 0},
            "status": "idle",
            "error": None,
            "created_at": now,
            "updated_at": now,
        }
        with self._guard:
            self._save(self._key(subject, "conversations", cid), entry)
        return entry

    def update_conversation(self, subject: str, conversation_id: str, *, updater) -> dict:  # noqa: ANN001
        key = self._key(subject, "conversations", _identifier(conversation_id))
        with self._record_lock(key):
            if get_state_store().read_bytes(self._archive_key(subject, conversation_id)) is not None:
                raise ValueError("Archived conversation must be restored before use")
            record = self._read(key)
            updated = updater(record)
            updated["updated_at"] = time.time()
            self._save(key, updated)
            return updated

    async def compact_conversation(self, subject: str, conversation_id: str) -> dict:
        import asyncio

        from .hosted_chat import compact_history
        from .hosted_chat_context import DEFAULT_CONTEXT_WINDOW

        cid = _identifier(conversation_id)
        key = self._key(subject, "conversations", cid)

        def snapshot() -> dict:
            # Read under the normal cross-process record lock, but never hold
            # it (or the store-wide guard) during a model network request.
            with self._record_lock(key):
                if get_state_store().read_bytes(self._archive_key(subject, cid)) is not None:
                    raise ValueError("Restore an archived conversation before compacting it")
                record = self._read(key)
                if record["status"] == "running":
                    raise ValueError("Stop the active turn before compacting")
                return record

        before = await asyncio.to_thread(snapshot)
        profile = await asyncio.to_thread(
            self.profile, subject, before["profile_id"], with_secret=True
        )
        compacted = await compact_history(
            endpoint=profile["endpoint"], key=profile["api_key"],
            model=profile["model"], messages=before["messages"],
            context=before.get("context"),
            context_size=profile.get("context_window", DEFAULT_CONTEXT_WINDOW),
            session_id=before.get("session_id"), force=True,
        )
        if compacted is None:
            raise ValueError("Not enough completed history to compact")

        def commit() -> dict:
            with self._record_lock(key):
                if get_state_store().read_bytes(self._archive_key(subject, cid)) is not None:
                    raise ValueError("Conversation was archived during compact")
                record = self._read(key)
                if record != before:
                    raise ValueError("Conversation changed during compact; please retry")
                record["context"] = compacted
                record["updated_at"] = time.time()
                self._save(key, record)
                return record

        return await asyncio.to_thread(commit)

    def delete_conversation(self, subject: str, conversation_id: str) -> None:
        cid = _identifier(conversation_id)
        key = self._key(subject, "conversations", cid)
        with self._record_lock(key):
            if cid in self._archive_ids(subject):
                raise ValueError("Use the archived-conversation delete action")
            if self._read(key)["status"] == "running":
                raise ValueError("Stop the active turn before deleting this conversation")
            get_state_store().delete(key)

    def delete_archived_conversation(self, subject: str, conversation_id: str) -> None:
        cid = _identifier(conversation_id)
        key = self._key(subject, "conversations", cid)
        with self._record_lock(key):
            archived = self.archived_conversation(subject, cid)
            store = get_state_store()
            existing = store.read_bytes(key)
            if existing is not None:
                restored = {k: v for k, v in archived.items() if k != "archived_at"}
                if json.loads(existing) == restored:
                    store.delete(key)
            store.delete(self._archive_key(subject, cid))
            store.delete(self._archive_metadata_key(subject, cid))


def _identifier(value: str) -> str:
    if (
        not value
        or len(value) > 70
        or not all(c.isascii() and (c.isalnum() or c in "-_") for c in value)
    ):
        raise ValueError("Invalid record identifier")
    return value


hosted_chat_store = HostedChatStore()

RUN_LEASE_SECONDS = 90
RUN_HEARTBEAT_SECONDS = 15


def _close_unknown_tool_calls(messages: list[dict]) -> None:
    """Preserve conversation validity without replaying unknown-side-effect calls."""
    pending: set[str] = set()
    for message in messages:
        if message.get("role") == "assistant":
            pending.update(
                str(call["id"])
                for call in (message.get("tool_calls") or [])
                if isinstance(call, dict) and call.get("id")
            )
        elif message.get("role") == "tool":
            pending.discard(str(message.get("tool_call_id") or ""))
    for call_id in sorted(pending):
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": "Execution outcome unknown after interruption. Do not automatically repeat this operation; inspect LSM audit and target state.",
            }
        )


class HostedChatRunner:
    """Detached per-conversation background turns, with durable checkpoints."""

    def __init__(self) -> None:
        self._tasks: dict[tuple[str, str], Any] = {}
        self._lock = threading.RLock()

    async def start(
        self, subject: str, conversation_id: str, text: str, base_url: str, bearer: str,
        public_origin: str | None = None,
    ) -> dict:
        import asyncio

        from .hosted_chat import complete_turn

        if not text.strip() or len(text) > 40_000:
            raise ValueError("Message must contain 1–40000 characters")
        key = (subject, conversation_id)
        run_id = uuid.uuid4().hex
        with self._lock:
            task = self._tasks.get(key)
            if task and not task.done():
                raise ValueError("A chat turn is already running")

            def prepare(record: dict) -> dict:
                if record["status"] == "running":
                    raise ValueError("An interrupted turn is awaiting explicit recovery")
                _close_unknown_tool_calls(record["messages"])
                record["messages"].append({"role": "user", "content": text.strip()})
                record["status"] = "running"
                record["run_id"] = run_id
                record["cancel_requested"] = False
                record["lease_until"] = time.time() + RUN_LEASE_SECONDS
                record["error"] = None
                if record["title"] == "New chat":
                    record["title"] = text.strip()[:100]
                return record

            current = await asyncio.to_thread(
                hosted_chat_store.update_conversation,
                subject, conversation_id, updater=prepare,
            )

            def owned_update(updater):
                def guarded(record: dict) -> dict:
                    if record.get("status") != "running" or record.get("run_id") != run_id:
                        raise ValueError("Hosted Chat run ownership was lost")
                    return updater(record)

                return hosted_chat_store.update_conversation(
                    subject, conversation_id, updater=guarded
                )

            async def heartbeat(run_task) -> None:
                while True:
                    await asyncio.sleep(RUN_HEARTBEAT_SECONDS)
                    try:
                        record = await asyncio.to_thread(
                            owned_update,
                            lambda r: {
                                **r,
                                "lease_until": time.time() + RUN_LEASE_SECONDS,
                            },
                        )
                    except ValueError:
                        # Ownership was revoked; do not continue making tool calls.
                        run_task.cancel()
                        return
                    except Exception:
                        # Transient storage failures must not permanently stop renewals.
                        continue
                    if record.get("cancel_requested"):
                        run_task.cancel()
                        return

            async def execute() -> None:
                heartbeat_task = asyncio.create_task(heartbeat(asyncio.current_task()))
                try:
                    profile = await asyncio.to_thread(
                        hosted_chat_store.profile, subject, current["profile_id"], with_secret=True
                    )

                    previous_events = 0

                    async def checkpoint(messages: list[dict], events: list[dict]) -> None:
                        nonlocal previous_events

                        def save(record: dict) -> dict:
                            record["messages"] = messages
                            # Tool events are sanitized; no MCP App tokens or API keys.
                            record["events"].extend(events[previous_events:])
                            return record

                        await asyncio.to_thread(owned_update, save)
                        previous_events = len(events)

                    async def save_context(compacted: dict) -> None:
                        await asyncio.to_thread(
                            owned_update, lambda r: {**r, "context": compacted}
                        )

                    from .hosted_chat_context import DEFAULT_CONTEXT_WINDOW

                    await complete_turn(
                        base_url=base_url,
                        bearer=bearer,
                        endpoint=profile["endpoint"],
                        key=profile["api_key"],
                        model=profile["model"],
                        messages=current["messages"],
                        context=current.get("context"),
                        context_size=profile.get("context_window", DEFAULT_CONTEXT_WINDOW),
                        context_checkpoint=save_context,
                        tools_enabled=True,
                        session_id=current.get("session_id"),
                        checkpoint=checkpoint,
                        **({"public_origin": public_origin} if public_origin else {}),
                    )
                except asyncio.CancelledError:
                    # Retain tool results; never auto-replay a possibly non-idempotent tool.
                    with contextlib.suppress(ValueError):
                        await asyncio.to_thread(
                            owned_update,
                            lambda r: {
                                **r,
                                "status": "interrupted",
                                "error": "Turn interrupted",
                                "run_id": None,
                                "lease_until": None,
                            },
                        )
                    raise
                except Exception as exc:
                    # Transport errors can include raw Authorization headers. Never
                    # persist their exception text, even when profile keys are encrypted.
                    error = (
                        f"ValueError: {exc}"[:400] if type(exc) is ValueError
                        else f"{type(exc).__name__}: Hosted Chat turn failed"
                    )
                    with contextlib.suppress(ValueError):
                        await asyncio.to_thread(
                            owned_update,
                            lambda r: {
                                **r,
                                "status": "failed",
                                "error": error,
                                "run_id": None,
                                "lease_until": None,
                            },
                        )
                else:
                    with contextlib.suppress(ValueError):
                        await asyncio.to_thread(
                            owned_update,
                            lambda r: {
                                **r,
                                "status": "idle",
                                "error": None,
                                "run_id": None,
                                "lease_until": None,
                            },
                        )
                finally:
                    heartbeat_task.cancel()
                    await asyncio.gather(heartbeat_task, return_exceptions=True)

            run = asyncio.create_task(execute(), name=f"hosted-chat-{conversation_id}")
            self._tasks[key] = run

            def cleanup(done_task):
                with self._lock:
                    if self._tasks.get(key) is done_task:
                        self._tasks.pop(key, None)

            run.add_done_callback(cleanup)
            return hosted_chat_store._summary(current)

    def stop(self, subject: str, conversation_id: str) -> None:
        def request_stop(record: dict) -> dict:
            if record["status"] != "running":
                raise ValueError("No active Hosted Chat turn")
            record["cancel_requested"] = True
            return record

        hosted_chat_store.update_conversation(subject, conversation_id, updater=request_stop)
        # A different replica observes the durable stop request on heartbeat.
        with self._lock:
            task = self._tasks.get((subject, conversation_id))
            if task and not task.done():
                # HTTP routes call stop() via asyncio.to_thread; asyncio Task
                # cancellation must run on the task's owning loop.
                with contextlib.suppress(RuntimeError):
                    task.get_loop().call_soon_threadsafe(task.cancel)

    @staticmethod
    def reconcile(subject: str, conversation_id: str) -> dict:
        def reconcile_locked(record: dict) -> dict:
            # A remote replica's task is not in this process. Only an expired
            # durable lease is evidence of interruption, under the store lock.
            if record["status"] == "running" and (record.get("lease_until") or 0) <= time.time():
                record["status"] = "interrupted"
                record["error"] = "Agent Run lease expired; inspect tool effects before retrying"
                record["run_id"] = None
                record["lease_until"] = None
            return record

        current = hosted_chat_store.conversation(subject, conversation_id)
        if current["status"] != "running" or (current.get("lease_until") or 0) > time.time():
            return current
        return hosted_chat_store.update_conversation(
            subject, conversation_id, updater=reconcile_locked
        )


hosted_chat_runner = HostedChatRunner()
