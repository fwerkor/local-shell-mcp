"""Differential checks against the unchanged, pinned LibreChat module."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from local_shell_mcp.webui.artifacts import (
    edit_artifact,
    find_all_artifacts,
    replace_artifact_content,
    unescape_latex,
)

FIXTURES = Path(__file__).parent / "fixtures/librechat"
VECTORS = json.loads((FIXTURES / "artifacts_vectors.json").read_text())


def test_pinned_original_artifact_oracle():
    manifest = json.loads((FIXTURES / "artifacts_sources.json").read_text())
    assert manifest["commit"] == "e8f3be08623663d4ad7f7241e693c94469b63bb0"
    assert hashlib.sha256((FIXTURES / "artifacts_reference.cjs").read_bytes()).hexdigest() == manifest["fixtureSha256"]
    assert hashlib.sha256((FIXTURES / "artifacts_latex_reference.cjs").read_bytes()).hexdigest() == manifest["latexFixtureSha256"]
    assert VECTORS["source"] == manifest
    node = shutil.which("node")
    if not node:
        assert os.getenv("LSM_REQUIRE_SOURCE_ORACLES") != "1", "Original Node artifact oracle is required"
        return
    script = "const fs=require('fs'),m=require(process.argv[1]);const cases=JSON.parse(fs.readFileSync(0,'utf8'));console.log(JSON.stringify(cases.map(c=>{const a=m.findAllArtifacts(c.message);return {artifacts:a,replaced:a.map(x=>m.replaceArtifactContent(x.text,x,c.original,c.updated))};})))"
    result = json.loads(subprocess.check_output([node, "-e", script, str(FIXTURES / "artifacts_reference.cjs")], input=json.dumps(VECTORS["cases"]).encode()))
    assert result == VECTORS["expected"]


def test_original_artifact_behavior_matches_python():
    for index, (case, expected) in enumerate(zip(VECTORS["cases"], VECTORS["expected"], strict=True)):
        artifacts = find_all_artifacts(case["message"])
        result = {"artifacts": artifacts, "replaced": [replace_artifact_content(a["text"], a, case["original"], case["updated"]) for a in artifacts]}
        assert result == expected, (index, case, result, expected)


def test_edit_artifact_preserves_other_message_content_and_unescapes_latex():
    original = {"text": "unchanged", "content": [{"type": "tool_call", "text": ":::artifact not text"}, {"type": "text", "text": ":::artifact{x}\n$14\n:::"}]}
    result, path = edit_artifact(original, 0, r"\$14", "$20")
    assert path == "/content/1/text"
    assert result["content"][1]["text"] == ":::artifact{x}\n$20\n:::"
    assert result["text"] == original["text"]
    assert original["content"][1]["text"].endswith("$14\n:::")
    with pytest.raises(ValueError, match="index"):
        edit_artifact(original, 1, "", "")
    with pytest.raises(ValueError, match="not found"):
        edit_artifact(original, 0, "missing", "new")
    assert unescape_latex(r"\\$2 $$\\ce{H2O}$$ $$\\pu{kg}$$") == r"$2 $\ce{H2O}$ $\pu{kg}$"


def test_original_latex_behavior_matches_python():
    assert [unescape_latex(item) for item in VECTORS["latex"]["cases"]] == VECTORS["latex"]["expected"]
