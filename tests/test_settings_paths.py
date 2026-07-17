from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import local_shell_mcp.settings as settings_module
from local_shell_mcp.settings import (
    Settings,
    get_settings,
    validate_public_oauth_configuration,
)


def test_workspace_relative_defaults_match_resolved_platform_defaults(tmp_path, monkeypatch):
    lexical_workspace = Path("platform-default-workspace")
    lexical_state = lexical_workspace / ".local-shell-mcp"
    lexical_audit = lexical_state / "audit.jsonl"
    lexical_agent_config = lexical_state / "agent_config"

    monkeypatch.setattr(settings_module, "DEFAULT_WORKSPACE_ROOT", lexical_workspace)
    monkeypatch.setattr(settings_module, "DEFAULT_STATE_DIR", lexical_state)
    monkeypatch.setattr(settings_module, "DEFAULT_AUDIT_LOG_PATH", lexical_audit)
    monkeypatch.setattr(settings_module, "DEFAULT_AGENT_CONFIG_DIR", lexical_agent_config)

    workspace = (tmp_path / "custom-workspace").resolve()
    settings = Settings(
        workspace_root=workspace,
        state_dir=lexical_state.resolve(),
        audit_log_path=lexical_audit.resolve(),
        agent_config_dir=lexical_agent_config.resolve(),
    )

    updated = settings.with_workspace_relative_defaults()

    expected_state = workspace / ".local-shell-mcp"
    assert updated.state_dir == expected_state
    assert updated.audit_log_path == expected_state / "audit.jsonl"
    assert updated.agent_config_dir == expected_state / "agent_config"


def test_custom_state_dir_moves_default_audit_and_agent_paths(tmp_path):
    custom_state = (tmp_path / "custom-state").resolve()
    settings = Settings(state_dir=custom_state)

    updated = settings.with_workspace_relative_defaults()

    assert updated.state_dir == custom_state
    assert updated.audit_log_path == custom_state / "audit.jsonl"
    assert updated.agent_config_dir == custom_state / "agent_config"


def test_explicit_agent_and_audit_paths_do_not_follow_custom_state(tmp_path):
    custom_state = (tmp_path / "custom-state").resolve()
    custom_audit = (tmp_path / "logs" / "audit.jsonl").resolve()
    custom_agent = (tmp_path / "agent-config").resolve()
    settings = Settings(
        state_dir=custom_state,
        audit_log_path=custom_audit,
        agent_config_dir=custom_agent,
    )

    updated = settings.with_workspace_relative_defaults()

    assert updated.state_dir == custom_state
    assert updated.audit_log_path == custom_audit
    assert updated.agent_config_dir == custom_agent


def test_public_oauth_requires_strong_secret_and_admin_pin():
    base = {
        "auth_mode": "oauth",
        "public_base_url": "https://control.example.com",
    }

    with pytest.raises(RuntimeError, match="OAUTH_JWT_SECRET"):
        validate_public_oauth_configuration(
            Settings(**base, oauth_jwt_secret="short", oauth_admin_pin="a-strong-admin-pin")
        )

    with pytest.raises(RuntimeError, match="OAUTH_ADMIN_PIN"):
        validate_public_oauth_configuration(
            Settings(**base, oauth_jwt_secret="s" * 32, oauth_admin_pin=None)
        )

    with pytest.raises(RuntimeError, match="OAUTH_ADMIN_PIN"):
        validate_public_oauth_configuration(
            Settings(
                **base,
                oauth_jwt_secret="s" * 32,
                oauth_admin_pin="change-me-long-random-pin",
            )
        )

    with pytest.raises(RuntimeError, match="at least 8 characters"):
        validate_public_oauth_configuration(
            Settings(**base, oauth_jwt_secret="s" * 32, oauth_admin_pin="1234567")
        )

    validate_public_oauth_configuration(
        Settings(**base, oauth_jwt_secret="s" * 32, oauth_admin_pin="12345678")
    )

    validate_public_oauth_configuration(
        Settings(**base, oauth_jwt_secret="s" * 32, oauth_admin_pin="a-strong-admin-pin")
    )


def test_default_oauth_secret_is_random_and_persisted(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "oauth")
    monkeypatch.delenv("LOCAL_SHELL_MCP_OAUTH_JWT_SECRET", raising=False)
    get_settings.cache_clear()

    first = get_settings().oauth_jwt_secret
    get_settings.cache_clear()
    second = get_settings().oauth_jwt_secret

    assert first == second
    assert first != "dev-change-me"
    assert len(first.encode("utf-8")) >= 32
    secret_path = tmp_path / ".state" / "oauth-jwt-secret"
    assert secret_path.read_text(encoding="utf-8").strip() == first


def test_concurrent_oauth_secret_initialization_returns_one_value(tmp_path):
    state_dir = tmp_path / ".state"

    with ThreadPoolExecutor(max_workers=16) as executor:
        values = list(
            executor.map(
                lambda _index: settings_module._get_or_create_oauth_secret(state_dir),
                range(32),
            )
        )

    assert len(set(values)) == 1
    assert (state_dir / "oauth-jwt-secret").read_text(encoding="utf-8").strip() == values[0]


def test_invalid_persisted_oauth_secret_is_not_silently_replaced(tmp_path, monkeypatch):
    state_dir = tmp_path / ".state"
    state_dir.mkdir()
    secret_path = state_dir / "oauth-jwt-secret"
    secret_path.write_text("short", encoding="utf-8")
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(state_dir))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "oauth")
    monkeypatch.delenv("LOCAL_SHELL_MCP_OAUTH_JWT_SECRET", raising=False)
    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="exists but is invalid"):
        get_settings()

    assert secret_path.read_text(encoding="utf-8") == "short"


def test_mcp_session_defaults():
    settings = Settings()

    assert settings.mcp_session_idle_timeout_s == 180
    assert settings.mcp_max_sessions == 1024


def test_removed_dynamic_agent_bridge_settings_are_not_exposed():
    settings = Settings()

    for name in (
        "agent_bridge_enabled",
        "agent_mcp_probe_timeout_s",
        "agent_mcp_call_timeout_s",
        "agent_dynamic_mcp_tools",
    ):
        assert not hasattr(settings, name)
