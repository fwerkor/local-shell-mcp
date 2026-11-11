#!/usr/bin/env python3
"""Regenerate golden vectors using the pinned original Node/Zod implementation.

Run export-librechat-agent-config.cjs first when upstream source fixtures change.
Requires development pytest and React build dependencies; no production Node use.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/librechat"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", default=shutil.which("node"))
    parser.add_argument("--node-modules", type=Path, default=ROOT / "ui/workspace/node_modules")
    args = parser.parse_args()
    if not args.node or not (args.node_modules / "zod").is_dir():
        raise RuntimeError("Original Node/Zod reference dependencies are required")
    spec = importlib.util.spec_from_file_location("agent_reference_cases", ROOT / "tests/test_webui_agent_config_source.py")
    assert spec and spec.loader
    cases_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cases_module)
    sources = json.loads((FIXTURES / "agent_config_source_hashes.json").read_text(encoding="utf-8"))
    program = """
const fs = require('fs'); const source = require(process.argv[1]);
const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(cases.map(item => {
 if (process.argv[2] === 'parameters') return source.sanitizeModelParameters(item);
 const schema = item.create ? source.agentCreateSchema : source.agentUpdateSchema;
 const parsed = schema.safeParse(item.payload);
 return parsed.success ? {ok:true, value:parsed.data} : {ok:false};
})));
"""
    for name, cases, parameters in (
        ("agent_validation_vectors.json", cases_module._cases(), False),
        ("agent_parameter_vectors.json", cases_module._parameter_cases(), True),
    ):
        fixture = FIXTURES / ("agent_parameters_reference.cjs" if parameters else "agent_validation_reference.cjs")
        output = subprocess.check_output(
            [args.node, "-e", program, str(fixture), "parameters" if parameters else "schema"],
            input=json.dumps(cases).encode("utf-8"), env={**os.environ, "NODE_PATH": str(args.node_modules)},
        )
        record = {"source_hashes": sources, "cases": cases, "expected": json.loads(output)}
        (FIXTURES / name).write_text(json.dumps(record, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        print(f"Exported {len(cases)} original Node cases: {name}")


if __name__ == "__main__":
    main()
