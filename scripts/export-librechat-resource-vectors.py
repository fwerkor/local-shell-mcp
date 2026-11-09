#!/usr/bin/env python3
"""Run extracted original Agent resource/update operators and record their results."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/librechat"


def cases():
    result = []
    resources = ["context", "file_search", "ocr", "execute_code", "image_edit"]
    for resource in resources:
        result.append([
            {"action": "add", "resource": resource, "file": "one"},
            {"action": "add", "resource": resource, "file": "one"},
            {"action": "add", "resource": resource, "file": "two"},
            {"action": "remove", "files": [{"tool_resource": resource, "file_id": "one"}]},
            {"action": "remove", "files": [{"tool_resource": resource, "file_id": "missing"}]},
            {"action": "remove", "files": []},
            {"action": "remove", "files": [{"tool_resource": resource, "file_id": "two"}]},
            {"action": "add", "resource": resource, "file": "one"},
        ])
    for left in resources:
        for right in resources:
            result.append([
                {"action": "add", "resource": left, "file": "one"},
                {"action": "add", "resource": right, "file": "two"},
                {"action": "remove", "files": [
                    {"tool_resource": left, "file_id": "one"},
                    {"tool_resource": right, "file_id": "two"}]},
            ])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", default=shutil.which("node"))
    args = parser.parse_args()
    if not args.node:
        raise RuntimeError("Node is required to execute original-source functions")
    vectors = cases()
    expected = json.loads(subprocess.check_output([args.node, str(FIXTURES / "agent_resource_oracle.cjs")],
                          input=json.dumps(vectors).encode("utf-8")))
    result = {"sources": json.loads((FIXTURES / "agent_resource_sources.json").read_text(encoding="utf-8")),
              "cases": vectors, "expected": expected}
    (FIXTURES / "agent_resource_vectors.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Exported {len(vectors)} sequences / {sum(map(len, vectors))} original operator transitions")


if __name__ == "__main__":
    main()
