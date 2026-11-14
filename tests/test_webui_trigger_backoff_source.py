"""Direct Bun/TypeScript differential against SHA-pinned LibreChat triggers/backoff.ts."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from local_shell_mcp.webui.subagent_wakeup import waiting_retry_seconds

_ROOT = Path(__file__).parent
_SRC = _ROOT / "fixtures/librechat/trigger_backoff_source.ts"
_ORACLE = _ROOT / "fixtures/librechat/trigger_backoff_oracle.mjs"
_LOCK = _ROOT.parent / "ui/workspace/UPSTREAM_LOCK.json"


def test_original_lc_source_retry_matches_python_sqlite_delivery_deferral():
    upstream = next(item for item in json.loads(_LOCK.read_text())["modules"]
                    if item["repository"] == "LibreChat" and item["path"] ==
                    "packages/api/src/agents/triggers/backoff.ts")
    assert hashlib.sha256(_SRC.read_bytes()).hexdigest() == upstream["sha256"]
    bun = shutil.which("bun")
    if bun is None:
        if os.environ.get("LSM_REQUIRE_SOURCE_ORACLES") == "1":
            pytest.fail("Source-pinned Bun TypeScript oracle is required in CI")
        pytest.skip("Bun is unavailable outside original-source differential CI")
    inputs = [{"since": since, "now": now} for since, now in [
        (0, 0), (1_000, 0), (0, 1), (0, 4_999), (0, 5_000),
        (0, 49_999), (0, 50_000), (0, 50_001),
        (0, 60_001), (0, 90_000), (0, 139_999), (0, 140_000),
        (10_000, 610_000), (0, 600_000), (0, 10_000_000),
    ]]
    result = subprocess.run([bun, str(_ORACLE)], input=json.dumps(inputs), capture_output=True,
                            text=True, check=True, timeout=20)
    assert [waiting_retry_seconds(case["since"], case["now"]) for case in inputs] == [
        int(value) for value in json.loads(result.stdout)]
