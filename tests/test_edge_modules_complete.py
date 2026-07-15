from __future__ import annotations

import asyncio
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.requests import Request

import local_shell_mcp.audit as audit_module
import local_shell_mcp.auth as auth
import local_shell_mcp.conpty_ops as conpty_ops
import local_shell_mcp.http_app as http_app
import local_shell_mcp.playwright_ops as playwright
import local_shell_mcp.search_ops as search
import local_shell_mcp.tmux_helper as tmux_helper
import local_shell_mcp.ui_security as ui_security
import local_shell_mcp.version as version
from local_shell_mcp.models import CommandResult
from local_shell_mcp.settings import get_settings


def _configure(tmp_path, monkeypatch, **extra):
    values = {
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT": str(tmp_path),
        "LOCAL_SHELL_MCP_STATE_DIR": str(tmp_path / ".state"),
        "LOCAL_SHELL_MCP_AUDIT_LOG_PATH": str(tmp_path / "audit.jsonl"),
        "LOCAL_SHELL_MCP_AUTH_MODE": "none",
        "LOCAL_SHELL_MCP_MAX_HTTP_REQUEST_BYTES": "16",
    }
    values.update({key: str(value) for key, value in extra.items()})
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


def _request(
    path="/tools/read_file",
    *,
    headers=None,
    client=("127.0.0.1", 1),
    method="GET",
):
    raw_headers = [(name.lower().encode(), value.encode()) for name, value in (headers or {}).items()]
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": raw_headers,
            "client": client,
            "server": ("test", 80),
        }
    )


def test_audit_sanitization_trimming_and_all_filters(tmp_path, monkeypatch):
    _configure(
        tmp_path,
        monkeypatch,
        LOCAL_SHELL_MCP_AUTH_MODE="oauth",
        LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN="configured-secret-pin",
        LOCAL_SHELL_MCP_OAUTH_JWT_SECRET="configured-secret-key-that-is-long-enough",
        LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES=200,
        LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES=40,
    )
    settings = get_settings()
    secrets = audit_module._audit_configured_secrets(settings)
    assert "configured-secret-pin" in secrets
    redacted = audit_module._redact_audit_text(
        "Bearer abc.def configured-secret-pin ghp_" + "x" * 30 + "z" * 3000,
        secrets,
    )
    assert "configured-secret-pin" not in redacted
    assert "Bearer" not in redacted
    assert audit_module._redact_audit_text("z" * 3000, ()).endswith("…<truncated>")

    value = audit_module._sanitize_audit_value(
        {
            "token": "hidden",
            "api_token": "hidden",
            "token_id": "visible",
            "db_password": "hidden",
            "items": list(range(110)),
            "tuple": (1, 2),
            "object": object(),
        },
        secrets,
    )
    assert value["token"] == "<redacted>"
    assert value["api_token"] == "<redacted>"
    assert value["token_id"] == "visible"
    assert value["db_password"] == "<redacted>"
    assert len(value["items"]) == 100
    assert value["tuple"] == [1, 2]
    assert "object at" in value["object"]

    path = settings.audit_log_path
    audit_module._trim_audit_log(path, 100)
    path.write_text("short\n", encoding="utf-8")
    audit_module._trim_audit_log(path, 100)
    path.write_text(("x" * 60 + "\n") * 10, encoding="utf-8")
    audit_module._trim_audit_log(path, 100)
    assert path.stat().st_size <= 100

    settings.max_audit_tail_bytes = 10_000
    settings.max_audit_log_bytes = 10_000
    rows = [
        {"ts": 1, "event": "mcp_tool_call_start", "tool": "read_file", "machine": "a", "session": "s", "detail": "needle"},
        {"ts": 2, "event": "oauth_auth_failed", "node": "b", "session": "x"},
        ["not", "dict"],
    ]
    path.write_text("bad-json\n" + "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    matched = audit_module.query_audit(
        limit=9999,
        node="a",
        event="call",
        operation="read",
        session="s",
        search="needle",
        start_ts=0,
        end_ts=1,
        sort="asc",
    )
    assert matched["total_matched"] == 1
    assert matched["entries"][0]["operation"] == "read"
    assert audit_module._operation_type({}) == "other"
    assert audit_module._operation_type({"event": "remote_worker_registered"}) == "worker"


