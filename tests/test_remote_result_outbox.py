"""Regression tests for durable remote-result delivery limits and failures."""

import asyncio
import json

import pytest

from local_shell_mcp import remote
from local_shell_mcp.settings import get_settings


@pytest.fixture
def outbox(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_RESULT_OUTBOX_DIR", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


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


@pytest.mark.parametrize("tool", ["shell_start", "run_shell_tool", "run_shell_persist_tool", "run_python_persist_tool"])
async def test_spooled_result_retains_reset_generation_and_mutation_preservation(
    outbox, monkeypatch, tool
):
    async def execute(*args):
        return {"done": True}

    monkeypatch.setattr(remote, "_execute_worker_job_with_heartbeat", execute)
    await remote._run_worker_job(
        {"id": "reset-result", "tool": tool, "args": {}, "reset_generation": 3},
        "https://controller.test",
        {},
        0.005,
    )
    path = next(outbox.glob("*.json"))
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["reset_generation"] == 3
    assert bool(persisted.get("preserve_across_reset")) == (tool != "run_shell_tool")
    attempts = 0

    def post(url, payload, headers=None, timeout=None):
        nonlocal attempts
        if url.endswith("/result"):
            attempts += 1
            if attempts < 3:
                raise RuntimeError("temporary result upload failure")
            return {"ok": True, "data": {"accepted": True}}
        return {"ok": True, "data": {"accepted": True, "reset_generation": 4}}

    monkeypatch.setattr(remote, "_worker_post_json", post)
    monkeypatch.setattr(remote, "_WORKER_RETRY_INITIAL_DELAY_S", 0.02)
    monkeypatch.setattr(remote, "_WORKER_RETRY_MAX_DELAY_S", 0.02)
    in_progress = set()
    sender = asyncio.create_task(
        remote._worker_result_outbox_sender("https://controller.test", {}, 0.005, in_progress)
    )

    async def wait_until_drained():
        while path.exists() or in_progress:
            await asyncio.sleep(0.01)

    try:
        # Native Windows runners can spend multiple seconds in worker IO
        # scheduling. Wait for a real drained outbox instead of assuming that
        # three retries must always fit within three wall-clock seconds.
        await asyncio.wait_for(wait_until_drained(), 20)
    finally:
        sender.cancel()
        with pytest.raises(asyncio.CancelledError):
            await sender
    assert attempts == 3 if tool != "run_shell_tool" else attempts < 3


async def test_invalid_outbox_entry_does_not_block_valid_results(outbox, monkeypatch):
    broken = outbox / "000-invalid.json"
    broken.write_text("{}", encoding="utf-8")
    valid = remote._worker_store_result_outbox({"job_id": "healthy"})

    async def submit(result, *args):
        assert result["job_id"] == "healthy"
        return {"ok": True, "data": {"accepted": True}}

    monkeypatch.setattr(remote, "_submit_worker_result_with_heartbeat", submit)
    sender = asyncio.create_task(
        remote._worker_result_outbox_sender("https://controller.test", {}, 1, set())
    )
    try:
        async def wait_until_drained():
            while valid.exists():
                await asyncio.sleep(0.01)
        await asyncio.wait_for(wait_until_drained(), 5)
        assert broken.exists()
    finally:
        sender.cancel()
        with pytest.raises(asyncio.CancelledError):
            await sender


async def test_missing_ack_does_not_delete_outbox_result(outbox, monkeypatch):
    path = remote._worker_store_result_outbox({"job_id": "not-acknowledged"})
    failure = asyncio.Event()

    async def submit(*args):
        return {"ok": True, "data": {}}

    monkeypatch.setattr(remote, "_submit_worker_result_with_heartbeat", submit)
    monkeypatch.setattr(remote, "_worker_log_retry", lambda *args: failure.set())
    sender = asyncio.create_task(
        remote._worker_result_outbox_sender("https://controller.test", {}, 1, set())
    )
    try:
        await asyncio.wait_for(failure.wait(), 3)
        assert path.exists()
    finally:
        sender.cancel()
        with pytest.raises(asyncio.CancelledError):
            await sender


def test_concurrent_spooling_respects_item_limit(outbox, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    monkeypatch.setattr(remote, "REMOTE_WORKER_RESULT_OUTBOX_MAX_ITEMS", 1)
    barrier = Barrier(4)

    def spool(index):
        barrier.wait(timeout=5)
        try:
            remote._worker_store_result_outbox({"job_id": str(index)})
            return True
        except RuntimeError as exc:
            assert "outbox is full" in str(exc)
            return False

    with ThreadPoolExecutor(max_workers=4) as executor:
        assert sum(executor.map(spool, range(4))) == 1
    assert len(list(outbox.glob("*.json"))) == 1
