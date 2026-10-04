"""Regression tests for durable remote-result delivery limits and failures."""

import asyncio
import json

import pytest

from local_shell_mcp import remote


@pytest.fixture
def outbox(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_RESULT_OUTBOX_DIR", str(tmp_path))
    return tmp_path


@pytest.mark.parametrize("limit", ["items", "bytes"])
def test_full_outbox_rejects_new_results_but_allows_existing_result_update(
    outbox, monkeypatch, limit
):
    original = {"job_id": "one", "data": "finished"}
    path = remote._worker_store_result_outbox(original)
    if limit == "items":
        monkeypatch.setattr(remote, "REMOTE_WORKER_RESULT_OUTBOX_MAX_ITEMS", 1)
    else:
        monkeypatch.setattr(remote, "REMOTE_WORKER_RESULT_OUTBOX_MAX_BYTES", path.stat().st_size)
    with pytest.raises(RuntimeError, match="outbox"):
        remote._worker_store_result_outbox({"job_id": "two", "data": "new"})
    updated = {**original, "lifecycle": {"result_submit_started_at": 123}}
    assert remote._worker_store_result_outbox(updated) == path
    assert json.loads(path.read_text(encoding="utf-8")) == updated
    assert list(outbox.glob("*.json")) == [path]
    assert not list(outbox.glob("*.tmp.*"))


def test_outbox_requires_job_id_before_creating_file(outbox):
    with pytest.raises(ValueError, match="job id"):
        remote._worker_store_result_outbox({"data": "orphan"})
    assert list(outbox.iterdir()) == []


@pytest.mark.parametrize("failure", ["read", "submit", "timing"])
async def test_sender_preserves_result_and_releases_claim_after_failure(
    outbox, monkeypatch, failure
):
    path = remote._worker_store_result_outbox({"job_id": "one", "lifecycle": {}})
    if failure == "read":
        path.write_text("[]", encoding="utf-8")
    reached_failure = asyncio.Event()
    logs = []
    in_progress = set()

    def log(operation, error, delay):
        logs.append((operation, str(error)))
        reached_failure.set()

    async def submit(*args):
        if failure == "submit":
            raise ConnectionError("controller offline")
        await asyncio.Event().wait()

    def store_result(result):
        raise OSError("disk unavailable")

    monkeypatch.setattr(remote, "_worker_log_retry", log)
    monkeypatch.setattr(remote, "_submit_worker_result_with_heartbeat", submit)
    if failure == "timing":
        monkeypatch.setattr(remote, "_worker_store_result_outbox", store_result)
    sender = asyncio.create_task(
        remote._worker_result_outbox_sender("https://controller.test", {}, 1, in_progress)
    )
    try:
        await asyncio.wait_for(reached_failure.wait(), 2)
    finally:
        sender.cancel()
        with pytest.raises(asyncio.CancelledError):
            await sender
    assert path.exists()
    assert not in_progress
    expected = {
        "read": "read result outbox",
        "submit": "result outbox submit",
        "timing": "update result outbox timing",
    }
    assert logs[0][0] == expected[failure]


async def test_sender_discards_result_rejected_by_controller(outbox, monkeypatch):
    path = remote._worker_store_result_outbox({"job_id": "expired"})
    discarded = []
    in_progress = set()

    async def submit(*args):
        return {"data": {"accepted": False}}

    monkeypatch.setattr(remote, "_submit_worker_result_with_heartbeat", submit)
    monkeypatch.setattr(remote, "audit", lambda event, **data: discarded.append((event, data)))
    sender = asyncio.create_task(
        remote._worker_result_outbox_sender("https://controller.test", {}, 1, in_progress)
    )

    async def wait_until_drained():
        while path.exists() or in_progress:
            await asyncio.sleep(0.01)

    try:
        await asyncio.wait_for(wait_until_drained(), 2)
    finally:
        sender.cancel()
        with pytest.raises(asyncio.CancelledError):
            await sender
    assert discarded == [("remote_result_outbox_discarded", {"job_id": "expired"})]
    assert not path.exists()
    assert not in_progress
