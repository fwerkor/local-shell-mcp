from __future__ import annotations

from types import SimpleNamespace

import pytest

import local_shell_mcp.human_ui as human_ui
import local_shell_mcp.jobs as jobs
import local_shell_mcp.main as main_module
import local_shell_mcp.remote_worker_cli as remote_worker_cli
import local_shell_mcp.settings as settings_module
import local_shell_mcp.tools as tools
import local_shell_mcp.version as version


class FakeMcp:
    def __init__(self, *, streamable: bool = False, sse: bool = False, legacy_type_error: bool = False):
        self.calls: list[tuple[str, object]] = []
        self._legacy_type_error = legacy_type_error
        self._session_manager = SimpleNamespace(session_idle_timeout=0)
        if streamable:
            self.streamable_http_app = lambda: "streamable-inner"
        if sse:
            self.sse_app = lambda: "sse-inner"

    def run(self, *, transport: str) -> None:
        self.calls.append(("run", transport))
        if self._legacy_type_error and transport == "streamable-http":
            self._legacy_type_error = False
            raise TypeError("old sdk")


def _settings(**updates):
    defaults = {
        "mode": "mcp",
        "host": "127.0.0.1",
        "port": 9876,
        "auth_mode": "none",
        "remote_enabled": False,
        "mcp_session_idle_timeout_s": 9,
    }
    defaults.update(updates)
    return SimpleNamespace(**defaults)


def test_run_mcp_stdio_and_legacy_fallback(monkeypatch):
    validated = []
    fake = FakeMcp()
    monkeypatch.setattr(settings_module, "get_settings", lambda: _settings(mode="stdio"))
    monkeypatch.setattr(settings_module, "validate_public_oauth_configuration", validated.append)
    monkeypatch.setattr(tools, "build_mcp", lambda: fake)

    main_module.run_mcp()

    assert fake.calls == [("run", "stdio")]
    assert validated and validated[0].mode == "stdio"

    legacy = FakeMcp(legacy_type_error=True)
    monkeypatch.setattr(settings_module, "get_settings", lambda: _settings())
    monkeypatch.setattr(tools, "build_mcp", lambda: legacy)
    main_module.run_mcp()
    assert legacy.calls == [("run", "streamable-http"), ("run", "sse")]


def test_run_mcp_streamable_and_sse(monkeypatch):
    import uvicorn

    runs = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: runs.append((app, kwargs)))
    monkeypatch.setattr(settings_module, "validate_public_oauth_configuration", lambda value: None)
    monkeypatch.setattr(main_module, "_build_mcp_http_app", lambda mcp: ("wrapped", mcp))

    streamable = FakeMcp(streamable=True)
    monkeypatch.setattr(settings_module, "get_settings", lambda: _settings())
    monkeypatch.setattr(tools, "build_mcp", lambda: streamable)
    main_module.run_mcp()
    assert runs.pop() == (("wrapped", streamable), {"host": "127.0.0.1", "port": 9876})

    class FakeApp:
        def __init__(self):
            self.middleware = []

        def add_middleware(self, middleware, **kwargs):
            self.middleware.append((middleware, kwargs))

    monkeypatch.setattr(main_module, "_with_oauth_routes", lambda inner: FakeApp())
    for auth_mode, expected_middleware_count in (("none", 1), ("oauth", 2)):
        sse = FakeMcp(sse=True)
        monkeypatch.setattr(settings_module, "get_settings", lambda mode=auth_mode: _settings(auth_mode=mode))
        monkeypatch.setattr(tools, "build_mcp", lambda item=sse: item)
        main_module.run_mcp()
        app, kwargs = runs.pop()
        assert kwargs == {"host": "127.0.0.1", "port": 9876}
        assert len(app.middleware) == expected_middleware_count


