"""Regression tests for the advisory locale-quality audit."""
from pathlib import Path
from runpy import run_path

quality_findings = run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/check-webui-i18n.py")
)["quality_findings"]


def test_detects_english_fallback_and_state_collision():
    source = {
        "com_ui_test_enabled": "Enabled",
        "com_ui_test_disabled": "Disabled",
        "com_ui_test_description": "This is the description.",
        "com_lsm_channel_protocol_openai": "OpenAI Chat Completions",
        "com_ui_test_short": "Model",
    }
    translated = {
        **source,
        "com_ui_test_enabled": "已启用",
        "com_ui_test_disabled": "已启用",
    }
    assert quality_findings(source, translated) == [
        "com_ui_test_description: possible untranslated English text",
        "com_ui_test_enabled / com_ui_test_disabled: identical labels for distinct states",
    ]


def test_distinct_localized_states_and_technical_names_are_valid():
    source = {
        "com_ui_test_select_all": "Select all",
        "com_ui_test_deselect_all": "Deselect all",
        "com_ui_test_description": "This is the description.",
        "com_ui_code_environment_shell_posix": "macOS / Linux / WSL2",
    }
    translated = {
        **source,
        "com_ui_test_select_all": "全选",
        "com_ui_test_deselect_all": "取消全选",
        "com_ui_test_description": "这是说明。",
    }
    assert quality_findings(source, translated) == []
