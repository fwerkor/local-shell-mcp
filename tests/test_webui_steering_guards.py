"""Guard and authorization cases for the source-compatible durable steer queue."""

from __future__ import annotations

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


@pytest.mark.asyncio
async def test_http_abort_returns_and_preserves_unapplied_steers(context):
    generations, steering, job, _ = context
    queued = _enqueue(steering, job, cid="pending-abort", text="A follow-up to keep")
    app = Starlette(routes=generation_routes.generation_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                base_url="http://test") as client:
        stopped = await client.post("/api/agents/chat/abort", json={
            "conversationId": job.conversation_id,
            "generationCreatedAt": job.generation_created_at,
        })
        assert stopped.status_code == 200, stopped.text
        assert [s["steerId"] for s in stopped.json()["pendingSteers"]] == [queued["steerId"]]
        assert generations.latest("local", job.conversation_id).status == "aborted"
        replay = await client.post("/api/agents/chat/steer/deliver", json={
            "conversationId": job.conversation_id,
            "generationCreatedAt": job.generation_created_at,
            "clientSteerId": "pending-abort", "text": "A follow-up to keep",
        })
        assert replay.status_code == 202 and replay.json()["replayed"]
        assert replay.json()["leftover"] is True
        again = await client.post("/api/agents/chat/abort", json={
            "conversationId": job.conversation_id,
        })
        assert again.status_code == 409


@pytest.mark.asyncio
async def test_steer_http_requires_current_machine_grants_and_agent_ownership(context, monkeypatch):
    from local_shell_mcp.webui import machine_permissions
    from local_shell_mcp.webui.agents import AgentRepository

    generations, steering, job, _ = context
    app = Starlette(routes=generation_routes.generation_routes())
    monkeypatch.setattr(machine_permissions, "resolve_access", lambda *_: {"local": "write"})
    monkeypatch.setattr(generation_routes, "_request_grant", lambda _request: (frozenset(), None))
    payload = {"conversationId": job.conversation_id, "text": "Trying to steer", "clientSteerId": "guard"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                base_url="http://test") as client:
        blocked = await client.post("/api/agents/chat/steer", json=payload)
        assert blocked.status_code == 403 and blocked.json()["code"] == "FORBIDDEN"
        assert steering.pending("local", job.run_id) == []
        monkeypatch.setattr(generation_routes, "_request_grant", lambda _request: (
            frozenset({"shell:read", "shell:write"}), None,
        ))
        permitted = await client.post("/api/agents/chat/steer", json=payload)
        assert permitted.status_code == 202, permitted.text
        assert steering.pending("local", job.run_id)[0]["text"] == "Trying to steer"
        # A subsequent generation using a deleted private Agent cannot be
        # re-steered merely by guessing its conversation id.
        assert generations.finish("local", job.run_id, status="complete")
        repo = AgentRepository(steering.database)
        private = repo.create("local", {"name": "private", "provider": "openAI", "model": "stub"})
        next_run, _ = generations.begin("local", {
            "conversationId": job.conversation_id, "text": "New task",
        }, private)
        repo.delete("local", private["id"])
        denied = await client.post("/api/agents/chat/steer", json={
            "conversationId": next_run.conversation_id,
            "text": "Do something", "clientSteerId": "new-attempt",
        })
        assert denied.status_code == 403 and denied.json()["code"] == "FORBIDDEN"


