"""Differential checks against original pinned LibreChat HITL functions."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.ask_user_tools import (
    ASK_USER_QUESTION_DEFINITION,
    ASK_USER_TOOLS,
    build_ask_user_payload,
    resolve_ask_user_question_resume,
)
from local_shell_mcp.webui.generations import GenerationStore

FIXTURES = Path(__file__).parent / "fixtures" / "librechat"


def test_provider_definition_is_exact_original_source_export():
    original = json.loads((FIXTURES / "ask_user_definition.json").read_text())
    assert original == ASK_USER_QUESTION_DEFINITION
    assert ASK_USER_TOOLS[0]["function"] == {
        "name": original["name"], "description": original["description"], "parameters": original["schema"]}


def test_resume_validation_matches_original_node_functions():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is a development-only differential oracle; required in React CI")
    cases = []
    for payload in [{}, {"questions": None}, {"questions": []},
        {"questions": [{"id": "a"}, {"id": "b"}]},
        {"questions": [{"id": "a"}, {"id": "a"}]},
        {"questions": [{"id": "0bad"}]}, {"questions": [{"id": "a"}] * 5}]:
        for body in [{}, {"answer": ""}, {"answer": " "}, {"answer": "ok"},
            {"answer": "x" * 16001}, {"answer": "😀" * 8001},
            {"answers": []}, {"answers": {"a": "one"}},
            {"answers": {"b": "two", "a": "one"}},
            {"answers": {"a": "", "b": "two"}},
            {"answers": {"a": True, "b": "two"}},
            {"answers": {"a": "x" * 16001, "b": "two"}},
            {"answers": {"a": "one", "b": "two", "unknown": "three"}}]:
            cases.append([payload, body])
    script = """
const fs = require('node:fs');
const oracle = require(process.argv[1]);
const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(cases.map(([p,b]) => oracle.resolveAskUserQuestionResume(p,b))));
"""
    result = subprocess.run([node, "-e", script, str(FIXTURES / "hitl_reference.cjs")],
        input=json.dumps(cases), text=True, capture_output=True, check=True)
    assert [resolve_ask_user_question_resume(*case) for case in cases] == json.loads(result.stdout)


def test_question_schema_limits_strip_unknown_keys_and_batch_fallback():
    payload = build_ask_user_payload({"questions": [{"id": "target", "header": "Where",
        "question": "Choose", "description": "Context", "extra": "strip",
        "options": [{"label": "x" * 280, "value": "v" * 500, "extra": True}],
        "multiSelect": True}, {"id": "format", "question": "Format?"}]}, "call")
    assert payload["tool_call_id"] == "call"
    assert "extra" not in payload["questions"][0]
    assert "id" not in payload["question"] and "header" not in payload["question"]
    assert payload["questions"][0]["options"][0] == {"label": "x" * 280, "value": "v" * 500}
    assert build_ask_user_payload({"question": "legacy", "questions": []}, "old")["question"] == {"question": "legacy"}
    assert len(build_ask_user_payload({"questions": [{"id": "a", "question": "😀" * 1000}]}, "c")["questions"]) == 1
    invalid = [None, {}, {"questions": []}, {"questions": [{}]},
        {"questions": [None]}, {"questions": [{"id": "bad id", "question": "q"}]},
        {"questions": [{"id": "a", "question": "q"}] * 2},
        {"questions": [{"id": "a", "question": ""}]},
        {"questions": [{"id": "a", "question": "😀" * 1001}]},
        {"questions": [{"id": "a", "question": "q", "header": ""}]},
        {"questions": [{"id": "a", "question": "q", "multiSelect": 1}]},
        {"questions": [{"id": "a", "question": "q", "options": "invalid"}]},
        {"questions": [{"id": "a", "question": "q", "options": [None]}]},
        {"questions": [{"id": "a", "question": "q", "options": [{"label": "x" * 281, "value": "v"}]}]},
        {"question": None, "questions": []}]
    for arguments in invalid:
        with pytest.raises(ValueError):
            build_ask_user_payload(arguments, "call")


def test_batch_answers_resume_after_restart_without_losing_question_ids(tmp_path):
    store = GenerationStore(SQLiteDatabase(tmp_path))
    job, _ = store.begin("alice", {"text": "Choose"})
    payload = build_ask_user_payload({"questions": [
        {"id": "file", "question": "File?"}, {"id": "format", "question": "Format?"}]}, "ask")
    pending = {"actionId": "action", "payload": payload}
    assert store.pause_for_question("alice", job.run_id, pending, [], "partial")
    recreated = GenerationStore(SQLiteDatabase(tmp_path))
    with pytest.raises(ValueError, match="every question"):
        recreated.answer_question("alice", job.run_id, "action", {"answers": {"file": "a"}})
    assert recreated.pending_action("alice", job.run_id) == pending
    resumed, history, partial = recreated.answer_question("alice", job.run_id, "action",
        {"answers": {"format": "json", "file": "a"}})
    assert resumed.run_id == job.run_id and partial == "partial"
    assert json.loads(history[-1]["content"]) == {"answers": {"file": "a", "format": "json"}}
    assert list(json.loads(history[-1]["content"])["answers"]) == ["file", "format"]
    with pytest.raises(KeyError):
        recreated.answer_question("alice", job.run_id, "action", {"answers": {"file": "a", "format": "json"}})
