"""Crash-safe LibreChat Actions OAuth checkpoint replay through real HTTP routes."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import SQLiteDatabase, shared_database
from local_shell_mcp.webui import action_oauth, agent_runner, generation_routes
from local_shell_mcp.webui.action_spec import normalize_action_tool_name, tool_name
from local_shell_mcp.webui.actions import ActionRepository
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.providers import ModelToolCall, ProviderConfig
from local_shell_mcp.webui.routes import _repo


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "oauth")
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "https://chat.example.org")
    get_settings.cache_clear()
    db = shared_database(get_settings().state_dir)
    store = GenerationStore(db)
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append({"path": self.path, "authorization": self.headers.get("Authorization")})
            response = json.dumps({"hasToken": self.headers.get("Authorization") == "Bearer new-test-access"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, *_):
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("LSM_ACTION_ALLOWED_ADDRESSES", f"127.0.0.1:{http.server_port}")
    url = f"http://127.0.0.1:{http.server_port}"
    agent = AgentRepository(db).create("local", {"name": "OAuth Resume", "provider": "openAI", "model": "test"})
    specification = {"openapi": "3.0.0", "servers": [{"url": url}], "paths": {
        "/record": {"get": {"operationId": "fetchRecord", "responses": {"200": {}}}},
    }}
    agent, action = ActionRepository(db).save("local", agent["id"], {
        "metadata": {"domain": url, "raw_spec": json.dumps(specification), "auth": {
            "type": "oauth", "authorization_url": "https://id.example.org/oauth/authorize",
            "client_url": "https://id.example.org/oauth/token", "scope": "read",
            "token_exchange_method": "default_post"},
            "oauth_client_id": "id", "oauth_client_secret": "private-client-secret"},
        "functions": [{"type": "function", "function": {"name": "fetchRecord"}}],
    })
    tool = normalize_action_tool_name(tool_name("fetchRecord", url))
    generation, _ = store.begin("local", {"text": "Fetch the record"}, agent)
    model_calls = []

    async def model(_profile, history, *, tools, **kwargs):
        assert tool in {item["function"]["name"] for item in tools}
        model_calls.append(history[-1]["role"])
        if history[-1]["role"] == "tool":
            assert json.loads(history[-1]["content"])["hasToken"]
            yield "Record fetched."
        else:
            yield ModelToolCall("call-oauth", tool, {})

    profile = ProviderConfig("openai", "test", "https://model.invalid", "")
    monkeypatch.setattr(generation_routes, "provider_config", lambda *_: profile)
    monkeypatch.setattr(agent_runner, "provider_config", lambda *_: profile)
    monkeypatch.setattr(generation_routes, "stream_model_with_tools", model)

    async def token_exchange(_url, payload, creds, method):
        assert payload["code"] == "oauth-code"
        assert creds["oauth_client_secret"] == "private-client-secret"
        return {"access_token": "new-test-access", "refresh_token": "new-test-refresh", "expires_in": 900}

    monkeypatch.setattr(action_oauth, "_exchange", token_exchange)
    from local_shell_mcp.webui.agent_routes import agent_routes

    app = Starlette(routes=[*agent_routes(), *generation_routes.generation_routes()])

    async def wrapped(scope, receive, send):
        if scope["type"] == "http":
            headers = {key.decode(): value.decode() for key, value in scope.get("headers", [])}
            owner = headers.get("x-owner")
            if owner:
                scope.setdefault("state", {})["principal"] = SimpleNamespace(
                    subject=owner, claims={"scope": headers.get("x-scopes", ""),
                                           "exp": int(time.time()) + 2400})
        await app(scope, receive, send)

    yield SimpleNamespace(db=db, store=store, agent=agent, action=action, tool=tool,
                          gen=generation, profile=profile, app=wrapped, seen=seen,
                          model_calls=model_calls, path=tmp_path / ".local-shell-mcp")
    for task in list(generation_routes._TASKS.values()):
        task.cancel()
    http.shutdown()
    thread.join(timeout=2)
    http.server_close()
    get_settings.cache_clear()


async def _pause(ctx):
    await generation_routes._run_model("local", ctx.gen, ctx.profile, parent_agent=ctx.agent)
    assert ctx.store.latest("local", ctx.gen.conversation_id).status == "requires_action"
    assert ctx.store.pending_action("local", ctx.gen.run_id)["payload"]["type"] == "action_oauth"
    assert ctx.model_calls == ["user"]
    auth = [e["data"]["delta"]["auth"] for _, e in ctx.store.events("local", ctx.gen.run_id)
            if e.get("event") == "on_run_step_delta" and e.get("data", {}).get("delta", {}).get("auth")]
    assert len(auth) == 1
    return parse_qs(urlsplit(auth[0]).query)["state"][0]


async def _login(ctx, state, client):
    url = f"/api/actions/{ctx.action['action_id']}/oauth"
    response = await client.post(url + "/bind", headers={"x-owner": "local"})
    assert response.status_code == 200, response.text
    response = await client.get(url + "/callback", params={"state": state, "code": "oauth-code"})
    assert response.status_code == 302 and response.headers["location"].startswith("/oauth/success")


@pytest.mark.asyncio
async def test_restart_preserves_signin_and_bearer_reattachment_runs_action_once(scenario):
    ctx = scenario
    state = await _pause(ctx)
    assert ctx.store.recover_orphans() == 0
    reopened = GenerationStore(SQLiteDatabase(ctx.path))
    assert reopened.pending_action("local", ctx.gen.run_id)["payload"]["tool_call_id"] == "call-oauth"
    assert not ctx.seen
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ctx.app),
                                 base_url="https://chat.example.org", follow_redirects=False) as client:
        await _login(ctx, state, client)
        assert ctx.store.latest("local", ctx.gen.conversation_id).status == "requires_action"
        # A new authenticated browser attaches after the Controller restarts.
        query = await client.get(f"/api/agents/chat/status/{ctx.gen.conversation_id}",
                                 headers={"x-owner": "local"})
        assert query.status_code == 200, query.text
        assert query.json()["active"] is True
        assert "pendingAction" not in query.json()  # native React renders the auth tool delta
        await asyncio.wait_for(asyncio.gather(*list(generation_routes._TASKS.values())), timeout=8)
        assert ctx.store.latest("local", ctx.gen.conversation_id).status == "complete"
        assert ctx.model_calls == ["user", "tool"]
        assert len(ctx.seen) == 1 and ctx.seen[0]["authorization"] == "Bearer new-test-access"
        events = json.dumps(ctx.store.events("local", ctx.gen.run_id))
        assert "private-client-secret" not in events
        assert "new-test-access" not in events
        assert "new-test-refresh" not in events
        assert any(event.get("event") == "on_run_step_delta" and
                   event["data"].get("delta", {}).get("auth") == ""
                   for _, event in ctx.store.events("local", ctx.gen.run_id))
        assert ctx.store.pending_action("local", ctx.gen.run_id) is None


@pytest.mark.asyncio
async def test_machine_scopes_are_rechecked_before_oauth_continuation(scenario):
    ctx = scenario
    state = await _pause(ctx)
    _repo().save_setting("local", "agent.machine_policy.global", {"local": "write"})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ctx.app),
                                 base_url="https://chat.example.org", follow_redirects=False) as client:
        await _login(ctx, state, client)
        path = f"/api/agents/chat/status/{ctx.gen.conversation_id}"
        denied = await client.get(path, headers={"x-owner": "local", "x-scopes": "shell:read"})
        assert denied.status_code == 403
        assert ctx.store.pending_action("local", ctx.gen.run_id) is not None
        assert not ctx.seen
        allowed = await client.get(path, headers={"x-owner": "local", "x-scopes": "shell:read shell:write"})
        assert allowed.status_code == 200, allowed.text
        await asyncio.wait_for(asyncio.gather(*list(generation_routes._TASKS.values())), timeout=8)
        assert len(ctx.seen) == 1 and ctx.model_calls == ["user", "tool"]


@pytest.mark.asyncio
async def test_workspace_cookie_resumes_automatically_without_becoming_machine_grant(scenario):
    from local_shell_mcp.webui.auth import COOKIE, WebAuthStore

    ctx = scenario
    state = await _pause(ctx)
    web = WebAuthStore(ctx.path)
    ticket = web.issue_ticket("local", "shell:read", int(time.time()) + 1800)
    cookie, _ = web.redeem(ticket)
    _repo().save_setting("local", "agent.machine_policy.global", {"local": "write"})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ctx.app),
                                 base_url="https://chat.example.org", follow_redirects=False) as client:
        client.cookies.set(COOKIE, cookie)
        await _login(ctx, state, client)
        assert ctx.store.latest("local", ctx.gen.conversation_id).status == "requires_action"
        assert not ctx.seen
        # Revoke and reissue a stronger authenticated session.
        web.revoke(cookie)
        ticket = web.issue_ticket("local", "shell:read shell:write", int(time.time()) + 1800)
        web.redeem(ticket)
        response = await client.get(f"/api/agents/chat/status/{ctx.gen.conversation_id}",
                                    headers={"x-owner": "local", "x-scopes": "shell:read shell:write"})
        assert response.status_code == 200
        await asyncio.wait_for(asyncio.gather(*list(generation_routes._TASKS.values())), timeout=8)
        assert len(ctx.seen) == 1


@pytest.mark.asyncio
async def test_claim_restart_replay_fence_prevents_duplicate_http_execution(scenario):
    ctx = scenario
    await _pause(ctx)
    action_oauth._store_tokens(ActionRepository(ctx.db), "local", ctx.action["action_id"],
                               {"access_token": "new-test-access", "expires_in": 900})
    claimed = ctx.store.claim_oauth("local", ctx.gen.run_id, ctx.action["action_id"], "call-oauth", 1)
    assert claimed is not None and ctx.store.latest("local", ctx.gen.conversation_id).status == "running"
    assert ctx.store.recover_orphans() == 1
    assert ctx.store.latest("local", ctx.gen.conversation_id).status == "requires_action"
    claimed = ctx.store.claim_oauth("local", ctx.gen.run_id, ctx.action["action_id"], "call-oauth", 1)
    assert claimed is not None
    ctx.store.oauth_dispatch("local", ctx.gen.run_id, "call-oauth", "dispatching")
    with pytest.raises(PermissionError):
        ctx.store.oauth_dispatch("local", ctx.gen.run_id, "call-oauth", "dispatching")
    assert ctx.store.recover_orphans() == 1
    assert ctx.store.latest("local", ctx.gen.conversation_id).status == "interrupted"
    assert not ctx.seen
    # An old callback or a new browser cannot revive an already dispatched,
    # potentially consequential Action without a durable HTTP result.
    assert ctx.store.claim_oauth("local", ctx.gen.run_id, ctx.action["action_id"], "call-oauth", 1) is None
    assert ctx.model_calls == ["user"]


@pytest.mark.asyncio
async def test_stale_action_version_never_consumes_oauth_resume(scenario):
    ctx = scenario
    await _pause(ctx)
    action_oauth._store_tokens(ActionRepository(ctx.db), "local", ctx.action["action_id"],
                               {"access_token": "new-test-access", "expires_in": 900})
    with ctx.db.connect() as db:
        db.execute("UPDATE action_records SET version=version+1 WHERE id=?", (ctx.action["action_id"],))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ctx.app),
                                 base_url="https://chat.example.org", follow_redirects=False) as client:
        res = await client.get(f"/api/agents/chat/status/{ctx.gen.conversation_id}",
                               headers={"x-owner": "local"})
        assert res.status_code == 200
        assert ctx.store.latest("local", ctx.gen.conversation_id).status == "requires_action"
        assert not ctx.seen


@pytest.mark.asyncio
async def test_crash_after_post_tool_checkpoint_recovers_without_replaying_action(scenario, monkeypatch):
    """Regression: post-tool checkpoint saved, process dies before clearing OAuth fence."""
    from local_shell_mcp.webui.agent_runtime import AgentLoopState
    from local_shell_mcp.webui.checkpoints import SQLiteCheckpointSaver

    ctx = scenario
    await _pause(ctx)
    repo = ActionRepository(ctx.db)
    action_oauth._store_tokens(repo, "local", ctx.action["action_id"], {
        "access_token": "new-test-access", "expires_in": 900,
    })
    assert ctx.store.claim_oauth("local", ctx.gen.run_id, ctx.action["action_id"], "call-oauth", 1)
    ctx.store.oauth_dispatch("local", ctx.gen.run_id, "call-oauth", "dispatching")
    runner = agent_runner.AgentRunner(
        "local", ctx.gen, ctx.db, ctx.store, scopes=set(), grant_expires=None,
        stream_tools=generation_routes.stream_model_with_tools,
        stream_text=generation_routes.stream_model, on_text=lambda _: asyncio.sleep(0),
        profile=ctx.profile, agent=ctx.agent,
    )
    saver = SQLiteCheckpointSaver(ctx.db, "local")
    original = saver.get_tuple(saver.config(ctx.gen.conversation_id, ctx.gen.run_id, event_actor=True))
    assert original is not None and len(original["checkpoint"]["channel_values"]["pending_calls"]) == 1
    runner.active_config = original["config"]
    output = json.dumps({"hasToken": True})
    await runner._completed(ModelToolCall("call-oauth", ctx.tool, {}), {
        "proposal": {"name": ctx.tool, "args": {}}, "output": output,
    })
    assert ctx.store.pending_action("local", ctx.gen.run_id) is None
    assert ctx.store.get("local", ctx.gen.run_id).status == "running"
    snapshot = original["checkpoint"]["channel_values"]
    messages = [*snapshot["messages"], {
        "role": "tool", "tool_call_id": "call-oauth", "content": output,
    }]
    state = AgentLoopState(runner._context(ctx.agent, profile=ctx.profile), messages,
                           snapshot["step"], snapshot["model_turn"], [], False, False)

    def crash_after_checkpoint(*_):
        raise OSError("Controller died before clearing OAuth replay marker")

    monkeypatch.setattr(ctx.store, "clear_oauth_checkpoint", crash_after_checkpoint)
    with pytest.raises(OSError, match="Controller died"):
        await runner._save(state, [])
    assert ctx.store.recover_orphans() == 1
    pending = ctx.store.pending_action("local", ctx.gen.run_id)
    assert pending["payload"]["checkpoint_completed"] is True
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ctx.app),
                                 base_url="https://chat.example.org", follow_redirects=False) as client:
        response = await client.get(f"/api/agents/chat/status/{ctx.gen.conversation_id}",
                                    headers={"x-owner": "local"})
        assert response.status_code == 200, response.text
        await asyncio.wait_for(asyncio.gather(*list(generation_routes._TASKS.values())), timeout=8)
    assert ctx.store.get("local", ctx.gen.run_id).status == "complete"
    assert ctx.model_calls == ["user", "tool"]
    assert ctx.seen == []  # The preceding HTTP result is reused from SQLite.


@pytest.mark.asyncio
async def test_expired_action_oauth_link_reissues_once_across_concurrent_status_requests(scenario):
    ctx = scenario
    initial_state = await _pause(ctx)
    original = [e for _, e in ctx.store.events("local", ctx.gen.run_id)
                if e.get("event") == "on_run_step_delta" and e.get("data", {}).get("delta", {}).get("auth")]
    assert len(original) == 1
    with ctx.db.connect() as conn:
        conn.execute("UPDATE action_oauth_flows SET expires_at=? WHERE run_id=?",
                     (int(time.time()) - 10, ctx.gen.run_id))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ctx.app),
                                 base_url="https://chat.example.org", follow_redirects=False) as client:
        url = f"/api/agents/chat/status/{ctx.gen.conversation_id}"
        responses = await asyncio.gather(*(client.get(url, headers={"x-owner": "local"}) for _ in range(8)))
        assert all(res.status_code == 200 for res in responses)
        prompts = [e for _, e in ctx.store.events("local", ctx.gen.run_id)
                   if e.get("event") == "on_run_step_delta" and e.get("data", {}).get("delta", {}).get("auth")]
        assert len(prompts) == 2
        reissued_state = parse_qs(urlsplit(prompts[-1]["data"]["delta"]["auth"]).query)["state"][0]
        assert reissued_state != initial_state
        assert ctx.store.get("local", ctx.gen.run_id).status == "requires_action"
        with ctx.db.connect() as conn:
            assert conn.execute("SELECT count(*) FROM action_oauth_flows WHERE run_id=?",
                                (ctx.gen.run_id,)).fetchone()[0] == 1
        path = f"/api/actions/{ctx.action['action_id']}/oauth"
        assert (await client.post(path + "/bind", headers={"x-owner": "local"})).status_code == 200
        invalid = await client.get(path + "/callback", params={"state": initial_state, "code": "oauth-code"})
        assert "invalid_state" in invalid.headers["location"]
        valid = await client.get(path + "/callback", params={"state": reissued_state, "code": "oauth-code"})
        assert valid.status_code == 302 and "/oauth/success" in valid.headers["location"]
        result = await client.get(url, headers={"x-owner": "local"})
        assert result.status_code == 200
        await asyncio.wait_for(asyncio.gather(*list(generation_routes._TASKS.values())), timeout=8)
        assert ctx.store.get("local", ctx.gen.run_id).status == "complete"
        assert len(ctx.seen) == 1


@pytest.mark.asyncio
async def test_user_abort_invalidates_outstanding_oauth_callback(scenario):
    ctx = scenario
    state = await _pause(ctx)
    path = f"/api/actions/{ctx.action['action_id']}/oauth"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ctx.app),
                                 base_url="https://chat.example.org", follow_redirects=False) as client:
        assert (await client.post(path + "/bind", headers={"x-owner": "local"})).status_code == 200
        response = await client.post("/api/agents/chat/abort", json={
            "conversationId": ctx.gen.conversation_id,
        }, headers={"x-owner": "local"})
        assert response.status_code == 200, response.text
        assert ctx.store.get("local", ctx.gen.run_id).status == "aborted"
        callback = await client.get(path + "/callback", params={"state": state, "code": "oauth-code"})
        assert callback.status_code == 302 and "invalid_state" in callback.headers["location"]
        assert action_oauth._token(ActionRepository(ctx.db), "local", ctx.action["action_id"], "access") is None
        assert ctx.seen == []


@pytest.mark.asyncio
async def test_expired_oauth_prompt_requires_machine_grants_before_reissuing(scenario):
    """A principal without current machine scope cannot rotate IdP state."""
    ctx = scenario
    await _pause(ctx)
    _repo().save_setting("local", "agent.machine_policy.global", {"local": "write"})
    with ctx.db.connect() as db:
        db.execute("UPDATE action_oauth_flows SET expires_at=? WHERE run_id=?",
                   (int(time.time()) - 1, ctx.gen.run_id))
    initial_events = ctx.store.events("local", ctx.gen.run_id)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ctx.app),
                                 base_url="https://chat.example.org", follow_redirects=False) as client:
        result = await client.get(f"/api/agents/chat/status/{ctx.gen.conversation_id}",
                                  headers={"x-owner": "local", "x-scopes": "shell:read"})
        assert result.status_code == 403
        assert ctx.store.events("local", ctx.gen.run_id) == initial_events
        valid = await client.get(f"/api/agents/chat/status/{ctx.gen.conversation_id}",
                                 headers={"x-owner": "local", "x-scopes": "shell:read shell:write"})
        assert valid.status_code == 200
        assert len(ctx.store.events("local", ctx.gen.run_id)) == len(initial_events) + 1


@pytest.mark.asyncio
async def test_two_oauth_actions_in_one_model_batch_never_send_http_before_both_grants(scenario, monkeypatch):
    """Sequential browser approvals preserve the original sibling ToolNode batch."""
    ctx = scenario
    actions = ActionRepository(ctx.db)
    base = ctx.action["metadata"]["domain"]
    second_spec = {"openapi": "3.0.3", "servers": [{"url": base}], "paths": {
        "/record-2": {"get": {"operationId": "fetchOther", "responses": {"200": {}}}},
    }}
    updated_agent, second = actions.save("local", ctx.agent["id"], {
        "metadata": {"domain": base, "raw_spec": json.dumps(second_spec), "auth": {
            "type": "oauth", "authorization_url": "https://id.example.org/oauth/authorize",
            "client_url": "https://id.example.org/oauth/token", "scope": "read",
            "token_exchange_method": "default_post"},
            "oauth_client_id": "id", "oauth_client_secret": "private-client-secret"},
        "functions": [{"type": "function", "function": {"name": "fetchOther"}}],
    })
    ctx.agent = updated_agent
    second_tool = normalize_action_tool_name(tool_name("fetchOther", base))

    async def two_tools(_profile, history, *, tools, **kwargs):
        ctx.model_calls.append(history[-1]["role"])
        available = {item["function"]["name"] for item in tools}
        assert ctx.tool in available and second_tool in available
        if history[-1]["role"] == "tool":
            assert len([m for m in history if m.get("role") == "tool"]) == 2
            yield "Both Actions completed."
        else:
            yield ModelToolCall("call-oauth", ctx.tool, {})
            yield ModelToolCall("call-oauth-2", second_tool, {})

    monkeypatch.setattr(generation_routes, "stream_model_with_tools", two_tools)
    state_first = await _pause(ctx)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ctx.app),
                                 base_url="https://chat.example.org", follow_redirects=False) as client:
        await _login(ctx, state_first, client)
        assert not ctx.seen
        status = await client.get(f"/api/agents/chat/status/{ctx.gen.conversation_id}",
                                  headers={"x-owner": "local"})
        assert status.status_code == 200
        await asyncio.wait_for(asyncio.gather(*list(generation_routes._TASKS.values())), timeout=8)
        assert ctx.store.get("local", ctx.gen.run_id).status == "requires_action"
        assert ctx.store.pending_action("local", ctx.gen.run_id)["payload"]["tool_call_id"] == "call-oauth-2"
        assert not ctx.seen  # No sibling can dispatch before all required grants.
        prompts = [item for _, item in ctx.store.events("local", ctx.gen.run_id)
                   if item.get("event") == "on_run_step_delta" and item.get("data", {}).get("delta", {}).get("auth")]
        assert len(prompts) == 2
        state_second = parse_qs(urlsplit(prompts[-1]["data"]["delta"]["auth"]).query)["state"][0]
        path = f"/api/actions/{second['action_id']}/oauth"
        assert (await client.post(path + "/bind", headers={"x-owner": "local"})).status_code == 200
        response = await client.get(path + "/callback", params={"state": state_second, "code": "oauth-code"})
        assert response.status_code == 302 and "/oauth/success" in response.headers["location"]
        status = await client.get(f"/api/agents/chat/status/{ctx.gen.conversation_id}",
                                  headers={"x-owner": "local"})
        assert status.status_code == 200
        await asyncio.wait_for(asyncio.gather(*list(generation_routes._TASKS.values())), timeout=8)
        assert ctx.store.get("local", ctx.gen.run_id).status == "complete"
        assert ctx.model_calls == ["user", "tool"]
        assert len(ctx.seen) == 2
        assert sorted(item["path"] for item in ctx.seen) == ["/record", "/record-2"]


@pytest.mark.asyncio
async def test_approved_action_oauth_login_keeps_review_and_calls_once(scenario, monkeypatch):
    """Tool Approval -> sign-in -> same reviewed tool, without bypass or replay."""
    ctx = scenario
    _repo().save_setting("local", "endpoints", {"agents": {"toolApproval": {
        "enabled": True, "ask": [ctx.tool],
    }}})
    await generation_routes._run_model("local", ctx.gen, ctx.profile, parent_agent=ctx.agent)
    pending = ctx.store.pending_action("local", ctx.gen.run_id)
    assert pending["payload"]["type"] == "tool_approval"
    assert len(ctx.model_calls) == 1 and not ctx.seen
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ctx.app),
                                 base_url="https://chat.example.org", follow_redirects=False) as client:
        approval = await client.post("/api/agents/chat/resume", json={
            "conversationId": ctx.gen.conversation_id, "actionId": pending["actionId"],
            "decisions": [{"tool_call_id": "call-oauth", "decision": "approve"}],
        }, headers={"x-owner": "local"})
        assert approval.status_code == 200, approval.text
        await asyncio.wait_for(asyncio.gather(*list(generation_routes._TASKS.values())), timeout=8)
        assert ctx.store.get("local", ctx.gen.run_id).status == "requires_action"
        assert ctx.store.approved_review("local", ctx.gen.run_id) is None  # approval is retained in paused state
        with ctx.db.connect() as conn:
            row = conn.execute("SELECT state FROM runs WHERE id=?", (ctx.gen.run_id,)).fetchone()
        assert json.loads(row["state"])["approvedToolBatch"]["actionId"] == pending["actionId"]
        assert not ctx.seen
        oauth_events = [e for _, e in ctx.store.events("local", ctx.gen.run_id)
                        if e.get("event") == "on_run_step_delta" and e.get("data", {}).get("delta", {}).get("auth")]
        assert len(oauth_events) == 1
        state = parse_qs(urlsplit(oauth_events[0]["data"]["delta"]["auth"]).query)["state"][0]
        await _login(ctx, state, client)
        resumed = await client.get(f"/api/agents/chat/status/{ctx.gen.conversation_id}",
                                   headers={"x-owner": "local"})
        assert resumed.status_code == 200, resumed.text
        await asyncio.wait_for(asyncio.gather(*list(generation_routes._TASKS.values())), timeout=8)
        assert ctx.store.get("local", ctx.gen.run_id).status == "complete"
        assert ctx.model_calls == ["user", "tool"]
        assert len(ctx.seen) == 1
