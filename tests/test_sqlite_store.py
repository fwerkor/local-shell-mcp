"""Regression tests for the unified SQLite controller/workspace database."""

from __future__ import annotations

import concurrent.futures
import sqlite3
from pathlib import Path

import pytest

from local_shell_mcp.sqlite_store import DB_NAME, SQLiteStateStore, shared_database


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


def test_parallel_cold_sqlite_startup_serializes_wal_schema(tmp_path: Path) -> None:
    """Cache misses in separate threads must not race WAL/schema initialization."""
    import threading

    shared_database.cache_clear()
    ready = threading.Barrier(8)

    def initialize(_: int) -> Path:
        ready.wait(timeout=10)
        return SQLiteStateStore(tmp_path, migrate_files=False).database.path

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        paths = list(executor.map(initialize, range(8)))
    assert paths == [tmp_path / DB_NAME] * 8


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
    store.write_bytes("settings/check", b"ok")
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
    import os
    real_open = os.open

    def broken_open(path, *args, **kwargs):
        if Path(path).name == "legacy.json":
            raise PermissionError("simulated migration interruption")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", broken_open)
    with pytest.raises(PermissionError):
        store.migrate_files()
    assert store.read_bytes("legacy.json") is None
    monkeypatch.setattr(os, "open", real_open)
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


def test_default_controller_imports_legacy_state_on_startup(tmp_path: Path, monkeypatch) -> None:
    from local_shell_mcp.settings import get_settings

    state_dir = tmp_path / ".local-shell-mcp"
    state_dir.mkdir()
    data = {
        "oauth-clients.json": b'{"version":1,"clients":{}}',
        "jobs.json": b'{"version":2,"jobs":[]}',
        "remote-workers.json": b'{"version":1,"workers":[]}',
        "audit.jsonl": b'{"event":"hello"}\n',
        "sessions/example.json": b'{"session_id":"example"}',
        "audit-archive/sample.jsonl.zst": b"fake archived data",
        "audit-payloads/abcdef.json.gz": b"fake payload",
    }
    for name, raw in data.items():
        path = state_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    for path in (state_dir / "jobs" / "attempt.log", state_dir / "tmp" / "huge.bin"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"regenerable-only")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(state_dir))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.delenv("LOCAL_SHELL_MCP_STATE_BACKEND", raising=False)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.state_backend == "sqlite"
        store = SQLiteStateStore(state_dir)
        for name, raw in data.items():
            assert store.read_bytes(name) == raw
            assert (state_dir / name).read_bytes() == raw
        assert store.read_bytes("jobs/attempt.log") is None
        assert store.read_bytes("tmp/huge.bin") is None
        assert store.migrate_files() == 0
    finally:
        get_settings.cache_clear()


def test_changed_old_state_is_refreshed_but_sqlite_changes_win(tmp_path: Path) -> None:
    path = tmp_path / "jobs.json"
    path.write_bytes(b"v1")
    store = SQLiteStateStore(tmp_path)
    assert store.read_bytes("jobs.json") == b"v1"
    path.write_bytes(b"v2-with-different-size")
    assert store.migrate_files() == 1
    assert store.read_bytes("jobs.json") == b"v2-with-different-size"
    store.write_bytes("jobs.json", b"sqlite-is-authoritative")
    path.write_bytes(b"v3-updated-by-old-server")
    assert store.migrate_files() == 0
    assert store.read_bytes("jobs.json") == b"sqlite-is-authoritative"
    assert path.read_bytes() == b"v3-updated-by-old-server"


def test_legacy_scan_ignores_nested_symlinks_and_binary_runtime(tmp_path: Path) -> None:
    outside = tmp_path.parent / (tmp_path.name + "-outside.json")
    outside.write_bytes(b"should-not-import")
    (tmp_path / "sessions").mkdir()
    (tmp_path / "sessions" / "linked.json").symlink_to(outside)
    (tmp_path / "browser-artifacts").mkdir()
    (tmp_path / "browser-artifacts" / "snapshot.json").write_bytes(b"not-durable-state")
    (tmp_path / "module.js").write_bytes(b"not-durable-state")
    store = SQLiteStateStore(tmp_path)
    assert store.read_bytes("sessions/linked.json") is None
    assert store.read_bytes("browser-artifacts/snapshot.json") is None
    assert store.read_bytes("module.js") is None


