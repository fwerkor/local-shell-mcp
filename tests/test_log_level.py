from __future__ import annotations

import logging

import pytest

from local_shell_mcp import main


def test_log_level_defaults_to_warning(monkeypatch):
    monkeypatch.delenv("LOCAL_SHELL_MCP_LOG_LEVEL", raising=False)

    assert main._log_level_name() == "WARNING"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("debug", "DEBUG"),
        (" Info ", "INFO"),
        ("warning", "WARNING"),
        ("ERROR", "ERROR"),
        ("critical", "CRITICAL"),
    ],
)
def test_log_level_is_case_insensitive(value, expected):
    assert main._log_level_name(value) == expected


def test_invalid_log_level_is_rejected():
    with pytest.raises(ValueError, match="LOCAL_SHELL_MCP_LOG_LEVEL"):
        main._log_level_name("trace")


def test_configure_logging_sets_root_level(monkeypatch):
    root = logging.getLogger()
    previous_level = root.level
    monkeypatch.setenv("LOCAL_SHELL_MCP_LOG_LEVEL", "debug")
    try:
        assert main._configure_logging() == "DEBUG"
        assert root.level == logging.DEBUG
    finally:
        root.setLevel(previous_level)
