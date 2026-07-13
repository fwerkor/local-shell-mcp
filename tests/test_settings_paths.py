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
