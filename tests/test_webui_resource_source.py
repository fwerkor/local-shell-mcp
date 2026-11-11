"""Original Node operators and Python SQLite must agree beyond feature names."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.agents import AgentRepository

FIXTURES = Path(__file__).parent / "fixtures/librechat"
VECTORS = json.loads((FIXTURES / "agent_resource_vectors.json").read_text(encoding="utf-8"))


def normalized(value):
    return {"tools": value.get("tools", []), "tool_resources": value.get("tool_resources", {})}


def test_resource_source_fixture_has_pinned_provenance_and_live_oracle():
    manifest = json.loads((FIXTURES / "agent_resource_sources.json").read_text(encoding="utf-8"))
    assert manifest == VECTORS["sources"]
    assert manifest["commit"] == "e8f3be08623663d4ad7f7241e693c94469b63bb0"
    assert {"addAgentResourceFile", "updateAgent", "removeAgentResourceFiles"} <= set(manifest["functions"])
    node = shutil.which("node")
    if not node:
        assert os.environ.get("LSM_REQUIRE_SOURCE_ORACLES") != "1", "Live original Node oracle is required"
        return
    expected = json.loads(subprocess.check_output([node, str(FIXTURES / "agent_resource_oracle.cjs")],
                         input=json.dumps(VECTORS["cases"]).encode("utf-8")))
    assert expected == VECTORS["expected"]


@pytest.mark.parametrize("operations,expected", list(zip(VECTORS["cases"], VECTORS["expected"], strict=True)))
def test_sqlite_resource_transitions_match_original_update_agent(tmp_path, operations, expected):
    repo = AgentRepository(SQLiteDatabase(tmp_path))
    created = repo.create("alice", {"name": "Resource agent", "provider": "openAI", "model": None,
                                    "tools": [], "tool_resources": {}})
    ident = created["id"]
    with repo.database.connect() as db:
        for blob in ("one", "two"):
            db.execute("INSERT INTO attachments(id,owner,name,path,content_type,metadata) VALUES(?,?,?,?,?,?)",
                       (blob, "alice", blob, "/owned/" + blob, "text/plain", "{}"))
    results = []
    for operation in operations:
        if operation["action"] == "add":
            value = repo.add_resource_file("alice", ident, operation["resource"], operation["file"])
        else:
            value = repo.remove_resource_files("alice", ident, operation["files"])
        versions = repo.versions("alice", ident)
        results.append({**normalized(value), "version": value["version"],
                        "snapshots": [normalized(snapshot) for snapshot in reversed(versions)]})
    assert results == expected
