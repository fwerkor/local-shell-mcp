from __future__ import annotations

import os
import stat
import sys
from pathlib import Path


def _configure_embedded_tui() -> None:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if not bundle_root:
        return
    executable_name = "local-shell-mcp-tui.exe" if os.name == "nt" else "local-shell-mcp-tui"
    candidate = Path(bundle_root) / "local_shell_mcp" / "ui_runtime" / executable_name
    if not candidate.is_file():
        return
    if os.name != "nt":
        candidate.chmod(
            candidate.stat().st_mode
            | stat.S_IXUSR
            | stat.S_IXGRP
            | stat.S_IXOTH
        )
    os.environ.setdefault("LOCAL_SHELL_MCP_UI_TUI_COMMAND", str(candidate))


_configure_embedded_tui()

from local_shell_mcp.main import main  # noqa: E402


if __name__ == "__main__":
    main(sys.argv[1:])
