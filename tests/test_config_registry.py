import re
from pathlib import Path

from local_shell_mcp.config_registry import SETTING_SPECS, validate_setting_specs
from local_shell_mcp.settings import Settings, load_settings


def test_setting_specs_cover_settings_fields():
    validate_setting_specs()


def test_generated_config_examples_are_current():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "scripts/generate-config-examples.py", "--check"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_config_examples_include_every_registered_setting():
    env_example = Path(".env.example").read_text()
    yaml_example = Path("config.example.yaml").read_text()

    for spec in SETTING_SPECS:
        assert re.search(rf"^{spec.env_var}=", env_example, flags=re.MULTILINE)
        assert re.search(rf"^{spec.name}:", yaml_example, flags=re.MULTILINE)
        for word in spec.help.split():
            assert word in env_example
            assert word in yaml_example


def test_generated_yaml_example_loads_without_losing_defaults(monkeypatch):
    for spec in SETTING_SPECS:
        monkeypatch.delenv(spec.env_var, raising=False)
    monkeypatch.delenv("LOCAL_SHELL_MCP_CONFIG", raising=False)

    settings = load_settings("config.example.yaml", create_dirs=False)
    defaults = Settings()

    assert settings.command_denylist == defaults.command_denylist
    assert settings.path_denylist == defaults.path_denylist
    assert settings.allow_full_container == defaults.allow_full_container