def test_auth_scopes_hosts_tokens_and_metadata(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    principal = auth.Principal(None, "x", {"scope": ["read", 2, ""]})
    assert auth.principal_scopes(principal) == {"read", "2"}
    assert auth.principal_scopes(auth.Principal(None, None, {"scope": 1})) == set()
    auth.require_scopes(principal, [])
    auth.require_scopes(auth.Principal(None, None, {"auth": "none"}), ["missing"])
    with pytest.raises(HTTPException) as exc:
        auth.require_scopes(principal, ["missing", "read"])
    assert exc.value.status_code == 403
    assert "scope=" in exc.value.headers["WWW-Authenticate"]

    token = auth._CURRENT_PRINCIPAL.set(principal)
    try:
        with pytest.raises(HTTPException):
            auth.require_current_scopes(["missing"])
    finally:
        auth._CURRENT_PRINCIPAL.reset(token)
    auth.require_current_scopes(["missing"])

    expected = {
        "/tools/download/create": ("shell:read", "file:share"),
        "/tools/todo": ("shell:read",),
        "/tools/write_file": ("shell:read", "shell:write"),
        "/tools/run_shell": ("shell:read", "shell:execute"),
        "/tools/browser/text": ("browser:use",),
        "/tools/browser/capture": ("browser:use", "shell:write"),
        "/tools/playwright/run_script": ("browser:use", "shell:execute"),
        "/tools/other": ("shell:read",),
        "/other": (),
    }
    for path, scopes in expected.items():
        method = "GET" if path == "/tools/todo" else None
        assert auth.required_scopes_for_http_tool(path, method) == scopes
    assert auth.required_scopes_for_http_tool("/tools/todo", "POST") == (
        "shell:read",
        "shell:write",
    )

    for host, result in (
        ("localhost", True),
        ("127.0.0.1:123", True),
        ("[::1]:123", True),
        ("[::1", True),
        ("example.com", False),
        ("", False),
    ):
        assert auth._host_header_is_loopback(_request(headers={"host": host})) is result
    assert auth._is_localhost(_request(client=None)) is False
    assert auth._extract_token(_request(headers={"authorization": "Bearer abc"})) == "abc"
    assert auth._extract_token(_request(headers={"authorization": "Basic abc"})) is None

    monkeypatch.setenv("LOCAL_SHELL_MCP_UI_PATH", "/console")
    get_settings.cache_clear()
    for path in (
        "/healthz",
        "/remote/transfer/x",
        "/.well-known/x",
        "/oauth/x",
        "/download/x",
        "/console",
        "/console/",
        "/console/callback",
        "/console/wallpaper",
        "/console/assets/app.js",
    ):
        assert auth._is_public_path(path)
    assert not auth._is_public_path("/private")


def test_auth_oauth_body_and_mcp_helpers(tmp_path, monkeypatch):
    _configure(
        tmp_path,
        monkeypatch,
        LOCAL_SHELL_MCP_AUTH_MODE="oauth",
        LOCAL_SHELL_MCP_OAUTH_JWT_SECRET="x" * 40,
        LOCAL_SHELL_MCP_PUBLIC_BASE_URL="http://testserver",
    )
    settings = get_settings()
    with pytest.raises(HTTPException, match="Missing OAuth"):
        auth._verify_oauth(_request(), settings)

    import local_shell_mcp.oauth as oauth

    monkeypatch.setattr(oauth, "validate_bearer_token", lambda *args: (_ for _ in ()).throw(jwt.InvalidTokenError("bad")))
    with pytest.raises(HTTPException, match="Invalid OAuth"):
        auth._verify_oauth(
            _request(headers={"authorization": "Bearer bad"}), settings
        )
    monkeypatch.setattr(oauth, "validate_bearer_token", lambda *args: {"sub": "user", "scope": "shell:read"})
    verified = auth._verify_oauth(
        _request(headers={"authorization": "Bearer good"}), settings
    )
    assert verified.subject == "user"

    messages = iter(
        [
            {"type": "http.request", "body": b"a", "more_body": True},
            {"type": "http.disconnect"},
        ]
    )

    async def receive():
        return next(messages)

    assert asyncio.run(auth._read_body(receive)) == b"a"

    messages = iter([{"type": "http.request", "body": b"too long", "more_body": False}])

    async def large_receive():
        return next(messages)

    with pytest.raises(auth.RequestBodyTooLarge):
        asyncio.run(auth._read_body(large_receive, 2))

    original_calls = []

    async def original_receive():
        original_calls.append(True)
        return {"type": "http.disconnect"}

    replay = auth._body_receive(b"body", original_receive)
    assert asyncio.run(replay())["body"] == b"body"
    assert asyncio.run(replay())["type"] == "http.disconnect"
    assert original_calls

    assert auth._mcp_methods_from_body(b"") == set()
    assert auth._mcp_methods_from_body(b"bad") == set()
    assert auth._mcp_methods_from_body(b"[1,{\"method\":\"ping\"}]") == {"ping"}
    assert not auth._is_mcp_discovery_request({"path": "/other", "method": "POST"}, b"{}")
    assert not auth._is_mcp_discovery_request({"path": "/mcp", "method": "POST"}, b"[]")


def test_auth_middlewares_all_fast_paths(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, LOCAL_SHELL_MCP_MCP_MAX_SESSIONS=1)
    calls = []
    sent = []

    async def app(scope, receive, send):
        calls.append(scope)

    async def receive():
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def send(message):
        sent.append(message)

    manager = SimpleNamespace(
        _server_instances={
            "dead": SimpleNamespace(is_terminated=True),
            "live": SimpleNamespace(is_terminated=False),
        },
        _session_owners={"dead": "x", "live": "y"},
    )
    limiter = auth.McpSessionLimitMiddleware(app, manager)
    assert limiter._active_session_count() == 1
    assert "dead" not in manager._server_instances
    assert limiter._is_new_session({"type": "websocket"}) is False
    assert limiter._is_new_session({"type": "http", "path": "/other", "method": "POST"}) is False
    assert limiter._is_new_session(
        {
            "type": "http",
            "path": "/mcp",
            "method": "POST",
            "headers": [(b"mcp-session-id", b"x")],
        }
    ) is False
    asyncio.run(
        limiter(
            {"type": "http", "path": "/mcp", "method": "POST", "headers": []},
            receive,
            send,
        )
    )
    assert sent[0]["status"] == 429

    manager._server_instances = []
    assert limiter._active_session_count() == 0
    calls.clear()
    asyncio.run(limiter({"type": "http", "path": "/other", "method": "GET"}, receive, send))
    assert calls

    middleware = auth.AuthMiddleware(app)
    calls.clear()
    asyncio.run(middleware({"type": "websocket", "path": "/x"}, receive, send))
    assert calls
    calls.clear()
    asyncio.run(middleware({"type": "http", "path": "/healthz", "method": "GET"}, receive, send))
    assert calls

    body_limit = auth.RequestBodyLimitMiddleware(app)
    calls.clear()
    asyncio.run(body_limit({"type": "http", "path": "/x", "method": "GET"}, receive, send))
    assert calls
    calls.clear()
    asyncio.run(
        body_limit(
            {"type": "http", "path": "/remote/transfer/upload/x", "method": "PUT"},
            receive,
            send,
        )
    )
    assert calls

    sent.clear()
    asyncio.run(
        body_limit(
            {
                "type": "http",
                "path": "/x",
                "method": "POST",
                "headers": [(b"content-length", b"999")],
            },
            receive,
            send,
        )
    )
    assert sent[0]["status"] == 413
    calls.clear()
    asyncio.run(
        body_limit(
            {
                "type": "http",
                "path": "/x",
                "method": "POST",
                "headers": [(b"content-length", b"invalid")],
            },
            receive,
            send,
        )
    )
    assert calls and calls[-1][auth._REQUEST_BODY_SCOPE_KEY] == b"{}"


def test_playwright_helpers_and_generated_scripts(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, LOCAL_SHELL_MCP_MAX_FILE_WRITE_BYTES=4)
    with pytest.raises(ValueError, match="Refusing"):
        playwright._assert_script_size("12345")
    playwright._assert_script_size("1234")
    with pytest.raises(ValueError, match="browser"):
        playwright._validate_browser("edge", "load")
    with pytest.raises(ValueError, match="wait_until"):
        playwright._validate_browser("chromium", "later")

    captured = []

    async def generated(script, **kwargs):
        captured.append((script, kwargs))
        return {"ok": True}

    monkeypatch.setattr(playwright, "_run_generated_script", generated)
    result = asyncio.run(
        playwright.browser_get_text("https://example.test", "firefox", "load", "main")
    )
    assert result["ok"] is True
    assert "locator('main')" in captured[-1][0]

    with pytest.raises(ValueError, match="capture_format"):
        asyncio.run(playwright.browser_capture("x", capture_format="jpg"))
    with pytest.raises(ValueError, match="requires chromium"):
        asyncio.run(playwright.browser_capture("x", capture_format="pdf", browser="firefox"))

    out = tmp_path / "shot.png"

    async def make_capture(script, **kwargs):
        out.write_bytes(b"png")
        return {"ok": True}

    monkeypatch.setattr(playwright, "_run_generated_script", make_capture)
    capture = asyncio.run(
        playwright.browser_capture("x", str(out), capture_format=" PNG ", width="10", height="20")
    )
    assert capture["capture_path"].endswith("shot.png")
    monkeypatch.setattr(playwright, "_run_generated_script", lambda *args, **kwargs: asyncio.sleep(0, result={"ok": False}))
    capture = asyncio.run(playwright.browser_capture("x", str(out)))
    assert capture["capture_path"] is None

    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_FILE_WRITE_BYTES", "1000")
    get_settings.cache_clear()
    commands = []

    async def run_shell(command, **kwargs):
        commands.append((command, kwargs))
        return CommandResult(
            ok=True,
            exit_code=0,
            timed_out=False,
            duration_ms=1,
            cwd=".",
            command=command,
            stdout="",
            stderr="",
            truncated=False,
        )

    monkeypatch.setattr(playwright, "run_shell", run_shell)
    custom = asyncio.run(playwright.playwright_run_script("print(1)", cwd=".", timeout_s=2))
    assert custom["script_path"].endswith(".py")
    assert commands[-1][1]["max_output_bytes"] == 1_000_000


def test_tmux_selection_backend_and_version(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(tmux_helper.platform, "system", lambda: "Linux")
    for machine, tag in (("AMD64", "linux-x86_64"), ("arm64", "linux-aarch64"), ("riscv", None)):
        monkeypatch.setattr(tmux_helper.platform, "machine", lambda value=machine: value)
        assert tmux_helper._platform_tag() == tag
    monkeypatch.setattr(tmux_helper.platform, "system", lambda: "Windows")
    monkeypatch.setattr(tmux_helper.platform, "machine", lambda: "x86_64")
    assert tmux_helper._platform_tag() is None

    helper = tmp_path / "tmux"
    helper.write_text("x", encoding="utf-8")
    monkeypatch.setattr(tmux_helper, "_platform_tag", lambda: "linux-x86_64")
    monkeypatch.setattr(tmux_helper.Path, "resolve", lambda self: tmp_path / "module.py")
    assert tmux_helper.bundled_tmux_path() is None

    monkeypatch.setattr(tmux_helper, "bundled_tmux_path", lambda: helper)
    monkeypatch.setattr(tmux_helper.shutil, "which", lambda value: "/usr/bin/tmux" if value == "tmux" else None)
    assert tmux_helper.resolve_tmux().source == "system"

    configured = tmp_path / "configured"
    configured.write_text("x", encoding="utf-8")
    configured.chmod(configured.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("LOCAL_SHELL_MCP_TMUX_BIN", str(configured))
    get_settings.cache_clear()
    monkeypatch.setattr(tmux_helper.shutil, "which", lambda value: None)
    assert tmux_helper.resolve_tmux().source == "configured"

    monkeypatch.setenv("LOCAL_SHELL_MCP_TMUX_BIN", "missing")
    get_settings.cache_clear()
    assert tmux_helper.resolve_tmux().source == "bundled"
    monkeypatch.setattr(tmux_helper, "bundled_tmux_path", lambda: None)
    assert tmux_helper.resolve_tmux().source == "native"
    assert tmux_helper.tmux_socket_name().startswith("local-shell-mcp-")

    os_proxy = SimpleNamespace(**{**vars(os), "name": "posix"})
    monkeypatch.setattr(tmux_helper, "os", os_proxy)
    monkeypatch.setattr(
        tmux_helper,
        "resolve_tmux",
        lambda: tmux_helper.TmuxSelection("/tmux", "bundled"),
    )
    info = tmux_helper.persistent_shell_backend_info()
    assert info["backend"] == "tmux-bundled"
    assert info["tmux_helper_version"] == tmux_helper.TMUX_HELPER_VERSION
    monkeypatch.setattr(tmux_helper, "resolve_tmux", lambda: tmux_helper.TmuxSelection(None, "native"))
    assert tmux_helper.persistent_shell_backend_info()["backend"] == "native"

    os_proxy.name = "nt"
    monkeypatch.setattr(conpty_ops, "is_available", lambda: True)
    assert tmux_helper.persistent_shell_backend_info()["backend"] == "conpty"
    monkeypatch.setattr(conpty_ops, "is_available", lambda: False)
    assert tmux_helper.persistent_shell_backend_info()["backend"] == "native"

    monkeypatch.setattr(version.importlib_metadata, "version", lambda name: "9.9")
    assert version.package_version() == "9.9"
    monkeypatch.setattr(
        version.importlib_metadata,
        "version",
        lambda name: (_ for _ in ()).throw(version.importlib_metadata.PackageNotFoundError()),
    )
    assert version.package_version() == version.__version__
    assert "package 2.0" in version.format_version_info({"version": "1.0", "package_version": "2.0"})
    assert version.format_version_info({"version": "1.0", "package_version": "1.0"}) == "local-shell-mcp 1.0"


def test_ui_security_creation_races_and_loopback(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    inherited = "i" * 32
    monkeypatch.setenv(ui_security.UI_LOCAL_TOKEN_ENV, inherited)
    assert ui_security.get_or_create_ui_local_token() == inherited
    monkeypatch.delenv(ui_security.UI_LOCAL_TOKEN_ENV)

    path = ui_security._token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("e" * 32, encoding="utf-8")
    assert ui_security.get_or_create_ui_local_token() == "e" * 32
    path.write_text("short", encoding="utf-8")
    assert ui_security._read_token(path) is None

    real_open = os.open
    attempts = 0

    def race_open(target, flags, mode=0o777):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            path.write_text("r" * 32, encoding="utf-8")
            raise FileExistsError(target)
        return real_open(target, flags, mode)

    monkeypatch.setattr(ui_security.os, "open", race_open)
    assert ui_security.get_or_create_ui_local_token() == "r" * 32

    connection = _request(headers={ui_security.UI_LOCAL_TOKEN_HEADER: "r" * 32})
    assert ui_security.has_valid_ui_local_token(connection)
    assert not ui_security.has_valid_ui_local_token(_request())
    for client, expected in (
        (("localhost", 1), True),
        (("127.0.0.1", 1), True),
        (("[::1]", 1), True),
        (("fe80::1%eth0", 1), False),
        (("invalid", 1), False),
        (None, False),
    ):
        assert ui_security.is_loopback_connection(_request(client=client)) is expected


def test_search_real_tree_and_fake_grep_branches(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, LOCAL_SHELL_MCP_MAX_TREE_ENTRIES=2)
    file_path = tmp_path / "file.txt"
    file_path.write_text("x", encoding="utf-8")
    non_dir = search.tree_sync("file.txt")
    assert non_dir["is_directory"] is False
    missing = search.tree_sync("missing/child")
    assert missing["exists"] is False

    (tmp_path / ".git").mkdir()
    (tmp_path / "dir").mkdir()
    (tmp_path / "dir" / "nested.txt").write_text("x", encoding="utf-8")
    (tmp_path / "other.txt").write_text("x", encoding="utf-8")
    tree = search.tree_sync(".", depth=10, max_entries=2)
    assert tree["truncated"] is True
    assert not any(".git" in row for row in tree["entries"])
    async_tree = asyncio.run(search.tree(".", 1, 10))
    assert async_tree["exists"] is True

    class Stream:
        def __init__(self, lines=None, data=b""):
            self.lines = list(lines or [])
            self.data = data

        async def readline(self):
            return self.lines.pop(0) if self.lines else b""

        async def read(self, size):
            return self.data

    class Process:
        def __init__(self):
            match = {
                "type": "match",
                "data": {
                    "path": {"text": "file.txt"},
                    "line_number": 1,
                    "submatches": [{"start": 2}],
                    "lines": {"text": "hello\n"},
                },
            }
            self.stdout = Stream([b"not-json\n", json.dumps({"type": "summary"}).encode() + b"\n", json.dumps(match).encode() + b"\n"])
            self.stderr = Stream(data=b"e" * 100)
            self.returncode = 0
            self.terminated = False

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        async def wait(self):
            return self.returncode

    process = Process()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", lambda *args, **kwargs: asyncio.sleep(0, result=process))
    monkeypatch.setattr(search, "_close_process_transport", lambda proc: asyncio.sleep(0))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_OUTPUT_BYTES", "10")
    get_settings.cache_clear()
    result = asyncio.run(search.grep("hello", regex=False, case_sensitive=False, glob="*.txt", max_results=1))
    assert result["count"] == 1
    assert result["matches"][0]["column"] == 3
    assert result["truncated"] is True
    assert process.terminated is True



def test_http_app_executes_every_route_wrapper(tmp_path, monkeypatch):
    _configure(
        tmp_path,
        monkeypatch,
        LOCAL_SHELL_MCP_MAX_HTTP_REQUEST_BYTES=10_000,
    )

    async def async_value(*args, **kwargs):
        return {"args": list(args), "kwargs": kwargs}

    def sync_value(*args, **kwargs):
        return {"args": list(args), "kwargs": kwargs}

    monkeypatch.setattr(http_app, "list_installed_skills", sync_value)
    monkeypatch.setattr(http_app, "load_installed_skill", sync_value)
    monkeypatch.setattr(http_app, "read_installed_skill_file", sync_value)
    monkeypatch.setattr(http_app, "public_run_shell", lambda *args, **kwargs: asyncio.sleep(0, result=SimpleNamespace(model_dump=lambda: {"shell": True})))
    for name in (
        "start_shell", "send_shell", "read_shell", "kill_shell", "list_shells",
        "tree", "grep", "browser_capture", "browser_get_text", "playwright_run_script",
    ):
        monkeypatch.setattr(http_app, name, async_value)
    for name in (
        "list_dir", "glob_paths", "create_download_link", "list_download_links",
        "revoke_download_link", "read_texts", "write_text", "edit_text", "delete_path",
        "todo_read", "todo_write",
    ):
        monkeypatch.setattr(http_app, name, sync_value)
    monkeypatch.setattr(
        http_app,
        "download_endpoint",
        lambda request: asyncio.sleep(0, result=JSONResponse({"download": True})),
    )
    monkeypatch.setattr(http_app, "ui_routes", lambda: [])
    client = TestClient(http_app.build_http_app())

    requests = [
        ("get", "/tools/skills_list", None),
        ("post", "/tools/skill_load", {"name": "skill"}),
        ("post", "/tools/skill_read_file", {"name": "skill", "path": "guide.md"}),
        ("post", "/tools/run_shell", {"command": "true", "timeout_s": None, "max_output_bytes": None}),
        ("post", "/tools/shell_start", {}),
        ("post", "/tools/shell_send", {"session_id": "s", "input_text": "x", "enter": False}),
        ("post", "/tools/shell_read", {"session_id": "s", "lines": 10}),
        ("post", "/tools/shell_kill", {"session_id": "s"}),
        ("get", "/tools/shell_list", None),
        ("post", "/tools/list_files", {"recursive": True, "max_entries": 3}),
        ("post", "/tools/tree", {"depth": 2, "max_entries": 3}),
        ("post", "/tools/glob", {"pattern": "*", "max_results": 3}),
        ("post", "/tools/grep", {"query": "x", "regex": False, "case_sensitive": False, "max_results": None}),
        ("get", "/download/token", None),
        ("post", "/tools/download/create", {"path": "x", "ttl_s": None, "max_downloads": None}),
        ("get", "/tools/download/list?include_expired=true", None),
        ("post", "/tools/download/revoke", {"token": "x"}),
        ("post", "/tools/read_file", {"path": "x", "start_line": None, "end_line": None}),
        ("post", "/tools/write_file", {"path": "x", "content": "y", "overwrite": False}),
        ("post", "/tools/edit_file", {"path": "x", "edits": []}),
        ("post", "/tools/delete", {"path": "x", "recursive": True}),
        ("get", "/tools/todo", None),
        ("post", "/tools/todo", {"todos": []}),
        ("post", "/tools/browser/capture", {"url": "x", "full_page": False, "width": 1, "height": 2}),
        ("post", "/tools/browser/text", {"url": "x"}),
        ("post", "/tools/playwright/run_script", {"script": "x", "timeout_s": 2}),
    ]
    for method, path, body in requests:
        response = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
        assert response.status_code == 200, (method, path, response.text)

    monkeypatch.setattr(
        http_app,
        "public_run_shell",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad timeout")),
    )
    client = TestClient(http_app.build_http_app())
    assert client.post("/tools/run_shell", json={"command": "x"}).status_code == 400
    assert client.post("/tools/skill_load", json={"name": "x", "extra": 1}).status_code == 400


def test_search_timeout_no_stream_and_tree_permission_branches(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    class TimeoutStream:
        async def readline(self):
            raise TimeoutError

    class Process:
        stdout = TimeoutStream()
        stderr = None
        returncode = None
        terminated = False

        def terminate(self):
            self.terminated = True

        async def wait(self):
            self.returncode = -15
            return self.returncode

    process = Process()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", lambda *args, **kwargs: asyncio.sleep(0, result=process))
    monkeypatch.setattr(search, "_close_process_transport", lambda proc: asyncio.sleep(0))
    result = asyncio.run(search.grep("x"))
    assert result["ok"] is False
    assert process.terminated is True
    assert result["stderr"] == ""

    directory = tmp_path / "blocked"
    directory.mkdir()
    real_iterdir = Path.iterdir

    def iterdir(path):
        if path == directory:
            raise OSError("denied")
        return real_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", iterdir)
    tree_result = search.tree_sync("blocked")
    assert tree_result["entries"] == []


def test_bundled_tmux_permissions_and_windows_import_failure(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    module_path = tmp_path / "tmux_helper.py"
    helper = tmp_path / "helpers" / "linux-x86_64" / "tmux"
    helper.parent.mkdir(parents=True)
    helper.write_text("binary", encoding="utf-8")
    monkeypatch.setattr(tmux_helper, "__file__", str(module_path))
    monkeypatch.setattr(tmux_helper, "_platform_tag", lambda: "linux-x86_64")

    access_calls = iter([False, True])
    monkeypatch.setattr(tmux_helper.os, "access", lambda *args: next(access_calls))
    assert tmux_helper.bundled_tmux_path() == helper

    helper.chmod(0o600)
    monkeypatch.setattr(tmux_helper.os, "access", lambda *args: False)
    monkeypatch.setattr(Path, "chmod", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("chmod")))
    assert tmux_helper.bundled_tmux_path() is None

    monkeypatch.setattr(tmux_helper, "_platform_tag", lambda: None)
    assert tmux_helper.bundled_tmux_path() is None
    os_proxy = SimpleNamespace(**{**vars(os), "name": "nt"})
    monkeypatch.setattr(tmux_helper, "os", os_proxy)
    monkeypatch.setattr(conpty_ops, "is_available", lambda: (_ for _ in ()).throw(RuntimeError("import")))
    assert tmux_helper.persistent_shell_backend_info()["backend"] == "native"


def test_ui_token_irrecoverable_paths_and_final_retry(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    path = ui_security._token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.delenv(ui_security.UI_LOCAL_TOKEN_ENV, raising=False)

    monkeypatch.setattr(ui_security.os, "open", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("open")))
    monkeypatch.setattr(Path, "lstat", lambda self: (_ for _ in ()).throw(FileNotFoundError(self)))
    with pytest.raises(RuntimeError, match="Unable to create"):
        ui_security.get_or_create_ui_local_token()

    path.write_text("short", encoding="utf-8")
    monkeypatch.setattr(Path, "lstat", lambda self: SimpleNamespace())
    monkeypatch.setattr(Path, "unlink", lambda self: (_ for _ in ()).throw(PermissionError("unlink")))
    with pytest.raises(RuntimeError, match="replace invalid"):
        ui_security.get_or_create_ui_local_token()

    unlink_calls = []
    monkeypatch.setattr(Path, "unlink", lambda self: unlink_calls.append(str(self)))
    monkeypatch.setattr(ui_security, "_read_token", lambda path: None)
    with pytest.raises(RuntimeError, match="initialize"):
        ui_security.get_or_create_ui_local_token()
    assert len(unlink_calls) == 2
