"""Released file-state cutover preserves committed SQLite decisions on retry."""
from pathlib import Path

import pytest

from local_shell_mcp.sqlite_store import SQLiteStateStore, shared_database


def test_deleted_destination_is_not_revived_by_changed_legacy_file(tmp_path):
    path = tmp_path / "jobs.json"
    path.write_bytes(b"released jobs v1")
    state = SQLiteStateStore(tmp_path)
    state.delete("jobs.json")
    path.write_bytes(b"old controller continued writing v2")
    shared_database.cache_clear()
    reopened = SQLiteStateStore(tmp_path)
    assert reopened.read_bytes("jobs.json") is None
    assert reopened.migrate_files() == 0
    assert path.read_bytes() == b"old controller continued writing v2"
    with reopened.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM legacy_imports WHERE key='jobs.json'").fetchone()[0] == 1
    # Even an oversized obsolete writer cannot block startup after deletion.
    with path.open("wb") as handle:
        handle.truncate(65 * 1024 * 1024)
    assert reopened.migrate_files() == 0
    reopened.write_bytes("jobs.json", b"new controller recreated state")
    path.write_bytes(b"old controller v3")
    assert reopened.migrate_files() == 0
    assert reopened.read_bytes("jobs.json") == b"new controller recreated state"


def test_interrupted_multi_file_cutover_rolls_back_rows_and_journal_before_restart(tmp_path, monkeypatch):
    first = tmp_path / "a-jobs.json"
    last = tmp_path / "z-workers.json"
    first.write_bytes(b"jobs-before-upgrade")
    last.write_bytes(b"workers-before-upgrade")
    state = SQLiteStateStore(tmp_path, migrate_files=False)
    state.write_bytes("sqlite-only.json", b"authoritative")
    import os
    original = os.open

    def interrupted(path, *args, **kwargs):
        if Path(path) == last:
            raise PermissionError("simulated failure after first import")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", interrupted)
        with pytest.raises(PermissionError, match="after first import"):
            state.migrate_files()
    assert state.read_bytes("a-jobs.json") is None
    assert state.read_bytes("sqlite-only.json") == b"authoritative"
    with state.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM legacy_imports").fetchone()[0] == 0
    shared_database.cache_clear()
    restarted = SQLiteStateStore(tmp_path)
    assert restarted.read_bytes("a-jobs.json") == first.read_bytes()
    assert restarted.read_bytes("z-workers.json") == last.read_bytes()
    assert restarted.read_bytes("sqlite-only.json") == b"authoritative"
    assert restarted.migrate_files() == 0


def test_large_released_audit_import_is_bounded_and_survives_restart(tmp_path):
    import hashlib
    import tracemalloc

    archive = tmp_path / "audit-archive" / "released-audit.jsonl.zst"
    archive.parent.mkdir()
    size = 65 * 1024 * 1024 + 17
    with archive.open("wb") as source:
        source.truncate(size)
    state = SQLiteStateStore(tmp_path, migrate_files=False)
    tracemalloc.start()
    try:
        assert state.migrate_files() == 1
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 12 * 1024 * 1024
    assert archive.stat().st_size == size
    assert state.size_bytes("audit-archive/released-audit.jsonl.zst") == size
    with state.database.connect() as db:
        digest = hashlib.sha256()
        digest.update(db.execute("SELECT value FROM state").fetchone()[0])
        for row in db.execute("SELECT value FROM state_append_chunks ORDER BY id"):
            assert len(row[0]) <= 1024 * 1024
            digest.update(row[0])
        journal = db.execute("SELECT imported_digest,source_size FROM legacy_imports").fetchone()
        assert journal[0] == digest.hexdigest()
        assert journal[1] == size
    shared_database.cache_clear()
    reopened = SQLiteStateStore(tmp_path)
    assert reopened.migrate_files() == 0
    assert reopened.size_bytes("audit-archive/released-audit.jsonl.zst") == size


def test_streamed_import_refreshes_whole_value_but_keeps_sqlite_appends(tmp_path, monkeypatch):
    from local_shell_mcp import sqlite_store

    monkeypatch.setattr(sqlite_store, "_LEGACY_CHUNK_BYTES", 4)
    legacy = tmp_path / "audit.jsonl"
    legacy.write_bytes(b"released-first-log")
    state = SQLiteStateStore(tmp_path)
    assert state.read_bytes("audit.jsonl") == b"released-first-log"
    legacy.write_bytes(b"released-second-log-with-more-bytes")
    assert state.migrate_files() == 1
    assert state.read_bytes("audit.jsonl") == b"released-second-log-with-more-bytes"
    assert state.size_bytes("audit.jsonl") == len(b"released-second-log-with-more-bytes")
    state.append_bytes("audit.jsonl", b"live-controller")
    legacy.write_bytes(b"stale-old-controller-write")
    assert state.migrate_files() == 0
    assert state.read_bytes("audit.jsonl") == b"released-second-log-with-more-byteslive-controller"


def test_stream_chunk_write_failure_rolls_back_and_can_retry(tmp_path, monkeypatch):
    import sqlite3

    from local_shell_mcp import sqlite_store

    monkeypatch.setattr(sqlite_store, "_LEGACY_CHUNK_BYTES", 4)
    (tmp_path / "a-jobs.json").write_bytes(b"jobs")
    (tmp_path / "z-audit.jsonl").write_bytes(b"first-second-third")
    state = SQLiteStateStore(tmp_path, migrate_files=False)
    with state.database.connect() as db:
        db.execute("CREATE TRIGGER fail_chunk BEFORE INSERT ON state_append_chunks "
                   "BEGIN SELECT RAISE(ABORT,'simulated disk write rejection'); END")
    with pytest.raises(sqlite3.IntegrityError, match="disk write rejection"):
        state.migrate_files()
    with state.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM state").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM state_append_chunks").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM legacy_imports").fetchone()[0] == 0
        db.execute("DROP TRIGGER fail_chunk")
    shared_database.cache_clear()
    recovered = SQLiteStateStore(tmp_path)
    assert recovered.read_bytes("a-jobs.json") == b"jobs"
    assert recovered.read_bytes("z-audit.jsonl") == b"first-second-third"
    assert recovered.size_bytes("z-audit.jsonl") == len(b"first-second-third")


@pytest.mark.parametrize("phase", ["before_open", "during_read"])
def test_changing_legacy_snapshot_aborts_whole_import_and_retries(tmp_path, monkeypatch, phase):
    import os
    from types import SimpleNamespace

    legacy = tmp_path / "released.json"
    legacy.write_bytes(b"stable-before-read")
    state = SQLiteStateStore(tmp_path, migrate_files=False)
    original = os.fstat
    calls = 0

    def changing(fd):
        nonlocal calls
        calls += 1
        info = original(fd)
        if phase == "before_open" and calls == 1:
            return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino,
                                   st_size=info.st_size, st_mtime_ns=info.st_mtime_ns + 1)
        if phase == "during_read" and calls == 2:
            with legacy.open("ab") as writer:
                writer.write(b"-concurrent-old-writer")
            return original(fd)
        return info

    with monkeypatch.context() as patch:
        patch.setattr(os, "fstat", changing)
        with pytest.raises(RuntimeError, match="changed during import"):
            state.migrate_files()
    assert state.read_bytes("released.json") is None
    with state.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM legacy_imports").fetchone()[0] == 0
    assert state.migrate_files() == 1
    assert state.read_bytes("released.json") == legacy.read_bytes()
