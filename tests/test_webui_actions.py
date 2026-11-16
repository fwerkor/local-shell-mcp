"""LibreChat Actions endpoint, execution, credential, network and restart tests."""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import action_routes, agent_routes, routes
from local_shell_mcp.webui.action_runtime import invoke_action
from local_shell_mcp.webui.action_spec import (
    encoded_domain,
    is_action_tool,
    normalize_action_tool_name,
    operations,
    parse_spec,
    tool_name,
    validate_domain,
)
from local_shell_mcp.webui.actions import ActionRepository
from local_shell_mcp.webui.agents import AgentRepository


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/sleep"):
            time.sleep(.35)
        if self.path.startswith("/redirect"):
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()
            return
        status = 500 if self.path.startswith("/error") else 200
        result = json.dumps({"method": "GET", "url": self.path,
                             "hasKey": self.headers.get("Authorization") == "Bearer action-secret"}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(result)))
        self.end_headers()
        with contextlib.suppress(BrokenPipeError):
            self.wfile.write(result)

    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(size))
        result = json.dumps({"method": "POST", "body": body,
                             "hasKey": self.headers.get("Authorization") == "Bearer action-secret"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(result)

    def log_message(self, *args):
        pass


@pytest.fixture
def server(monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("LSM_ACTION_ALLOWED_ADDRESSES", f"127.0.0.1:{server.server_port}")
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join(timeout=1)
    server.server_close()


def make_spec(server: str):
    return {
        "openapi": "3.0.3", "servers": [{"url": server}],
        "paths": {
            "/echo/{item}": {"get": {"operationId": "getItem", "summary": "Get item",
                "parameters": [
                    {"name": "item", "in": "path", "required": True,
                     "schema": {"type": "string"}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer"}},
                ], "responses": {"200": {"description": "ok"}}}},
            "/post": {"post": {"operationId": "createItem",
                "requestBody": {"content": {"application/json": {
                    "schema": {"type": "object", "properties": {"message": {"type": "string"}},
                               "required": ["message"]}}}},
                "responses": {"200": {"description": "ok"}}}},
            "/error": {"get": {"operationId": "fail", "responses": {"500": {"description": "error"}}}},
            "/redirect": {"get": {"operationId": "redirect", "responses": {"302": {"description": "redirect"}}}},
            "/sleep": {"get": {"operationId": "slow", "responses": {"200": {"description": "ok"}}}},
        },
    }


def new_agent(db, owner="alice"):
    return AgentRepository(db).create(owner, {"provider": "openAI", "model": None, "name": "Tester"})


def body(server, *, auth=True):
    spec = make_spec(server)
    return {
        "metadata": {"domain": server, "raw_spec": json.dumps(spec),
                     **({"auth": {"type": "service_http", "authorization_type": "bearer"},
                         "api_key": "action-secret"} if auth else {"auth": {"type": "none"}})},
        "functions": [{"type": "function", "function": {"name": name}} for name in operations(spec)],
    }


def test_parser_openapi_tool_shape_and_ssrf_rejections(server):
    spec = make_spec(server)
    parsed = operations(parse_spec(json.dumps(spec)))
    assert list(parsed) == ["getItem", "createItem", "fail", "redirect", "slow"]
    assert parsed["getItem"]["locations"] == {"item": "path", "limit": "query"}
    assert parsed["createItem"]["parameters"]["required"] == ["message"]
    assert parsed["createItem"]["content_type"] == "application/json"
    assert tool_name("getItem", server) == "getItem_action_" + encoded_domain(server)
    assert is_action_tool("getItem_action_api---org")
    assert not is_action_tool("get_action_mcp_server")
    assert normalize_action_tool_name("get_foo---bar_action_api---org") == "get_foo---bar_action_api_org"
    with pytest.raises(ValueError, match="Domain mismatch"):
        validate_domain("https://example.com", server)
    with pytest.raises(ValueError):
        parse_spec("{}")
    with pytest.raises(ValueError):
        parse_spec("servers: []")
    with pytest.raises(ValueError):
        operations({"paths": {"/a": {"get": {"operationId": "slash/name"}}}})


def test_storage_credentials_version_and_boundaries(tmp_path, server):
    db = SQLiteDatabase(tmp_path)
    agent = new_agent(db)
    repo = ActionRepository(db)
    updated, saved = repo.save("alice", agent["id"], body(server))
    assert updated["version"] == 2
    assert len(updated["tools"]) == 5 and len(updated["actions"]) == 1
    assert len(repo.list("alice")) == 1
    assert repo.list("bob") == []
    assert saved["metadata"]["domain"] == server
    assert "api_key" not in str(saved) and "action-secret" not in str(saved)
    assert "action-secret" not in db.path.read_bytes().decode("utf-8", errors="ignore")
    assert "action-secret" not in json.dumps(AgentRepository(db).versions("alice", agent["id"]))
    if os.name != "nt":
        assert (tmp_path / "actions-fernet.key").stat().st_mode & 0o077 == 0
    names = {tool["function"]["name"] for tool in repo.tool_schemas("alice", updated)}
    assert names == {normalize_action_tool_name(x) for x in updated["tools"]}
    assert repo.tool_schemas("alice", updated, selected_tools=[]) == []
    assert len(repo.tool_schemas("alice", updated, selected_tools=[next(iter(names))])) == 1
    for name in names:
        assert "secret" not in json.dumps(repo.get_for_tool("alice", agent["id"], name)[2])
    assert repo.get_for_tool("bob", agent["id"], next(iter(names))) is None
    assert repo.get_for_tool("alice", agent["id"], "unselected") is None
    with pytest.raises(KeyError):
        repo.delete("bob", agent["id"], saved["action_id"])
    patch = body(server)
    patch["action_id"] = saved["action_id"]
    patch["metadata"].pop("api_key")
    second, action = repo.save("alice", agent["id"], patch)
    assert second["version"] == 3 and action["version"] == 2
    changed = body(server.replace("127.0.0.1", "127.0.0.2"))
    changed["action_id"] = saved["action_id"]
    changed["metadata"].pop("api_key")
    with pytest.raises(ValueError, match="credentials must be re-entered"):
        repo.save("alice", agent["id"], changed)
    assert len(repo.list("alice")) == 1
    assert repo.delete("alice", agent["id"], saved["action_id"])
    assert repo.list("alice") == []
    assert AgentRepository(db).get("alice", agent["id"])["tools"] == []
    assert not repo.delete("alice", agent["id"], saved["action_id"])


@pytest.mark.asyncio
async def test_api_contract_and_auth(tmp_path, server, monkeypatch):
    db = SQLiteDatabase(tmp_path)
    agent = new_agent(db)
    repo = ActionRepository(db)
    monkeypatch.setattr(action_routes, "_repository", lambda: repo)
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(auth_mode="oauth"))
    app = Starlette(routes=agent_routes.agent_routes())

    async def principal(scope, receive, send):
        if scope["type"] == "http":
            who = dict(scope.get("headers", [])).get(b"x-test-user")
            if who:
                scope.setdefault("state", {})["principal"] = SimpleNamespace(subject=who.decode())
        await app(scope, receive, send)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=principal), base_url="http://webui") as client:
        assert (await client.get("/api/agents/actions")).status_code == 401
        assert (await client.post(f"/api/agents/actions/{agent['id']}", json=body(server))).status_code == 401
        alice, bob = {"x-test-user": "alice"}, {"x-test-user": "bob"}
        assert (await client.get("/api/agents/actions", headers=bob)).json() == []
        assert (await client.post(f"/api/agents/actions/{agent['id']}", headers=bob, json=body(server))).status_code == 404
        created = await client.post(f"/api/agents/actions/{agent['id']}", headers=alice, json=body(server))
        assert created.status_code == 200, created.text
        updated, action = created.json()
        assert action["agent_id"] == agent["id"] and updated["version"] == 2
        assert "action-secret" not in created.text
        assert "api_key" not in created.text
        assert len((await client.get("/api/agents/actions", headers=alice)).json()) == 1
        aid = action["action_id"]
        assert (await client.delete(f"/api/agents/actions/{agent['id']}/{aid}", headers=bob)).status_code == 404
        assert (await client.delete(f"/api/agents/actions/{agent['id']}/{aid}", headers=alice)).status_code == 200
        assert (await client.get("/api/agents/actions", headers=alice)).json() == []


@pytest.mark.asyncio
async def test_real_http_success_error_timeout_redirect_cancel_and_restart(tmp_path, server, monkeypatch):
    db = SQLiteDatabase(tmp_path)
    agent = new_agent(db)
    repo = ActionRepository(db)
    updated, action = repo.save("alice", agent["id"], body(server))
    # Restart: new DB instance and repository open the same encrypted content.
    reopened = ActionRepository(SQLiteDatabase(tmp_path))
    assert reopened.list("alice")[0] == action
    assert reopened.tool_schemas("alice", updated)
    for name, args, method in [
        ("getItem", {"item": "a/b", "limit": 3}, "GET"),
        ("createItem", {"message": "hello"}, "POST"),
    ]:
        key = normalize_action_tool_name(tool_name(name, server))
        value = await invoke_action("alice", agent["id"], key, args, reopened.database)
        data = json.loads(value)
        assert data["method"] == method and data["hasKey"]
        if name == "getItem":
            assert data["url"] == "/echo/a%2Fb?limit=3"
        else:
            assert data["body"] == {"message": "hello"}
    for name, expect in [("fail", "HTTP 500"), ("redirect", "HTTP 302")]:
        value = await invoke_action("alice", agent["id"], normalize_action_tool_name(tool_name(name, server)), {}, db)
        assert expect in value
    from local_shell_mcp.webui import action_runtime
    monkeypatch.setattr(action_runtime, "_TIMEOUT_S", .035)
    name = normalize_action_tool_name(tool_name("slow", server))
    assert "timeout" in (await invoke_action("alice", agent["id"], name, {}, db)).lower()
    monkeypatch.setattr(action_runtime, "_TIMEOUT_S", 1.0)
    task = asyncio.create_task(invoke_action("alice", agent["id"], name, {}, db))
    await asyncio.sleep(.035)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # An omitted allowlist may never probe loopback/private/metadata addresses.
    monkeypatch.delenv("LSM_ACTION_ALLOWED_ADDRESSES")
    assert "PermissionError" in await invoke_action("alice", agent["id"], name, {}, db)
    assert "action-secret" not in str(reopened.list("alice"))


@pytest.mark.asyncio
async def test_multiple_tools_and_scope_rejection(tmp_path, server):
    db = SQLiteDatabase(tmp_path)
    agent = new_agent(db)
    repo = ActionRepository(db)
    repo.save("alice", agent["id"], body(server, auth=False))
    names = [normalize_action_tool_name(tool_name(op, server)) for op in ("getItem", "fail")]
    outputs = await asyncio.gather(*[
        invoke_action("alice", agent["id"], name, {"item": "x"} if i == 0 else {}, db)
        for i, name in enumerate(names)
    ])
    assert json.loads(outputs[0])["url"] == "/echo/x"
    assert "HTTP 500" in outputs[1]
    assert repo.get_for_tool("alice", agent["id"], "session_manage") is None



def test_original_react_actions_builder_has_no_credential_console_logging():
    """Minimal necessary upstream adaptation: never log API keys or OAuth secrets."""
    from pathlib import Path

    base = Path(__file__).resolve().parents[1]
    for relpath in [
        "ui/workspace/client/src/components/SidePanel/Agents/ActionsInput.tsx",
        "ui/workspace/client/src/components/SidePanel/Builder/ActionsInput.tsx",
    ]:
        client = (base / relpath).read_text()
        assert "saving action" not in client
        assert "console.log('authFormData'" not in client
        assert "logger.log('actions'" not in client
        assert "api_key: authFormData.api_key" in client
