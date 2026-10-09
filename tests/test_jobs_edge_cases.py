from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from edge_case_support import _FakeHandle, _MemoryStateStore

import local_shell_mcp.jobs as jobs_module


def test_jobs_nonfile_store_recovers_and_rejects_invalid_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(jobs_module, "audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        jobs_module, "get_settings", lambda: SimpleNamespace(state_backend="memory")
    )
    valid = (
        '{"version":' + str(jobs_module.JOB_STORE_VERSION) + ',"jobs":[{"job_id":"ok"}]}'
    ).encode()

    store = _MemoryStateStore(
        {
            jobs_module.JOB_STORE_FILE_NAME: b"[]",
            jobs_module.JOB_STORE_BACKUP_FILE_NAME: valid,
        }
    )
    monkeypatch.setattr(jobs_module, "get_state_store", lambda: store)
    assert jobs_module._load_store()["jobs"] == [{"job_id": "ok"}]

    store.values = {
        jobs_module.JOB_STORE_FILE_NAME: b'{"version":999,"jobs":[]}',
        jobs_module.JOB_STORE_BACKUP_FILE_NAME: (
            '{"version":' + str(jobs_module.JOB_STORE_VERSION) + ',"jobs":"bad"}'
        ).encode(),
    }
    with pytest.raises(RuntimeError, match="unreadable"):
        jobs_module._load_store()

    store.values = {
        jobs_module.JOB_STORE_FILE_NAME: None,
        jobs_module.JOB_STORE_BACKUP_FILE_NAME: valid,
    }
    assert jobs_module._load_store()["jobs"] == [{"job_id": "ok"}]

def test_jobs_remove_attempt_files_stateless_keeps_requested_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _MemoryStateStore(
        {
            "job-logs/job_x/1.log": b"1",
            "job-logs/job_x/2.log": b"2",
            "job-logs/job_x/3.log": b"3",
        }
    )
    monkeypatch.setattr(
        jobs_module, "get_settings", lambda: SimpleNamespace(stateless_controller=True)
    )
    monkeypatch.setattr(jobs_module, "get_state_store", lambda: store)
    jobs_module._remove_attempt_files("job_x", keep_attempt=2)
    assert store.deleted == ["job-logs/job_x/1.log", "job-logs/job_x/3.log"]

def test_jobs_windows_lock_helpers_and_contention(monkeypatch: pytest.MonkeyPatch) -> None:
    modes: list[int] = []

    class FakeMsvcrt:
        LK_NBLCK = 3
        LK_UNLCK = 4

        @staticmethod
        def locking(fd: int, mode: int, count: int) -> None:
            assert (fd, count) == (7, 1)
            modes.append(mode)

    monkeypatch.setitem(sys.modules, "msvcrt", FakeMsvcrt)
    monkeypatch.setattr(jobs_module.os, "name", "nt")
    handle = _FakeHandle()
    assert jobs_module._try_lock_store_file(handle) is True
    jobs_module._unlock_store_file(handle)
    assert modes == [3, 4]

    class ContendedMsvcrt(FakeMsvcrt):
        @staticmethod
        def locking(fd: int, mode: int, count: int) -> None:
            raise OSError(11, "busy")

    monkeypatch.setitem(sys.modules, "msvcrt", ContendedMsvcrt)
    assert jobs_module._try_lock_store_file(handle) is False

    class BrokenMsvcrt(FakeMsvcrt):
        @staticmethod
        def locking(fd: int, mode: int, count: int) -> None:
            raise OSError(5, "broken")

    monkeypatch.setitem(sys.modules, "msvcrt", BrokenMsvcrt)
    with pytest.raises(OSError):
        jobs_module._try_lock_store_file(handle)

def test_jobs_idempotency_scans_malformed_and_conflicting_records() -> None:
    fingerprint = "fp"
    key_hash = jobs_module._idempotency_key_hash("key")
    job = {
        "job_id": "j",
        "idempotency_requests": [
            "bad",
            {"action": "other", "key_hash": key_hash, "fingerprint": fingerprint},
            {"action": "retry", "key_hash": key_hash, "fingerprint": fingerprint},
        ],
    }
    store = {"jobs": [{"job_id": "skip", "idempotency_requests": "bad"}, job]}
    assert (
        jobs_module._find_idempotent_job(store, action="retry", key="key", fingerprint=fingerprint)
        is job
    )
    with pytest.raises(ValueError, match="different request"):
        jobs_module._find_idempotent_job(
            {
                "jobs": [
                    {
                        "idempotency_requests": [
                            {
                                "action": "retry",
                                "key_hash": key_hash,
                                "fingerprint": "different",
                            }
                        ]
                    }
                ]
            },
            action="retry",
            key="key",
            fingerprint=fingerprint,
        )

def test_jobs_read_log_tail_state_and_file_edges(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _MemoryStateStore({"job-logs/j/1.log": b"one\ntwo\nthree\n"})
    monkeypatch.setattr(jobs_module, "get_state_store", lambda: store)
    monkeypatch.setattr(
        jobs_module,
        "get_settings",
        lambda: SimpleNamespace(max_job_log_bytes=1024),
    )
    assert jobs_module._read_log_tail("state://job-logs/j/1.log", 2) == "two\nthree\n"
    assert jobs_module._read_log_tail(str(tmp_path / "missing.log"), 3) == ""
    log = tmp_path / "job.log"
    log.write_bytes(b"a\nb\nc\n")
    assert jobs_module._read_log_tail(str(log), 2) == "b\nc\n"

def test_jobs_managed_store_update_timeout_nonfile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextlib.contextmanager
    def busy_store():
        raise TimeoutError("busy")
        yield {}

    monkeypatch.setattr(jobs_module, "_store_transaction", busy_store)
    monkeypatch.setattr(jobs_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(jobs_module, "audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        jobs_module, "get_settings", lambda: SimpleNamespace(state_backend="memory")
    )
    with pytest.raises(TimeoutError, match="unable to update"):
        jobs_module._managed_store_update("update_progress", "job_x", {})
