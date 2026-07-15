from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

import local_shell_mcp.settings as settings


def test_ui_path_csv_shell_and_default_helpers(tmp_path, monkeypatch):
    assert settings.normalize_ui_path(" /console//nested ") == "/console/nested"
    for value in ("ui", "/", "/a/../b", "/api", "/api/x", "/x?y", "/x#y", r"/x\y"):
        with pytest.raises(ValueError):
            settings.normalize_ui_path(value)

    assert settings._split_csv(None) == []
    assert settings._split_csv(["a", "b"]) == ["a", "b"]
    assert settings._split_csv(" a, ,b ") == ["a", "b"]

    monkeypatch.setattr(settings.os, "name", "nt")
    assert settings.default_shell_executable() == "powershell.exe"
    assert settings.default_python_executable() == "python.exe"
    monkeypatch.setattr(settings.os, "name", "posix")
    assert settings.default_shell_executable() == "/bin/bash"
    assert settings.default_python_executable() == "python3"

    value = tmp_path / "value"
    assert settings._matches_default_path(value, value)

    class BrokenPath:
        def __eq__(self, other):
            return False

        def resolve(self):
            raise OSError("broken")

    assert settings._matches_default_path(BrokenPath(), Path("other")) is False


def test_yaml_flatten_apply_get_settings_and_redaction(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text(
        """
mode: http
ui:
  wallpaper: none
remote:
  enabled: false
port: 9001
""".strip(),
        encoding="utf-8",
    )
    flat = settings._flatten_yaml(config)
    assert flat == {
        "mode": "http",
        "ui_wallpaper": "none",
        "remote_enabled": False,
        "port": 9001,
    }
    with pytest.raises(FileNotFoundError):
        settings._flatten_yaml(tmp_path / "missing.yaml")
    monkeypatch.setattr(settings, "yaml", None)
    with pytest.raises(RuntimeError, match="PyYAML"):
        settings._flatten_yaml(config)

    import yaml

    monkeypatch.setattr(settings, "yaml", yaml)
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("LOCAL_SHELL_MCP_CONFIG", str(config))
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_OAUTH_JWT_SECRET", "x" * 40)
    monkeypatch.setenv("LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN", "secret-pin-value")
    settings.get_settings.cache_clear()
    loaded = settings.get_settings()
    assert loaded.mode == "http"
    assert loaded.port == 9001
    assert loaded.ui_wallpaper == "none"
    assert loaded.remote_enabled is False
    assert loaded.workspace_root == workspace.resolve()
    assert workspace.is_dir()

    dumped = settings.safe_settings_dump(loaded)
    assert dumped["oauth_jwt_secret"] == "<redacted>"
    assert dumped["oauth_admin_pin"] == "<redacted>"
    loaded.oauth_admin_pin = None
    assert settings.safe_settings_dump(loaded)["oauth_admin_pin"] is None


def test_pydantic_settings_validation_and_copy_paths(tmp_path):
    model = settings.Settings(
        workspace_root=tmp_path,
        state_dir=tmp_path / "state",
        audit_log_path=tmp_path / "audit.jsonl",
        agent_config_dir=tmp_path / "agents",
        allow_full_container=True,
        command_denylist=["blocked"],
        path_denylist=["hidden"],
    )
    assert model.command_denylist == []
    assert model.path_denylist == []
    assert model.with_workspace_relative_defaults() is model

    copied = settings._replace_settings(model, port=9999)
    assert copied.port == 9999
    assert model.port != 9999

    config = tmp_path / "settings.yaml"
    config.write_text("port: 7654\nshell:\n  executable: /bin/sh\n", encoding="utf-8")
    applied = model.apply_yaml(config)
    assert applied.port == 7654
    assert applied.shell_executable == "/bin/sh"

    assert settings.Settings(command_denylist="a,b").command_denylist == ["a", "b"]
    assert settings.Settings(path_denylist=["a"]).path_denylist == ["a"]


@pytest.mark.parametrize(
    "updates, message",
    [
        ({"max_jobs": -1}, "greater than or equal"),
        ({"oauth_access_token_ttl_s": -1}, "greater than or equal"),
        ({"port": 0}, "greater than zero"),
        ({"file_download_default_max_downloads": -1}, "greater than or equal"),
    ],
)
def test_additional_numeric_validation(updates, message):
    with pytest.raises(ValueError, match=message):
        settings.Settings(**updates)


def test_oauth_validation_early_returns_and_secret_read(tmp_path):
    settings.validate_public_oauth_configuration(
        settings.Settings(auth_mode="none", oauth_jwt_secret="short")
    )
    settings.validate_public_oauth_configuration(
        settings.Settings(
            auth_mode="oauth",
            oauth_jwt_secret="s" * 32,
            public_base_url=None,
        )
    )

    missing = tmp_path / "missing"
    assert settings._read_oauth_secret(missing) is None
    short = tmp_path / "short"
    short.write_text("tiny", encoding="utf-8")
    assert settings._read_oauth_secret(short) is None
    valid = tmp_path / "valid"
    valid.write_text("v" * 32, encoding="utf-8")
    assert settings._read_oauth_secret(valid) == "v" * 32


def _load_fallback_settings(monkeypatch):
    module_name = "local_shell_mcp._fallback_settings_test"
    path = Path(settings.__file__)
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    monkeypatch.setitem(sys.modules, "pydantic", None)
    monkeypatch.setitem(sys.modules, "pydantic_settings", None)
    spec.loader.exec_module(module)
    assert module._PYDANTIC_AVAILABLE is False
    return module


def test_dependency_light_fallback_settings(tmp_path, monkeypatch):
    fallback = _load_fallback_settings(monkeypatch)

    assert fallback._env_bool("YES") is True
    assert fallback._env_bool("off") is False
    assert fallback._coerce_env_value("true", False) is True
    assert fallback._coerce_env_value("12", 1) == 12
    assert fallback._coerce_env_value("1.5", 1.0) == 1.5
    assert fallback._coerce_env_value("a,b", []) == ["a", "b"]
    assert fallback._coerce_env_value("", None) is None
    assert fallback._coerce_env_value("value", "old") == "value"

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("FALLBACK_ROOT", str(tmp_path / "expanded"))
    path_value = fallback._coerce_env_value("$FALLBACK_ROOT", Path("."))
    assert path_value == (tmp_path / "expanded").resolve()

    workspace = tmp_path / "fallback-workspace"
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / "fallback-state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_PORT", "9010")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    monkeypatch.setenv("LOCAL_SHELL_MCP_COMMAND_DENYLIST", "one,two")
    instance = fallback.Settings()
    assert instance.port == 9010
    assert instance.remote_enabled is False
    assert instance.command_denylist == ["one", "two"]
    assert instance.workspace_root == workspace.resolve()

    dumped = instance.model_dump(mode="json")
    assert dumped["workspace_root"] == str(workspace.resolve())
    assert instance.model_copy(update={"port": 9020}).port == 9020

    yaml_path = tmp_path / "fallback.yaml"
    yaml_path.write_text("port: 9030\nui:\n  wallpaper: none\n", encoding="utf-8")
    applied = instance.apply_yaml(yaml_path)
    assert applied.port == 9030
    assert applied.ui_wallpaper == "none"

    for name in (
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT",
        "LOCAL_SHELL_MCP_STATE_DIR",
        "LOCAL_SHELL_MCP_PORT",
        "LOCAL_SHELL_MCP_REMOTE_ENABLED",
        "LOCAL_SHELL_MCP_COMMAND_DENYLIST",
    ):
        monkeypatch.delenv(name, raising=False)
    relative = fallback.Settings(
        workspace_root=workspace,
        state_dir=fallback.DEFAULT_STATE_DIR,
        audit_log_path=fallback.DEFAULT_AUDIT_LOG_PATH,
        agent_config_dir=fallback.DEFAULT_AGENT_CONFIG_DIR,
    ).with_workspace_relative_defaults()
    assert relative.state_dir == workspace.resolve() / ".local-shell-mcp"
    assert relative.audit_log_path == relative.state_dir / "audit.jsonl"

    unrestricted = fallback.Settings(allow_full_container=True)
    assert unrestricted.command_denylist == []
    assert unrestricted.path_denylist == []


def test_get_settings_creates_relative_defaults(tmp_path, monkeypatch):
    workspace = tmp_path / "new-workspace"
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(workspace))
    monkeypatch.delenv("LOCAL_SHELL_MCP_STATE_DIR", raising=False)
    monkeypatch.delenv("LOCAL_SHELL_MCP_AUDIT_LOG_PATH", raising=False)
    monkeypatch.delenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", raising=False)
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.delenv("LOCAL_SHELL_MCP_CONFIG", raising=False)
    settings.get_settings.cache_clear()

    loaded = settings.get_settings()

    assert loaded.state_dir == workspace.resolve() / ".local-shell-mcp"
    assert loaded.audit_log_path.parent.is_dir()
    assert loaded.agent_config_dir.is_dir()
