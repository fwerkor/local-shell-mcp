import json

from local_shell_mcp.agent_bridge import (
    AgentBridgeManifest,
    _redact_text,
    load_agent_manifest,
    redact_mapping,
)
from local_shell_mcp.settings import get_settings


def test_agent_config_dir_defaults_to_home_agent(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.delenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert str(settings.agent_config_dir) == "/home/agent/local-shell-mcp-config"
    assert settings.agent_bridge_enabled is True
    assert settings.agent_mcp_probe_timeout_s == 5


def test_agent_config_dir_env_override(monkeypatch, tmp_path):
    config_dir = tmp_path / "agent-config"
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(config_dir))
    get_settings.cache_clear()

    assert get_settings().agent_config_dir == config_dir.resolve()


def test_load_agent_manifest_missing_config(tmp_path):
    manifest = load_agent_manifest(tmp_path)

    assert manifest.status == "missing_config"
    assert manifest.config_path == tmp_path / "config.json"
    assert manifest.data == AgentBridgeManifest()
    assert manifest.errors == []


def test_load_agent_manifest_valid_config(tmp_path):
    config = {
        "version": 1,
        "mcpServers": {
            "github": {
                "type": "stdio",
                "command": "github-mcp-server",
                "args": ["stdio"],
                "env": {"GITHUB_TOKEN": "secret"},
            },
            "docs": {
                "type": "http",
                "url": "https://example.com/mcp",
                "headers": {"Authorization": "Bearer secret"},
                "enabled": False,
            },
        },
        "skills": {"enabled": True, "directory": "skills"},
        "dynamicTools": {"mcp": False, "skills": True},
    }
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")

    manifest = load_agent_manifest(tmp_path)

    assert manifest.status == "loaded"
    assert manifest.data.mcp_servers["github"].command == "github-mcp-server"
    assert manifest.data.mcp_servers["docs"].enabled is False
    assert manifest.data.dynamic_tools.mcp is False
    assert manifest.data.skills.directory == "skills"


def test_load_agent_manifest_invalid_json(tmp_path):
    (tmp_path / "config.json").write_text("{not-json", encoding="utf-8")

    manifest = load_agent_manifest(tmp_path)

    assert manifest.status == "invalid_config"
    assert manifest.data == AgentBridgeManifest()
    assert manifest.errors
    assert "JSON" in manifest.errors[0] or "Expecting" in manifest.errors[0]


def test_load_agent_manifest_invalid_encoding(tmp_path):
    (tmp_path / "config.json").write_bytes(b'{"version": 1, "bad": "\xff"}')

    manifest = load_agent_manifest(tmp_path)

    assert manifest.status == "invalid_config"
    assert manifest.data == AgentBridgeManifest()
    assert manifest.errors


def test_load_agent_manifest_invalid_schema_does_not_leak_sensitive_inputs(tmp_path):
    config = {
        "version": 1,
        "mcpServers": {
            "docs": {
                "type": "http",
                "url": "https://example.com/mcp",
                "headers": {"Authorization": ["Bearer secret"]},
                "env": {"GITHUB_TOKEN": ["ghp_secret"]},
            }
        },
    }
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")

    manifest = load_agent_manifest(tmp_path)
    errors = "\n".join(manifest.errors)

    assert manifest.status == "invalid_config"
    assert manifest.errors
    assert "Bearer secret" not in errors
    assert "ghp_secret" not in errors


def test_redact_mapping_hides_secret_values():
    redacted = redact_mapping(
        {
            "GITHUB_TOKEN": "ghp_secret",
            "Authorization": "Bearer secret",
            "Cookie": "session=secret",
            "PRIVATE_KEY": "private secret",
            "AWS_ACCESS_KEY_ID": "AKIASECRET",
            "credentials": {"label": "secret"},
            "normal": "visible",
            "nested": {"password": "secret", "label": "ok"},
            "argv": ["--token=secret", "--api-key=secret", "visible"],
            "split_argv": ["--password", "secret", "visible"],
        }
    )

    assert redacted["GITHUB_TOKEN"] == "<redacted>"
    assert redacted["Authorization"] == "<redacted>"
    assert redacted["Cookie"] == "<redacted>"
    assert redacted["PRIVATE_KEY"] == "<redacted>"
    assert redacted["AWS_ACCESS_KEY_ID"] == "<redacted>"
    assert redacted["credentials"] == "<redacted>"
    assert redacted["normal"] == "visible"
    assert redacted["nested"]["password"] == "<redacted>"
    assert redacted["nested"]["label"] == "ok"
    assert redacted["argv"] == ["--token=<redacted>", "--api-key=<redacted>", "visible"]
    assert redacted["split_argv"] == ["--password", "<redacted>", "visible"]
    assert redact_mapping("--token=secret") == "--token=<redacted>"

    spaced_token = redact_mapping("tool --token secret")
    assert "secret" not in spaced_token
    assert "<redacted>" in spaced_token
    assert redact_mapping(["--password secret", "safe"]) == ["--password <redacted>", "safe"]


def test_redact_text_hides_quoted_dict_argv_and_url_userinfo_secrets():
    redacted = _redact_text(
        '{"api_key": "super-secret"} '
        "{'token': 'super-secret'} "
        '["--token", "super-secret"] '
        "['--token', 'super-secret'] "
        "https://user:super-secret@example.com/path"
    )

    assert "super-secret" not in redacted
    assert redacted.count("<redacted>") == 5
    assert '"api_key": "<redacted>"' in redacted
    assert "'token': '<redacted>'" in redacted
    assert '["--token", "<redacted>"]' in redacted
    assert "['--token', '<redacted>']" in redacted
    assert "https://user:<redacted>@example.com/path" in redacted


def test_redact_text_hides_realistic_stringified_secrets():
    redacted = _redact_text(
        'env={"GITHUB_TOKEN": "ghp_secret"} '
        '{ "X-API-Key": "super secret with spaces!" } '
        "AWS_SECRET_ACCESS_KEY=abc123 "
        "Authorization: Basic abc123\n"
        "Cookie: session=abc123; refresh=def456\n"
        "password: multi word secret"
    )

    assert "ghp_secret" not in redacted
    assert "super secret with spaces!" not in redacted
    assert "abc123" not in redacted
    assert "def456" not in redacted
    assert "multi word secret" not in redacted
    assert "<redacted>" in redacted


def test_redact_text_hides_standalone_high_confidence_tokens():
    tokens = [
        "ghp_1234567890abcdef1234567890abcdef123456",
        "sk-1234567890abcdef1234567890abcdef",
        "AKIA1234567890ABCDEF",
    ]

    redacted = _redact_text(f"probe failed with {' '.join(tokens)}")

    for token in tokens:
        assert token not in redacted
    assert "<redacted>" in redacted


def test_agent_bridge_manifest_populates_python_field_names():
    manifest = AgentBridgeManifest(
        mcp_servers={"github": {"type": "stdio", "command": "github-mcp-server"}},
        dynamic_tools={"mcp": False, "skills": True},
    )

    assert manifest.mcp_servers["github"].command == "github-mcp-server"
    assert manifest.dynamic_tools.mcp is False