def test_applied_steer_is_replayed_after_crash_before_checkpoint_without_duplicates(context):
    from local_shell_mcp.webui.agent_runner import AgentRunner
    from local_shell_mcp.webui.agent_runtime import AgentContext, AgentLoopState
    from local_shell_mcp.webui.providers import ProviderConfig

    generations, steering, job, _ = context
    first = _enqueue(steering, job, 'recovery-1', 'Use the new direction')
    second = _enqueue(steering, job, 'recovery-2', 'Use the new direction')
    assert len(steering.drain('local', job.run_id, boundary='terminal')) == 2
    assert first['steerId'] != second['steerId']
    reopened = SQLiteDatabase(steering.database.root)
    profile = ProviderConfig('openai', 'fake', 'https://example.invalid', '')

    async def fake_stream(*args, **kwargs):
        yield 'model response'

    async def noop(_):
        return None

    runner = AgentRunner('local', job, reopened, GenerationStore(reopened),
                         scopes=set(), grant_expires=None, stream_tools=fake_stream,
                         stream_text=fake_stream, on_text=noop, profile=profile)
    # The graph checkpoint predates drain(), while the durable run-state
    # receipt already says applied. The instruction must still reach the model.
    state = AgentLoopState(AgentContext(profile, []), [{'role': 'user', 'content': 'original'}])
    runner._reconcile_drained_steers(state)
    assert [m['content'] for m in state.messages if m.get('source') == 'steer'] == [
        'Use the new direction', 'Use the new direction']
    runner._reconcile_drained_steers(state)
    assert len([m for m in state.messages if m.get('source') == 'steer']) == 2


