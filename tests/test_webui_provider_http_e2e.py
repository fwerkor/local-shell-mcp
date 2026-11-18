"""Real loopback TCP HTTP/SSE model-provider round trips (no vendor credentials)."""
from __future__ import annotations

import asyncio
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette

from local_shell_mcp.settings import get_settings
from local_shell_mcp.webui import generation_routes, misc_routes, routes
from local_shell_mcp.webui.providers import ProviderConfig


class _Provider(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def do_POST(self):
        content = self.rfile.read(int(self.headers["Content-Length"]))
        body = json.loads(content)
        self.server.received.append(body)
        kind = self.server.kind
        if kind == "openai":
            done = any(row["role"] == "tool" for row in body["messages"])
        elif kind == "anthropic":
            done = any(isinstance(row["content"], list) and any(part.get("type") == "tool_result"
                       for part in row["content"]) for row in body["messages"])
        else:
            done = any(any("functionResponse" in part for part in row["parts"])
                       for row in body["contents"])
        if not done and len(self.server.received) >= 3:
            done = True
        if not done and kind == "openai":
            frames = [{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call-local-1",
                "function": {"name": "file_read", "arguments": '{"path":"readme.txt"}'}}]}}]}]
        elif not done and kind == "anthropic":
            frames = [{"type": "content_block_start", "index": 0,
                       "content_block": {"type": "tool_use", "id": "call-local-1", "name": "file_read", "input": {}}},
                      {"type": "content_block_delta", "index": 0,
                       "delta": {"type": "input_json_delta", "partial_json": '{"path":"readme.txt"}'}}]
        elif not done:
            frames = [{"candidates": [{"content": {"parts": [{"functionCall": {
                "name": "file_read", "args": {"path": "readme.txt"}}, "thoughtSignature": "sig-1"}]}}]}]
        elif kind == "openai":
            frames = [{"choices": [{"delta": {"content": "HTTP complete"}}]}]
        elif kind == "anthropic":
            frames = [{"type": "content_block_delta", "index": 0,
                       "delta": {"type": "text_delta", "text": "HTTP complete"}}]
        else:
            frames = [{"candidates": [{"content": {"parts": [{"text": "HTTP complete"}]}}]}]
        payload = "".join("data: " + json.dumps(item) + "\n\n" for item in frames) + "data: [DONE]\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload.encode())))
        self.end_headers()
        self.wfile.write(payload.encode())


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["openai", "anthropic", "google"])
async def test_real_http_sse_tool_loop_reload_and_followup(tmp_path, monkeypatch, kind):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    monkeypatch.delenv("LOCAL_SHELL_MCP_STATE_BACKEND", raising=False)
    get_settings.cache_clear()
    (tmp_path / "readme.txt").write_text("Real HTTP model should receive this file.")
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), _Provider)
    upstream.kind = kind
    upstream.received = []
    worker = threading.Thread(target=upstream.serve_forever, daemon=True)
    worker.start()
    api_url = f"http://127.0.0.1:{upstream.server_port}"
    monkeypatch.setattr(generation_routes, "provider_config", lambda *_args: ProviderConfig(
        kind, "mock", api_url + ("/chat/completions" if kind == "openai" else "/messages"), "test-token"))
    app = Starlette(routes=[*generation_routes.generation_routes(), *routes.webui_routes(),
                             *misc_routes.misc_routes()])
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="error", access_log=False))
    running = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(.02)
        assert server.started
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=20) as client:
            cid = (await client.post("/api/convos", json={"title": "Real SSE test"})).json()["conversationId"]
            prefs = {"web": True, "lsm": True, "mcp": False, "memory": False,
                     "machines": {"local": "read"}}
            change = await client.put(f"/api/lsm/preferences/{cid}", json=prefs)
            assert change.status_code == 200, change.text
            started = await client.post("/api/agents/chat", json={"conversationId": cid,
                "text": "Read the fixture", "provider": kind})
            assert started.status_code == 202, started.text
            for _ in range(160):
                state = (await client.get(f"/api/agents/chat/status/{cid}")).json()
                if state.get("status") in {"complete", "error", "interrupted"}:
                    break
                await asyncio.sleep(.04)
            assert state["status"] == "complete", state
            from local_shell_mcp.sqlite_store import SQLiteDatabase
            from local_shell_mcp.webui.generations import GenerationStore

            db = SQLiteDatabase(tmp_path / ".local-shell-mcp")
            stored = GenerationStore(db)
            history = stored.history("local", cid)
            assert [s["role"] for s in history] == ["user", "assistant", "tool", "assistant"]
            assert "Real HTTP model should receive this file" in history[2]["content"]
            assert history[-1]["content"] == "HTTP complete"
            if kind == "google":
                assert history[1]["tool_calls"][0]["provider_data"]["thoughtSignature"] == "sig-1"
            # The React client consumes a real SSE endpoint with durable events.
            events = await client.get(f"/api/agents/chat/stream/{cid}")
            assert events.status_code == 200
            assert "on_run_step_completed" in events.text
            assert "on_message_delta" in events.text
            second = await client.post("/api/agents/chat", json={"conversationId": cid,
                "text": "Summarize earlier tools", "provider": kind})
            assert second.status_code == 202
            for _ in range(160):
                next_state = (await client.get(f"/api/agents/chat/status/{cid}")).json()
                if next_state.get("status") in {"complete", "error", "interrupted"}:
                    break
                await asyncio.sleep(.04)
            assert next_state["status"] == "complete", next_state
            assert len(upstream.received) == 3
            assert "Real HTTP model should receive this file" in json.dumps(upstream.received[-1])
            assert len(GenerationStore(SQLiteDatabase(tmp_path / ".local-shell-mcp")).history("local", cid)) >= 6
    finally:
        server.should_exit = True
        await running
        upstream.shutdown()
        upstream.server_close()
        worker.join(timeout=2)
        await generation_routes.shutdown_generations()
        get_settings.cache_clear()
