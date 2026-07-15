#!/usr/bin/env python3
"""Enforce per-module coverage floors after subprocess data is combined."""

from __future__ import annotations

import json
import sys
from pathlib import Path

GLOBAL_MINIMUM = 93.0
MODULE_MINIMUM = 90.0
CRITICAL_MINIMUM = 92.0
CRITICAL_MODULES = {
    "src/local_shell_mcp/human_ui.py",
    "src/local_shell_mcp/remote.py",
    "src/local_shell_mcp/shell_ops.py",
    "src/local_shell_mcp/tools.py",
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    report_path = Path(args[0] if args else "coverage.json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    failures: list[str] = []

    total = float(report["totals"]["percent_covered"])
    if total < GLOBAL_MINIMUM:
        failures.append(
            f"total coverage {total:.2f}% is below {GLOBAL_MINIMUM:.2f}%"
        )

    for path, details in sorted(report["files"].items()):
        covered = float(details["summary"]["percent_covered"])
        minimum = CRITICAL_MINIMUM if path in CRITICAL_MODULES else MODULE_MINIMUM
        if covered < minimum:
            failures.append(
                f"{path}: {covered:.2f}% is below the {minimum:.2f}% floor"
            )

    if failures:
        print("Coverage gate failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print(
        f"Coverage gates passed: total={total:.2f}%, "
        f"all modules>={MODULE_MINIMUM:.2f}%, "
        f"critical modules>={CRITICAL_MINIMUM:.2f}%"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
