"""Source-level steering contracts: durable FIFO receipts, React SSE and provider-bound delivery."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import generation_routes
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ProviderConfig
from local_shell_mcp.webui.steering import SteeringStore, SteerRejection


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    db = SQLiteDatabase(tmp_path / ".state")
    generations = GenerationStore(db)
    steering = SteeringStore(db)
    job, _ = generations.begin("local", {"text": "A question"})
    profile = ProviderConfig("openai", "mock", "http://localhost:8900/v1/chat/completions", "")
    monkeypatch.setattr(generation_routes, "_database", lambda: db)
    yield generations, steering, job, profile
    get_settings.cache_clear()


def _enqueue(steering, job, cid="stable-id", text="Try the new direction", **kw):
    return steering.enqueue("local", {
        "conversationId": job.conversation_id, "generationCreatedAt": job.generation_created_at,
        "text": text, "clientSteerId": cid, **kw,
    }, preempt_capable=True)


def test_steering_receipt_survives_duplicate_retry_and_terminal_replay(context):
    generations, steering, job, _ = context
    first = _enqueue(steering, job, preempt=True, quotes=["  excerpt  "])
    assert first["status"] == "queued" and first["preempt"] is True
    assert first["position"] == 1 and first["quotesAccepted"] is True
    assert steering.pending("local", job.run_id)[0]["quotes"] == ["excerpt"]
    second = _enqueue(steering, job, preempt=True, quotes=["  excerpt  "])
    assert second["steerId"] == first["steerId"] and second["replayed"]
    with pytest.raises(SteerRejection) as conflict:
        _enqueue(steering, job, preempt=True, text="Different content", quotes=["excerpt"])
    assert conflict.value.body["code"] == "STEER_IDEMPOTENCY_CONFLICT"
    assert steering.has_preempt("local", job.run_id)
    applied = steering.drain("local", job.run_id, boundary="stream")
    assert [item["steerId"] for item in applied] == [first["steerId"]]
    assert steering.pending("local", job.run_id) == []
    assert not steering.has_preempt("local", job.run_id)
    assert generations.finish("local", job.run_id, status="complete", text="Finished")
    replay = _enqueue(steering, job, preempt=True, quotes=["  excerpt  "])
    assert replay["settled"] is True and replay["replayed"] is True and not replay["leftover"]
    events = [value for _, value in generations.events("local", job.run_id)]
    injected = next(e["data"] for e in events if e.get("event") == "on_steer_applied")
    assert injected["part"]["type"] == "steer"
    assert injected["part"]["steer"] == "Try the new direction"
    final = events[-1]["responseMessage"]["content"]
    assert any(part.get("steerId") == first["steerId"] for part in final)
    state, _ = generations.resume_snapshot("local", job.run_id)
    assert any(part.get("steerId") == first["steerId"] for part in state["aggregatedContent"])


def test_cancel_arm_owner_epoch_and_terminal_leftovers(context):
    generations, steering, job, _ = context
    one = _enqueue(steering, job, "a", "First")
    two = _enqueue(steering, job, "b", "Second")
    with pytest.raises(SteerRejection) as invalid:
        steering.enqueue("local", {
            "conversationId": job.conversation_id, "generationCreatedAt": job.generation_created_at + 10,
            "text": "Third", "clientSteerId": "c",
        }, preempt_capable=True)
    assert invalid.value.body["code"] == "RUN_REPLACED"
    assert steering.pending("other-owner", job.run_id) == []
    arm = steering.mutate("local", {"conversationId": job.conversation_id,
                                   "generationCreatedAt": job.generation_created_at,
                                   "steerId": two["steerId"]}, arm=True, preempt_capable=True)
    assert arm == {"armed": True, "preemptRevision": 2}
    assert steering.pending("local", job.run_id)[1]["preempt"] is True
    denied = steering.mutate("local", {"conversationId": job.conversation_id,
                                      "steerId": one["steerId"]}, arm=True, preempt_capable=False)
    assert denied == {"armed": False, "code": "PREEMPT_UNSUPPORTED"}
    assert steering.mutate("local", {"conversationId": job.conversation_id,
                                    "steerId": one["steerId"]}, arm=False, preempt_capable=True)["removed"]
    assert steering.mutate("local", {"conversationId": job.conversation_id, "steerId": one["steerId"],
                                    "clientSteerId": "a"}, arm=False, preempt_capable=True)["replayed"]
    assert len(steering.pending("local", job.run_id)) == 1
    assert generations.finish("local", job.run_id, status="aborted")
    terminal = generations.events("local", job.run_id)[-1][1]
    assert [s["steerId"] for s in terminal["pendingSteers"]] == [two["steerId"]]
    assert _enqueue(steering, job, "b", "Second")["leftover"] is True


def test_atomic_parallel_enqueue_limit_no_duplicate_receipts(context):
    _, steering, job, _ = context

    def enqueue(index):
        try:
            return _enqueue(steering, job, f"id-{index % 12}", f"text-{index % 12}")
        except SteerRejection as error:
            return error.body["code"]

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(enqueue, range(60)))
    accepted = [value for value in results if isinstance(value, dict)]
    assert len({value["steerId"] for value in accepted}) <= 10
    assert set(value for value in results if isinstance(value, str)) <= {"STEER_QUEUE_FULL"}
    assert len(steering.pending("local", job.run_id)) == 10


@pytest.mark.asyncio
async def test_live_midstream_preempt_reaches_same_model_generation(context, monkeypatch):
    generations, steering, job, profile = context
    started, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def streaming(_profile, messages, **_kwargs):
        calls.append(list(messages))
        if len(calls) == 1:
            started.set()
            await release.wait()
            yield "Old partial."
            yield "Unwanted old continuation."
        else:
            assert messages[-1]["role"] == "user"
            assert messages[-1]["source"] == "steer"
            assert "Try the new direction" in messages[-1]["content"]
            yield "New direction acknowledged."
    monkeypatch.setattr(generation_routes, "stream_model_with_tools", streaming)
    task = asyncio.create_task(generation_routes._run_model("local", job, profile))
    await asyncio.wait_for(started.wait(), 4)
    queued = _enqueue(steering, job, preempt=True)
    assert queued["preempt"]
    release.set()
    await asyncio.wait_for(task, 8)
    assert generations.latest("local", job.conversation_id).status == "complete"
    assert len(calls) == 2
    final = generations.events("local", job.run_id)[-1][1]["responseMessage"]
    assert final["text"] == "Old partial.New direction acknowledged."
    assert "Unwanted old continuation." not in final["text"]
    assert any(part.get("steerId") == queued["steerId"] for part in final["content"])


@pytest.mark.asyncio
async def test_steer_http_rejects_paused_and_preserves_same_receipt(context):
    generations, steering, job, _ = context
    app = Starlette(routes=generation_routes.generation_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        body = {"conversationId": job.conversation_id, "generationCreatedAt": job.generation_created_at,
                "clientSteerId": "client-1", "text": "Correction", "preempt": False}
        first = await client.post("/api/agents/chat/steer", json=body)
        assert first.status_code == 202, first.text
        duplicate = await client.post("/api/agents/chat/steer", json=body)
        assert duplicate.status_code == 202 and duplicate.json()["replayed"]
        with pytest.raises(SteerRejection):
            _enqueue(steering, job, "client-1", "conflict")
        paused = {"actionId": "hold", "payload": {"type": "ask_user_question"}}
        assert generations.pause_for_question("local", job.run_id, paused, [], "")
        rejected = await client.post("/api/agents/chat/steer", json={
            **body, "clientSteerId": "client-2",
        })
        assert rejected.status_code == 409 and rejected.json()["code"] == "RUN_PAUSED"
        stopped = await client.post("/api/agents/chat/steer/cancel", json={
            "conversationId": job.conversation_id, "steerId": first.json()["steerId"],
        })
        assert stopped.status_code == 200 and stopped.json()["removed"]
        status = await client.get(f"/api/agents/chat/status/{job.conversation_id}")
        assert status.json()["resumeState"]["pendingSteers"] == []



@pytest.mark.asyncio
async def test_preempt_discards_uncommitted_model_tool_batch(context, monkeypatch):
    from local_shell_mcp.webui import lsm_tool_registry
    from local_shell_mcp.webui.providers import ModelToolCall

    generations, steering, job, profile = context
    calls = []
    dispatched = []

    async def fake_dispatch(*args, **kwargs):
        dispatched.append((args, kwargs))
        return "A forbidden prior tool side effect"

    async def provider(profile, messages, **kwargs):
        calls.append(list(messages))
        if len(calls) == 1:
            yield ModelToolCall("stale-tool", "plan_manage", {"action": "list"})
            _enqueue(steering, job, cid="new-intent", text="Do not run the old tools", preempt=True)
            yield "Old model response was interrupted."
            yield "This chunk must not appear."
        else:
            assert "Do not run the old tools" in messages[-1]["content"]
            yield "Continue safely after steering."

    monkeypatch.setattr(lsm_tool_registry, "call_tool", fake_dispatch)
    monkeypatch.setattr(generation_routes, "stream_model_with_tools", provider)
    await generation_routes._run_model("local", job, profile)
    assert not dispatched, "A tool from an incomplete preempted model turn executed"
    assert len(calls) == 2
    assert generations.latest("local", job.conversation_id).status == "complete"
    last = generations.events("local", job.run_id)[-1][1]
    assert "This chunk must not appear." not in last["responseMessage"]["text"]


@pytest.mark.asyncio
async def test_tool_only_provider_stream_can_be_preempted_before_dispatch(context, monkeypatch):
    """Provider SSE may emit only tool proposals, with no assistant text chunks."""
    from local_shell_mcp.webui import lsm_tool_registry
    from local_shell_mcp.webui.providers import ModelToolCall

    generations, steering, job, profile = context
    calls = []
    dispatched = []

    async def fake_dispatch(*args, **kwargs):
        dispatched.append((args, kwargs))
        return "A stale tool was executed"

    async def provider(profile, messages, **kwargs):
        calls.append(list(messages))
        if len(calls) == 1:
            yield ModelToolCall("stale-tool", "plan_manage", {"action": "list"})
            _enqueue(steering, job, cid="tool-only", text="Discard that tool", preempt=True)
            yield ModelToolCall("stale-tool2", "plan_manage", {"action": "list"})
        else:
            assert "Discard that tool" in messages[-1]["content"]
            yield "Preempting tool-only stream worked."

    monkeypatch.setattr(lsm_tool_registry, "call_tool", fake_dispatch)
    monkeypatch.setattr(generation_routes, "stream_model_with_tools", provider)
    await generation_routes._run_model("local", job, profile)
    assert not dispatched
    assert len(calls) == 2
    assert generations.latest("local", job.conversation_id).status == "complete"
    last = generations.events("local", job.run_id)[-1][1]["responseMessage"]
    assert last["text"] == "Preempting tool-only stream worked."


@pytest.mark.asyncio
async def test_final_provider_boundary_preempt_does_not_execute_proposals(context, monkeypatch):
    """Catch a late steer after the final SSE frame and before tool dispatch."""
    from local_shell_mcp.webui import lsm_tool_registry
    from local_shell_mcp.webui.providers import ModelToolCall

    generations, steering, job, profile = context
    calls = []
    dispatched = []

    async def fake_dispatch(*args, **kwargs):
        dispatched.append((args, kwargs))
        return "Executed stale tool"

    async def provider(profile, messages, **kwargs):
        calls.append(list(messages))
        if len(calls) == 1:
            yield ModelToolCall("tool-id", "plan_manage", {"action": "list"})
            # This code runs on the stream's next pull, after the previous
            # per-chunk preempt check, but before the end-of-stream check.
            _enqueue(steering, job, cid="late-steer", text="Late request", preempt=True)
        else:
            assert "Late request" in messages[-1]["content"]
            yield "Late steer acknowledged."

    monkeypatch.setattr(lsm_tool_registry, "call_tool", fake_dispatch)
    monkeypatch.setattr(generation_routes, "stream_model_with_tools", provider)
    await generation_routes._run_model("local", job, profile)
    assert not dispatched
    assert len(calls) == 2
    assert generations.latest("local", job.conversation_id).status == "complete"
    assert generations.events("local", job.run_id)[-1][1]["responseMessage"]["text"] == "Late steer acknowledged."
