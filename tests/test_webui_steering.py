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


@pytest.mark.parametrize(("overrides", "expected"), [
    ({"conversationId": "new"}, "INVALID_CONVERSATION"),
    ({"conversationId": ""}, "INVALID_CONVERSATION"),
    ({"text": ""}, "EMPTY_TEXT"),
    ({"text": "\x00  "}, "EMPTY_TEXT"),
    ({"text": "x" * 16001}, "STEER_TOO_LONG"),
    ({"clientSteerId": "has space"}, "INVALID_CLIENT_STEER_ID"),
    ({"clientSteerId": "x" * 129}, "INVALID_CLIENT_STEER_ID"),
    ({"files": {"file_id": "bad"}}, "INVALID_FILES"),
    ({"files": [{"file_id": ""}]}, "INVALID_FILES"),
    ({"files": [{}]}, "INVALID_FILES"),
    ({"files": [{"file_id": str(i)} for i in range(11)]}, "TOO_MANY_FILES"),
    ({"files": [{"file_id": "missing"}]}, "INVALID_FILES"),
    ({"generationCreatedAt": "bad"}, "INVALID_GENERATION_IDENTITY"),
])
def test_source_steer_guard_ladder(context, overrides, expected):
    _, steering, job, _ = context
    body = {"conversationId": job.conversation_id, "generationCreatedAt": job.generation_created_at,
            "clientSteerId": "valid-guard", "text": "Hello"}
    body.update(overrides)
    with pytest.raises(SteerRejection) as exc:
        steering.enqueue("local", body, preempt_capable=True)
    assert exc.value.body["code"] == expected


def test_owner_missing_active_paused_and_terminal_denials(context):
    generations, steering, job, _ = context
    body = {"conversationId": job.conversation_id, "clientSteerId": "id", "text": "Hello"}
    with pytest.raises(SteerRejection) as other:
        steering.enqueue("other-owner", body, preempt_capable=True)
    assert other.value.body["code"] == "NO_ACTIVE_RUN"
    with pytest.raises(SteerRejection) as unknown:
        steering.enqueue("local", {**body, "conversationId": "missing"}, preempt_capable=True)
    assert unknown.value.body["code"] == "NO_ACTIVE_RUN"
    queued_before_pause = _enqueue(steering, job, "before-pause", "Queued first")
    assert generations.pause_for_question("local", job.run_id, {"actionId": "hold"}, [], "")
    assert steering.mutate("local", {
        "conversationId": job.conversation_id, "steerId": queued_before_pause["steerId"],
    }, arm=True, preempt_capable=True) == {"armed": False, "code": "PREEMPT_UNSUPPORTED"}
    with pytest.raises(SteerRejection) as paused:
        steering.enqueue("local", body, preempt_capable=True)
    assert paused.value.body["code"] == "RUN_PAUSED"
    assert generations.finish("local", job.run_id, status="aborted")
    with pytest.raises(SteerRejection) as done:
        steering.enqueue("local", body, preempt_capable=True)
    assert done.value.body["code"] == "NO_ACTIVE_RUN"


def test_non_idempotent_ordinary_steer_and_strict_delivery(context):
    generations, steering, job, _ = context
    body = {"conversationId": job.conversation_id, "text": "an ordinary steer"}
    with pytest.raises(SteerRejection) as strict:
        steering.enqueue("local", body, preempt_capable=True, strict_delivery=True)
    assert strict.value.body["code"] == "CLIENT_STEER_ID_REQUIRED"
    ack = steering.enqueue("local", body, preempt_capable=False)
    assert ack["preempt"] is False and "clientSteerId" not in ack
    assert steering.mutate("local", {"conversationId": job.conversation_id, "steerId": ack["steerId"]},
                           arm=False, preempt_capable=True)["removed"]
    another = steering.enqueue("local", {**body, "preempt": True}, preempt_capable=False)
    assert another["preempt"] is False
    assert steering.drain("local", job.run_id, boundary="stream") == []
    assert steering.drain("local", job.run_id, boundary="terminal")[0]["steerId"] == another["steerId"]
    assert generations.finish("local", job.run_id, status="complete")


def test_receipt_survives_replaced_generation_but_not_other_owner(context):
    generations, steering, job, _ = context
    ack = _enqueue(steering, job)
    assert generations.finish("local", job.run_id, status="complete")
    next_run, _ = generations.begin("local", {"conversationId": job.conversation_id,
                                             "text": "next run", "parentMessageId": job.user_message_id})
    assert next_run.run_id != job.run_id
    replay = _enqueue(steering, job)
    assert replay["steerId"] == ack["steerId"]
    assert replay["replayed"] and replay["leftover"]
    canceled = steering.mutate("local", {
        "conversationId": job.conversation_id, "generationCreatedAt": job.generation_created_at,
        "clientSteerId": "stable-id", "steerId": ack["steerId"],
    }, arm=False, preempt_capable=True)
    assert canceled == {"removed": True, "replayed": True}
    assert _enqueue(steering, job)["settled"]
    with pytest.raises(SteerRejection) as old:
        steering.enqueue("local", {"conversationId": job.conversation_id,
                                   "generationCreatedAt": job.generation_created_at,
                                   "clientSteerId": "another-id", "text": "new text"},
                         preempt_capable=True)
    assert old.value.body["code"] == "RUN_REPLACED"
    with pytest.raises(SteerRejection) as unauthorized:
        steering.enqueue("intruder", {"conversationId": job.conversation_id, "text": "peek",
                                      "clientSteerId": "stable-id"}, preempt_capable=True)
    assert unauthorized.value.body["code"] == "NO_ACTIVE_RUN"


