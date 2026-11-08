"""SQLite generation lease, event replay and authenticated native React SSE."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import generation_routes, routes
from local_shell_mcp.webui.generations import GenerationConflict, GenerationStore
from local_shell_mcp.webui.providers import ProviderConfig


@pytest.fixture
def database(tmp_path):
    return SQLiteDatabase(tmp_path / ".local-shell-mcp")


def test_generation_transaction_and_event_replay(database):
    store = GenerationStore(database)
    job, fresh = store.begin("alice", {
        "conversationId": "new", "clientRequestId": "turn-1", "text": "你好",
        "endpoint": "agents", "model": "test-model", "messageId": "user-1",
    })
    assert fresh is True
    assert job.status == "running"
    assert job.generation_created_at > 0
    same, fresh = store.begin("alice", {
        "conversationId": "new", "clientRequestId": "turn-1", "text": "你好"
    })
    assert not fresh
    assert same.run_id == job.run_id
    assert len(store.history("alice", job.conversation_id)) == 1
    with pytest.raises(GenerationConflict):
        store.begin("alice", {"conversationId": job.conversation_id, "text": "duplicate"})
    store.append("alice", job.run_id, {"event": "on_run_step", "data": {"id": "step-1"}})
    store.append("alice", job.run_id, {"event": "on_message_delta", "data": {"delta": {"text": "世界"}}})
    rows = store.events("alice", job.run_id)
    assert [data.get("event", "created") for _, data in rows] == ["created", "on_run_step", "on_message_delta"]
    assert len(store.events("alice", job.run_id, rows[1][0])) == 1
    assert store.finish("alice", job.run_id, status="complete", text="世界")
    assert not store.finish("alice", job.run_id, status="complete", text="duplicate")
    assert store.latest("alice", job.conversation_id).status == "complete"
    assert store.latest("bob", job.conversation_id) is None
    assert store.get("bob", job.run_id) is None
    assert store.history("alice", job.conversation_id)[-1]["content"] == "世界"
    assert store.events("alice", job.run_id)[-1][1]["final"] is True
    assert store.recover_orphans() == 0


def test_generation_rejects_bad_prompt_and_keeps_clean_database(database):
    store = GenerationStore(database)
    with pytest.raises(ValueError):
        store.begin("alice", {"text": ""})
    with pytest.raises(ValueError):
        store.begin("alice", {"text": "abc", "clientRequestId": "z" * 300})
    with database.connect() as conn:
        assert conn.execute("SELECT count(*) FROM conversations").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_crashed_generation_is_marked_interrupted_and_replayable(database):
    store = GenerationStore(database)
    job, _ = store.begin("alice", {"text": "a pending question"})
    store.append("alice", job.run_id, {"event": "on_message_delta", "data": {"text": "partial"}})
    assert store.recover_orphans() == 1
    assert store.recover_orphans() == 0
    assert store.latest("alice", job.conversation_id).status == "interrupted"
    assert store.events("alice", job.run_id)[-1][1]["final"] is True
    assert store.events("alice", job.run_id)[-1][1]["error"]


@pytest.mark.asyncio
async def test_streaming_generation_http_reconnect_and_token_isolation(database, monkeypatch):
    # Load native modules before replacing the settings accessor: imports in
    # those modules otherwise retain the test lambda after monkeypatch undo.
    from local_shell_mcp import settings as settings_module
    from local_shell_mcp import tools  # noqa: F401
    settings = settings_module.Settings(state_dir=database.root, workspace_root=database.root,
                                        auth_mode="oauth")

    monkeypatch.setattr(settings_module, "get_settings", lambda: settings)
    monkeypatch.setattr(routes, "get_settings", lambda: settings)

    async def fake_stream(profile, messages, **kwargs):
        assert profile.token == "model-secret"
        assert messages[-1]["content"] == "Hello"
        for fragment in ("Hi", " there"):
            await asyncio.sleep(0.01)
            yield fragment

    monkeypatch.setattr(generation_routes, "stream_model_with_tools", fake_stream)
    monkeypatch.setattr(generation_routes, "provider_config",
                        lambda kind, model: ProviderConfig("openai", model or "test", "https://test.invalid", "model-secret"))
    app = Starlette(routes=generation_routes.generation_routes())

    async def authenticated(scope, receive, send):
        if scope.get("type") == "http":
            principal = next((v.decode() for k, v in scope.get("headers", []) if k == b"x-test-owner"), None)
            if principal:
                scope.setdefault("state", {})["principal"] = SimpleNamespace(subject=principal)
        await app(scope, receive, send)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=authenticated), base_url="http://lsm") as client:
        alice, bob = {"x-test-owner": "alice"}, {"x-test-owner": "bob"}
        assert (await client.post("/api/agents/chat", json={"text": "Hello"})).status_code == 401
        start = await client.post("/api/agents/chat", headers=alice, json={
            "conversationId": "new", "text": "Hello", "model": "test", "clientRequestId": "first"
        })
        assert start.status_code == 202, start.text
        identity = start.json()
        assert identity["generationProtocolVersion"] == 2
        cid = identity["conversationId"]
        assert (await client.get(f"/api/agents/chat/status/{cid}", headers=bob)).json()["active"] is False
        other = await client.get(f"/api/agents/chat/stream/{cid}", headers=bob)
        assert other.status_code == 404
        stream = await client.get(f"/api/agents/chat/stream/{cid}", headers=alice)
        assert stream.status_code == 200, stream.text
        assert stream.headers["x-librechat-generation-protocol"] == "2"
        events = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")]
        assert events[0]["created"] is True
        assert events[1]["event"] == "on_run_step"
        assert [event["data"]["delta"]["content"]["text"] for event in events if event.get("event") == "on_message_delta"] == ["Hi", " there"]
        assert events[-1]["responseMessage"]["text"] == "Hi there"
        assert events[-1]["final"] is True
        assert (await client.get(f"/api/agents/chat/status/{cid}", headers=alice)).json()["status"] == "complete"
        replay = await client.get(f"/api/agents/chat/stream/{cid}", headers=alice, params={"after": 2})
        assert replay.status_code == 200
        assert "on_message_delta" in replay.text
        assert (await client.get(f"/api/agents/chat/stream/{cid}", headers=alice,
                                 params={"generationCreatedAt": "1"})).status_code == 409
    await generation_routes.shutdown_generations()
