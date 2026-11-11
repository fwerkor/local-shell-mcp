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
    original = json.loads((FIXTURES / "ask_user_definition.json").read_text(encoding="utf-8"))
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


async def test_original_catalog_is_available_without_machine_grants_and_is_optional(tmp_path, monkeypatch):
    import httpx
    from starlette.applications import Starlette

    from local_shell_mcp.settings import get_settings
    from local_shell_mcp.webui import agent_routes, generation_routes
    from local_shell_mcp.webui.ask_user_tools import ask_user_requested
    from local_shell_mcp.webui.providers import ProviderConfig

    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    get_settings.cache_clear()
    launched = []
    async def start(*args, **kwargs):
        launched.append(kwargs["ask_user_enabled"])
    monkeypatch.setattr(generation_routes, "_start_task", start)
    monkeypatch.setattr(generation_routes, "provider_config", lambda *_: ProviderConfig("openai", "test", "http://localhost/model", ""))
    app = Starlette(routes=[*agent_routes.agent_routes(), *generation_routes.generation_routes()])
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            catalog = await client.get("/api/agents/tools")
            expected = json.loads((FIXTURES / "ask_user_manifest.json").read_text(encoding="utf-8"))
            assert next(item for item in catalog.json() if item["pluginKey"] == "ask_user_question") == {**expected, "authenticated": True}
            assert (await client.get("/api/agents/tools/ask_user_question/auth")).json() == {"authenticated": True}
            assert (await client.get("/api/agents/tools/unknown/auth")).status_code == 404
            for enabled in [False, True]:
                result = await client.post("/api/agents/chat", json={"text": "Choose", "endpoint": "openAI",
                    "ephemeralAgent": {"ask_user_question": enabled}})
                assert result.status_code == 202
                store = generation_routes._generation_store()
                cid = result.json()["conversationId"]
                with store.database.connect() as db:
                    state = json.loads(db.execute("SELECT state FROM runs WHERE conversation_id=?", (cid,)).fetchone()[0])
                assert state["askUserEnabled"] is enabled
            assert launched == [False, True]
            assert not ask_user_requested({"tools": []}, {"ephemeralAgent": {"ask_user_question": True}})
            assert ask_user_requested({"tools": ["ask_user_question"]}, {})
            assert not ask_user_requested(None, {"ephemeralAgent": {"ask_user_question": "true"}})
            assert not ask_user_requested(None, {})
    finally:
        get_settings.cache_clear()
