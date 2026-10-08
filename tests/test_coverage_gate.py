from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("total", "module", "expected_pass"),
    [
        (95.0, 90.0, True),
        (96.0, 99.0, True),
        (94.99, 100.0, False),
        (96.0, 89.99, False),
    ],
)
def test_ci_coverage_floors(
    tmp_path: Path, total: float, module: float, expected_pass: bool
) -> None:
    report = {
        "totals": {"percent_covered": total},
        "files": {"src/local_shell_mcp/tools.py": {"summary": {"percent_covered": module}}},
    }
    report_path = tmp_path / "coverage.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "scripts/check-coverage.py"), str(report_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is expected_pass, result.stdout + result.stderr


def test_coverage_report_and_ci_gate_share_same_floor() -> None:
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["tool"]["coverage"]["report"]["fail_under"] == 95
