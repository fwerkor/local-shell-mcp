#!/usr/bin/env python3
"""Record the pinned original MultiAgentGraph construction behavior."""
from __future__ import annotations

import argparse
import itertools
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/librechat"


def cases():
    result = []
    pairs = list(itertools.permutations("abc", 2))
    for mask, kind, entry in itertools.product(range(64), [None, "direct", "handoff"], [None, "a", "b", "c"]):
        edges = [{"from": a, "to": b, **({"edgeType": kind} if kind else {})}
                 for index, (a, b) in enumerate(pairs) if mask & (1 << index)]
        result.append({"agentIds": list("abc"), "edges": edges,
                       **({"entryAgentId": entry} if entry else {})})
    for sources, targets, kind, entry in itertools.product(
            ["a", ["a"], ["a", "b"], ["a", "a"]], ["c", ["b", "c"], ["c", "c"]],
            [None, "direct", "handoff"], [None, "a", "b", "c"]):
        result.append({"agentIds": list("abc"), "edges": [{"from": sources, "to": targets,
                       **({"edgeType": kind} if kind else {})}],
                       **({"entryAgentId": entry} if entry else {})})
    for field in ("memberRecursionLimit", "maxHandoffs"):
        for value in (None, -1, 0, 1, 2.0, 2.5, True, "2", 9007199254740991, 9007199254740992):
            result.append({"agentIds": ["a"], "edges": [], field: value})
    for field in ("entryAgentId", "resultAgentId"):
        for value in (None, "", "a", "missing"):
            result.append({"agentIds": ["a"], "edges": [], field: value})
    result += [{"agentIds": [], "edges": []}, {"agentIds": ["a", "a"], "edges": []},
               {"agentIds": ["a"], "edges": [{"from": ["x", "a"], "to": ["y", "x"]}]}]
    for kind, scope in itertools.product([None, "direct", "handoff"], [None, "turn", "conversation", "bad"]):
        result.append({"agentIds": list("ab"), "edges": [{"from": "a", "to": "b", "edgeType": kind, "handoffScope": scope}]})
    for first, second in itertools.product(["turn", "conversation"], repeat=2):
        for condition in (None, {}):
            result.append({"agentIds": list("abc"), "edges": [
                {"from": "a", "to": "b", "handoffScope": first, "condition": condition},
                {"from": "a", "to": "b" if condition is None else "c", "handoffScope": second, "condition": condition}]})
    for grouped, prompted in itertools.product([False, True], repeat=2):
        result.append({"agentIds": list("abc"), "edges": [
            {"from": "a", "to": "b", "edgeType": "handoff"},
            {"from": ["a", "b"] if grouped else "a", "to": "c", "edgeType": "direct", "prompt": "Work" if prompted else ""}]})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", default=shutil.which("node"))
    args = parser.parse_args()
    vectors = cases()
    program = """const fs=require('fs'),run=require(process.argv[1]);
const cases=JSON.parse(fs.readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(cases.map(c=>{
try{return run(c);}catch(error){return {error:error.message};}})));"""
    expected = json.loads(subprocess.check_output([args.node, "-e", program, str(FIXTURES / "graph_topology_reference.cjs")],
                          input=json.dumps(vectors).encode("utf-8")))
    record = {"sources": json.loads((FIXTURES / "graph_topology_sources.json").read_text(encoding="utf-8")),
              "cases": vectors, "expected": expected}
    (FIXTURES / "graph_topology_vectors.json").write_text(json.dumps(record, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Exported {len(vectors)} original topology constructions")


if __name__ == "__main__":
    main()
