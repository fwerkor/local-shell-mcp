"""Agent authoring is checked against the actual pinned Zod implementation."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.agent_validation import clean_agent_config, sanitize_model_parameters
from local_shell_mcp.webui.agents import AgentRepository

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/librechat"


def _oracle(cases, *, parameters=False):
    node = shutil.which("node")
    modules = Path(os.environ.get("LSM_REFERENCE_NODE_MODULES", ROOT / "ui/workspace/node_modules"))
    vector_name = "agent_parameter_vectors.json" if parameters else "agent_validation_vectors.json"
    recorded = json.loads((FIXTURES / vector_name).read_text(encoding="utf-8"))
    assert recorded["cases"] == cases, "Regenerate reference vectors after changing source cases"
    assert recorded["source_hashes"] == json.loads((FIXTURES / "agent_config_source_hashes.json").read_text(encoding="utf-8"))
    if node is None or not (modules / "zod").exists():
        assert os.environ.get("LSM_REQUIRE_SOURCE_ORACLES") != "1", "Required original Node/Zod oracle is unavailable"
        return recorded["expected"]
    fixture = FIXTURES / ("agent_parameters_reference.cjs" if parameters else "agent_validation_reference.cjs")
    script = """
const fs=require('fs'); const source=require(process.argv[1]);
const cases=JSON.parse(fs.readFileSync(0,'utf8'));
const parameterMode=process.argv[2]==='parameters';
process.stdout.write(JSON.stringify(cases.map(item => {
 if(parameterMode) return source.sanitizeModelParameters(item);
 const parsed=(item.create ? source.agentCreateSchema : source.agentUpdateSchema).safeParse(item.payload);
 return parsed.success ? {ok:true,value:parsed.data} : {ok:false};
})));
"""
    env = {**os.environ, "NODE_PATH": str(modules)}
    live = json.loads(subprocess.check_output(
        [node, "-e", script, str(fixture), "parameters" if parameters else "schema"],
        input=json.dumps(cases).encode(), env=env,
    ))
    assert live == recorded["expected"], "Recorded vectors must match the pinned original implementation"
    return live


def _graph():
    return {"type": " research ", "name": " Research ", "description": " Find facts ",
            "agent_ids": ["first", "last"], "edges": [{"from": "first", "to": "last", "edgeType": "direct"}],
            "entry_agent_id": "first", "result_agent_id": "last"}


def _cases():
    values = [None, False, True, 0, 1.5, "", "value", [], {}, ["selected"]]
    valid = {"name": "  no implicit truncation  ", "description": None, "instructions": "x" * 80001,
             "avatar": {"filepath": "photo", "source": "local", "discard": True},
             "model_parameters": {"temperature": "0", "custom": {"nested": True}},
             "tools": ["ask_user_question"], "skills": [], "skills_enabled": True,
             "skill_authoring_enabled": False, "skills_scope": "selected", "memory_scope": "agent",
             "agent_ids": [], "edges": [{"from": "", "to": ["child"], "edgeType": "handoff",
                                           "description": "", "prompt": "", "promptKey": "", "discard": True}],
             "end_after_tools": True, "hide_sequential_outputs": False, "stateful_code_sessions": True,
             "stateful_code_environment": "agent-user", "code_environment_id": "env:1",
             "code_workspace_id": "", "repositoryInstructions": "prefer", "artifacts": "auto",
             "git_identity": {"name": " Agent ", "email": " bot@example.org ", "discard": True},
             "recursion_limit": 50, "conversation_starters": ["hello"],
             "tool_resources": {"context": {"file_ids": ["file"], "files": [{"secret": True}]},
                                "file_search": {"file_ids": [], "vector_store_ids": ["vs"]}, "unknown": {}},
             "tool_options": {"file_read": {"defer_loading": True, "allowed_callers": ["direct"],
                                              "run_in_background": False, "describe_intent": True, "discard": True}},
             "subagents": {"enabled": True, "allowSelf": False, "shareFiles": True,
                           "agent_ids": ["child"], "graphs": [_graph()], "discard": True},
             "support_contact": {"name": "admin", "email": "admin@example.org", "discard": True},
             "category": "research", "provider": "openAI", "model": "gpt-test", "secret": "discard"}
    cases = [{"create": create, "payload": copy.deepcopy(payload)}
             for create in (False, True) for payload in ({}, valid, {"provider": "openAI", "model": None})]
    for key in valid:
        for value in values:
            cases.append({"create": False, "payload": {key: value}})
    for key in ("provider", "model"):
        for value in values:
            cases.append({"create": True, "payload": {"provider": "openAI", "model": None, key: value}})
    for key in ("enabled", "allowSelf", "shareFiles", "agent_ids", "graphs"):
        for value in values:
            cases.append({"payload": {"subagents": {key: value}}})
    for mutation in [
        {"agent_ids": ["first", "first"]}, {"agent_ids": ["__start__", "last"]},
        {"agent_ids": ["a:b", "last"]}, {"entry_agent_id": "missing"}, {"result_agent_id": "missing"},
        {"edges": []}, {"agent_ids": ["first", "last", "unconnected"]},
        {"edges": [{"from": "first", "to": "first", "edgeType": "direct"}]},
        {"edges": [{"from": "first", "to": "missing", "edgeType": "direct"}]},
        {"edges": [{"from": ["first", "first"], "to": "last", "edgeType": "direct"}]},
        {"edges": [{"from": "first", "to": [], "edgeType": "direct"}]},
        {"edges": [{"from": "first", "to": "last", "edgeType": "handoff"}]},
        {"edges": [{"from": "first", "to": "last", "edgeType": "direct", "unknown": 1}]},
        {"edges": [{"from": "first", "to": "last", "edgeType": "direct", "excludeResults": True}]},
        {"edges": [{"from": "first", "to": "last", "edgeType": "direct", "prompt": "summary", "excludeResults": True}]},
        {"type": "self"}, {"type": "child"},
    ]:
        graph = {**_graph(), **mutation}
        cases.append({"payload": {"subagents": {"agent_ids": ["child"], "graphs": [graph]}}})
    cases += [{"payload": {"subagents": {"agent_ids": ["id"] * 11}}},
              {"payload": {"subagents": {"graphs": [_graph()] * 11}}},
              {"payload": {"subagents": {"graphs": [_graph()] * 2}}},
              {"payload": {"git_identity": {"name": "Bot", "email": "123+github-actions[bot]@users.noreply.github.com"}}},
              {"payload": {"git_identity": {"name": "invalid\nname", "email": "bot@example.org"}}},
              {"payload": {"git_identity": {"name": "x" * 129, "email": "bot@example.org"}}},
              {"payload": {"support_contact": {"email": "invalid"}}}]
    cases += [{"payload": {"edges": [{"to": "child"}]}},
              {"payload": {"subagents": {"graphs": [{**_graph(), "edges": [{"from": "first", "to": "last"}]}]}}},
              {"payload": {"subagents": {"graphs": [{**_graph(), "name": " "}]}}},
              {"payload": {"subagents": {"graphs": [{**_graph(), "agent_ids": []}]}}}]
    def graph(ids, edges, entry="a", result="d", kind="group"):
        return {"type": kind, "name": kind, "description": "graph", "agent_ids": ids,
                "edges": [{"edgeType": "direct", **edge} for edge in edges],
                "entry_agent_id": entry, "result_agent_id": result}
    branched = graph(["a", "b", "c", "d"], [
        {"from": "a", "to": ["b", "c"]}, {"from": ["b", "c"], "to": "d"}])
    invalid_graphs = [
        graph(["a", "b", "c", "d"], [{"from": "a", "to": ["b", "c"], "prompt": "bad"}, {"from": ["b", "c"], "to": "d"}]),
        graph(["a", "b", "c", "d"], [{"from": "a", "to": ["b", "c"]}, {"from": "b", "to": "d"}, {"from": "c", "to": "d"}]),
        graph(["a", "b", "c", "d"], [{"from": "a", "to": ["b", "c"]}, {"from": "a", "to": "b"}, {"from": ["b", "c"], "to": "d"}]),
        graph(["a", "b", "c", "d"], [{"from": "a", "to": ["b", "c"]}, {"from": "b", "to": "d"}]),
        graph(["a", "b", "c", "d"], [{"from": "a", "to": "d"}, {"from": "b", "to": "c"}, {"from": "c", "to": "b"}]),
        graph(["a", "b", "c", "d"], [{"from": "a", "to": "b", "prompt": "bad"}, {"from": "a", "to": "c"}, {"from": ["b", "c"], "to": "d"}]),
    ]
    for item in [branched, *invalid_graphs]:
        cases.append({"payload": {"subagents": {"graphs": [item]}}})
    long_graphs = []
    for prefix in ("first", "second"):
        ids = [prefix + str(i) for i in range(32)]
        long_graphs.append(graph(ids, [{"from": a, "to": b} for a, b in zip(ids, ids[1:], strict=False)], ids[0], ids[-1], prefix))
    cases.append({"payload": {"subagents": {"graphs": long_graphs}}})
    for key in ("defer_loading", "run_in_background", "describe_intent", "allowed_callers"):
        for value in values:
            cases.append({"payload": {"tool_options": {"tool": {key: value}}}})
    return cases


def test_authoring_schema_matches_original_zod_behavior():
    cases = _cases()
    expected = _oracle(cases)
    actual = []
    for case in cases:
        try:
            value = clean_agent_config(case["payload"], create=case.get("create", False))
            actual.append({"ok": True, "value": value})
        except ValueError:
            actual.append({"ok": False})
    assert actual == expected


def _parameter_cases():
    return [{"temperature": value, "topP": value, "maxTokens": value,
              "thinkingBudget": value, "custom": value}
             for value in [None, False, True, 0, -1, 0.75, "", "  ", "0", " -2 ", "1e3",
                           "0x10", "0b11", "0o10", "Infinity", "NaN", "placeholder", [], {}]]



def test_numeric_model_parameters_match_original_source():
    cases = _parameter_cases()
    assert [sanitize_model_parameters(case) for case in cases] == _oracle(cases, parameters=True)


def test_agent_builder_config_references_revisions_and_denial_rollback(tmp_path):
    db = SQLiteDatabase(tmp_path)
    repo = AgentRepository(db)
    child = repo.create("alice", {"provider": "openAI", "model": None, "name": "Child"})
    foreign = repo.create("bob", {"provider": "openAI", "model": None, "name": "Foreign"})
    parent = repo.create("alice", {"provider": "openAI", "model": None, "name": "Parent",
        "tools": [], "subagents": {"enabled": True, "allowSelf": False, "agent_ids": [child["id"]]},
        "edges": [{"from": "", "to": child["id"], "edgeType": "handoff"}],
        "model_parameters": {"temperature": "0", "max_tokens": "placeholder"}})
    assert parent["tools"] == []
    assert parent["edges"][0]["from"] == parent["id"]
    assert parent["model_parameters"] == {"temperature": 0}
    assert parent["category"] == "general"
    assert repo.get("bob", parent["id"]) is None
    snapshot = repo.get("alice", parent["id"])
    with pytest.raises(PermissionError):
        repo.update("alice", parent["id"], {"edges": [{"from": "", "to": foreign["id"]}]})
    with pytest.raises(ValueError):
        repo.update("alice", parent["id"], {"subagents": {"enabled": True, "agent_ids": ["missing"]}})
    assert repo.get("alice", parent["id"]) == snapshot
    assert len(repo.versions("alice", parent["id"])) == 1
    disabled = repo.update("alice", parent["id"], {"subagents": {"enabled": False, "agent_ids": [foreign["id"]]}})
    assert disabled["subagents"]["enabled"] is False
    assert repo.update("bob", parent["id"], {"name": "tamper"}) is None
    clone = repo.duplicate("alice", parent["id"])["agent"]
    assert clone["edges"][0]["from"] == clone["id"]
    assert clone["edges"][0]["to"] == child["id"]
    assert clone["tools"] == []
    restarted = AgentRepository(SQLiteDatabase(tmp_path))
    assert restarted.get("alice", clone["id"])["edges"] == clone["edges"]


def test_agent_resources_preserve_only_owned_canonical_file_ids(tmp_path):
    db = SQLiteDatabase(tmp_path)
    repo = AgentRepository(db)
    with db.connect() as connection:
        connection.executemany("INSERT INTO attachments(id,owner,name,path) VALUES(?,?,?,?)", [
            ("own", "alice", "a.txt", "/safe/a"), ("foreign", "bob", "b.txt", "/private/b"),
        ])
    agent = repo.create("alice", {"provider": "openAI", "model": None,
        "tool_resources": {"context": {"file_ids": ["own", "foreign"],
            "files": [{"file_id": "own", "filepath": "/forged"}, {"file_id": "missing"}]}}})
    assert agent["tool_resources"] == {"context": {"file_ids": ["own"]}}
    original = repo.get("alice", agent["id"])
    with pytest.raises(ValueError):
        repo.update("alice", agent["id"], {"tools": ["file_read", {"injected": True}]})
    assert repo.get("alice", agent["id"]) == original


def test_duplicate_rewrites_graph_self_members_without_mutating_original(tmp_path):
    repo = AgentRepository(SQLiteDatabase(tmp_path))
    child = repo.create("alice", {"provider": "openAI", "model": None})
    parent = repo.create("alice", {"provider": "openAI", "model": None, "subagents": {
        "enabled": True, "graphs": [{"type": "team", "name": "Team", "description": "Work",
            "agent_ids": ["", child["id"]], "entry_agent_id": "", "result_agent_id": child["id"],
            "edges": [{"from": "", "to": child["id"], "edgeType": "direct"}]}]}})
    clone = repo.duplicate("alice", parent["id"])["agent"]
    graph = clone["subagents"]["graphs"][0]
    assert graph["agent_ids"] == [clone["id"], child["id"]]
    assert graph["entry_agent_id"] == graph["edges"][0]["from"] == clone["id"]
    assert repo.get("alice", parent["id"])["subagents"]["graphs"][0]["entry_agent_id"] == parent["id"]
