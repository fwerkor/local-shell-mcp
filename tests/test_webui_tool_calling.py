"""Function-call streaming, owner-scoped native tools and deny-by-default policy."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui import generation_routes, misc_routes, routes
from local_shell_mcp.webui.native_tools import _execute, _path, run_machine_tool
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig, stream_model_with_tools


def _mock_sse(monkeypatch, frames):
    original = httpx.AsyncClient
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, text="\n\n".join(frames) + "\n\n", headers={"content-type": "text/event-stream"})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    return captured


@pytest.mark.asyncio
async def test_openai_fragmented_function_call_stream(monkeypatch):
    sent = _mock_sse(monkeypatch, [
        'data: {"choices":[{"delta":{"content":"Checking ","tool_calls":[{"index":0,"id":"call_0","function":{"name":"file_","arguments":"{\\"path\\":\\""}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"list","arguments":".\\"}"}}]}}]}',
        'data: [DONE]',
    ])
    profile = ProviderConfig("openai", "local", "http://127.0.0.1:11434/v1/chat/completions", "")
    tools = [{"type": "function", "function": {"name": "file_list"}}]
    result = [item async for item in stream_model_with_tools(profile, [{"role": "user", "content": "ls"}], tools=tools)]
    assert result == ["Checking ", ModelToolCall("call_0", "file_list", {"path": "."})]
    body = json.loads(sent[0].content)
    assert body["tools"] == tools
    assert body["parallel_tool_calls"] is False
    assert "authorization" not in sent[0].headers


@pytest.mark.asyncio
@pytest.mark.parametrize("frames,message", [
    (['data: {"choices":[{"delta":{"tool_calls":[{"index":5,"id":"a"}]}}]}'], "index"),
    (['data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call","function":{"name":"file_list","arguments":"{broken"}}]}}]}'], "JSON"),
    (['data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call","function":{"name":"file_list","arguments":"[1,2]"}}]}}]}'], "object"),
    (['data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"file_list","arguments":"{}"}}]}}]}'], "Incomplete"),
])
async def test_invalid_model_tool_calls_do_not_dispatch(monkeypatch, frames, message):
    _mock_sse(monkeypatch, frames)
    profile = ProviderConfig("openai", "mock", "https://api.example.test/chat/completions", "secret")
    with pytest.raises(ValueError, match=message):
        [item async for item in stream_model_with_tools(profile, [], tools=[{"type": "function"}])]


def test_workspace_read_only_tool_paths_and_output_limits(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "file.txt").write_text("hello world")
    (root / "directory").mkdir()
    (root / "large.txt").write_bytes(b"x" * 10000)
    (root / "binary.bin").write_bytes(b"\x00" * 100)
    (root / "escape").symlink_to(tmp_path)
    (root / ".local-shell-mcp").mkdir()
    (root / ".local-shell-mcp" / "secrets.json").write_text("private")
    (root / "private-state").mkdir()
    (root / "private-state" / "secrets.json").write_text("private")
    assert _path(root, "file.txt") == (root / "file.txt").resolve()
    assert json.loads(_execute(root, ModelToolCall("x", "file_list", {"path": "."})))['entries']
    assert json.loads(_execute(root, ModelToolCall("x", "file_read", {"path": "file.txt"})))['text'] == "hello world"
    assert json.loads(_execute(root, ModelToolCall("x", "file_read", {"path": "large.txt"})))['truncated'] is True
    assert all(not row["name"].startswith(".") for row in json.loads(
        _execute(root, ModelToolCall("x", "file_list", {}))) ["entries"])
    for path in ("../", "/etc/passwd", "escape/file.txt", ".local-shell-mcp/secrets.json"):
        with pytest.raises((ValueError, PermissionError, FileNotFoundError)):
            _path(root, path)
    with pytest.raises(ValueError, match="Binary"):
        _execute(root, ModelToolCall("x", "file_read", {"path": "binary.bin"}))
    with pytest.raises(PermissionError, match="private state"):
        _execute(root, ModelToolCall("x", "file_read", {"path": "private-state/secrets.json"}),
                 root / "private-state")
    listed = json.loads(_execute(root, ModelToolCall("x", "file_list", {}),
                                 root / "private-state"))
    assert "private-state" not in [entry["name"] for entry in listed["entries"]]
    for call in (ModelToolCall("x", "mcp_manage", {}), ModelToolCall("x", "run_shell", {"command": "pwd"}),
                 ModelToolCall("x", "file_list", {"path": ".", "limit": 200})):
        with pytest.raises(ValueError):
            _execute(root, call)


@pytest.mark.asyncio
async def test_background_generation_reads_workspace_only_after_explicit_enablement(tmp_path, monkeypatch):
    (tmp_path / "hello.txt").write_text("read-only sample")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    monkeypatch.delenv("LOCAL_SHELL_MCP_STATE_BACKEND", raising=False)
    get_settings.cache_clear()
    calls = []

    async def plain(*_args, **_kwargs):
        yield "Native tools are disabled."

    async def model(*_args, **kwargs):
        calls.append(kwargs)
        history = _args[1]
        if any(row.get("role") == "tool" for row in history):
            assert "hello.txt" in history[-1]["content"]
            yield "I found hello.txt."
        else:
            yield ModelToolCall("tool_1", "file_list", {"path": "."})

    monkeypatch.setattr(generation_routes, "provider_config", lambda *_: ProviderConfig(
        "openai", "mock", "http://127.0.0.1:11434/v1/chat/completions", "",
    ))
    monkeypatch.setattr(generation_routes, "stream_model_with_tools", model)
    monkeypatch.setattr(generation_routes, "stream_model", plain)
    app = Starlette(routes=[*generation_routes.generation_routes(), *routes.webui_routes(), *misc_routes.misc_routes()])
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            cid = (await client.post("/api/convos", json={"title": "Test"})).json()["conversationId"]
            deny = await client.post("/api/agents/chat", json={"conversationId": cid, "text": "Before permission"})
            assert deny.status_code == 202
            for _ in range(100):
                if (await client.get(f"/api/agents/chat/status/{cid}")).json().get("status") == "complete":
                    break
                await asyncio.sleep(.02)
            assert calls == []
            prefs = {"web": True, "lsm": True, "mcp": False, "memory": False,
                     "machines": {"local": "read"}}
            response = await client.put(f"/api/lsm/preferences/{cid}", json=prefs)
            assert response.status_code == 200
            new = await client.post("/api/agents/chat", json={"conversationId": cid, "text": "List files"})
            assert new.status_code == 202
            for _ in range(150):
                outcome = (await client.get(f"/api/agents/chat/status/{cid}")).json()
                if outcome.get("status") in {"complete", "error"}:
                    break
                await asyncio.sleep(.02)
            assert outcome["status"] == "complete"
            assert len(calls) == 2
            assert (await client.get(f"/api/messages/{cid}")).json()[-1]["text"] == "I found hello.txt."
            generation = generation_routes._generation_store().latest("local", cid)
            events = generation_routes._generation_store().events("local", generation.run_id)
            assert any(event.get("data", {}).get("type") == "tool_calls" for _, event in events)
            assert all("read-only sample" not in str(event) for _, event in events)
    finally:
        await generation_routes.shutdown_generations()
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_tool_policy_is_rechecked_before_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    try:
        from local_shell_mcp.webui.routes import _repo

        _repo().save_setting("local", "agent.machine_policy.global", {"local": "none"})
        with pytest.raises((PermissionError, KeyError)):
            await run_machine_tool("local", "abc", ModelToolCall("1", "file_read", {"path": "x"}))
        _repo().save_setting("local", "agent.machine_policy.global", {"local": "read"})
        with pytest.raises((PermissionError, KeyError)):
            await run_machine_tool("local", "abc", ModelToolCall("1", "mcp_tool_call", {}))
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_oauth_scope_is_checked_before_creating_tool_enabled_run(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "oauth")
    monkeypatch.delenv("LOCAL_SHELL_MCP_STATE_BACKEND", raising=False)
    get_settings.cache_clear()
    from local_shell_mcp.sqlite_store import shared_database
    from local_shell_mcp.webui.storage import WorkspaceRepository

    repository = WorkspaceRepository(shared_database(get_settings().state_dir.resolve()))
    cid = repository.create_conversation("alice", {"title": "Private files"})["conversationId"]
    repository.save_setting("alice", "agent.machine_policy.conversation." + cid, {"local": "read"})
    monkeypatch.setattr(generation_routes, "provider_config", lambda *_: ProviderConfig(
        "openai", "mock", "http://127.0.0.1:11434/v1/chat/completions", "",
    ))
    app = Starlette(routes=generation_routes.generation_routes())

    async def principal(scope, receive, send):
        scope.setdefault("state", {})["principal"] = SimpleNamespace(
            subject="alice", claims={"scope": "", "auth": "oauth"},
        )
        await app(scope, receive, send)

    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=principal), base_url="http://test") as client:
            denied = await client.post("/api/agents/chat", json={"conversationId": cid, "text": "read secret"})
            assert denied.status_code == 403
            assert (await client.get(f"/api/agents/chat/status/{cid}")).json()["active"] is False
            with shared_database(get_settings().state_dir.resolve()).connect() as db:
                assert db.execute("SELECT count(*) FROM runs WHERE conversation_id=?", (cid,)).fetchone()[0] == 0
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_revoking_tool_permission_while_model_streams_prevents_filesystem_access(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    from local_shell_mcp.webui.routes import _repo

    owner, cid = "local", "temporary_conversation"
    _repo().save_setting(owner, "agent.machine_policy.conversation." + cid, {"local": "read"})
    _repo().save_setting(owner, "agent.machine_policy.conversation." + cid, {"local": "none"})
    try:
        with pytest.raises((PermissionError, KeyError)):
            await run_machine_tool(owner, cid, ModelToolCall("tool-a", "file_list", {"path": "."}))
    finally:
        get_settings.cache_clear()