def test_cancel_arm_mutation_failures_and_legacy_races(context):
    generations, steering, job, _ = context
    for body, expected in [
        ({"conversationId": "new", "steerId": "s"}, "INVALID_CONVERSATION"),
        ({"conversationId": job.conversation_id}, "INVALID_STEER_ID"),
        ({"conversationId": job.conversation_id, "steerId": "s",
          "generationCreatedAt": "invalid"}, "INVALID_GENERATION_IDENTITY"),
        ({"conversationId": job.conversation_id, "steerId": "s",
          "generationCreatedAt": job.generation_created_at + 100}, "RUN_REPLACED"),
    ]:
        with pytest.raises(SteerRejection) as exc:
            steering.mutate("local", body, arm=False, preempt_capable=True)
        assert exc.value.body["code"] == expected
    assert steering.mutate("bob", {"conversationId": job.conversation_id, "steerId": "s"},
                           arm=True, preempt_capable=True) == {"armed": False}
    assert steering.mutate("local", {"conversationId": job.conversation_id, "steerId": "s"},
                           arm=True, preempt_capable=True) == {"armed": False}
    one = _enqueue(steering, job, "a", "Hello", preempt=True)
    assert steering.mutate("local", {"conversationId": job.conversation_id,
                                    "steerId": one["steerId"]}, arm=True, preempt_capable=True) == {"armed": False}
    assert steering.drain("local", job.run_id, boundary="stream")
    assert steering.mutate("local", {"conversationId": job.conversation_id,
                                    "steerId": one["steerId"]}, arm=False, preempt_capable=True) == {"removed": False}
    assert generations.finish("local", job.run_id, status="complete")
    assert steering.mutate("local", {"conversationId": job.conversation_id,
                                    "steerId": "absent"}, arm=False, preempt_capable=True) == {"removed": False}


def test_fifo_applied_events_indexes_quotes_and_followup_history(context):
    generations, steering, job, _ = context
    first = _enqueue(steering, job, "a", "First", quotes=[42, "", "  quote\n2  "] +
                     [""] * 11 + ["last"])
    second = _enqueue(steering, job, "b", "Second")
    assert steering.drain("local", job.run_id, boundary="post_tools")
    assert generations.finish("local", job.run_id, status="complete", text="")
    events = [value["data"] for _, value in generations.events("local", job.run_id)
              if value.get("event") == "on_steer_applied"]
    assert [x["steerId"] for x in events] == [first["steerId"], second["steerId"]]
    assert [x["index"] for x in events] == [0, 1]
    history = generations.history("local", job.conversation_id, message_id=job.response_message_id)
    assert [item["source"] for item in history if item.get("source")] == ["steer", "steer"]
    assert "quote" in next(item["content"] for item in history if item.get("source") == "steer")
    snapshot, _ = generations.resume_snapshot("local", job.run_id)
    assert [p["steerId"] for p in snapshot["aggregatedContent"]] == [
        first["steerId"], second["steerId"],
    ]


def test_steer_receipt_limit_and_expired_receipt_cleanup(context):
    import json

    from local_shell_mcp.webui.storage import _json

    _, steering, job, _ = context
    with steering.database.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT state FROM runs WHERE id=?", (job.run_id,)).fetchone()
        state = json.loads(row["state"])
        state["steering"] = {"queue": [], "receipts": {
            f"id-{i}": {"state": "queued", "expiresAt": 9999999999999} for i in range(100)
        }}
        db.execute("UPDATE runs SET state=? WHERE id=?", (_json(state), job.run_id))
    with pytest.raises(SteerRejection) as full:
        _enqueue(steering, job, cid="extra")
    assert full.value.body["code"] == "STEER_RECEIPT_LIMIT"
    with steering.database.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT state FROM runs WHERE id=?", (job.run_id,)).fetchone()
        state = json.loads(row["state"])
        state["steering"]["receipts"]["id-0"]["state"] = "applied"
        state["steering"]["receipts"]["id-0"]["expiresAt"] = 1
        db.execute("UPDATE runs SET state=? WHERE id=?", (_json(state), job.run_id))
    assert _enqueue(steering, job, cid="extra")["status"] == "queued"


@pytest.mark.asyncio
async def test_http_ordinary_and_strict_delivery_routes(context):
    _, _, job, _ = context
    app = Starlette(routes=generation_routes.generation_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        base = {"conversationId": job.conversation_id, "text": "No receipt"}
        strict = await client.post("/api/agents/chat/steer/deliver", json=base)
        assert strict.status_code == 400 and strict.json()["code"] == "CLIENT_STEER_ID_REQUIRED"
        regular = await client.post("/api/agents/chat/steer", json=base)
        assert regular.status_code == 202
        arm = await client.post("/api/agents/chat/steer/arm", json={
            "conversationId": job.conversation_id, "steerId": regular.json()["steerId"],
        })
        assert arm.status_code == 200 and arm.json()["armed"]
        bad = await client.post("/api/agents/chat/steer/arm", json={"conversationId": "new"})
        assert bad.status_code == 400 and bad.json()["code"] == "INVALID_CONVERSATION"
