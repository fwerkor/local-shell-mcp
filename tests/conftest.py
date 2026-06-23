from __future__ import annotations

import os
import shlex
import sys


def python_shell_command(code: str) -> str:
    """Return a shell command that runs the current Python interpreter cross-platform."""

    if os.name == "nt":
        escaped_executable = sys.executable.replace("'", "''")
        escaped_code = code.replace("'", "''")
        return f"& '{escaped_executable}' -c '{escaped_code}'"
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"
