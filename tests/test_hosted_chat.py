from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from local_shell_mcp import hosted_chat
from local_shell_mcp.hosted_chat_store import HostedChatRunner, HostedChatStore
from local_shell_mcp.settings import get_settings


@pytest.fixture(autouse=True)
def isolated_workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def chat_store(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "file")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.delenv("LOCAL_SHELL_MCP_HOSTED_CHAT_ENCRYPTION_KEY", raising=False)
    get_settings.cache_clear()
    yield HostedChatStore(prefix="hosted-chat-test")
    get_settings.cache_clear()


def test_profiles_are_encrypted_durable_and_scoped(chat_store, tmp_path):
    profile = chat_store.put_profile(
        "alice",
        {
            "name": "My Model",
            "model": "unit-test-model",
            "endpoint": "https://model.example.test/v1",
            "api_key": "ultra-secret-api-key",
        },
    )
    assert "api_key" not in profile and "encrypted_key" not in profile
    key = chat_store._key("alice", "profiles", profile["id"])
    raw = (tmp_path / "state" / key).read_bytes()
    assert b"ultra-secret-api-key" not in raw
    assert (
        chat_store.profile("alice", profile["id"], with_secret=True)["api_key"]
        == "ultra-secret-api-key"
    )
    reloaded = HostedChatStore(prefix="hosted-chat-test")
    assert reloaded.profiles("alice")[0]["model"] == "unit-test-model"
    assert reloaded.profiles("bob") == []
    with pytest.raises(ValueError):
        reloaded.profile("bob", profile["id"])
    if os.name != "nt":
        assert (tmp_path / "state" / "hosted-chat-encryption-key").stat().st_mode & 0o777 == 0o600
    reloaded.put_profile("alice", {**profile, "name": "Renamed", "api_key": ""})
    assert (
        reloaded.profile("alice", profile["id"], with_secret=True)["api_key"]
        == "ultra-secret-api-key"
    )


def test_chat_history_durable_no_truncation(chat_store):
    profile = chat_store.put_profile(
        "alice",
        {
            "name": "Testing",
            "model": "model",
            "endpoint": "https://example.net/v1",
            "api_key": "secret",
        },
    )
    record = chat_store.create_conversation("alice", profile_id=profile["id"], session_id="s_123")
    record = chat_store.update_conversation(
        "alice",
        record["id"],
        updater=lambda r: {
            **r,
            "messages": [{"role": "user", "content": f"Message {i}"} for i in range(101)],
        },
    )
    assert (
        len(
            HostedChatStore(prefix="hosted-chat-test").conversation("alice", record["id"])[
                "messages"
            ]
        )
        == 101
    )
    assert chat_store.conversations("alice")[0]["id"] == record["id"]
    assert "messages" not in chat_store.conversations("alice")[0]
    assert not chat_store.conversations("bob")
    with pytest.raises(ValueError):
        chat_store.conversation("bob", record["id"])
    chat_store.delete_conversation("alice", record["id"])
    with pytest.raises(ValueError):
        chat_store.conversation("alice", record["id"])


def test_endpoint_validation():
    assert hosted_chat.validate_endpoint("https://example.net/v1/") == "https://example.net/v1"
    for endpoint in (
        "http://model.example/v1",
        "https://localhost:8000/v1",
        "https://user:pass@example.com/v1",
        "https://127.0.0.1/v1",
        "https://example.com/v1?token=secret",
    ):
        with pytest.raises(ValueError):
            hosted_chat.validate_endpoint(endpoint)


@pytest.mark.asyncio
async def test_tool_call_loop_preserves_results_but_not_private_metadata(monkeypatch):
    responses = iter(
        [
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "run_shell",
                                        "arguments": '{"command":"echo hi"}',
                                    },
                                },
                            ],
                        }
                    }
                ]
            },
            {"choices": [{"message": {"content": "Done", "role": "assistant"}}]},
        ]
    )
    calls = []
    checkpoints = []

    class FakeTool:
        def model_dump(self, **_):
            return {
                "name": "run_shell",
                "description": "Run command",
                "inputSchema": {"type": "object", "properties": {"command": {"type": "string"}}},
            }

    class FakeResult:
        isError = False

        def model_dump(self, **_):
            return {
                "content": [{"type": "text", "text": "hi"}],
                "_meta": {"local-shell-mcp/live": {"token": "sensitive-live-token"}},
            }

    class FakeMcp:
        async def list_tools(self):
            return SimpleNamespace(tools=[FakeTool()])

        async def call_tool(self, name, arguments, **kwargs):
            calls.append((name, arguments))
            return FakeResult()

    @asynccontextmanager
    async def fake_mcp(*_):
        yield FakeMcp()

    class FakeHttp:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, *args, **kwargs):
            return SimpleNamespace(status_code=200, json=lambda: next(responses))

    async def checkpoint(messages, events):
        checkpoints.append((json.loads(json.dumps(messages)), list(events)))

    monkeypatch.setattr(hosted_chat, "mcp_session", fake_mcp)
    monkeypatch.setattr(hosted_chat.httpx, "AsyncClient", lambda **_: FakeHttp())
    result = await hosted_chat.complete_turn(
        base_url="http://localhost:9999",
        bearer="",
        endpoint="https://example.net/v1",
        key="dummy-key",
        model="test-model",
        messages=[{"role": "user", "content": "Do something"}],
        tools_enabled=True,
        session_id="s_123",
        checkpoint=checkpoint,
    )
    assert result["messages"][-1]["content"] == "Done"
    assert calls == [("run_shell", {"command": "echo hi", "logical_session_id": "s_123"})]
    assert result["events"][0]["result"]["content"][0]["text"] == "hi"
    assert "sensitive-live-token" not in json.dumps(result)
    assert "sensitive-live-token" not in json.dumps(checkpoints)
    assert checkpoints[-1][0][-1]["content"] == "Done"


