"""One durable SQLite database for controller state and the web workspace."""

from __future__ import annotations

import contextlib
import hashlib
import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

DB_NAME = "lsm.sqlite3"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value BLOB NOT NULL,
    updated_at INTEGER NOT NULL DEFAULT (unixepoch())
);
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (unixepoch())
);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    agent_id TEXT,
    model TEXT,
    endpoint TEXT,
    archived INTEGER NOT NULL DEFAULT 0,
    pinned INTEGER NOT NULL DEFAULT 0,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    updated_at INTEGER NOT NULL DEFAULT (unixepoch())
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    parent_id TEXT,
    role TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '{}',
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    updated_at INTEGER NOT NULL DEFAULT (unixepoch())
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_conversations_owner ON conversations(owner, archived, updated_at DESC);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    updated_at INTEGER NOT NULL DEFAULT (unixepoch())
);
CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner, updated_at DESC);
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    config TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    updated_at INTEGER NOT NULL DEFAULT (unixepoch())
);
CREATE INDEX IF NOT EXISTS idx_agents_owner ON agents(owner, updated_at DESC);
CREATE TABLE IF NOT EXISTS web_login_tickets (
    hash TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    scopes TEXT NOT NULL,
    grant_until INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS web_sessions (
    hash TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    scopes TEXT NOT NULL,
    grant_until INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (unixepoch())
);
CREATE INDEX IF NOT EXISTS idx_web_sessions_expiry ON web_sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_web_tickets_expiry ON web_login_tickets(expires_at);
CREATE TABLE IF NOT EXISTS settings (
    owner TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY(owner, key)
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    agent_id TEXT,
    status TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    updated_at INTEGER NOT NULL DEFAULT (unixepoch())
);
CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    content_type TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL DEFAULT (unixepoch())
);
CREATE VIRTUAL TABLE IF NOT EXISTS message_search USING fts5(
    message_id UNINDEXED, conversation_id UNINDEXED, text, tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS message_search_insert AFTER INSERT ON messages BEGIN
    INSERT INTO message_search(message_id, conversation_id, text)
    VALUES(new.id, new.conversation_id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS message_search_delete AFTER DELETE ON messages BEGIN
    DELETE FROM message_search WHERE message_id = old.id;
END;
CREATE TRIGGER IF NOT EXISTS message_search_update AFTER UPDATE OF text ON messages BEGIN
    DELETE FROM message_search WHERE message_id = old.id;
    INSERT INTO message_search(message_id, conversation_id, text)
    VALUES(new.id, new.conversation_id, new.text);
END;
"""


class SQLiteDatabase:
    def __init__(self, state_dir: Path) -> None:
        self.root = Path(state_dir)
        self.path = self.root / DB_NAME
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.path.exists() and os.name != "nt":
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
        with self.connect() as db:
            db.executescript("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON; " + _SCHEMA)
            db.execute("PRAGMA user_version=1")

    @contextlib.contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def backup(self, destination: Path) -> None:
        """Consistent online backup including controller and chat records."""
        destination = Path(destination)
        if destination.resolve() == self.path.resolve():
            raise ValueError("Cannot back up database over itself")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as source, sqlite3.connect(destination) as output:
            source.backup(output)


_KEY_LOCKS: dict[tuple[str, str], threading.RLock] = {}
_KEY_LOCKS_GUARD = threading.Lock()
_LOCK_DEPTH = threading.local()


@lru_cache(maxsize=16)
def shared_database(state_dir: Path) -> SQLiteDatabase:
    return SQLiteDatabase(state_dir)


class SQLiteStateStore:
    """StateStore-compatible transactional key/value interface in the shared DB."""

    def __init__(self, state_dir: Path, *, migrate_files: bool = True) -> None:
        self.database = shared_database(Path(state_dir).resolve())
        self.root = self.database.root
        if migrate_files:
            self.migrate_files()

    def read_bytes(self, key: str) -> bytes | None:
        with self.database.connect() as db:
            row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
            return bytes(row[0]) if row else None

    def write_bytes(self, key: str, value: bytes) -> None:
        with self.database.connect() as db:
            db.execute(
                "INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) "
                "DO UPDATE SET value=excluded.value, updated_at=unixepoch()",
                (key, sqlite3.Binary(value)),
            )

    def append_bytes(self, key: str, value: bytes) -> int:
        with self.database.connect() as db:
            db.execute(
                "INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) "
                "DO UPDATE SET value=CAST(state.value || excluded.value AS BLOB), updated_at=unixepoch()",
                (key, sqlite3.Binary(value)),
            )
            return int(db.execute("SELECT length(value) FROM state WHERE key=?", (key,)).fetchone()[0])

    def size_bytes(self, key: str) -> int | None:
        with self.database.connect() as db:
            row = db.execute("SELECT length(value) FROM state WHERE key=?", (key,)).fetchone()
            return int(row[0]) if row else None

    def delete(self, key: str) -> None:
        with self.database.connect() as db:
            db.execute("DELETE FROM state WHERE key=?", (key,))

    def list_keys(self, prefix: str = "") -> list[str]:
        with self.database.connect() as db:
            # Escape wildcard characters so prefix semantics match FileStateStore.
            escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            rows = db.execute("SELECT key FROM state WHERE key LIKE ? ESCAPE '\\' ORDER BY key", (escaped + "%",))
            return [row[0] for row in rows]

    @contextlib.contextmanager
    def lock(self, key: str) -> Iterator[None]:
        """Reentrant local locking plus cross-process advisory lock for transactions."""
        name = (str(self.database.path.resolve()), key)
        with _KEY_LOCKS_GUARD:
            lock = _KEY_LOCKS.setdefault(name, threading.RLock())
        with lock:
            depths = getattr(_LOCK_DEPTH, "depths", None)
            if depths is None:
                depths = {}
                _LOCK_DEPTH.depths = depths
            if depths.get(name, 0):
                depths[name] += 1
                try:
                    yield
                finally:
                    depths[name] -= 1
                return
            lock_dir = self.root / "locks"
            lock_dir.mkdir(parents=True, exist_ok=True)
            path = lock_dir / (hashlib.sha256(key.encode("utf-8")).hexdigest() + ".lock")
            with path.open("a+b") as handle:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    if handle.read(1) == b"":
                        handle.write(b"0")
                        handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                depths[name] = 1
                try:
                    yield
                finally:
                    depths.pop(name, None)
                    if os.name == "nt":
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def migrate_files(self) -> int:
        """Copy historical file state transactionally without deleting original files.

        Idempotent: an imported record is never overwritten on subsequent starts.
        On failure, the transaction is rolled back and the files remain untouched.
        """
        marker = "__schema/file_state_import_v1"
        skip_names = {DB_NAME, DB_NAME + "-wal", DB_NAME + "-shm", DB_NAME + "-journal"}
        with self.lock(marker), self.database.connect() as db:
                if db.execute("SELECT 1 FROM state WHERE key=?", (marker,)).fetchone():
                    return 0
                count = 0
                for path in self.root.rglob("*"):
                    if not path.is_file() or path.is_symlink() or path.name in skip_names:
                        continue
                    key = path.relative_to(self.root).as_posix()
                    if key.startswith("locks/") or key.startswith("chat/") or key.startswith("runtime/"):
                        continue
                    db.execute("INSERT OR IGNORE INTO state(key,value) VALUES(?,?)", (key, path.read_bytes()))
                    count += 1
                db.execute("INSERT INTO state(key,value) VALUES(?,?)", (marker, str(int(time.time())).encode()))
                return count
