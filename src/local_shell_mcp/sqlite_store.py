"""One durable SQLite database for controller state and the web workspace."""

from __future__ import annotations

import contextlib
import hashlib
import os
import sqlite3
import threading
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
CREATE TABLE IF NOT EXISTS state_append_chunks (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL REFERENCES state(key) ON DELETE CASCADE,
    value BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_state_append_chunks_key ON state_append_chunks(key,id);
CREATE TABLE IF NOT EXISTS state_append_lengths (
    key TEXT PRIMARY KEY REFERENCES state(key) ON DELETE CASCADE,
    total_size INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS legacy_imports (
    key TEXT PRIMARY KEY,
    source_mtime_ns INTEGER NOT NULL,
    source_size INTEGER NOT NULL,
    imported_digest TEXT NOT NULL
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
CREATE TABLE IF NOT EXISTS agent_versions (
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    snapshot TEXT NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    PRIMARY KEY(agent_id,version)
);
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
"""

_FTS_SCHEMA = """
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
        if os.name != "nt":
            # O_CREAT without EXCL tolerates simultaneous first-run processes.
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT, 0o600)
            os.close(descriptor)
        with self.connect() as db:
            db.executescript("PRAGMA journal_mode=WAL; " + _SCHEMA)
            try:
                db.executescript(_FTS_SCHEMA)
            except sqlite3.OperationalError as exc:
                if not any(marker in str(exc).lower() for marker in (
                    "no such module: fts5", "error in tokenizer constructor", "no such tokenizer",
                )):
                    raise
                self.fts_enabled = False
            else:
                self.fts_enabled = True
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
            if row is None:
                return None
            parts = [bytes(row[0])]
            parts.extend(bytes(chunk[0]) for chunk in db.execute(
                "SELECT value FROM state_append_chunks WHERE key=? ORDER BY id", (key,)
            ))
            return b"".join(parts)

    def write_bytes(self, key: str, value: bytes) -> None:
        with self.database.connect() as db:
            db.execute(
                "INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) "
                "DO UPDATE SET value=excluded.value, updated_at=unixepoch()",
                (key, sqlite3.Binary(value)),
            )
            db.execute("DELETE FROM state_append_chunks WHERE key=?", (key,))
            db.execute("DELETE FROM state_append_lengths WHERE key=?", (key,))

    def append_bytes(self, key: str, value: bytes) -> int:
        with self.database.connect() as db:
            db.execute("INSERT OR IGNORE INTO state(key,value) VALUES(?,X'')", (key,))
            if value:
                db.execute("INSERT INTO state_append_chunks(key,value) VALUES(?,?)",
                           (key, sqlite3.Binary(value)))
                db.execute(
                    "INSERT INTO state_append_lengths(key,total_size) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET total_size=total_size+excluded.total_size",
                    (key, len(value)),
                )
            size = db.execute(
                "SELECT length(s.value) + COALESCE(a.total_size,0) FROM state s "
                "LEFT JOIN state_append_lengths a ON a.key=s.key WHERE s.key=?",
                (key,),
            ).fetchone()[0]
            return int(size)

    def size_bytes(self, key: str) -> int | None:
        with self.database.connect() as db:
            row = db.execute(
                "SELECT length(s.value) + COALESCE(a.total_size,0) FROM state s "
                "LEFT JOIN state_append_lengths a ON a.key=s.key WHERE s.key=?",
                (key,),
            ).fetchone()
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

    def _legacy_paths(self) -> Iterator[Path]:
        """Enumerate durable state, never job outputs, browser caches or uploads."""
        root = self.root
        root_files = {"oauth-jwt-secret", "remote-workers.generation"}
        # Some state keys are created by optional tools; import their JSON
        # objects without accidentally treating build artifacts as state.
        for path in sorted(root.iterdir()):
            if path.is_symlink() or not path.is_file():
                continue
            if path.name.startswith("hosted-chat"):
                # Hosted Chat was an unpublished prototype. Do not carry its
                # profiles, conversations, secrets or archives into the new UI.
                continue
            if path.name in root_files or path.suffix in {".json", ".jsonl"}:
                yield path
        for name in (
            "sessions", "audit-archive", "audit-payloads", "remote", "agent_config",
        ):
            parent = root / name
            if parent.is_symlink() or not parent.is_dir():
                continue
            for path in sorted(parent.rglob("*")):
                relative = path.relative_to(parent)
                if not path.is_file() or path.is_symlink():
                    continue
                if any((parent.joinpath(*relative.parts[:depth])).is_symlink()
                       for depth in range(1, len(relative.parts))):
                    continue
                yield path

    def migrate_files(self) -> int:
        """Import legacy durable state, atomically, without deleting originals.

        On repeated startup, only files changed since the previous import are
        considered. SQLite-local edits win over stale file updates, while
        never-modified imported rows can be refreshed during cutover.
        """
        count = 0
        with self.lock("__schema/legacy_file_import"), self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for path in self._legacy_paths():
                key = path.relative_to(self.root).as_posix()
                try:
                    key.encode("utf-8")
                except UnicodeEncodeError:
                    # POSIX surrogate-escaped filesystem entries are not valid
                    # SQLite TEXT keys. Keep those files untouched.
                    continue
                info = path.stat()
                previous = db.execute(
                    "SELECT source_mtime_ns,source_size,imported_digest FROM legacy_imports WHERE key=?",
                    (key,),
                ).fetchone()
                if previous and previous[0] == info.st_mtime_ns and previous[1] == info.st_size:
                    continue
                if info.st_size > 64 * 1024 * 1024:
                    raise RuntimeError(f"Legacy state entry is too large for safe automatic import: {key}")
                payload = path.read_bytes()
                digest = hashlib.sha256(payload).hexdigest()
                existing = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
                if existing is None:
                    db.execute("INSERT INTO state(key,value) VALUES(?,?)", (key, sqlite3.Binary(payload)))
                    count += 1
                elif previous and hashlib.sha256(bytes(existing[0])).hexdigest() == previous[2] and not db.execute(
                    "SELECT 1 FROM state_append_chunks WHERE key=? LIMIT 1", (key,)
                ).fetchone():
                    db.execute("UPDATE state SET value=?,updated_at=unixepoch() WHERE key=?",
                               (sqlite3.Binary(payload), key))
                    count += 1
                else:
                    # The destination may predate the import journal, or have
                    # been modified by SQLite clients. Never overwrite it.
                    continue
                db.execute(
                    "INSERT INTO legacy_imports(key,source_mtime_ns,source_size,imported_digest) "
                    "VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
                    "source_mtime_ns=excluded.source_mtime_ns, "
                    "source_size=excluded.source_size, imported_digest=excluded.imported_digest",
                    (key, info.st_mtime_ns, info.st_size, digest),
                )
            return count
