from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
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
    issue_ui_local_token,
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
            "LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN": "secret" * 8,
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
        {CLI_LOCAL_TOKEN_HEADER: "local-secret"},
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
    inherited_token = "inherited-host-secret-abcdefghijklmnopqrstuvwxyz"
    inherited_token_file = str(tmp_path / "inherited-token-file")
    monkeypatch.setenv("LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN", inherited_token)
    monkeypatch.setenv(cli_call.CLI_TOKEN_FILE_ENV, inherited_token_file)
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
            assert cli_call.CLI_TOKEN_FILE_ENV not in os.environ
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
    assert os.environ["LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN"] == inherited_token
    assert os.environ[cli_call.CLI_TOKEN_FILE_ENV] == inherited_token_file


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


def test_resolve_local_token_supports_explicit_cli_credentials_only(tmp_path):
    explicit = tmp_path / "token"
    explicit.write_text("x" * 40, encoding="utf-8")
    assert cli_call._resolve_local_token({}, str(explicit)) == "x" * 40
    assert cli_call._resolve_local_token({cli_call.CLI_TOKEN_FILE_ENV: str(explicit)}, None) == (
        "x" * 40
    )
    assert cli_call._resolve_local_token(
        {"LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN": "z" * 40}, None
    ) == "z" * 40
    assert cli_call._resolve_local_token(
        {"LOCAL_SHELL_MCP_UI_LOCAL_TOKEN": "u" * 40}, None
    ) is None
    assert cli_call._resolve_local_token(
        {"LOCAL_SHELL_MCP_STATE_DIR": str(tmp_path / "state")}, None
    ) is None

    with pytest.raises(ValueError, match="at least 32"):
        cli_call._resolve_local_token({"LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN": "short"}, None)
    with pytest.raises(ValueError, match="unable to read"):
        cli_call._read_token_file(tmp_path / "missing")
    explicit.write_text("short", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid"):
        cli_call._read_token_file(explicit)


def test_dotenv_and_cli_environment_are_read_only(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    monkeypatch.setenv("MCP_PORT", "9999")
    monkeypatch.setenv("LSM_ROOT", "/srv/lsm")
    dotenv.write_text(
        "# comment\n"
        "LOCAL_SHELL_MCP_HOST='127.0.0.2' # loopback\n"
        "export LOCAL_SHELL_MCP_PORT=${MCP_PORT:-8765} # controller port\n"
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT=\"${LSM_ROOT:-/workspace}/data\"\n"
        "LOCAL_SHELL_MCP_UI_LOCAL_TOKEN=dotenv-token-abcdefghijklmnopqrstuvwxyz\n"
        "LOCAL_SHELL_MCP_PUBLIC_BASE_URL=\"https://example.test/#fragment\" # public URL\n"
        "LOCAL_SHELL_MCP_STATE_BACKEND_URL=redis://cache#0\n"
        "LOCAL_SHELL_MCP_STATE_DIR='${LSM_ROOT:-/workspace}/literal'\n"
        "LOCAL_SHELL_MCP_LOG_LEVEL=${UNSET_LEVEL:-${DEFAULT_LEVEL:-WARNING}}\n"
        "DEFAULT_LEVEL=INFO\n"
        "ignored-line\n",
        encoding="utf-8",
    )
    parsed = cli_call._read_dotenv(dotenv)
    assert parsed["LOCAL_SHELL_MCP_HOST"] == "127.0.0.2"
    assert parsed["LOCAL_SHELL_MCP_PORT"] == "9999"
    assert parsed["LOCAL_SHELL_MCP_WORKSPACE_ROOT"] == "/srv/lsm/data"
    assert parsed["LOCAL_SHELL_MCP_PUBLIC_BASE_URL"] == "https://example.test/#fragment"
    assert parsed["LOCAL_SHELL_MCP_STATE_BACKEND_URL"] == "redis://cache#0"
    assert parsed["LOCAL_SHELL_MCP_STATE_DIR"] == "${LSM_ROOT:-/workspace}/literal"
    assert parsed["LOCAL_SHELL_MCP_LOG_LEVEL"] == "WARNING"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOCAL_SHELL_MCP_PORT", "10001")
    values = cli_call._cli_environment()
    assert values["LOCAL_SHELL_MCP_HOST"] == "127.0.0.2"
    assert values["LOCAL_SHELL_MCP_PORT"] == "10001"
    assert values["LOCAL_SHELL_MCP_UI_LOCAL_TOKEN"].startswith("dotenv-token-")

    assert cli_call._controller_endpoint_defaults(values) == ("127.0.0.2", 10001)
    assert not (tmp_path / "workspace").exists()


def test_compose_dotenv_interpolation_forms():
    variables = {"SET": "value", "EMPTY": ""}

    assert cli_call._interpolate_dotenv("$SET/${SET}/$$", variables) == "value/value/$"
    assert (
        cli_call._parse_dotenv_value(r'"prefix-\$SET"', variables=variables)
        == "prefix-$SET"
    )
    assert (
        cli_call._parse_dotenv_value(r'"$\$SET"', variables=variables)
        == "$$SET"
    )
    assert (
        cli_call._parse_dotenv_value(r'"\\$SET"', variables=variables)
        == r"\value"
    )
    assert (
        cli_call._parse_dotenv_value(
            r'"${UNSET:-\${SET}x}"', variables=variables
        )
        == "${SET}x"
    )
    assert (
        cli_call._parse_dotenv_value(
            r'"${UNSET:-\${SET}"', variables=variables
        )
        == "${SET"
    )
    assert cli_call._interpolate_dotenv("${UNSET:-fallback}", variables) == "fallback"
    assert cli_call._interpolate_dotenv("${EMPTY:-fallback}", variables) == "fallback"
    assert cli_call._interpolate_dotenv("${EMPTY-fallback}", variables) == ""
    assert cli_call._interpolate_dotenv("${UNSET-fallback}", variables) == "fallback"
    assert cli_call._interpolate_dotenv("${SET:+alternate}", variables) == "alternate"
    assert cli_call._interpolate_dotenv("${UNSET:+alternate}", variables) == ""
    assert cli_call._interpolate_dotenv("${SET+alternate}", variables) == "alternate"
    assert cli_call._interpolate_dotenv("${EMPTY:+alternate}", variables) == ""
    assert cli_call._interpolate_dotenv("${EMPTY+alternate}", variables) == "alternate"
    assert cli_call._interpolate_dotenv("${UNSET:-${SET:-fallback}}", variables) == "value"
    assert cli_call._interpolate_dotenv("${SET:?required}", variables) == "value"
    assert cli_call._interpolate_dotenv("${EMPTY?required}", variables) == ""

    with pytest.raises(ValueError, match="EMPTY: required"):
        cli_call._interpolate_dotenv("${EMPTY:?required}", variables)
    with pytest.raises(ValueError, match="UNSET: required"):
        cli_call._interpolate_dotenv("${UNSET?required}", variables)
    with pytest.raises(ValueError, match="missing"):
        cli_call._interpolate_dotenv("${SET", variables)
    with pytest.raises(ValueError, match="missing"):
        cli_call._parse_dotenv_value(r'"${UNSET:-${SET}"', variables=variables)
    with pytest.raises(ValueError, match="invalid dotenv interpolation"):
        cli_call._interpolate_dotenv("${9BAD}", variables)
    with pytest.raises(ValueError, match="invalid dotenv interpolation"):
        cli_call._interpolate_dotenv("${SET:=other}", variables)
    with pytest.raises(ValueError, match="nested too deeply"):
        cli_call._interpolate_dotenv("value", variables, depth=21)


def test_yaml_controller_values_are_loaded_read_only_with_environment_precedence(
    tmp_path, monkeypatch
):
    config = tmp_path / "controller.yaml"
    config.write_text(
        "host: 127.0.0.3\n"
        "port: 9123\n"
        "auth_mode: oauth\n"
        "max_timeout_s: 45\n"
        "workspace_root: /yaml/workspace\n",
        encoding="utf-8",
    )
    values = cli_call._apply_yaml_controller_values(
        {"LOCAL_SHELL_MCP_CONFIG": str(config)}
    )
    assert values["LOCAL_SHELL_MCP_HOST"] == "127.0.0.3"
    assert values["LOCAL_SHELL_MCP_PORT"] == "9123"
    assert values["LOCAL_SHELL_MCP_AUTH_MODE"] == "oauth"
    assert values["LOCAL_SHELL_MCP_MAX_TIMEOUT_S"] == "45"
    assert values["LOCAL_SHELL_MCP_WORKSPACE_ROOT"] == "/yaml/workspace"
    assert values["LOCAL_SHELL_MCP_STATE_DIR"] == str(
        Path("/yaml/workspace") / ".local-shell-mcp"
    )

    overridden = cli_call._apply_yaml_controller_values(
        {
            "LOCAL_SHELL_MCP_CONFIG": str(config),
            "LOCAL_SHELL_MCP_PORT": "9555",
            "LOCAL_SHELL_MCP_AUTH_MODE": "none",
            "LOCAL_SHELL_MCP_WORKSPACE_ROOT": "/env/workspace",
        }
    )
    assert overridden["LOCAL_SHELL_MCP_HOST"] == "127.0.0.3"
    assert overridden["LOCAL_SHELL_MCP_PORT"] == "9555"
    assert overridden["LOCAL_SHELL_MCP_AUTH_MODE"] == "none"
    assert overridden["LOCAL_SHELL_MCP_STATE_DIR"] == str(
        Path("/env/workspace") / ".local-shell-mcp"
    )
    assert not (tmp_path / "workspace").exists()

    with pytest.raises(ValueError, match="unable to load LOCAL_SHELL_MCP_CONFIG"):
        cli_call._apply_yaml_controller_values(
            {"LOCAL_SHELL_MCP_CONFIG": str(tmp_path / "missing.yaml")}
        )


def test_run_call_cli_uses_yaml_controller_defaults(tmp_path, monkeypatch, capsys):
    config = tmp_path / "controller.yaml"
    config.write_text(
        "host: 127.0.0.4\nport: 9234\nauth_mode: none\nmax_timeout_s: 120\n",
        encoding="utf-8",
    )
    calls = []
    monkeypatch.setattr(
        cli_call,
        "_cli_environment",
        lambda: {"LOCAL_SHELL_MCP_CONFIG": str(config)},
    )

    async def fake_call(url, tool, arguments, *, local_token, sse_read_timeout):
        calls.append((url, tool, arguments, local_token, sse_read_timeout))
        return {"ok": True}, False

    monkeypatch.setattr(cli_call, "_call_controller", fake_call)
    cli_call.run_call_cli(["environment_get", "--json", "{}"])
    assert calls == [
        ("http://127.0.0.4:9234/mcp", "environment_get", {}, None, 300.0)
    ]
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_controller_defaults_reject_invalid_values():
    with pytest.raises(ValueError, match="integer"):
        cli_call._controller_endpoint_defaults({"LOCAL_SHELL_MCP_PORT": "bad"})
    with pytest.raises(ValueError, match="between 1 and 65535"):
        cli_call._controller_endpoint_defaults({"LOCAL_SHELL_MCP_PORT": "70000"})
    with pytest.raises(ValueError, match="number"):
        cli_call._controller_max_timeout({"LOCAL_SHELL_MCP_MAX_TIMEOUT_S": "bad"})
    with pytest.raises(ValueError, match="greater than zero"):
        cli_call._controller_max_timeout({"LOCAL_SHELL_MCP_MAX_TIMEOUT_S": "0"})


def test_loopback_http_client_factory_disables_redirects_and_environment_proxies(monkeypatch):
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
    assert captured["follow_redirects"] is False
    assert captured["headers"] == {"x": "y"}
    assert captured["timeout"] is timeout
    assert captured["auth"] is auth


def test_run_call_cli_explicit_controller_options_bypass_unrelated_local_config(
    tmp_path, monkeypatch, capsys
):
    token_file = tmp_path / "controller-token"
    token_file.write_text("t" * 40, encoding="utf-8")
    missing_config = tmp_path / "missing.yaml"
    calls = []
    monkeypatch.setattr(
        cli_call,
        "_cli_environment",
        lambda: {
            "LOCAL_SHELL_MCP_CONFIG": str(missing_config),
            "LOCAL_SHELL_MCP_PORT": "not-a-port",
            "LOCAL_SHELL_MCP_MAX_TIMEOUT_S": "not-a-timeout",
            "LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN": "short",
        },
    )

    async def fake_call(url, tool, arguments, *, local_token, sse_read_timeout):
        calls.append((url, tool, arguments, local_token, sse_read_timeout))
        return {"ok": True}, False

    monkeypatch.setattr(cli_call, "_call_controller", fake_call)
    cli_call.run_call_cli(
        [
            "environment_get",
            "--json",
            "{}",
            "--url",
            "http://127.0.0.1:9911/mcp",
            "--token-file",
            str(token_file),
            "--read-timeout",
            "12",
        ]
    )

    assert calls == [
        (
            "http://127.0.0.1:9911/mcp",
            "environment_get",
            {},
            "t" * 40,
            12.0,
        )
    ]
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_run_call_cli_explicit_url_does_not_validate_unused_port(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        cli_call,
        "_cli_environment",
        lambda: {
            "LOCAL_SHELL_MCP_PORT": "not-a-port",
            "LOCAL_SHELL_MCP_MAX_TIMEOUT_S": "15",
        },
    )

    async def fake_call(url, tool, arguments, *, local_token, sse_read_timeout):
        calls.append((url, sse_read_timeout))
        return {"ok": True}, False

    monkeypatch.setattr(cli_call, "_call_controller", fake_call)
    cli_call.run_call_cli(
        ["environment_get", "--json", "{}", "--url", "http://127.0.0.1:9912/mcp"]
    )
    assert calls == [("http://127.0.0.1:9912/mcp", 300.0)]
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_run_call_cli_explicit_timeout_does_not_validate_unused_max_timeout(
    monkeypatch, capsys
):
    calls = []
    monkeypatch.setattr(
        cli_call,
        "_cli_environment",
        lambda: {
            "LOCAL_SHELL_MCP_HOST": "127.0.0.2",
            "LOCAL_SHELL_MCP_PORT": "9913",
            "LOCAL_SHELL_MCP_MAX_TIMEOUT_S": "not-a-timeout",
        },
    )

    async def fake_call(url, tool, arguments, *, local_token, sse_read_timeout):
        calls.append((url, sse_read_timeout))
        return {"ok": True}, False

    monkeypatch.setattr(cli_call, "_call_controller", fake_call)
    cli_call.run_call_cli(
        ["environment_get", "--json", "{}", "--read-timeout", "9"]
    )
    assert calls == [("http://127.0.0.2:9913/mcp", 9.0)]
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_run_call_cli_auth_none_without_explicit_token_sends_none(monkeypatch, capsys):
    calls = []

    monkeypatch.setattr(
        cli_call,
        "_cli_environment",
        lambda: {"LOCAL_SHELL_MCP_AUTH_MODE": "none"},
    )

    async def fake_call(url, tool, arguments, *, local_token, sse_read_timeout):
        calls.append((url, tool, arguments, local_token, sse_read_timeout))
        return {"ok": True}, False

    monkeypatch.setattr(cli_call, "_call_controller", fake_call)
    cli_call.run_call_cli(["environment_get", "--json", "{}"])
    assert calls[0][3] is None
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_run_call_cli_auth_none_honors_explicit_token_file(tmp_path, monkeypatch, capsys):
    token_file = tmp_path / "controller-token"
    token_file.write_text("t" * 40, encoding="utf-8")
    calls = []

    monkeypatch.setattr(
        cli_call,
        "_cli_environment",
        lambda: {"LOCAL_SHELL_MCP_AUTH_MODE": "none"},
    )

    async def fake_call(url, tool, arguments, *, local_token, sse_read_timeout):
        calls.append((url, tool, arguments, local_token, sse_read_timeout))
        return {"ok": True}, False

    monkeypatch.setattr(cli_call, "_call_controller", fake_call)
    cli_call.run_call_cli(
        [
            "environment_get",
            "--json",
            "{}",
            "--token-file",
            str(token_file),
        ]
    )
    assert calls[0][3] == "t" * 40
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_run_call_cli_auth_none_honors_explicit_token_environment(monkeypatch, capsys):
    calls = []
    token = "e" * 40
    monkeypatch.setattr(
        cli_call,
        "_cli_environment",
        lambda: {
            "LOCAL_SHELL_MCP_AUTH_MODE": "none",
            "LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN": token,
        },
    )

    async def fake_call(url, tool, arguments, *, local_token, sse_read_timeout):
        calls.append((url, tool, arguments, local_token, sse_read_timeout))
        return {"ok": True}, False

    monkeypatch.setattr(cli_call, "_call_controller", fake_call)
    cli_call.run_call_cli(["environment_get", "--json", "{}"])
    assert calls[0][3] == token
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

    ui_bridge_request = _request(
        "/api/ui/bootstrap",
        [
            (b"host", b"127.0.0.1:8765"),
            (CLI_LOCAL_TOKEN_HEADER.encode(), raw_token.encode()),
        ],
        client=("172.17.0.1", 45678),
    )
    ui_principal = verify_request(ui_bridge_request)
    assert ui_principal.subject == "local-cli"
    assert ui_principal.claims["auth"] == "local-cli"

    # In hardened Compose mode, the controller's internal UI token must not
    # authenticate /mcp even from loopback; only the host-held CLI token may do so.
    ui_token = issue_ui_local_token(
        email=None, subject="operator", scopes=("shell:read", "remote:use")
    ).encode()
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

    public_ui_target = _request(
        "/api/ui/bootstrap",
        [
            (b"host", b"mcp.example.com"),
            (CLI_LOCAL_TOKEN_HEADER.encode(), raw_token.encode()),
        ],
        client=("172.18.0.3", 45678),
    )
    with pytest.raises(HTTPException) as exc:
        verify_request(public_ui_target)
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


def test_ui_token_never_authenticates_mcp(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    token = issue_ui_local_token(
        email="operator@example.test", subject="operator", scopes=("shell:read",)
    ).encode()

    with pytest.raises(HTTPException) as exc:
        verify_request(
            _request(
                "/mcp",
                [
                    (b"host", b"127.0.0.1:8765"),
                    (UI_LOCAL_TOKEN_HEADER.encode(), token),
                ],
            )
        )
    assert exc.value.status_code == 401

    principal = verify_request(
        _request(
            "/api/ui/bootstrap",
            [
                (b"host", b"127.0.0.1:8765"),
                (UI_LOCAL_TOKEN_HEADER.encode(), token),
            ],
        )
    )
    assert principal.subject == "operator"
    assert principal.claims["auth"] == "ui-session"
    assert principal.claims["scope"] == "shell:read"
