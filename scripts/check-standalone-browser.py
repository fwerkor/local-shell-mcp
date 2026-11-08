"""Smoke-test an LSM executable with no bundled Playwright installation."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader

EXPECTED_WEBUI_PAYLOAD = "local_shell_mcp/webui/frontend.tar.gz"


EXPECTED_SIDECAR = {
    "local_shell_mcp/browser_external/browser_sessions.py",
    "local_shell_mcp/browser_external/browser_external_service.py",
    "local_shell_mcp/browser_external/browser_external_paths.py",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    args = parser.parse_args()
    archive = CArchiveReader(str(args.binary.resolve()))
    # PyInstaller records Windows archive paths with backslashes.
    contents = {name.replace("\\", "/") for name in archive.toc}
    missing = EXPECTED_SIDECAR - contents
    assert not missing, f"External browser source is absent from executable: {sorted(missing)}"
    assert EXPECTED_WEBUI_PAYLOAD in contents, "Compiled first-party React WebUI missing from executable"
    assert not any(path.startswith("playwright/") for path in contents), (
        "Playwright package leaked into the standalone executable"
    )

    with tempfile.TemporaryDirectory(prefix="lsm-browser-smoke-") as workspace:
        env = os.environ.copy()
        env.update(
            LOCAL_SHELL_MCP_WORKSPACE_ROOT=workspace,
            LOCAL_SHELL_MCP_STATE_DIR=str(Path(workspace) / ".state"),
            LOCAL_SHELL_MCP_AUTH_MODE="none",
            LOCAL_SHELL_MCP_PYTHON_BIN=sys.executable,
        )
        command = [
            str(args.binary.resolve()),
            "call",
            "browser_session",
            "--direct",
            "--json",
            '{"action":"list"}',
        ]
        completed = subprocess.run(
            command, env=env, capture_output=True, text=True, timeout=45, check=True
        )
        payload = json.loads(completed.stdout)
        assert payload["ok"] is True, payload
        assert payload["data"]["sessions"] == [], payload
    print("Standalone browser sidecar smoke passed; Playwright is external only")


if __name__ == "__main__":
    main()
