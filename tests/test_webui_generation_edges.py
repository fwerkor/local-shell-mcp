"""Generation start, replay, interruption and identity-fencing error contracts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.webui import generation_routes, routes
from local_shell_mcp.webui.providers import ProviderConfig


@pytest.fixture(autouse=True)
def native_settings_environment(tmp_path, monkeypatch):
    # Native modules retain their imported accessor; configure its environment
    # as well as the endpoint accessor mocks, on non-root CI runners too.
    from local_shell_mcp.settings import get_settings

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def configured_generation_routes(tmp_path, monkeypatch):
    # FastMCP imports the settings accessor at module import. Never let a
    # process-wide mocked accessor escape this fixture via a lazy native import.
    import local_shell_mcp.tools  # noqa: F401
    from local_shell_mcp import settings as settings_module

    config = settings_module.Settings(auth_mode="oauth", state_dir=tmp_path,
                                      workspace_root=tmp_path)
    monkeypatch.setattr(settings_module, "get_settings", lambda: config)
    monkeypatch.setattr(routes, "get_settings", lambda: config)
    monkeypatch.setattr(generation_routes, "provider_config",
                        lambda kind, model: ProviderConfig("openai", model or "local", "http://127.0.0.1:11434/v1/chat/completions", ""))
    app = Starlette(routes=generation_routes.generation_routes())

    async def principal(scope, receive, send):
        if scope.get("type") == "http":
            owner = next((v.decode() for k, v in scope.get("headers", []) if k == b"x-owner"), None)
            if owner:
                scope.setdefault("state", {})["principal"] = SimpleNamespace(subject=owner)
        await app(scope, receive, send)

    return principal


@pytest.mark.asyncio
async def test_generation_aborts_cancels_live_task_and_enforces_epoch(configured_generation_routes, monkeypatch):
    began = asyncio.Event()
    held = asyncio.Event()

    async def slow_model(*_args, **_kwargs):
        began.set()
        yield "first "
        await held.wait()
        yield "second"

    monkeypatch.setattr(generation_routes, "stream_model_with_tools", slow_model)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=configured_generation_routes),
                                base_url="http://test") as client:
        alice, bob = {"x-owner": "alice"}, {"x-owner": "bob"}
        bad = await client.post("/api/agents/chat", headers=alice, json={"text": ""})
        assert bad.status_code == 400
        assert (await client.post("/api/agents/chat", headers=alice, json={"text": "Hello", "agent_id": "missing"})).status_code == 404
        assert (await client.post("/api/agents/chat", headers=alice,
                                  json={"text": "Hello", "conversationId": "missing"})).status_code == 404
        started = await client.post("/api/agents/chat/openAI", headers=alice,
                                    json={"text": "Stream forever", "conversationId": "new",
                                          "clientRequestId": "manual-test"})
        assert started.status_code == 202
        job = started.json()
        await asyncio.wait_for(began.wait(), 5)
        cid = job["conversationId"]
        assert (await client.get("/api/agents/chat/active", headers=alice)).json()["activeJobIds"] == [cid]
        assert (await client.get("/api/agents/chat/active", headers=bob)).json()["activeJobIds"] == []
        assert (await client.get(f"/api/agents/chat/status/{cid}", headers=alice)).json()["active"] is True
        assert (await client.post("/api/agents/chat/resume", headers=bob,
                                  json={"conversationId": cid})).status_code == 404
        assert (await client.post("/api/agents/chat/resume", headers=alice,
                                  json={"conversationId": cid})).json()["status"] == "resumed"
        assert (await client.post("/api/agents/chat", headers=alice,
                                  json={"text": "again", "conversationId": cid})).status_code == 409
        same = await client.post("/api/agents/chat", headers=alice,
                                 json={"text": "Stream forever", "clientRequestId": "manual-test"})
        assert same.status_code == 202
        assert same.json()["status"] == "resumed"
        assert (await client.get(f"/api/agents/chat/stream/{cid}", headers=bob)).status_code == 404
        assert (await client.get(f"/api/agents/chat/stream/{cid}", headers=alice,
                                 params={"generationCreatedAt": "not-integer"})).status_code == 400
        assert (await client.get(f"/api/agents/chat/stream/{cid}", headers=alice,
                                 params={"generationCreatedAt": 1})).status_code == 409
        assert (await client.get(f"/api/agents/chat/stream/{cid}", headers=alice,
                                 params={"after": "invalid"})).status_code == 400
        assert (await client.post("/api/agents/chat/abort", headers=alice, json={})).status_code == 400
        assert (await client.post("/api/agents/chat/abort", headers=alice,
                                  json={"conversationId": cid, "generationCreatedAt": -1})).status_code == 409
        assert (await client.post("/api/agents/chat/abort", headers=bob,
                                  json={"conversationId": cid})).status_code == 404
        aborted = await client.post("/api/agents/chat/abort", headers=alice,
                                    json={"conversationId": cid, "generationCreatedAt": job["generationCreatedAt"]})
        assert aborted.status_code == 200
        for _ in range(50):
            if (await client.get(f"/api/agents/chat/status/{cid}", headers=alice)).json()["status"] == "aborted":
                break
            await asyncio.sleep(0.01)
        assert (await client.get(f"/api/agents/chat/status/{cid}", headers=alice)).json()["status"] == "aborted"
        assert (await client.post("/api/agents/chat/resume", headers=alice,
                                  json={"conversationId": cid})).status_code == 409
        events = generation_routes._generation_store().events("alice", generation_routes._generation_store().latest("alice", cid).run_id)
        assert events[-1][1]["aborted"] is True
        assert (await client.post("/api/agents/chat/resume", headers=alice, json={})).status_code == 400
        assert (await client.post("/api/agents/chat/abort", headers=alice,
                                  json={"conversationId": "missing"})).status_code == 404
    held.set()
    await generation_routes.shutdown_generations()


@pytest.mark.asyncio
async def test_generation_model_failure_is_durable_and_redacted(configured_generation_routes, monkeypatch):
    async def broken_provider(*_args, **_kwargs):
        raise RuntimeError("Bearer secret-model-token")
        yield "never"  # pragma: no cover

    monkeypatch.setattr(generation_routes, "stream_model_with_tools", broken_provider)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=configured_generation_routes),
                                base_url="http://test") as client:
        alice = {"x-owner": "alice"}
        response = await client.post("/api/agents/chat", json={"text": "Will fail"}, headers=alice)
        assert response.status_code == 202
        cid = response.json()["conversationId"]
        for _ in range(60):
            status = (await client.get(f"/api/agents/chat/status/{cid}", headers=alice)).json()
            if status.get("status") == "error":
                break
            await asyncio.sleep(0.01)
        assert status["status"] == "error"
        recorded = generation_routes._generation_store().latest("alice", cid)
        events = generation_routes._generation_store().events("alice", recorded.run_id)
        assert events[-1][1]["final"] is True
        assert "secret-model-token" not in str(events)
        assert (await client.get("/api/agents/chat/active", headers=alice)).json()["activeJobIds"] == []
        terminal = await client.get(f"/api/agents/chat/stream/{cid}", headers=alice)
        assert terminal.status_code == 200
        assert "Model generation failed" in terminal.text
    await generation_routes.shutdown_generations()



@pytest.mark.asyncio
async def test_http_human_resume_claim_retry_and_identity_boundaries(
    configured_generation_routes, monkeypatch,
):
    """Source React resumes the original action and cannot swap Agent/model."""

    store = generation_routes._generation_store()
    job, _ = store.begin("alice", {"text": "Need a human decision", "model": "test"})
    pending = {
        "actionId": "ask-bound", "conversationId": job.conversation_id,
        "payload": {
            "type": "ask_user_question", "tool_call_id": "q1",
            "question": {"question": "Choose a format"},
        },
    }
    assert store.pause_for_question("alice", job.run_id, pending, [], "")
    started = []

    async def fake_start(*args, **kwargs):
        started.append((args, kwargs))

    monkeypatch.setattr(generation_routes, "_start_task", fake_start)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=configured_generation_routes),
                                base_url="http://test") as client:
        url = "/api/agents/chat/resume"
        user = {"x-owner": "alice"}
        body = {"conversationId": job.conversation_id, "actionId": "ask-bound", "answer": "markdown"}
        wrong_epoch = await client.post(url, json={**body, "generationCreatedAt": -1}, headers=user)
        assert wrong_epoch.status_code == 409
        wrong_agent = await client.post(url, json={**body, "agent_id": "substituted"}, headers=user)
        assert wrong_agent.status_code == 409
        wrong_model = await client.post(url, json={**body, "model": "different"}, headers=user)
        assert wrong_model.status_code == 409
        assert (await client.post(url, json=body, headers={"x-owner": "bob"})).status_code == 404
        first = await client.post(url, json=body, headers=user)
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "resuming"
        assert first.json()["generationCreatedAt"] == job.generation_created_at
        assert store.get("alice", job.run_id).status == "running"
        identical = await client.post(url, json=body, headers=user)
        assert identical.status_code == 200, identical.text
        assert identical.json()["status"] == "resuming"
        changed = await client.post(url, json={**body, "answer": "json"}, headers=user)
        assert changed.status_code == 400
        assert len(started) == 2
        assert started[0][1]["resume_history"] == started[1][1]["resume_history"]
        assert store.get("alice", job.run_id).status == "running"


@pytest.mark.asyncio
async def test_http_approval_restart_claim_and_expiration_routes(
    configured_generation_routes, monkeypatch,
):
    from local_shell_mcp.webui.approval_runtime import build_approval_payload
    from local_shell_mcp.webui.providers import ModelToolCall

    store = generation_routes._generation_store()
    job, _ = store.begin("alice", {"text": "Review a native call"})
    approval = {
        "actionId": "approval-bound", "conversationId": job.conversation_id,
        "payload": build_approval_payload([ModelToolCall("call-1", "plan_manage", {"action": "list"})]),
    }
    assert store.pause_for_approval("alice", job.run_id, approval, [], "")
    dispatched = []

    async def fake_start(*args, **kwargs):
        dispatched.append(kwargs.get("approved_batch"))

    monkeypatch.setattr(generation_routes, "_start_task", fake_start)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=configured_generation_routes),
                                base_url="http://test") as client:
        url = "/api/agents/chat/resume"
        headers = {"x-owner": "alice"}
        body = {"conversationId": job.conversation_id, "actionId": "approval-bound",
                "decisions": [{"tool_call_id": "call-1", "decision": "reject"}]}
        first = await client.post(url, json=body, headers=headers)
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "resuming"
        assert len(dispatched) == 1 and dispatched[0] is not None
        repeated = await client.post(url, json=body, headers=headers)
        assert repeated.status_code == 200, repeated.text
        assert len(dispatched) == 2
        assert dispatched[0].entries == dispatched[1].entries
        changed = await client.post(url, json={**body, "decisions": [
            {"tool_call_id": "call-1", "decision": "approve"},
        ]}, headers=headers)
        assert changed.status_code == 400

        expired, _ = store.begin("alice", {"text": "An expired question"})
        stale = {"actionId": "ask-expired", "expiresAt": 1, "payload": {
            "type": "ask_user_question", "tool_call_id": "q", "question": {"question": "Old?"}}}
        assert store.pause_for_question("alice", expired.run_id, stale, [], "")
        denied = await client.post(url, json={
            "conversationId": expired.conversation_id, "actionId": "ask-expired", "answer": "yes",
        }, headers=headers)
        assert denied.status_code == 409
        assert store.get("alice", expired.run_id).status == "interrupted"
        assert store.events("alice", expired.run_id)[-1][1]["final"]


@pytest.mark.asyncio
async def test_controller_reclaims_claimed_action_on_restart(configured_generation_routes, monkeypatch):
    """Startup recovery returns a claimed action to the original React card."""
    store = generation_routes._generation_store()
    job, _ = store.begin("alice", {"text": "Recover after restart"})
    pending = {"actionId": "ask-restart", "payload": {
        "type": "ask_user_question", "tool_call_id": "call-1",
        "question": {"question": "Choose?"}}}
    assert store.pause_for_question("alice", job.run_id, pending, [], "")
    store.answer_question("alice", job.run_id, "ask-restart", {"answer": "yes"})
    assert store.recover_claimed_resumes() == 1
    assert store.recover_orphans() == 0
    assert store.pending_action("alice", job.run_id) == pending
    assert store.recover_claimed_resumes() == 0
