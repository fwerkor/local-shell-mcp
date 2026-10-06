from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
from types import SimpleNamespace

import pytest
from starlette.exceptions import HTTPException
from starlette.requests import Request

import local_shell_mcp.cli_call as cli_call
import local_shell_mcp.settings as settings_module
import local_shell_mcp.tools as tools_module
from local_shell_mcp.auth import _CURRENT_PRINCIPAL, Principal, verify_request
from local_shell_mcp.session_runtime import get_session_runtime_manager
from local_shell_mcp.ui_security import (
    CLI_LOCAL_TOKEN_HEADER,
    CLI_LOCAL_TOKEN_SHA256_ENV,
    UI_LOCAL_TOKEN_HEADER,
    get_or_create_ui_local_token,
)


def _configure(tmp_path, monkeypatch, *, mode: str = "mcp", auth_mode: str = "oauth") -> None:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODE", mode)
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", auth_mode)
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    settings_module.get_settings.cache_clear()


def _request(
    path: str,
    headers: list[tuple[bytes, bytes]] | None = None,
    *,
    client: tuple[str, int] | None = ("127.0.0.1", 12345),
) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "headers": headers or [(b"host", b"127.0.0.1:8765")],
            "query_string": b"",
            "client": client,
            "server": ("127.0.0.1", 8765),
        }
    )