def test_explicit_file_backend_still_works_without_initializing_sqlite(tmp_path: Path, monkeypatch) -> None:
    from local_shell_mcp.settings import get_settings

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "file")
    get_settings.cache_clear()
    try:
        assert get_settings().state_backend == "file"
        assert not (tmp_path / ".local-shell-mcp" / DB_NAME).exists()
    finally:
        get_settings.cache_clear()


def test_search_falls_back_when_sqlite_lacks_fts5(tmp_path: Path) -> None:
    from local_shell_mcp.webui.storage import WorkspaceRepository

    store = SQLiteStateStore(tmp_path)
    repo = WorkspaceRepository(store.database)
    conversation_id = repo.create_conversation("local", {"title": "test"})["conversationId"]
    repo.add_message("local", conversation_id, {"role": "user", "text": "SQLite 中文全文检索"})
    was_enabled = store.database.fts_enabled
    try:
        store.database.fts_enabled = False
        assert len(repo.search_messages("local", "中文全")) == 1
    finally:
        store.database.fts_enabled = was_enabled


def test_incremental_appends_do_not_rewrite_entire_audit_blob(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path)
    store.write_bytes("audit.jsonl", b"old\n")
    for index in range(100):
        store.append_bytes("audit.jsonl", f"entry-{index}\n".encode())
    expected = b"old\n" + b"".join(f"entry-{i}\n".encode() for i in range(100))
    assert store.read_bytes("audit.jsonl") == expected
    assert store.size_bytes("audit.jsonl") == len(expected)
    with store.database.connect() as conn:
        assert conn.execute("SELECT length(value) FROM state WHERE key='audit.jsonl'").fetchone()[0] == 4
        assert conn.execute("SELECT count(*) FROM state_append_chunks WHERE key='audit.jsonl'").fetchone()[0] == 100
    store.write_bytes("audit.jsonl", b"compacted\n")
    assert store.read_bytes("audit.jsonl") == b"compacted\n"
    with store.database.connect() as conn:
        assert conn.execute("SELECT count(*) FROM state_append_chunks").fetchone()[0] == 0
    store.delete("audit.jsonl")
    assert store.read_bytes("audit.jsonl") is None


def test_sqlite_append_protects_from_stale_file_import(tmp_path: Path) -> None:
    file_path = tmp_path / "audit.jsonl"
    file_path.write_bytes(b"old\n")
    store = SQLiteStateStore(tmp_path)
    store.append_bytes("audit.jsonl", b"live-sqlite\n")
    file_path.write_bytes(b"old\nstale-file-update\n")
    assert store.migrate_files() == 0
    assert store.read_bytes("audit.jsonl") == b"old\nlive-sqlite\n"


@pytest.mark.skipif(__import__("os").name == "nt", reason="POSIX undecodable filename")
def test_invalid_utf8_filenames_do_not_block_controller_bootstrap(tmp_path: Path) -> None:
    import os

    name = os.fsdecode(b"invalid-\xff-name.json")
    try:
        (tmp_path / name).write_bytes(b"should-be-skipped")
    except (OSError, UnicodeError):
        pytest.skip("Host filesystem cannot represent surrogate-escaped filename")
    (tmp_path / "jobs.json").write_bytes(b"valid")
    store = SQLiteStateStore(tmp_path)
    assert store.read_bytes("jobs.json") == b"valid"


