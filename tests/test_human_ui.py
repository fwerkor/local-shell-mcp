from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocket

from local_shell_mcp.audit import audit, query_audit, suppress_audit
from local_shell_mcp.http_app import build_http_app
from local_shell_mcp.human_ui import _authorize_websocket, _bounded_int
from local_shell_mcp.oauth import public_base_url
from local_shell_mcp.remote import execute_worker_tool
from local_shell_mcp.settings import get_settings
from local_shell_mcp.ui_security import UI_LOCAL_TOKEN_HEADER, get_or_create_ui_local_token


def _configure(tmp_path, monkeypatch, *, auth_mode: str = "none") -> None:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", auth_mode)
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()


def test_human_file_api_has_yazi_style_directory_payload(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    (tmp_path / "folder").mkdir()
    (tmp_path / "alpha.txt").write_text("alpha", encoding="utf-8")

    client = TestClient(build_http_app())
    response = client.get("/api/ui/files", params={"machine": "local", "path": "."})

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["machine"] == "local"
    assert payload["path"] == "."
    assert [entry["name"] for entry in payload["entries"]][:2] == [".state", "folder"]
    assert any(entry["name"] == "alpha.txt" and entry["type"] == "file" for entry in payload["entries"])


def test_editor_content_reads_the_complete_bounded_file(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    content = "\n".join(f"line-{index}" for index in range(350))
    (tmp_path / "long.txt").write_text(content, encoding="utf-8")
    client = TestClient(build_http_app())

    response = client.get(
        "/api/ui/files/content",
        params={"machine": "local", "path": "long.txt"},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["truncated"] is False
    assert payload["content"] == content
    assert "line-349" in payload["content"]


def test_editor_refuses_files_larger_than_the_read_limit(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_FILE_READ_BYTES", "64")
    get_settings.cache_clear()
    original = "0123456789" * 20
    (tmp_path / "too-large.txt").write_text(original, encoding="utf-8")
    client = TestClient(build_http_app())

    response = client.get(
        "/api/ui/files/content",
        params={"machine": "local", "path": "too-large.txt"},
    )

    assert response.status_code == 400
    assert "editor read limit" in response.json()["message"]
    assert (tmp_path / "too-large.txt").read_text(encoding="utf-8") == original


def test_file_manager_rejects_workspace_escape_and_recursive_self_copy(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.txt").write_text("data", encoding="utf-8")
    client = TestClient(build_http_app())

    escaped = client.post(
        "/api/ui/files/mkdir",
        json={"machine": "local", "path": "../escaped"},
    )
    recursive = client.post(
        "/api/ui/files/copy",
        json={"machine": "local", "path": "source", "destination": "source/nested"},
    )

    assert escaped.status_code == 400
    assert "escapes workspace" in escaped.json()["message"]
    assert recursive.status_code == 400
    assert "inside the source directory" in recursive.json()["message"]
    assert not (tmp_path.parent / "escaped").exists()
    assert not (source / "nested").exists()


@pytest.mark.asyncio
async def test_remote_human_file_action_keeps_worker_workspace_policy(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="escapes workspace"):
        await execute_worker_tool(
            "human_file_action",
            {"_human": True, "action": "touch", "path": "../escaped.txt"},
        )

    result = await execute_worker_tool(
        "human_file_action",
        {"_human": True, "action": "touch", "path": "safe.txt"},
    )
    assert result["path"] == "safe.txt"
    assert (tmp_path / "safe.txt").is_file()


def test_terminal_api_rejects_invalid_line_count(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    client = TestClient(build_http_app())

    response = client.get(
        "/api/ui/terminals/read",
        params={"machine": "local", "session_id": "missing", "lines": "many"},
    )

    assert response.status_code == 400
    assert response.json()["message"] == "lines must be an integer"


def test_terminal_dimensions_are_clamped_to_safe_limits():
    assert _bounded_int("2", default=120, minimum=20, maximum=500, label="cols") == 20
    assert _bounded_int("99999", default=120, minimum=20, maximum=500, label="cols") == 500
    with pytest.raises(ValueError, match="cols must be an integer"):
        _bounded_int("wide", default=120, minimum=20, maximum=500, label="cols")


def test_human_file_mutations_are_not_audited(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    client = TestClient(build_http_app())

    response = client.post(
        "/api/ui/files/write",
        json={"machine": "local", "path": "manual.txt", "content": "human"},
    )

    assert response.status_code == 200
    assert (tmp_path / "manual.txt").read_text(encoding="utf-8") == "human"
    audit_path = tmp_path / "audit.jsonl"
    assert not audit_path.exists() or audit_path.read_text(encoding="utf-8") == ""


def test_suppress_audit_context_excludes_manual_activity(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    audit("mcp_tool_call_start", tool="list_files", machine="worker-a")
    with suppress_audit():
        audit("shell_send", session="manual")
    audit("mcp_tool_call_end", tool="list_files", ok=True, machine="worker-a")

    records = [
        json.loads(line)
        for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [record["event"] for record in records] == [
        "mcp_tool_call_start",
        "mcp_tool_call_end",
    ]


def test_query_audit_filters_node_operation_and_order(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    path = tmp_path / "audit.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(record)
            for record in [
                {"ts": 10, "event": "mcp_tool_call_start", "tool": "read_file", "machine": "worker-a"},
                {"ts": 20, "event": "mcp_tool_call_start", "tool": "run_shell_tool", "machine": "worker-b"},
                {"ts": 30, "event": "mcp_tool_call_end", "tool": "run_shell_tool", "machine": "worker-b", "ok": True},
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = query_audit(node="worker-b", operation="run", sort="asc")

    assert result["total_matched"] == 2
    assert [entry["ts"] for entry in result["entries"]] == [20, 30]
    assert all(entry["node"] == "worker-b" for entry in result["entries"])


def test_webui_shell_is_public_but_api_remains_oauth_protected(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth_mode="oauth")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST", "false")
    get_settings.cache_clear()
    client = TestClient(build_http_app())

    page = client.get("/ui")
    api = client.get("/api/ui/bootstrap")

    assert page.status_code == 200
    assert "Human Interface" in page.text
    assert api.status_code == 401


def test_native_tui_token_bypasses_oauth_without_weakening_browser_api(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth_mode="oauth")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST", "false")
    get_settings.cache_clear()
    token = get_or_create_ui_local_token()
    client = TestClient(build_http_app())

    response = client.get(
        "/api/ui/bootstrap",
        headers={UI_LOCAL_TOKEN_HEADER: token},
    )

    assert response.status_code == 200
    assert response.json()["data"]["machines"]["machines"][0]["name"] == "local"


def _websocket_for_test(*, client_host: str = "127.0.0.1", protocols: list[str] | None = None) -> WebSocket:
    headers = [(b"host", b"control.example.com")]
    if protocols:
        headers.append((b"sec-websocket-protocol", ", ".join(protocols).encode()))
    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "scheme": "wss",
        "path": "/ui/ws",
        "raw_path": b"/ui/ws",
        "query_string": b"",
        "headers": headers,
        "client": (client_host, 4242),
        "server": ("control.example.com", 443),
        "subprotocols": protocols or [],
    }

    async def receive():
        return {"type": "websocket.disconnect"}

    async def send(message):  # noqa: ARG001
        return None

    return WebSocket(scope, receive, send)


def test_oauth_websocket_does_not_trust_loopback_reverse_proxy(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth_mode="oauth")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST", "true")
    get_settings.cache_clear()

    assert _authorize_websocket(_websocket_for_test(client_host="127.0.0.1")) is False


def test_none_auth_mode_allows_websocket_without_token(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth_mode="none")

    assert _authorize_websocket(_websocket_for_test(client_host="203.0.113.9")) is True


def test_websocket_origin_maps_to_http_oauth_resource(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth_mode="oauth")
    websocket = _websocket_for_test(client_host="203.0.113.9")

    assert public_base_url(websocket) == "https://control.example.com"
