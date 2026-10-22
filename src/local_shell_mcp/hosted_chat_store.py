"""Durable, principal-scoped Hosted Chat data backed by LSM's state store."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import secrets
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
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        key = path.read_bytes()
    else:
        with os.fdopen(descriptor, "wb") as handle:
            key = secrets.token_bytes(32)
            handle.write(key)
            handle.flush()
            os.fsync(handle.fileno())
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
        from .hosted_chat import validate_endpoint

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
                if len(secret) > 8192:
                    raise ValueError("API key is too long")
                encrypted = _encrypt(secret, f"{subject}:{profile_id}")
            else:
                encrypted = previous["encrypted_key"]
            item = {
                "id": profile_id,
                "name": name,
                "model": model,
                "endpoint": endpoint,
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

    def conversations(self, subject: str) -> list[dict]:
        return [self._summary(r) for r in self._records(subject, "conversations")]

    @staticmethod
    def _summary(record: dict) -> dict:
        return {k: v for k, v in record.items() if k != "messages" and k != "events"}

    def conversation(self, subject: str, conversation_id: str) -> dict:
        return self._read(self._key(subject, "conversations", _identifier(conversation_id)))

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
            record = self._read(key)
            updated = updater(record)
            updated["updated_at"] = time.time()
            self._save(key, updated)
            return updated

    def delete_conversation(self, subject: str, conversation_id: str) -> None:
        key = self._key(subject, "conversations", _identifier(conversation_id))
        with self._record_lock(key):
            if self._read(key)["status"] == "running":
                raise ValueError("Stop the active turn before deleting this conversation")
            get_state_store().delete(key)


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
        self, subject: str, conversation_id: str, text: str, base_url: str, bearer: str
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

            current = hosted_chat_store.update_conversation(
                subject, conversation_id, updater=prepare
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
                    record = await asyncio.to_thread(
                        owned_update,
                        lambda r: {
                            **r,
                            "lease_until": time.time() + RUN_LEASE_SECONDS,
                        },
                    )
                    if record.get("cancel_requested"):
                        run_task.cancel()
                        return

            async def execute() -> None:
                heartbeat_task = asyncio.create_task(heartbeat(asyncio.current_task()))
                try:
                    profile = hosted_chat_store.profile(
                        subject, current["profile_id"], with_secret=True
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

                    await complete_turn(
                        base_url=base_url,
                        bearer=bearer,
                        endpoint=profile["endpoint"],
                        key=profile["api_key"],
                        model=profile["model"],
                        messages=current["messages"],
                        tools_enabled=True,
                        session_id=current.get("session_id"),
                        checkpoint=checkpoint,
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
                    error = f"{type(exc).__name__}: {exc}"[:400]
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
                task.cancel()

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