def test_parse_arguments_accepts_flag_stdin_and_empty(monkeypatch):
    assert cli_call._parse_arguments('{"command":"pwd"}') == {"command": "pwd"}

    monkeypatch.setattr(cli_call.sys, "stdin", io.StringIO('{"path":"README.md"}'))
    assert cli_call._parse_arguments(None) == {"path": "README.md"}

    monkeypatch.setattr(cli_call.sys, "stdin", io.StringIO(""))
    assert cli_call._parse_arguments(None) == {}

    with pytest.raises(ValueError, match="JSON object"):
        cli_call._parse_arguments("[1,2,3]")
    with pytest.raises(ValueError, match="invalid JSON"):
        cli_call._parse_arguments("{bad")

    class Tty(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr(cli_call.sys, "stdin", Tty("ignored"))
    assert cli_call._parse_arguments(None) == {}


def test_validate_loopback_mcp_url():
    assert cli_call._validate_loopback_mcp_url("http://127.0.0.1:8765") == (
        "http://127.0.0.1:8765/mcp"
    )
    assert cli_call._validate_loopback_mcp_url("http://localhost:8765/mcp") == (
        "http://localhost:8765/mcp"
    )
    assert cli_call._validate_loopback_mcp_url("http://127.0.0.2:8765/mcp") == (
        "http://127.0.0.2:8765/mcp"
    )
    assert cli_call._validate_loopback_mcp_url("http://[::1]:8765/mcp") == (
        "http://[::1]:8765/mcp"
    )
    with pytest.raises(ValueError, match="loopback"):
        cli_call._validate_loopback_mcp_url("https://example.com/mcp")
    with pytest.raises(ValueError, match="/mcp"):
        cli_call._validate_loopback_mcp_url("http://127.0.0.1:8765/api/ui")


def test_run_call_cli_controller_output_session_and_failure(monkeypatch, capsys):
    calls = []

    async def fake_call(url, tool, arguments, *, local_token, sse_read_timeout):
        calls.append((url, tool, arguments, local_token, sse_read_timeout))
        return {"ok": True, "data": {"stdout": "ok"}}, False

    monkeypatch.setattr(
        cli_call,
        "_cli_environment",
        lambda: {
            "LOCAL_SHELL_MCP_HOST": "127.0.0.2",
            "LOCAL_SHELL_MCP_PORT": "9999",
            "LOCAL_SHELL_MCP_MAX_TIMEOUT_S": "900",
            "LOCAL_SHELL_MCP_AUTH_MODE": "oauth",
            "LOCAL_SHELL_MCP_UI_LOCAL_TOKEN": "secret" * 8,
        },
    )
    monkeypatch.setattr(cli_call, "_call_controller", fake_call)

    cli_call.run_call_cli(
        ["run_shell", "--json", '{"command":"printf ok"}', "--session", "s_demo"]
    )

    assert calls == [
        (
            "http://127.0.0.2:9999/mcp",
            "run_shell",
            {"command": "printf ok", "logical_session_id": "s_demo"},
            "secret" * 8,
            960.0,
        )
    ]
    assert json.loads(capsys.readouterr().out) == {"ok": True, "data": {"stdout": "ok"}}

    async def fake_failure(url, tool, arguments, **kwargs):
        return {"ok": False, "message": "boom"}, True

    monkeypatch.setattr(cli_call, "_call_controller", fake_failure)
    with pytest.raises(SystemExit) as exc:
        cli_call.run_call_cli(["run_shell", "--json", '{"command":"false"}'])
    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_run_call_cli_direct_and_runtime_error(monkeypatch, capsys):
    calls = []

    async def fake_direct(tool, arguments, *, environment=None):
        calls.append((tool, arguments, environment))
        return {"ok": True}, False

    direct_environment = {"LOCAL_SHELL_MCP_WORKSPACE_ROOT": "/tmp/direct-workspace"}
    monkeypatch.setattr(cli_call, "_call_direct", fake_direct)
    monkeypatch.setattr(cli_call, "_cli_environment", lambda: direct_environment)

    cli_call.run_call_cli(["environment_get", "--direct", "--json", "{}"])
    assert calls == [("environment_get", {}, direct_environment)]
    assert json.loads(capsys.readouterr().out) == {"ok": True}

    async def explode(url, tool, arguments, **kwargs):
        raise RuntimeError("controller unavailable")

    monkeypatch.setattr(
        cli_call,
        "_cli_environment",
        lambda: {"LOCAL_SHELL_MCP_AUTH_MODE": "none"},
    )
    monkeypatch.setattr(cli_call, "_call_controller", explode)
    with pytest.raises(SystemExit) as exc:
        cli_call.run_call_cli(["environment_get", "--json", "{}"])
    assert exc.value.code == 1
    assert "controller unavailable" in capsys.readouterr().err


def test_normalize_mcp_and_direct_results():
    envelope = SimpleNamespace(
        model_dump=lambda **kwargs: {
            "content": [{"type": "text", "text": "ignored"}],
            "structuredContent": {"ok": True, "data": {"value": 1}},
            "isError": False,
        }
    )
    assert cli_call._normalize_mcp_result(envelope) == (
        {"ok": True, "data": {"value": 1}},
        False,
    )
    assert cli_call._normalize_direct_result(([], {"ok": False, "message": "no"})) == (
        {"ok": False, "message": "no"},
        True,
    )
    assert cli_call._normalize_direct_result(([SimpleNamespace(model_dump=lambda **kwargs: {"x": 1})], None)) == (
        [{"x": 1}],
        False,
    )
    assert cli_call._normalize_direct_result(
        SimpleNamespace(
            model_dump=lambda **kwargs: {
                "structuredContent": {"ok": True, "data": {"value": 2}}
            }
        )
    ) == ({"ok": True, "data": {"value": 2}}, False)
    assert cli_call._normalize_direct_result({"ok": True, "data": {"plain": True}}) == (
        {"ok": True, "data": {"plain": True}},
        False,
    )
    assert cli_call._normalize_mcp_result(
        SimpleNamespace(
            model_dump=lambda **kwargs: {
                "structuredContent": {"ok": False, "message": "bad"},
                "isError": False,
            }
        )
    ) == ({"ok": False, "message": "bad"}, True)
    assert cli_call._normalize_mcp_result({"isError": True, "content": []}) == (
        {"isError": True, "content": []},
        True,
    )
    assert cli_call._normalize_mcp_result(
        {"structuredContent": {"ok": True, "data": {"ok": False, "exit_code": 1}}}
    ) == ({"ok": True, "data": {"ok": False, "exit_code": 1}}, True)
    assert cli_call._normalize_direct_result(
        ([], {"ok": True, "data": {"ok": False, "exit_code": 2}})
    ) == ({"ok": True, "data": {"ok": False, "exit_code": 2}}, True)
    assert cli_call._jsonable((1, [2], {"three": 3})) == [1, [2], {"three": 3}]


def test_call_controller_uses_local_token_and_mcp_session(monkeypatch):
    calls = []

    class Streams:
        async def __aenter__(self):
            calls.append(("transport-enter",))
            return "read", "write", None

        async def __aexit__(self, exc_type, exc, tb):
            calls.append(("transport-exit", exc_type))

    class Session:
        def __init__(self, read_stream, write_stream):
            calls.append(("session-init", read_stream, write_stream))

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            calls.append(("session-exit", exc_type))

        async def initialize(self):
            calls.append(("initialize",))

        async def call_tool(self, tool, arguments):
            calls.append(("call-tool", tool, arguments))
            return SimpleNamespace(
                model_dump=lambda **kwargs: {
                    "structuredContent": {"ok": True, "data": {"value": 7}},
                    "isError": False,
                }
            )

    def fake_transport(url, headers, sse_read_timeout, httpx_client_factory):
        calls.append(("transport", url, headers, sse_read_timeout, httpx_client_factory))
        return Streams()

    monkeypatch.setattr(cli_call, "streamablehttp_client", fake_transport)
    monkeypatch.setattr(cli_call, "ClientSession", Session)

    assert asyncio.run(
        cli_call._call_controller(
            "http://127.0.0.1:8765/mcp",
            "environment_get",
            {"logical_session_id": None},
            local_token="local-secret",
            sse_read_timeout=3660.0,
        )
    ) == ({"ok": True, "data": {"value": 7}}, False)
    assert calls[0] == (
        "transport",
        "http://127.0.0.1:8765/mcp",
        {
            UI_LOCAL_TOKEN_HEADER: "local-secret",
            CLI_LOCAL_TOKEN_HEADER: "local-secret",
        },
        3660.0,
        cli_call._loopback_http_client_factory,
    )
    assert ("call-tool", "environment_get", {"logical_session_id": None}) in calls


def test_call_direct_reuses_registered_tool_surface_with_trusted_principal(monkeypatch):
    assert _CURRENT_PRINCIPAL.get() is None

    class Mcp:
        async def call_tool(self, tool, arguments):
            assert tool == "environment_get"
            assert arguments == {}
            principal = _CURRENT_PRINCIPAL.get()
            assert principal is not None
            assert principal.subject == "native-tui"
            assert principal.claims["auth"] == "native-tui"
            assert tools_module._current_session_subject() is None
            return [], {"ok": True, "data": {"direct": True}}

    monkeypatch.setattr(tools_module, "build_mcp", lambda: Mcp())
    assert asyncio.run(cli_call._call_direct("environment_get", {})) == (
        {"ok": True, "data": {"direct": True}},
        False,
    )
    assert _CURRENT_PRINCIPAL.get() is None


def test_call_direct_applies_dotenv_without_exposing_host_cli_token(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    environment = {
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT": str(workspace),
        "LOCAL_SHELL_MCP_STATE_DIR": str(state_dir),
        "LOCAL_SHELL_MCP_AUDIT_LOG_PATH": str(tmp_path / "audit.jsonl"),
        "LOCAL_SHELL_MCP_AUTH_MODE": "none",
        "LOCAL_SHELL_MCP_REMOTE_ENABLED": "false",
        "LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN": "host-only-secret-abcdefghijklmnopqrstuvwxyz",
    }

    class Mcp:
        async def call_tool(self, tool, arguments):
            assert tool == "environment_get"
            assert arguments == {}
            assert os.environ["LOCAL_SHELL_MCP_WORKSPACE_ROOT"] == str(workspace)
            assert "LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN" not in os.environ
            return [], {
                "ok": True,
                "data": {
                    "workspace_root": str(settings_module.get_settings().workspace_root),
                },
            }

    monkeypatch.setattr(tools_module, "build_mcp", lambda: Mcp())
    payload, failed = asyncio.run(
        cli_call._call_direct("environment_get", {}, environment=environment)
    )
    assert failed is False
    assert payload["data"]["workspace_root"] == str(workspace)
    assert "LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN" not in os.environ


def test_call_direct_can_attach_existing_local_user_session(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, auth_mode="oauth")
    manager = get_session_runtime_manager()
    session = manager.manage("local-user", action="start", objective="existing local task")
    session_id = session["session_id"]

    payload, failed = asyncio.run(
        cli_call._call_direct(
            "environment_get",
            {"logical_session_id": session_id},
        )
    )

    assert failed is False
    assert payload["ok"] is True
    current = manager.get(session_id, subject="local-user")
    assert any(item["type"] == "tool.completed" for item in current["recent_activity"])


def test_run_call_cli_rejects_bad_input_url_and_handles_interrupt(monkeypatch, capsys):
    monkeypatch.setattr(
        cli_call,
        "_cli_environment",
        lambda: {"LOCAL_SHELL_MCP_AUTH_MODE": "none"},
    )

    with pytest.raises(SystemExit) as exc:
        cli_call.run_call_cli(["environment_get", "--json", "[]"])
    assert exc.value.code == 2

    with pytest.raises(SystemExit) as exc:
        cli_call.run_call_cli(
            ["environment_get", "--json", "{}", "--url", "https://example.com/mcp"]
        )
    assert exc.value.code == 2

    with pytest.raises(SystemExit) as exc:
        cli_call.run_call_cli(
            ["environment_get", "--json", "{}", "--read-timeout", "0"]
        )
    assert exc.value.code == 2

    async def interrupted(url, tool, arguments, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_call, "_call_controller", interrupted)
    with pytest.raises(SystemExit) as exc:
        cli_call.run_call_cli(["environment_get", "--json", "{}"])
    assert exc.value.code == 130
    assert "usage:" in capsys.readouterr().err


def test_default_controller_url_respects_loopback_bind():
    assert cli_call._default_controller_url(SimpleNamespace(host="127.0.0.2", port=9000)) == (
        "http://127.0.0.2:9000/mcp"
    )
    assert cli_call._default_controller_url(SimpleNamespace(host="::1", port=9000)) == (
        "http://[::1]:9000/mcp"
    )
    assert cli_call._default_controller_url(SimpleNamespace(host="0.0.0.0", port=9000)) == (
        "http://127.0.0.1:9000/mcp"
    )
    assert cli_call._default_controller_url(SimpleNamespace(host="not-an-ip", port=9000)) == (
        "http://127.0.0.1:9000/mcp"
    )


def test_resolve_local_token_supports_env_and_files(tmp_path):
    explicit = tmp_path / "token"
    explicit.write_text("x" * 40, encoding="utf-8")
    assert cli_call._resolve_local_token({}, str(explicit)) == "x" * 40
    assert cli_call._resolve_local_token({cli_call.CLI_TOKEN_FILE_ENV: str(explicit)}, None) == (
        "x" * 40
    )
    assert cli_call._resolve_local_token({"LOCAL_SHELL_MCP_UI_LOCAL_TOKEN": "z" * 40}, None) == (
        "z" * 40
    )

    state_dir = tmp_path / "state"
    token_path = state_dir / "ui" / "local-token"
    token_path.parent.mkdir(parents=True)
    token_path.write_text("s" * 40, encoding="utf-8")
    assert cli_call._resolve_local_token(
        {"LOCAL_SHELL_MCP_STATE_DIR": str(state_dir)}, None
    ) == "s" * 40

    workspace = tmp_path / "workspace"
    workspace_token = workspace / ".local-shell-mcp" / "ui" / "local-token"
    workspace_token.parent.mkdir(parents=True)
    workspace_token.write_text("w" * 40, encoding="utf-8")
    assert cli_call._resolve_local_token(
        {"LOCAL_SHELL_MCP_WORKSPACE_ROOT": str(workspace)}, None
    ) == "w" * 40

    workspace_token.write_text("short", encoding="utf-8")
    assert cli_call._resolve_local_token(
        {"LOCAL_SHELL_MCP_WORKSPACE_ROOT": str(workspace)}, None
    ) is None

    default_token = tmp_path / "default-token"
    default_token.write_text("d" * 40, encoding="utf-8")
    original_default = cli_call.DEFAULT_LOCAL_TOKEN_PATH
    cli_call.DEFAULT_LOCAL_TOKEN_PATH = default_token
    try:
        assert cli_call._resolve_local_token({}, None) == "d" * 40
        default_token.write_text("short", encoding="utf-8")
        assert cli_call._resolve_local_token({}, None) is None
    finally:
        cli_call.DEFAULT_LOCAL_TOKEN_PATH = original_default

    with pytest.raises(ValueError, match="unable to read"):
        cli_call._read_token_file(tmp_path / "missing")
    with pytest.raises(ValueError, match="invalid"):
        cli_call._read_token_file(workspace_token)


def test_dotenv_and_cli_environment_are_read_only(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "# comment\n"
        "LOCAL_SHELL_MCP_HOST='127.0.0.2'\n"
        "export LOCAL_SHELL_MCP_PORT=9999\n"
        "LOCAL_SHELL_MCP_UI_LOCAL_TOKEN=dotenv-token-abcdefghijklmnopqrstuvwxyz\n"
        "ignored-line\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOCAL_SHELL_MCP_PORT", "10001")
    values = cli_call._cli_environment()
    assert values["LOCAL_SHELL_MCP_HOST"] == "127.0.0.2"
    assert values["LOCAL_SHELL_MCP_PORT"] == "10001"
    assert values["LOCAL_SHELL_MCP_UI_LOCAL_TOKEN"].startswith("dotenv-token-")

    settings = cli_call._controller_defaults(values)
    assert settings.host == "127.0.0.2"
    assert settings.port == 10001
    assert settings.auth_mode == "oauth"
    assert not (tmp_path / "workspace").exists()


def test_controller_defaults_reject_invalid_values():
    with pytest.raises(ValueError, match="integer"):
        cli_call._controller_defaults({"LOCAL_SHELL_MCP_PORT": "bad"})
    with pytest.raises(ValueError, match="between 1 and 65535"):
        cli_call._controller_defaults({"LOCAL_SHELL_MCP_PORT": "70000"})
    with pytest.raises(ValueError, match="number"):
        cli_call._controller_defaults({"LOCAL_SHELL_MCP_MAX_TIMEOUT_S": "bad"})
    with pytest.raises(ValueError, match="greater than zero"):
        cli_call._controller_defaults({"LOCAL_SHELL_MCP_MAX_TIMEOUT_S": "0"})


def test_loopback_http_client_factory_disables_environment_proxies(monkeypatch):
    captured = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(cli_call.httpx, "AsyncClient", fake_client)
    timeout = cli_call.httpx.Timeout(10.0)
    auth = object()
    result = cli_call._loopback_http_client_factory(
        headers={"x": "y"}, timeout=timeout, auth=auth
    )
    assert result is not None
    assert captured["trust_env"] is False
    assert captured["follow_redirects"] is True
    assert captured["headers"] == {"x": "y"}
    assert captured["timeout"] is timeout
    assert captured["auth"] is auth


def test_run_call_cli_auth_none_skips_token_resolution(monkeypatch, capsys):
    calls = []

    monkeypatch.setattr(
        cli_call,
        "_cli_environment",
        lambda: {"LOCAL_SHELL_MCP_AUTH_MODE": "none"},
    )
    monkeypatch.setattr(
        cli_call,
        "_resolve_local_token",
        lambda values, token_file: (_ for _ in ()).throw(AssertionError("token lookup")),
    )

    async def fake_call(url, tool, arguments, *, local_token, sse_read_timeout):
        calls.append((url, tool, arguments, local_token, sse_read_timeout))
        return {"ok": True}, False

    monkeypatch.setattr(cli_call, "_call_controller", fake_call)
    cli_call.run_call_cli(["environment_get", "--json", "{}"])
    assert calls[0][3] is None
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_run_call_cli_help_does_not_load_controller_configuration(monkeypatch, capsys):
    monkeypatch.setattr(
        cli_call,
        "_cli_environment",
        lambda: (_ for _ in ()).throw(AssertionError("configuration loaded")),
    )
    with pytest.raises(SystemExit) as exc:
        cli_call.run_call_cli(["--help"])
    assert exc.value.code == 0
    assert "Invoke one local-shell-mcp tool" in capsys.readouterr().out


@pytest.mark.parametrize("auth_type", ["native-tui", "local-cli"])
def test_trusted_local_principal_can_use_existing_sessions(tmp_path, monkeypatch, auth_type):
    _configure(tmp_path, monkeypatch, auth_mode="oauth")
    token = _CURRENT_PRINCIPAL.set(
        Principal(email="localhost", subject=auth_type, claims={"auth": auth_type})
    )
    try:
        assert tools_module._current_session_subject() is None
        assert tools_module._current_session_subject(create=True) == "local-user"
    finally:
        _CURRENT_PRINCIPAL.reset(token)


def test_host_cli_token_authenticates_across_compose_bridge_only_for_loopback_target(
    tmp_path, monkeypatch
):
    _configure(tmp_path, monkeypatch)
    raw_token = "host-cli-token-abcdefghijklmnopqrstuvwxyz-0123456789"
    monkeypatch.setenv(
        CLI_LOCAL_TOKEN_SHA256_ENV,
        hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
    )
    bridge_request = _request(
        "/mcp",
        [
            (b"host", b"127.0.0.1:8765"),
            (CLI_LOCAL_TOKEN_HEADER.encode(), raw_token.encode()),
        ],
        client=("172.17.0.1", 45678),
    )
    principal = verify_request(bridge_request)
    assert principal.subject == "local-cli"
    assert principal.claims["auth"] == "local-cli"

    # In hardened Compose mode, the controller's internal UI token must not
    # authenticate /mcp even from loopback; only the host-held CLI token may do so.
    ui_token = get_or_create_ui_local_token().encode()
    with pytest.raises(HTTPException) as exc:
        verify_request(
            _request(
                "/mcp",
                [
                    (b"host", b"127.0.0.1:8765"),
                    (UI_LOCAL_TOKEN_HEADER.encode(), ui_token),
                ],
            )
        )
    assert exc.value.status_code == 401

    public_target = _request(
        "/mcp",
        [
            (b"host", b"mcp.example.com"),
            (CLI_LOCAL_TOKEN_HEADER.encode(), raw_token.encode()),
        ],
        client=("172.18.0.3", 45678),
    )
    with pytest.raises(HTTPException) as exc:
        verify_request(public_target)
    assert exc.value.status_code == 401

    monkeypatch.setenv(CLI_LOCAL_TOKEN_SHA256_ENV, "not-a-valid-digest")
    with pytest.raises(HTTPException) as exc:
        verify_request(bridge_request)
    assert exc.value.status_code == 401
    with pytest.raises(HTTPException) as exc:
        verify_request(
            _request(
                "/mcp",
                [
                    (b"host", b"127.0.0.1:8765"),
                    (UI_LOCAL_TOKEN_HEADER.encode(), ui_token),
                ],
            )
        )
    assert exc.value.status_code == 401


def test_local_token_authenticates_loopback_mcp_only(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    token = get_or_create_ui_local_token().encode()
    request = _request(
        "/mcp",
        [
            (b"host", b"127.0.0.1:8765"),
            (UI_LOCAL_TOKEN_HEADER.encode(), token),
        ],
    )

    principal = verify_request(request)
    assert principal.subject == "native-tui"
    assert principal.claims["auth"] == "native-tui"

    with pytest.raises(HTTPException) as exc:
        verify_request(_request("/mcp"))
    assert exc.value.status_code == 401

    with pytest.raises(HTTPException) as exc:
        verify_request(
            _request(
                "/other",
                [
                    (b"host", b"127.0.0.1:8765"),
                    (UI_LOCAL_TOKEN_HEADER.encode(), token),
                ],
            )
        )
    assert exc.value.status_code == 401
