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
