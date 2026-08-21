from __future__ import annotations

import contextlib
import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .settings import get_settings

_REDIS_LOCK_TTL_S = 30.0
_REDIS_LOCK_RENEW_INTERVAL_S = 10.0


class StateStore(Protocol):
    def read_bytes(self, key: str) -> bytes | None: ...

    def write_bytes(self, key: str, value: bytes) -> None: ...

    def delete(self, key: str) -> None: ...

    def list_keys(self, prefix: str = "") -> list[str]: ...

    def lock(self, key: str) -> contextlib.AbstractContextManager[None]: ...


class FileStateStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        path = self.root / key
        resolved_root = self.root.resolve()
        resolved = path.resolve()
        if resolved != resolved_root and resolved_root not in resolved.parents:
            raise ValueError(f"state key escapes state directory: {key}")
        return path

    def read_bytes(self, key: str) -> bytes | None:
        path = self._path(key)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None

    def write_bytes(self, key: str, value: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(value)
            with contextlib.suppress(OSError):
                temporary.chmod(0o600)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def list_keys(self, prefix: str = "") -> list[str]:
        if not self.root.exists():
            return []
        keys: list[str] = []
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            key = path.relative_to(self.root).as_posix()
            if key.startswith(prefix):
                keys.append(key)
        return sorted(keys)

    @contextlib.contextmanager
    def lock(self, key: str) -> Iterator[None]:
        del key
        yield


_MEMORY_VALUES: dict[str, bytes] = {}


@dataclass
class _MemoryLockEntry:
    lock: threading.RLock
    users: int = 0


_MEMORY_LOCKS: dict[str, _MemoryLockEntry] = {}
_MEMORY_GUARD = threading.RLock()


class MemoryStateStore:
    def __init__(self, namespace: str = "local-shell-mcp") -> None:
        self._namespace = namespace.strip(":") or "local-shell-mcp"

    def _key(self, key: str) -> str:
        return f"{self._namespace}:{key}"

    @contextlib.contextmanager
    def _locked_key(self, key: str) -> Iterator[str]:
        namespaced = self._key(key)
        with _MEMORY_GUARD:
            entry = _MEMORY_LOCKS.get(namespaced)
            if entry is None:
                entry = _MemoryLockEntry(threading.RLock())
                _MEMORY_LOCKS[namespaced] = entry
            entry.users += 1
        try:
            with entry.lock:
                yield namespaced
        finally:
            with _MEMORY_GUARD:
                entry.users -= 1
                if entry.users == 0 and _MEMORY_LOCKS.get(namespaced) is entry:
                    _MEMORY_LOCKS.pop(namespaced, None)

    def read_bytes(self, key: str) -> bytes | None:
        with self._locked_key(key) as namespaced:
            value = _MEMORY_VALUES.get(namespaced)
            return None if value is None else bytes(value)

    def write_bytes(self, key: str, value: bytes) -> None:
        with self._locked_key(key) as namespaced:
            _MEMORY_VALUES[namespaced] = bytes(value)

    def delete(self, key: str) -> None:
        with self._locked_key(key) as namespaced:
            _MEMORY_VALUES.pop(namespaced, None)

    def list_keys(self, prefix: str = "") -> list[str]:
        namespace_prefix = f"{self._namespace}:"
        with _MEMORY_GUARD:
            keys = [
                key.removeprefix(namespace_prefix)
                for key in _MEMORY_VALUES
                if key.startswith(namespace_prefix)
                and key.removeprefix(namespace_prefix).startswith(prefix)
            ]
        return sorted(keys)

    @contextlib.contextmanager
    def lock(self, key: str) -> Iterator[None]:
        with self._locked_key(key):
            yield


class RedisStateStore:
    def __init__(self, url: str, prefix: str) -> None:
        try:
            import redis
        except ImportError as exc:  # pragma: no cover - depends on optional extra.
            raise RuntimeError(
                "Redis state backend requires the 'redis' package; install local-shell-mcp[redis]"
            ) from exc
        self._client = redis.Redis.from_url(url)
        self._prefix = prefix.strip(":") or "local-shell-mcp"
        self._active_locks = threading.local()

    def _key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    def read_bytes(self, key: str) -> bytes | None:
        value = self._client.get(self._key(key))
        return None if value is None else bytes(value)

    def _refresh_active_locks(self) -> None:
        for lock in getattr(self._active_locks, "stack", ()):
            # Refresh immediately before a state mutation. Besides extending
            # the TTL, redis-py verifies that the lock token is still ours and
            # raises if another controller acquired the lock after expiry.
            lock.reacquire()

    def write_bytes(self, key: str, value: bytes) -> None:
        self._refresh_active_locks()
        self._client.set(self._key(key), value)

    def delete(self, key: str) -> None:
        self._refresh_active_locks()
        self._client.delete(self._key(key))

    def list_keys(self, prefix: str = "") -> list[str]:
        full_prefix = self._key(prefix)
        namespace_prefix = f"{self._prefix}:"
        keys: list[str] = []
        for raw in self._client.scan_iter(match=full_prefix + "*"):
            decoded = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            if decoded.startswith(namespace_prefix):
                keys.append(decoded.removeprefix(namespace_prefix))
        return sorted(keys)

    @contextlib.contextmanager
    def lock(self, key: str) -> Iterator[None]:
        # Session transactions can legitimately outlive the initial Redis lock
        # TTL (for example, a retained-history scan before Session creation).
        # Keep the same lock token visible to the renewal thread and refresh the
        # TTL until the protected transaction has actually finished.
        lock = self._client.lock(
            self._key(f"locks:{key}"),
            timeout=_REDIS_LOCK_TTL_S,
            blocking_timeout=5,
            thread_local=False,
        )
        acquired = lock.acquire(blocking=True)
        if not acquired:
            raise TimeoutError(f"timed out acquiring state lock: {key}")
        stop_renewal = threading.Event()

        def renew() -> None:
            while not stop_renewal.wait(_REDIS_LOCK_RENEW_INTERVAL_S):
                try:
                    lock.reacquire()
                except Exception:
                    # A transient Redis outage must not permanently stop lock
                    # renewal. Keep retrying until the protected transaction
                    # ends; state operations in the transaction still surface
                    # persistent backend failures to the caller.
                    continue

        renewal = threading.Thread(
            target=renew,
            name="lsm-redis-state-lock-renewal",
            daemon=True,
        )
        stack = getattr(self._active_locks, "stack", None)
        if stack is None:
            stack = []
            self._active_locks.stack = stack
        stack.append(lock)
        renewal.start()
        try:
            yield
        finally:
            stop_renewal.set()
            renewal.join(timeout=max(1.0, _REDIS_LOCK_RENEW_INTERVAL_S * 2))
            if stack and stack[-1] is lock:
                stack.pop()
            else:  # pragma: no cover - defensive against malformed nested use.
                with contextlib.suppress(ValueError):
                    stack.remove(lock)
            with contextlib.suppress(Exception):
                lock.release()


_STORE_CACHE: tuple[tuple[str, str | None, str, str], StateStore] | None = None
_STORE_CACHE_LOCK = threading.Lock()


def get_state_store() -> StateStore:
    global _STORE_CACHE
    settings = get_settings()
    signature = (
        settings.state_backend,
        settings.state_backend_url,
        settings.state_backend_prefix,
        str(settings.state_dir),
    )
    with _STORE_CACHE_LOCK:
        if _STORE_CACHE is not None and _STORE_CACHE[0] == signature:
            return _STORE_CACHE[1]
        if settings.state_backend == "file":
            store: StateStore = FileStateStore(settings.state_dir)
        elif settings.state_backend == "memory":
            store = MemoryStateStore(settings.state_backend_prefix)
        elif settings.state_backend == "redis":
            if not settings.state_backend_url:
                raise ValueError("state_backend_url is required when state_backend=redis")
            store = RedisStateStore(settings.state_backend_url, settings.state_backend_prefix)
        else:  # pragma: no cover - settings validation protects this branch.
            raise ValueError(f"unsupported state backend: {settings.state_backend}")
        _STORE_CACHE = (signature, store)
        return store


@contextlib.contextmanager
def state_lock(key: str) -> Iterator[None]:
    with get_state_store().lock(key):
        yield


def clear_memory_state() -> None:
    """Clear process-local state. Intended for tests and explicit ephemeral resets."""
    with _MEMORY_GUARD:
        _MEMORY_VALUES.clear()
        _MEMORY_LOCKS.clear()
