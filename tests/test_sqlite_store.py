"""Regression tests for the unified SQLite controller/workspace database."""

from __future__ import annotations

import concurrent.futures
import sqlite3
from pathlib import Path

import pytest

from local_shell_mcp.sqlite_store import DB_NAME, SQLiteStateStore


def test_transactional_binary_state(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path)
    payload = bytes(range(256))
    assert store.read_bytes("missing") is None
    assert store.size_bytes("missing") is None
    store.write_bytes("job/a", payload)
    assert store.read_bytes("job/a") == payload
    assert store.append_bytes("job/a", payload) == 512
    assert store.read_bytes("job/a") == payload * 2
    assert store.size_bytes("job/a") == 512
    assert store.list_keys("job/") == ["job/a"]
    store.delete("job/a")
    assert store.read_bytes("job/a") is None


def test_prefix_literal_escaping(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path)
    for name in ("a_1", "a%2", "ax2", "a\\z"):
        store.write_bytes(name, b"x")
    assert store.list_keys("a_") == ["a_1"]
    assert store.list_keys("a%") == ["a%2"]


def test_idempotent_file_import_keeps_original_files(tmp_path: Path) -> None:
    legacy = tmp_path / "remote" / "workers.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b'{"workers":1}')
    store = SQLiteStateStore(tmp_path)
    assert store.read_bytes("remote/workers.json") == legacy.read_bytes()
    store.write_bytes("remote/workers.json", b"updated")
    assert store.migrate_files() == 0
    assert store.read_bytes("remote/workers.json") == b"updated"
    assert legacy.read_bytes() == b'{"workers":1}'


def test_concurrent_append_with_lock(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path)

    def append(_: int) -> None:
        with store.lock("activity"):
            store.append_bytes("activity", b"x")

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        list(executor.map(append, range(100)))
    assert store.size_bytes("activity") == 100


def test_webui_tables_share_state_database(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path)
    with store.database.connect() as db:
        db.execute("INSERT INTO projects(id,owner,name) VALUES(?,?,?)", ("p1", "local", "Work"))
        db.execute("INSERT INTO conversations(id,owner,title,project_id) VALUES(?,?,?,?)", ("c1", "local", "你好", "p1"))
        db.execute("INSERT INTO messages(id,conversation_id,role,text) VALUES(?,?,?,?)", ("m1", "c1", "user", "南京大学你好"))
    assert store.database.path == tmp_path / DB_NAME
    with store.database.connect() as db:
        assert db.execute("SELECT message_id FROM message_search WHERE text MATCH '南京大' ").fetchone()[0] == "m1"
        assert db.execute("SELECT key FROM state LIMIT 1").fetchone() is not None
        db.execute("DELETE FROM conversations WHERE id=?", ("c1",))
        assert db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM message_search").fetchone()[0] == 0


def test_sqlite_online_backup_is_consistent(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path / "live")
    store.write_bytes("state/a", b"123")
    with store.database.connect() as db:
        db.execute("INSERT INTO projects(id,owner,name) VALUES(?,?,?)", ("p", "local", "Project"))
    destination = tmp_path / "backup" / "snapshot.sqlite3"
    store.database.backup(destination)
    with sqlite3.connect(destination) as conn:
        assert conn.execute("SELECT value FROM state WHERE key='state/a'").fetchone()[0] == b"123"
        assert conn.execute("SELECT name FROM projects WHERE id='p'").fetchone()[0] == "Project"


def test_bad_backup_destination(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path)
    with pytest.raises(ValueError):
        store.database.backup(store.database.path)


def test_nested_same_key_lock_is_reentrant(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path)
    with store.lock("same-key"), store.lock("same-key"):
        store.write_bytes("nested", b"works")
    assert store.read_bytes("nested") == b"works"


def test_migration_rolls_back_after_io_failure(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "legacy.json").write_bytes(b"old")
    store = SQLiteStateStore(tmp_path, migrate_files=False)
    real_read = Path.read_bytes

    def broken_read(path: Path) -> bytes:
        if path.name == "legacy.json":
            raise PermissionError("simulated migration interruption")
        return real_read(path)

    monkeypatch.setattr(Path, "read_bytes", broken_read)
    with pytest.raises(PermissionError):
        store.migrate_files()
    assert store.read_bytes("legacy.json") is None
    monkeypatch.setattr(Path, "read_bytes", real_read)
    assert store.migrate_files() > 0
    assert store.read_bytes("legacy.json") == b"old"


def test_sqlite_oauth_secret_shares_state_database(tmp_path: Path, monkeypatch) -> None:
    from local_shell_mcp.settings import get_settings

    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "oauth")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "sqlite")
    monkeypatch.delenv("LOCAL_SHELL_MCP_OAUTH_JWT_SECRET", raising=False)
    get_settings.cache_clear()
    try:
        first = get_settings().oauth_jwt_secret
        get_settings.cache_clear()
        assert get_settings().oauth_jwt_secret == first
        state = SQLiteStateStore(tmp_path / ".local-shell-mcp")
        assert state.read_bytes("oauth-jwt-secret").decode() == first
        assert not (tmp_path / ".local-shell-mcp" / "oauth-jwt-secret").exists()
    finally:
        get_settings.cache_clear()