@pytest.mark.asyncio
async def test_background_runner_checkpoints_survive_restart(chat_store, monkeypatch):
    from local_shell_mcp import hosted_chat_store as module

    monkeypatch.setattr(module, "hosted_chat_store", chat_store)
    runner = HostedChatRunner()
    profile = chat_store.put_profile(
        "alice",
        {
            "name": "Test",
            "model": "model",
            "endpoint": "https://example.net/v1",
            "api_key": "secret",
        },
    )
    chat = chat_store.create_conversation("alice", profile_id=profile["id"])

    async def fake_turn(*, messages, checkpoint, **_):
        await checkpoint([*messages, {"role": "assistant", "content": "persisted"}], [])
        return {}

    monkeypatch.setattr(hosted_chat, "complete_turn", fake_turn)
    started = await runner.start("alice", chat["id"], "Hello", "http://localhost:8765", "")
    assert started["status"] == "running"
    await asyncio.sleep(0.15)
    after = chat_store.conversation("alice", chat["id"])
    assert after["status"] == "idle"
    assert after["messages"][-1]["content"] == "persisted"
    assert after["messages"][0]["content"] == "Hello"


def test_hosted_chat_http_api_persists_profiles_and_history(chat_store, monkeypatch):
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    from local_shell_mcp.human_ui import ui_routes

    monkeypatch.setenv("LOCAL_SHELL_MCP_HOSTED_CHAT_ENABLED", "true")
    get_settings.cache_clear()
    with TestClient(Starlette(routes=ui_routes())) as client:
        profile = client.post(
            "/api/ui/hosted-chat/profile-save",
            json={
                "name": "Secure profile",
                "endpoint": "https://model.example.net/v1",
                "model": "model-1",
                "api_key": "private-key-not-exposed",
            },
        )
        assert profile.status_code == 200, profile.text
        public = profile.json()["data"]
        assert public["name"] == "Secure profile"
        assert "private-key-not-exposed" not in profile.text
        assert "private-key-not-exposed" not in client.get("/api/ui/hosted-chat/profiles").text

        chat = client.post(
            "/api/ui/hosted-chat/conversation-create",
            json={
                "profile_id": public["id"],
            },
        )
        assert chat.status_code == 200, chat.text
        cid = chat.json()["data"]["id"]
        details = client.get(f"/api/ui/hosted-chat/conversation?id={cid}")
        assert details.json()["data"]["messages"] == []
        response = client.post(
            "/api/ui/hosted-chat/conversation-update",
            json={
                "id": cid,
                "title": "Permanent conversation",
            },
        )
        assert response.json()["data"]["title"] == "Permanent conversation"
        listing = client.get("/api/ui/hosted-chat/conversations")
        assert listing.json()["data"][0]["title"] == "Permanent conversation"
        assert client.get("/api/ui/hosted-chat/conversation?id=c_notmine").status_code == 400
        assert (
            client.post("/api/ui/hosted-chat/conversation-delete", json={"id": cid}).status_code
            == 200
        )


def test_hosted_chat_disabled_by_default_and_rejects_ephemeral_state(chat_store, monkeypatch):
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    from local_shell_mcp.human_ui import ui_routes

    with TestClient(Starlette(routes=ui_routes())) as client:
        assert client.get("/api/ui/hosted-chat/profiles").status_code == 404
    monkeypatch.setenv("LOCAL_SHELL_MCP_HOSTED_CHAT_ENABLED", "true")
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "memory")
    get_settings.cache_clear()
    with TestClient(Starlette(routes=ui_routes())) as client:
        assert client.get("/api/ui/hosted-chat/profiles").status_code == 503