def test_steer_identity_recovery_does_not_consume_identical_prior_turn(context):
    from local_shell_mcp.webui.agent_runner import AgentRunner
    from local_shell_mcp.webui.agent_runtime import AgentContext, AgentLoopState
    from local_shell_mcp.webui.providers import ProviderConfig

    generations, steering, job, _ = context
    db = generations.database
    ack = _enqueue(steering, job, 'new-receipt', 'Be concise')
    assert len(steering.drain('local', job.run_id, boundary='terminal')) == 1
    profile = ProviderConfig('openai', 'stub', 'https://example.invalid', '')
    runner = AgentRunner('local', job, db, generations, scopes=set(), grant_expires=None,
                         stream_tools=None, stream_text=None, on_text=None, profile=profile)
    state = AgentLoopState(AgentContext(profile, []), [
        {'role': 'user', 'content': 'Be concise', 'source': 'steer', 'steerId': 'older-run'},
        {'role': 'user', 'content': 'Current query'},
    ])
    runner._reconcile_drained_steers(state)
    assert [msg['steerId'] for msg in state.messages if msg.get('source') == 'steer'] == [
        'older-run', ack['steerId']]
    runner._reconcile_drained_steers(state)
    assert len([msg for msg in state.messages if msg.get('steerId') == ack['steerId']]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('recovery_steers', [False, True])
async def test_post_tool_crash_recovered_steer_follows_cached_tool_result(context, recovery_steers):
    from local_shell_mcp.webui.agent_runner import AgentRunner
    from local_shell_mcp.webui.agent_runtime import AgentContext, AgentLoopState, ToolBatchOutput
    from local_shell_mcp.webui.providers import ModelToolCall

    generations, steering, job, profile = context
    db = generations.database
    pending = ModelToolCall('call-pending', 'run_shell', {'command': 'echo done'})
    original = [{'role': 'user', 'content': 'Run command'},
                {'role': 'assistant', 'content': None, 'tool_calls': [
                    {'id': 'call-pending', 'type': 'function',
                     'function': {'name': 'run_shell', 'arguments': '{"command":"echo done"'}}]}]

    async def unused(*args, **kwargs):
        yield 'done'

    async def noop(_):
        return None

    before = AgentRunner('local', job, db, generations, scopes=set(), grant_expires=None,
                         stream_tools=unused, stream_text=unused, on_text=noop, profile=profile)
    state = AgentLoopState(AgentContext(profile, []), original,
                           step=2, pending_calls=[pending], tool_step_started=True)
    before.saver.put(before.config, {
        'v': 1, 'id': '00000000000000000001',
        'channel_values': before._snapshot(state),
        'channel_versions': {'messages': 2}, 'versions_seen': {},
    }, {'source': 'loop', 'step': 2})
    new = _enqueue(steering, job, 'crash-recovery', 'Change next reply')
    assert steering.drain('local', job.run_id, boundary='post_tools')[0]['steerId'] == new['steerId']
    presented = []

    async def model(_profile, messages, **kwargs):
        presented.extend(messages)
        yield 'All finished.'

    resumed = AgentRunner('local', job, db, generations, scopes=set(), grant_expires=None,
                          stream_tools=model, stream_text=model, on_text=noop, profile=profile,
                          recovery_steers=recovery_steers)

    async def dispatch(_calls, _state):
        return ToolBatchOutput([{'role': 'tool', 'tool_call_id': 'call-pending', 'content': 'done'}])

    resumed._dispatch = dispatch
    await resumed.run(original)
    roles = [msg['role'] for msg in presented]
    assert roles[:4] == ['user', 'assistant', 'tool', 'user']
    assert presented[3]['steerId'] == new['steerId']


@pytest.mark.asyncio
async def test_preempt_cancelled_during_provider_close_cannot_finalize_partial_answer():
    from local_shell_mcp.webui.agent_runtime import (
        AgentContext,
        AgentLoopState,
        ToolBatchOutput,
        run_agent_loop,
    )
    from local_shell_mcp.webui.providers import ProviderConfig

    still_queued = [True]
    invocations = []
    texts = []

    class Stream:
        def __init__(self, index):
            self.index = index
            self.emitted = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.emitted:
                raise StopAsyncIteration
            self.emitted = True
            return 'Partial' if self.index == 0 else ' continued.'

        async def aclose(self):
            if self.index == 0:
                # Cancellation wins the race after seal but before drain.
                still_queued[0] = False

    def stream(*args, **kwargs):
        invocations.append(list(args[1]))
        return Stream(len(invocations) - 1)

    async def text(value):
        texts.append(value)

    async def preempt():
        return still_queued[0]

    async def drain(_state, boundary):
        assert boundary in {'stream', 'terminal'}
        return False

    async def dispatch(_calls, _state):
        return ToolBatchOutput([])

    profile = ProviderConfig('openai', 'test', 'https://example.invalid', '')
    state = AgentLoopState(AgentContext(profile, []), [{'role': 'user', 'content': 'Write a reply'}])
    final = await run_agent_loop(state, stream_tools=stream, stream_text=stream,
                                 dispatch=dispatch, on_text=text, on_boundary=drain,
                                 on_stream_chunk=preempt)
    assert len(invocations) == 2
    assert texts == ['Partial', ' continued.']
    assert final[-1]['content'] == ' continued.'
    assert final[-2]['content'] == 'Partial'


def test_replayed_tool_completion_keeps_steer_index_equal_to_snapshot(context):
    generations, steering, job, _ = context
    generations.append('local', job.run_id, {'event': 'on_message_delta', 'data': {
        'id': 'intro', 'delta': {'content': {'type': 'text', 'text': 'Before'}}}})
    completion = {'event': 'on_run_step_completed', 'data': {'result': {
        'id': 'tool-step-one', 'type': 'tool_call',
        'tool_call': {'id': 'call-1', 'name': 'read', 'output': 'ready'}}}}
    generations.append('local', job.run_id, completion)
    generations.append('local', job.run_id, completion)
    before, _ = generations.resume_snapshot('local', job.run_id)
    assert [part['type'] for part in before['aggregatedContent']] == ['text', 'tool_call']
    queued = _enqueue(steering, job, 'replayed-completion', 'Interpret the result')
    assert steering.drain('local', job.run_id, boundary='post_tools')[0]['steerId'] == queued['steerId']
    events = [e['data'] for _, e in generations.events('local', job.run_id)
              if e.get('event') == 'on_steer_applied']
    assert events[-1]['index'] == len(before['aggregatedContent']) == 2
    current, _ = generations.resume_snapshot('local', job.run_id)
    assert current['aggregatedContent'][2]['steerId'] == queued['steerId']
