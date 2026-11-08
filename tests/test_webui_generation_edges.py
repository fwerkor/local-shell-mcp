"""Generation start, replay, interruption and identity-fencing error contracts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.webui import generation_routes, routes
from local_shell_mcp.webui.providers import ProviderConfig


@pytest.fixture
def configured_generation_routes(tmp_path, monkeypatch):
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
