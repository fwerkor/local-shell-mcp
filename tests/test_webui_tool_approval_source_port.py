"""Source differential tests of original LibreChat tool approval decisions."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from local_shell_mcp.webui.tool_approval import (
    is_tool_approval_payload_valid,
    map_tool_approval_resolutions,
    resolve_tool_approval_resume,
)


def test_original_approval_validator_and_decision_map_are_equivalent():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node differential oracle is required in React CI")
    reference = Path(__file__).parent / "fixtures/librechat/hitl_reference.cjs"
    payloads = [
        {"action_requests": [], "review_configs": []},
        {"action_requests": [{"tool_call_id": "a"}], "review_configs": []},
        {"action_requests": [{"tool_call_id": ""}], "review_configs": [{"tool_call_id": "a"}]},
        {"action_requests": [{"tool_call_id": "a"}] * 2, "review_configs": [{"tool_call_id": "a"}] * 2},
        {"action_requests": [{"tool_call_id": "a"}], "review_configs": [{"tool_call_id": "foreign"}]},
        {"action_requests": [{"tool_call_id": "a"}, {"tool_call_id": "b"}],
         "review_configs": [{"tool_call_id": "a", "allowed_decisions": ["approve", "reject", "edit", "respond"]},
                            {"tool_call_id": "b", "allowed_decisions": ["reject", "respond"]}]},
    ]
    cases = []
    for payload in payloads:
        for decisions in [[], [{"tool_call_id": "foreign", "decision": "approve"}],
            [{"tool_call_id": "a", "decision": "approve"}],
            [{"tool_call_id": "a", "decision": "approve"}] * 2,
            [{"tool_call_id": "a", "decision": "edit"}, {"tool_call_id": "b", "decision": "respond"}],
            [{"tool_call_id": "a", "decision": "edit", "editedArguments": []}, {"tool_call_id": "b", "decision": "reject"}],
            [{"tool_call_id": "a", "decision": "edit", "editedArguments": {"value": "changed"}},
             {"tool_call_id": "b", "decision": "respond", "responseText": "Synthetic response"}],
            [{"tool_call_id": "a", "decision": "reject", "reason": "User reason"},
             {"tool_call_id": "b", "decision": "approve"}],
            [{"tool_call_id": "a", "decision": "reject"}, {"tool_call_id": "b", "decision": "reject"}],
            [{"tool_call_id": "a", "decision": "approve"}, {"tool_call_id": "b", "decision": "respond", "responseText": ""}],
        ]:
            cases.append([payload, decisions])
    script = """
const fs = require('node:fs');
const original = require(process.argv[1]);
const cases = JSON.parse(fs.readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(cases.map(([p,d]) => original.resolveToolApprovalResume(p,d))));
"""
    output = subprocess.run([node, "-e", script, str(reference)], input=json.dumps(cases),
        text=True, capture_output=True, check=True)
    assert [resolve_tool_approval_resume(*case) for case in cases] == json.loads(output.stdout)
    assert map_tool_approval_resolutions([
        {"tool_call_id": "a", "decision": "unknown"},
        {"tool_call_id": "b", "decision": "edit"},
        {"tool_call_id": "c", "decision": "respond"},
    ]) == {"a": {"type": "reject", "reason": "Unrecognized approval decision"},
           "b": {"type": "edit", "updatedInput": {}}, "c": {"type": "respond", "responseText": ""}}
    assert not is_tool_approval_payload_valid({})
    assert not is_tool_approval_payload_valid({"action_requests": [{"tool_call_id": "a"}, {"tool_call_id": "b"}],
        "review_configs": [{"tool_call_id": "a"}, {"tool_call_id": "a"}]})
