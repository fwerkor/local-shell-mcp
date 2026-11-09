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
    original = Path.read_bytes

    def interrupted(path):
        if path == last:
            raise PermissionError("simulated failure after first import")
        return original(path)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_bytes", interrupted)
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
