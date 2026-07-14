from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route
from starlette.websockets import WebSocket

from local_shell_mcp.audit import audit, query_audit, suppress_audit
from local_shell_mcp.http_app import build_http_app
from local_shell_mcp.human_ui import (
    UI_FULL_SCOPES,
    _authorize_websocket,
    _bounded_int,
    _idle_timeout_remaining,
    _split_tui_command,
    _UnixPtyProcess,
    _validate_tui_api_base,
    _WindowsPtyProcess,
    api_files,
    ui_asset,
)
from local_shell_mcp.oauth import issue_access_token, public_base_url
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



def test_ui_assets_reject_symlinks_outside_asset_root(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    assets.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside-secret", encoding="utf-8")
    link = assets / "escape.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not available in this environment")
    monkeypatch.setattr("local_shell_mcp.human_ui._assets_dir", lambda: assets)

    app = Starlette(routes=[Route("/assets/{path:path}", ui_asset)])
    response = TestClient(app).get("/assets/escape.txt")

    assert response.status_code == 404
    assert "outside-secret" not in response.text


@pytest.mark.asyncio
async def test_local_file_api_does_not_block_event_loop(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    def slow_list(*args, **kwargs):  # noqa: ANN002, ANN003
        time.sleep(0.25)
        return []

    monkeypatch.setattr("local_shell_mcp.human_ui.list_dir", slow_list)
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/ui/files",
        "raw_path": b"/api/ui/files",
        "query_string": b"machine=local&path=.",
        "headers": [],
        "client": ("127.0.0.1", 4242),
        "server": ("127.0.0.1", 8765),
    }
    request = Request(scope)
    started = time.perf_counter()
    task = asyncio.create_task(api_files(request))
    await asyncio.sleep(0.05)

    assert time.perf_counter() - started < 0.15
    response = await task
    assert response.status_code == 200

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
    (tmp_path / "long.txt").write_bytes(content.encode("utf-8"))
    client = TestClient(build_http_app(), client=("127.0.0.1", 4242))

    response = client.get(
        "/api/ui/files/content",
        params={"machine": "local", "path": "long.txt"},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["truncated"] is False
    assert payload["content"] == content
    assert "line-349" in payload["content"]


def test_editor_rejects_stale_save_and_preserves_newer_file(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    path = tmp_path / "shared.txt"
    path.write_text("opened", encoding="utf-8")
    path.chmod(0o640)
    client = TestClient(build_http_app())

    loaded = client.get(
        "/api/ui/files/content",
        params={"machine": "local", "path": "shared.txt"},
    ).json()["data"]
    path.write_text("changed by MCP", encoding="utf-8")

    conflict = client.post(
        "/api/ui/files/write",
        json={
            "machine": "local",
            "path": "shared.txt",
            "content": "human edit",
            "overwrite": True,
            "expected_sha256": loaded["sha256"],
        },
    )

    assert conflict.status_code == 409
    assert "reload before saving" in conflict.json()["message"]
    assert path.read_text(encoding="utf-8") == "changed by MCP"

    current = client.get(
        "/api/ui/files/content",
        params={"machine": "local", "path": "shared.txt"},
    ).json()["data"]
    saved = client.post(
        "/api/ui/files/write",
        json={
            "machine": "local",
            "path": "shared.txt",
            "content": "merged edit",
            "overwrite": True,
            "expected_sha256": current["sha256"],
        },
    )
    assert saved.status_code == 200
    assert path.read_text(encoding="utf-8") == "merged edit"
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o640
    assert not list(tmp_path.glob(".shared.txt.*.tmp"))


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


def test_ui_path_rejects_reserved_and_ambiguous_mounts(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    for value in ["/", "/api/ui", "/oauth/panel", "/ui/../mcp", "ui"]:
        monkeypatch.setenv("LOCAL_SHELL_MCP_UI_PATH", value)
        get_settings.cache_clear()
        with pytest.raises(ValueError):
            get_settings()

    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_PATH", "/operator/console/")
    get_settings.cache_clear()
    assert get_settings().ui_path == "/operator/console"


def test_remotes_api_honors_disabled_server_configuration(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()
    client = TestClient(build_http_app())

    listing = client.get("/api/ui/remotes")
    invite = client.post("/api/ui/remotes", json={"name": "disabled"})
    rename = client.post(
        "/api/ui/remotes/rename",
        json={"machine": "missing", "new_name": "other"},
    )

    assert listing.status_code == 200
    assert listing.json()["data"]["enabled"] is False
    assert invite.status_code == 400
    assert rename.status_code == 400
    assert "disabled" in invite.json()["message"]


def test_todo_api_rejects_stale_human_revision(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    client = TestClient(build_http_app())

    initial = client.get("/api/ui/todos").json()["data"]
    first = client.put(
        "/api/ui/todos",
        json={
            "expected_revision": initial["revision"],
            "todos": [{"id": "a", "content": "first", "status": "pending", "priority": "medium"}],
        },
    )
    assert first.status_code == 200
    assert first.json()["data"]["revision"] == 1

    stale = client.put(
        "/api/ui/todos",
        json={
            "expected_revision": initial["revision"],
            "todos": [{"id": "b", "content": "stale", "status": "pending", "priority": "medium"}],
        },
    )
    assert stale.status_code == 409
    assert "changed from revision" in stale.json()["message"]

    latest = client.get("/api/ui/todos").json()["data"]
    assert latest["revision"] == 1
    assert [item["id"] for item in latest["todos"]] == ["a"]
    assert not list((tmp_path / ".state").glob(".todos.json.*.tmp"))


def test_terminal_api_rejects_invalid_line_count(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    client = TestClient(build_http_app())

    response = client.get(
        "/api/ui/terminals/read",
        params={"machine": "local", "session_id": "missing", "lines": "many"},
    )

    assert response.status_code == 400
    assert response.json()["message"] == "lines must be an integer"


def test_windows_tui_command_parser_preserves_backslashes_and_quotes():
    assert _split_tui_command(
        r'D:\a\local-shell-mcp\ui\dist\local-shell-mcp-tui.exe',
        windows=True,
    ) == [r'D:\a\local-shell-mcp\ui\dist\local-shell-mcp-tui.exe']
    assert _split_tui_command(
        r'"D:\Program Files\local-shell-mcp-tui.exe" --flag',
        windows=True,
    ) == [r'D:\Program Files\local-shell-mcp-tui.exe', "--flag"]


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


def test_audit_storage_remains_valid_under_concurrent_trim_and_append(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES", "3000")
    get_settings.cache_clear()

    def write(index: int) -> None:
        audit("mcp_tool_call_end", tool="read_file", index=index, detail="x" * 80)

    with ThreadPoolExecutor(max_workers=12) as executor:
        list(executor.map(write, range(240)))

    path = tmp_path / "audit.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    assert records
    assert all(record["event"] == "mcp_tool_call_end" for record in records)
    assert path.stat().st_size < 5000
    assert not list(tmp_path.glob(".audit.jsonl.*.tmp"))


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



def test_audit_node_and_session_filters_are_exact(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    path = get_settings().audit_log_path
    path.write_text(
        "\n".join(
            [
                json.dumps({"ts": 1, "event": "shell_send", "machine": "worker-a", "session": "term"}),
                json.dumps({"ts": 2, "event": "shell_send", "machine": "worker-a2", "session": "term"}),
                json.dumps({"ts": 3, "event": "shell_send", "machine": "worker-a", "session": "term-extra"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = query_audit(node="worker-a", session="term")

    assert result["total_matched"] == 1
    assert result["entries"][0]["ts"] == 1

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
    client = TestClient(build_http_app(), client=("127.0.0.1", 4242))

    response = client.get(
        "/api/ui/bootstrap",
        headers={UI_LOCAL_TOKEN_HEADER: token},
    )

    assert response.status_code == 200
    assert response.json()["data"]["machines"]["machines"][0]["name"] == "local"



def test_native_tui_token_is_rejected_from_non_loopback_peer(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth_mode="oauth")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST", "false")
    get_settings.cache_clear()
    token = get_or_create_ui_local_token()
    client = TestClient(build_http_app(), client=("203.0.113.9", 4242))

    response = client.get(
        "/api/ui/bootstrap",
        headers={UI_LOCAL_TOKEN_HEADER: token},
    )

    assert response.status_code == 401


def test_human_ui_rejects_destructive_action_without_write_scope(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth_mode="oauth")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_OAUTH_JWT_SECRET", "scope-test-secret-which-is-at-least-32-bytes")
    get_settings.cache_clear()
    victim = tmp_path / "victim.txt"
    victim.write_text("keep", encoding="utf-8")
    token = issue_access_token(
        client_id="read-only",
        scope="shell:read",
        resource="http://testserver",
        issuer="http://testserver",
    )
    client = TestClient(build_http_app(), client=("203.0.113.9", 4242))

    response = client.post(
        "/api/ui/files/delete",
        headers={"Authorization": f"Bearer {token}"},
        json={"machine": "local", "path": "victim.txt"},
    )

    assert response.status_code == 403
    assert response.headers["www-authenticate"].startswith('Bearer error="insufficient_scope"')
    assert victim.read_text(encoding="utf-8") == "keep"


def test_native_tui_api_base_must_be_loopback():
    assert _validate_tui_api_base("http://127.0.0.1:8765/api/ui/") == (
        "http://127.0.0.1:8765/api/ui"
    )
    assert _validate_tui_api_base("https://localhost:8765/api/ui") == (
        "https://localhost:8765/api/ui"
    )
    with pytest.raises(ValueError, match="loopback"):
        _validate_tui_api_base("https://control.example.com/api/ui")

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



def _bearer_protocol(token: str) -> str:
    encoded = base64.urlsafe_b64encode(token.encode()).decode().rstrip("=")
    return f"bearer.{encoded}"


def test_websocket_requires_full_human_ui_scope_set(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth_mode="oauth")
    monkeypatch.setenv("LOCAL_SHELL_MCP_OAUTH_JWT_SECRET", "scope-test-secret-which-is-at-least-32-bytes")
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "https://control.example.com")
    monkeypatch.setenv("LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN", "long-random-test-pin")
    get_settings.cache_clear()
    read_only = issue_access_token(
        client_id="read-only",
        scope="shell:read",
        resource="https://control.example.com",
        issuer="https://control.example.com",
    )
    full = issue_access_token(
        client_id="full-ui",
        scope=" ".join(UI_FULL_SCOPES),
        resource="https://control.example.com",
        issuer="https://control.example.com",
    )

    assert (
        _authorize_websocket(
            _websocket_for_test(
                client_host="203.0.113.9",
                protocols=["lsm-ui", _bearer_protocol(read_only)],
            )
        )
        is False
    )
    assert (
        _authorize_websocket(
            _websocket_for_test(
                client_host="203.0.113.9",
                protocols=["lsm-ui", _bearer_protocol(full)],
            )
        )
        is True
    )

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


def test_http_localhost_bypass_is_not_inherited_by_reverse_proxy(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth_mode="oauth")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODE", "http")
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST", "true")
    monkeypatch.setenv("LOCAL_SHELL_MCP_OAUTH_JWT_SECRET", "x" * 32)
    get_settings.cache_clear()
    client = TestClient(build_http_app(), client=("127.0.0.1", 4242))

    direct = client.get("/tools/version", headers={"Host": "127.0.0.1:8765"})
    proxied = client.get(
        "/tools/version",
        headers={
            "Host": "public.example.test",
            "X-Forwarded-For": "203.0.113.9",
            "X-Forwarded-Proto": "https",
        },
    )

    assert direct.status_code == 200
    assert proxied.status_code == 401


def test_invalid_ui_token_path_fails_without_recursion(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    token_path = tmp_path / ".state" / "ui" / "local-token"
    token_path.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="invalid UI local token path"):
        get_or_create_ui_local_token()


def test_permission_error_for_existing_ui_token_path_is_reported(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    token_path = tmp_path / ".state" / "ui" / "local-token"
    token_path.mkdir(parents=True)
    real_open = os.open

    def permission_denied(path, flags, mode=0o777):  # noqa: ANN001
        if os.fspath(path) == os.fspath(token_path):
            raise PermissionError(13, "Permission denied", os.fspath(path))
        return real_open(path, flags, mode)

    monkeypatch.setattr(os, "open", permission_denied)

    with pytest.raises(RuntimeError, match="invalid UI local token path"):
        get_or_create_ui_local_token()


def test_terminal_idle_timeout_uses_latest_input_or_output_activity():
    assert _idle_timeout_remaining(100.0, 60.0, 130.0) == 30.0
    assert _idle_timeout_remaining(100.0, 60.0, 160.0) == 0.0
    assert _idle_timeout_remaining(150.0, 60.0, 160.0) == 50.0


@pytest.mark.asyncio
async def test_unix_pty_write_retries_short_writes(monkeypatch):
    process = _UnixPtyProcess.__new__(_UnixPtyProcess)
    process.master_fd = 123
    written = bytearray()

    attempts = 0
    waits = []

    def short_write(fd, data):
        nonlocal attempts
        assert fd == 123
        attempts += 1
        if attempts == 2:
            raise BlockingIOError
        count = min(2, len(data))
        written.extend(bytes(data[:count]))
        return count

    monkeypatch.setattr("local_shell_mcp.human_ui.os.write", short_write)
    monkeypatch.setattr(
        "local_shell_mcp.human_ui.select.select",
        lambda read, write, error, timeout: waits.append((read, write, error, timeout)),
    )
    await process.write(b"abcdef")
    assert bytes(written) == b"abcdef"
    assert waits == [([], [123], [], 0.1)]


@pytest.mark.asyncio
async def test_windows_pty_write_accepts_zero_from_async_pywinpty():
    process = _WindowsPtyProcess.__new__(_WindowsPtyProcess)
    calls = []

    class FakeProcess:
        def write(self, text):
            calls.append(text)
            return 0

    process.process = FakeProcess()
    await process.write(b"\x1bOR")

    assert calls == ["\x1bOR"]
