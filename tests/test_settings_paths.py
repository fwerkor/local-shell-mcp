from pathlib import Path

import local_shell_mcp.settings as settings_module
from local_shell_mcp.settings import Settings


def test_workspace_relative_defaults_match_resolved_platform_defaults(
    tmp_path, monkeypatch
):
    lexical_workspace = Path("platform-default-workspace")
    lexical_state = lexical_workspace / ".local-shell-mcp"
    lexical_audit = lexical_state / "audit.jsonl"
    lexical_agent_config = lexical_state / "agent_config"

    monkeypatch.setattr(settings_module, "DEFAULT_WORKSPACE_ROOT", lexical_workspace)
    monkeypatch.setattr(settings_module, "DEFAULT_STATE_DIR", lexical_state)
    monkeypatch.setattr(settings_module, "DEFAULT_AUDIT_LOG_PATH", lexical_audit)
    monkeypatch.setattr(
        settings_module, "DEFAULT_AGENT_CONFIG_DIR", lexical_agent_config
    )

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
