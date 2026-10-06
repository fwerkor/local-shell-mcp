from __future__ import annotations

import asyncio
import io
import json
from types import SimpleNamespace

import pytest
from starlette.exceptions import HTTPException
from starlette.requests import Request

import local_shell_mcp.cli_call as cli_call
import local_shell_mcp.settings as settings_module
import local_shell_mcp.tools as tools_module
from local_shell_mcp.auth import verify_request
from local_shell_mcp.ui_security import UI_LOCAL_TOKEN_HEADER, get_or_create_ui_local_token


def _configure(tmp_path, monkeypatch, *, mode: str = "mcp", auth_mode: str = "oauth") -> None:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_MODE", mode)
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", auth_mode)
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    settings_module.get_settings.cache_clear()


def _request(path: str, headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "headers": headers or [(b"host", b"127.0.0.1:8765")],
            "query_string": b"",
            "client": ("127.0.0.1", 12345),
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
    with pytest.raises(ValueError, match="loopback"):
        cli_call._validate_loopback_mcp_url("https://example.com/mcp")
    with pytest.raises(ValueError, match="/mcp"):
        cli_call._validate_loopback_mcp_url("http://127.0.0.1:8765/api/ui")


def test_run_call_cli_controller_output_session_and_failure(monkeypatch, capsys):
    calls = []

    async def fake_call(url, tool, arguments):
        calls.append((url, tool, arguments))
        return {"ok": True, "data": {"stdout": "ok"}}, False

    monkeypatch.setattr(cli_call, "get_settings", lambda: SimpleNamespace(port=9999))
    monkeypatch.setattr(cli_call, "_call_controller", fake_call)

    cli_call.run_call_cli(
        ["run_shell", "--json", '{"command":"printf ok"}', "--session", "s_demo"]
    )

    assert calls == [
        (
            "http://127.0.0.1:9999/mcp",
            "run_shell",
            {"command": "printf ok", "logical_session_id": "s_demo"},
        )
    ]
    assert json.loads(capsys.readouterr().out) == {"ok": True, "data": {"stdout": "ok"}}

    async def fake_failure(url, tool, arguments):
        return {"ok": False, "message": "boom"}, True

    monkeypatch.setattr(cli_call, "_call_controller", fake_failure)
    with pytest.raises(SystemExit) as exc:
        cli_call.run_call_cli(["run_shell", "--json", '{"command":"false"}'])
    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_run_call_cli_direct_and_runtime_error(monkeypatch, capsys):
    calls = []

    async def fake_direct(tool, arguments):
        calls.append((tool, arguments))
        return {"ok": True}, False

    monkeypatch.setattr(cli_call, "get_settings", lambda: SimpleNamespace(port=8765))
    monkeypatch.setattr(cli_call, "_call_direct", fake_direct)

    cli_call.run_call_cli(["environment_get", "--direct", "--json", "{}"])
    assert calls == [("environment_get", {})]
    assert json.loads(capsys.readouterr().out) == {"ok": True}

    async def explode(url, tool, arguments):
        raise RuntimeError("controller unavailable")

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
    assert cli_call._normalize_mcp_result(
        SimpleNamespace(
            model_dump=lambda **kwargs: {
                "structuredContent": {"ok": False, "message": "bad"},
                "isError": False,
            }
        )
    ) == ({"ok": False, "message": "bad"}, True)
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

    def fake_transport(url, headers):
        calls.append(("transport", url, headers))
        return Streams()

    monkeypatch.setattr(cli_call, "get_or_create_ui_local_token", lambda: "local-secret")
    monkeypatch.setattr(cli_call, "streamablehttp_client", fake_transport)
    monkeypatch.setattr(cli_call, "ClientSession", Session)

    assert asyncio.run(
        cli_call._call_controller(
            "http://127.0.0.1:8765/mcp", "environment_get", {"logical_session_id": None}
        )
    ) == ({"ok": True, "data": {"value": 7}}, False)
    assert calls[0] == (
        "transport",
        "http://127.0.0.1:8765/mcp",
        {UI_LOCAL_TOKEN_HEADER: "local-secret"},
    )
    assert ("call-tool", "environment_get", {"logical_session_id": None}) in calls


def test_call_direct_reuses_registered_tool_surface(monkeypatch):
    class Mcp:
        async def call_tool(self, tool, arguments):
            assert tool == "environment_get"
            assert arguments == {}
            return [], {"ok": True, "data": {"direct": True}}

    monkeypatch.setattr(tools_module, "build_mcp", lambda: Mcp())
    assert asyncio.run(cli_call._call_direct("environment_get", {})) == (
        {"ok": True, "data": {"direct": True}},
        False,
    )


def test_run_call_cli_rejects_bad_input_url_and_handles_interrupt(monkeypatch, capsys):
    monkeypatch.setattr(cli_call, "get_settings", lambda: SimpleNamespace(port=8765))

    with pytest.raises(SystemExit) as exc:
        cli_call.run_call_cli(["environment_get", "--json", "[]"])
    assert exc.value.code == 2

    with pytest.raises(SystemExit) as exc:
        cli_call.run_call_cli(
            ["environment_get", "--json", "{}", "--url", "https://example.com/mcp"]
        )
    assert exc.value.code == 2

    async def interrupted(url, tool, arguments):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_call, "_call_controller", interrupted)
    with pytest.raises(SystemExit) as exc:
        cli_call.run_call_cli(["environment_get", "--json", "{}"])
    assert exc.value.code == 130
    assert "usage:" in capsys.readouterr().err


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