def test_unreleased_hosted_chat_state_is_not_migrated(tmp_path: Path) -> None:
    (tmp_path / "hosted-chat-encryption-key").write_bytes(b"private-old-secret")
    (tmp_path / "hosted-chat-state.json").write_bytes(b"old-profile")
    (tmp_path / "hosted-chat" / "profiles").mkdir(parents=True)
    (tmp_path / "hosted-chat" / "profiles" / "old.json").write_bytes(b"old-profile")
    (tmp_path / "chat" / "old-conversations").mkdir(parents=True)
    (tmp_path / "chat" / "old-conversations" / "snapshot.json").write_bytes(b"old-chat")
    (tmp_path / "remote-workers.json").write_bytes(b"active-worker")
    store = SQLiteStateStore(tmp_path)
    assert store.read_bytes("hosted-chat-encryption-key") is None
    assert store.read_bytes("hosted-chat-state.json") is None
    assert store.read_bytes("hosted-chat/profiles/old.json") is None
    assert store.read_bytes("chat/old-conversations/snapshot.json") is None
    assert store.read_bytes("remote-workers.json") == b"active-worker"
    assert (tmp_path / "hosted-chat" / "profiles" / "old.json").is_file()


def test_conversation_title_and_message_search_works_without_fts5(tmp_path: Path) -> None:
    from local_shell_mcp.webui.storage import WorkspaceRepository

    store = SQLiteStateStore(tmp_path)
    repo = WorkspaceRepository(store.database)
    cid = repo.create_conversation("local", {"title": "Research"})["conversationId"]
    repo.add_message("local", cid, {"role": "user", "text": "NJU software engineering"})
    previous = store.database.fts_enabled
    try:
        store.database.fts_enabled = False
        assert repo.conversations("local", search="NJU")["conversations"][0]["conversationId"] == cid
        assert repo.conversations("local", search="Research")["conversations"][0]["conversationId"] == cid
    finally:
        store.database.fts_enabled = previous


def test_frozen_controller_defaults_beside_executable(tmp_path: Path, monkeypatch) -> None:
    import local_shell_mcp.settings as settings_module

    executable = tmp_path / "local-shell-mcp"
    monkeypatch.setattr(settings_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(settings_module.sys, "executable", str(executable))
    assert settings_module._default_workspace_root() == tmp_path
    assert settings_module._default_workspace_root() / ".local-shell-mcp" == tmp_path / ".local-shell-mcp"


def test_source_installation_retains_configurable_workspace(tmp_path: Path, monkeypatch) -> None:
    import local_shell_mcp.settings as settings_module

    monkeypatch.setattr(settings_module.sys, "frozen", False, raising=False)
    assert settings_module._default_workspace_root() == Path("/workspace")


def test_webui_module_import_does_not_require_sqlite_extension() -> None:
    """Even a broken SQLite Python build must permit explicit file-mode recovery."""
    import subprocess
    import sys

    code = (
        'import sys;sys.modules["sqlite3"]=None;'
        'import local_shell_mcp.webui.routes;'
        'import local_shell_mcp.webui.storage;'
        'import local_shell_mcp.webui.auth;'
        'import local_shell_mcp.webui.frontend;'
        'print("ok")'
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_file_backend_recovery_starts_when_sqlite_module_is_missing(tmp_path: Path) -> None:
    """Operators can recover controller configuration without a SQLite build."""
    import os
    import subprocess
    import sys

    code = (
        'import sys;sys.modules["sqlite3"]=None;'
        'from local_shell_mcp.settings import get_settings;'
        'from local_shell_mcp.webui import routes,auth,frontend;'
        'print(get_settings().state_backend)'
    )
    env = {
        **os.environ,
        "LOCAL_SHELL_MCP_STATE_BACKEND": "file",
        "LOCAL_SHELL_MCP_AUTH_MODE": "none",
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT": str(tmp_path),
        "LOCAL_SHELL_MCP_STATE_DIR": str(tmp_path / ".local-shell-mcp"),
    }
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "file"
    assert not (tmp_path / ".local-shell-mcp" / DB_NAME).exists()


def test_empty_append_is_safe(tmp_path: Path) -> None:
    store = SQLiteStateStore(tmp_path)
    assert store.append_bytes("audit.jsonl", b"") == 0
    assert store.read_bytes("audit.jsonl") == b""
    assert store.append_bytes("audit.jsonl", b"x") == 1
    assert store.size_bytes("audit.jsonl") == 1