def test_build_mcp_http_app_applies_timeout_and_middleware(monkeypatch):
    class FakeInnerMcp:
        def __init__(self):
            self._session_manager = SimpleNamespace(session_idle_timeout=0)

        def streamable_http_app(self):
            return object()

    class FakeApp:
        def __init__(self):
            self.middleware = []

        def add_middleware(self, middleware, **kwargs):
            self.middleware.append((middleware, kwargs))

    fake_app = FakeApp()
    monkeypatch.setattr(main_module, "_with_oauth_routes", lambda inner: fake_app)
    monkeypatch.setattr(settings_module, "get_settings", lambda: _settings(auth_mode="oauth"))
    mcp = FakeInnerMcp()

    result = main_module._build_mcp_http_app(mcp)

    assert result is fake_app
    assert mcp._session_manager.session_idle_timeout == 9
    assert len(fake_app.middleware) == 3

    no_manager = SimpleNamespace(streamable_http_app=lambda: object())
    fake_app.middleware.clear()
    monkeypatch.setattr(settings_module, "get_settings", lambda: _settings(auth_mode="none"))
    main_module._build_mcp_http_app(no_manager)
    assert len(fake_app.middleware) == 1


def test_run_http(monkeypatch):
    import uvicorn

    import local_shell_mcp.http_app as http_app

    settings = _settings(mode="http")
    calls = []
    monkeypatch.setattr(settings_module, "get_settings", lambda: settings)
    monkeypatch.setattr(settings_module, "validate_public_oauth_configuration", lambda value: calls.append(("validate", value)))
    monkeypatch.setattr(http_app, "build_http_app", lambda: "http-app")
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))

    main_module.run_http()

    assert calls == [("validate", settings), ("http-app", {"host": "127.0.0.1", "port": 9876})]


def test_main_subcommands_and_version(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(jobs, "run_job_runner_cli", lambda argv: calls.append(("job", argv)))
    monkeypatch.setattr(remote_worker_cli, "run_worker_cli", lambda argv: calls.append(("worker", argv)))
    monkeypatch.setattr(human_ui, "run_tui_cli", lambda argv: calls.append(("tui", argv)))
    monkeypatch.setattr(version, "format_version_info", lambda: "version-info")

    main_module.main(["job-runner", "a"])
    main_module.main(["worker", "b"])
    main_module.main(["tui", "c"])
    main_module.main(["version"])
    main_module.main(["--version"])
    main_module.main(["-V"])

    assert calls == [("job", ["a"]), ("worker", ["b"]), ("tui", ["c"])]
    output = capsys.readouterr().out
    assert "version-info" in output
    assert output.count("3.0.0") == 2


def test_main_modes_config_and_errors(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(main_module, "run_http", lambda: calls.append("http"))
    monkeypatch.setattr(main_module, "run_mcp", lambda: calls.append("mcp"))

    config = tmp_path / "config.yaml"
    config.write_text("mode: http\n", encoding="utf-8")

    monkeypatch.setattr(settings_module, "get_settings", lambda: _settings(mode="http"))
    main_module.main(["--config", str(config), "--mode", "http", "--no-remote"])
    assert calls == ["http"]
    assert main_module.os.environ["LOCAL_SHELL_MCP_CONFIG"] == str(config)
    assert main_module.os.environ["LOCAL_SHELL_MCP_MODE"] == "http"
    assert main_module.os.environ["LOCAL_SHELL_MCP_REMOTE_ENABLED"] == "false"

    monkeypatch.setattr(settings_module, "get_settings", lambda: _settings(mode="mcp"))
    main_module.main(["--remote"])
    monkeypatch.setattr(settings_module, "get_settings", lambda: _settings(mode="stdio"))
    main_module.main([])
    assert calls[-2:] == ["mcp", "mcp"]
    assert main_module.os.environ["LOCAL_SHELL_MCP_REMOTE_ENABLED"] == "true"

    monkeypatch.setattr(settings_module, "get_settings", lambda: _settings(mode="both"))
    with pytest.raises(SystemExit, match="mode=both"):
        main_module.main([])
    monkeypatch.setattr(settings_module, "get_settings", lambda: _settings(mode="invalid"))
    with pytest.raises(SystemExit, match="Unsupported mode"):
        main_module.main([])
