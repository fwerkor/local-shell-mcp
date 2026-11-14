"""Deterministic regressions for upload publication versus stale-intent recovery."""

from __future__ import annotations

import asyncio
import multiprocessing
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.exceptions import HTTPException

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import attachments


@pytest.fixture
def database(tmp_path, monkeypatch):
    db = SQLiteDatabase(tmp_path)
    monkeypatch.setattr(attachments, "_repo", lambda: SimpleNamespace(database=db))
    return db


async def chunks():
    yield b"published bytes"


def _recovery_worker(state_dir, output):
    try:
        database = SQLiteDatabase(Path(state_dir))
        output.put(attachments.recover_attachment_uploads(database))
    except Exception as exc:
        output.put(repr(exc))


@pytest.mark.asyncio
async def test_reclaimed_aged_upload_must_not_commit_dangling_file_row(database):
    processing = threading.Event()
    release = threading.Event()

    def slow_processing(*_):
        processing.set()
        assert release.wait(10), "test processor unexpectedly stalled"
        return {"extracted_text": "published bytes"}

    task = asyncio.create_task(attachments.publish_attachment(
        "alice", "race.txt", "text/plain", chunks(), database.root,
        file_id="race", process=slow_processing,
    ))
    try:
        assert await asyncio.to_thread(processing.wait, 10)
        with database.connect() as sql:
            sql.execute("UPDATE attachment_uploads SET created_at=0 WHERE file_id='race'")
        context = multiprocessing.get_context("spawn")
        output = context.Queue()
        process = context.Process(target=_recovery_worker, args=(str(database.root), output))
        process.start()
        process.join(timeout=20)
        assert process.exitcode == 0
        reclaimed = output.get(timeout=5)
        assert reclaimed == {"cleanedFileIds": ["race"], "retainedFileIds": []}
    finally:
        release.set()
    with pytest.raises(HTTPException) as error:
        await task
    assert error.value.status_code == 500
    with database.connect() as sql:
        assert sql.execute("SELECT count(*) FROM attachments WHERE id='race'").fetchone()[0] == 0
        assert sql.execute("SELECT count(*) FROM attachment_uploads WHERE file_id='race'").fetchone()[0] == 0
    assert not list((database.root / "attachments").rglob("*-race.txt"))


def test_publication_under_lock_wins_over_concurrent_recovery(database):
    committing = threading.Event()
    release = threading.Event()
    recovery_started = threading.Event()

    def binder(sql, _file_id):
        # The publisher holds the cross-process advisory lock and SQLite write lock here.
        assert sql.execute("SELECT 1 FROM attachment_uploads WHERE file_id='winner'").fetchone()
        committing.set()
        assert release.wait(10), "test transaction unexpectedly stalled"

    def publish():
        return asyncio.run(attachments.publish_attachment(
            "alice", "winner.txt", "text/plain", chunks(), database.root,
            file_id="winner", bind=binder,
        ))

    def recover():
        recovery_started.set()
        return attachments.recover_attachment_uploads(database, grace_seconds=-3600)

    with ThreadPoolExecutor(max_workers=2) as executor:
        publisher = executor.submit(publish)
        try:
            assert committing.wait(10)
            recovering = executor.submit(recover)
            assert recovery_started.wait(10)
        finally:
            release.set()
        record = publisher.result(timeout=15)
        outcome = recovering.result(timeout=15)
    assert outcome == {"cleanedFileIds": [], "retainedFileIds": []}
    assert Path(record["path"]).read_bytes() == b"published bytes"
    with database.connect() as sql:
        assert sql.execute("SELECT count(*) FROM attachments WHERE id='winner'").fetchone()[0] == 1
        assert sql.execute("SELECT count(*) FROM attachment_uploads").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_processor_that_alters_uploaded_content_is_not_published(database):
    def mutate_file(path, *_):
        Path(path).write_bytes(b"modified bytes!")
        return {"extracted_text": "forged"}

    with pytest.raises(HTTPException) as error:
        await attachments.publish_attachment(
            "alice", "mutated.txt", "text/plain", chunks(), database.root,
            file_id="mutated", process=mutate_file,
        )
    assert error.value.status_code == 500
    with database.connect() as sql:
        assert sql.execute("SELECT count(*) FROM attachments WHERE id='mutated'").fetchone()[0] == 0
    assert not list((database.root / "attachments").rglob("*-mutated.txt"))
