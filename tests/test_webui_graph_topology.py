"""Original SDK construction analysis; execution support is tested separately."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_shell_mcp.webui.graph_topology import GraphTopology, admit_agent_graph

FIXTURES = Path(__file__).parent / "fixtures/librechat"
VECTORS = json.loads((FIXTURES / "graph_topology_vectors.json").read_text(encoding="utf-8"))


def test_original_sdk_topology_cases_match_python():
    for index, (case, expected) in enumerate(zip(VECTORS["cases"], VECTORS["expected"], strict=True)):
        try:
            result = GraphTopology(case["agentIds"], case["edges"], entry_agent_id=case.get("entryAgentId"),
                result_agent_id=case.get("resultAgentId"), member_recursion_limit=case.get("memberRecursionLimit"),
                max_handoffs=case.get("maxHandoffs")).summary()
        except ValueError as error:
            result = {"error": str(error)}
        assert result == expected, (index, case, result, expected)


def test_original_sdk_topology_fixture_provenance_and_live_execution():
    manifest = json.loads((FIXTURES / "graph_topology_sources.json").read_text(encoding="utf-8"))
    assert VECTORS["sources"] == manifest
    assert manifest["commit"] == "c4ffb9b1b78421bf63eba3e56993017f922387f3"
    node = shutil.which("node")
    if not node:
        assert os.environ.get("LSM_REQUIRE_SOURCE_ORACLES") != "1", "Original SDK live oracle is required"
        return
    program = """const fs=require('fs'),run=require(process.argv[1]);
const cases=JSON.parse(fs.readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(cases.map(c=>{
try{return run(c);}catch(error){return {error:error.message};}})));"""
    expected = json.loads(subprocess.check_output([node, "-e", program, str(FIXTURES / "graph_topology_reference.cjs")],
                          input=json.dumps(VECTORS["cases"]).encode("utf-8")))
    assert expected == VECTORS["expected"]


def test_graph_admission_preserves_single_handoff_and_rejects_partial_execution():
    repository = SimpleNamespace(get=lambda owner, ident: {"id": ident} if owner == "alice" and ident in "abcd" else None)
    assert admit_agent_graph("alice", None, repository) is None
    assert admit_agent_graph("alice", {"id": "a", "edges": []}, repository) is None
    topology = admit_agent_graph("alice", {"id": "a", "edges": [{"from": "a", "to": "b"}]}, repository)
    assert topology.handoff_edges == [{"from": "a", "to": "b"}]
    cycle = admit_agent_graph("alice", {"id": "a", "edges": [
        {"from": "a", "to": "b"}, {"from": "b", "to": "a"}]}, repository)
    assert cycle.starting_nodes == ["a"]
    with pytest.raises(PermissionError, match="not owned"):
        admit_agent_graph("bob", {"id": "a", "edges": [{"from": "a", "to": "b"}]}, repository)
    for edge in ({"from": "a", "to": "b", "edgeType": "direct"}, {"from": "a", "to": ["b", "c"]}):
        with pytest.raises(ValueError, match="direct edges require"):
            admit_agent_graph("alice", {"id": "a", "edges": [edge]}, repository)
    with pytest.raises(ValueError, match="entry nodes require"):
        admit_agent_graph("alice", {"id": "a", "edges": [
            {"from": "a", "to": "b"}, {"from": "c", "to": "d"}]}, repository)
