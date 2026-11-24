from __future__ import annotations

import base64
import os
import shlex
import sys

import pytest


@pytest.fixture(autouse=True)
def reset_process_local_ui_token():
    """Keep the process-local privileged UI credential isolated between tests."""

    from local_shell_mcp import ui_security

    ui_security._UI_LOCAL_TOKENS.clear()
    yield
    ui_security._UI_LOCAL_TOKENS.clear()


def python_shell_command(code: str) -> str:
    """Return a shell command that runs the current Python interpreter cross-platform."""

    if os.name == "nt":
        escaped_executable = sys.executable.replace("'", "''")
        encoded = base64.b64encode(code.encode("utf-8")).decode("ascii")
        wrapper = f"import base64; exec(base64.b64decode('{encoded}'))"
        return f'& "{escaped_executable}" -c "{wrapper}"'
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


@pytest.fixture
def legacy_file_state_backend(monkeypatch):
    """Preserve legacy file-specific contract tests alongside SQLite-default tests.

    Old tests intentionally inspect audit.jsonl, job backup files, lock files,
    and on-disk registry permissions. Do not silently assume those file-level
    contracts apply to SQLite. New SQLite-default tests verify migrations and
    DB-backed equivalents independently.
    """
    from local_shell_mcp.settings import get_settings

    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_BACKEND", "file")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def isolated_controller_settings(tmp_path, monkeypatch):
    """Prevent tests of real controller helpers from touching system state."""
    from local_shell_mcp.settings import get_settings

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S", "0")
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()
