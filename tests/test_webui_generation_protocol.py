"""Differential tests against the pinned LibreChat protocol.js implementation."""

import itertools
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from starlette.requests import Request

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.generation_protocol import (
    GENERATION_PROTOCOL_HEADER,
    job_generation_protocol,
    negotiate_generation_protocol,
    parse_protocol_version,
    request_protocol,
    requested_generation_protocol,
)
from local_shell_mcp.webui.generations import GenerationStore


def test_negotiation_matches_original_node_for_every_transport_combination():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required only for the upstream differential oracle")
    values = [None, 1, 2, "1", "2", 0, 3, "", "02", True, False, ["2"], {}]
    cases = [
        {"body": {"generationProtocolVersion": body},
         "query": {"generationProtocolVersion": query},
         "headers": {GENERATION_PROTOCOL_HEADER: header}}
        for body, query, header in itertools.product(values, repeat=3)
    ]
    fixture = Path(__file__).parent / "fixtures/librechat/protocol.cjs"
    script = """
const fs = require('fs'); const p = require(process.argv[1]);
const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(cases.map(req => [
 p.getRequestedGenerationProtocol(req), p.negotiateNewGenerationProtocol(req),
 ...[undefined, {}, {generationProtocolVersion: 1}, {generationProtocolVersion: 2},
     {generationProtocolVersion: 'invalid'}].map(metadata =>
   p.negotiateExistingGenerationProtocol(req, {metadata}))
])));
"""
    expected = json.loads(subprocess.check_output(
        [node, "-e", script, str(fixture.resolve())], input=json.dumps(cases).encode(),
    ))
    actual = [[
        requested_generation_protocol(**case), negotiate_generation_protocol(**case),
        *[negotiate_generation_protocol(**case, metadata=metadata)
          for metadata in ({}, {}, {"generationProtocolVersion": 1},
                           {"generationProtocolVersion": 2},
                           {"generationProtocolVersion": "invalid"})],
    ] for case in cases]
    assert actual == expected
    assert parse_protocol_version(1.0) == 1
    assert parse_protocol_version(2.0) == 2
    assert parse_protocol_version(None) is None
    assert job_generation_protocol() == 1


def test_http_duplicate_and_conflicting_protocol_markers_cannot_upgrade():
    def request(query=b"", headers=()):
        return Request({"type": "http", "method": "GET", "path": "/", "query_string": query,
                        "headers": list(headers)})
    assert request_protocol(request()) == 1
    assert request_protocol(request(), {"generationProtocolVersion": 2}) == 2
    assert request_protocol(request(b"generationProtocolVersion=2"), stored_version=1) == 1
    assert request_protocol(request(b"generationProtocolVersion=2&generationProtocolVersion=2")) == 1
    assert request_protocol(request(headers=[(GENERATION_PROTOCOL_HEADER.encode(), b"2")])) == 2
    assert request_protocol(request(headers=[(GENERATION_PROTOCOL_HEADER.encode(), b"2"),
                                            (GENERATION_PROTOCOL_HEADER.encode(), b"1")])) == 1


def test_sqlite_protocol_is_immutable_on_idempotent_retry_and_restart(tmp_path):
    db = SQLiteDatabase(tmp_path)
    store = GenerationStore(db)
    payload = {"text": "hello", "clientRequestId": "request-1"}
    original, fresh = store.begin("alice", payload, protocol_version=1)
    assert fresh and original.protocol_version == 1
    retried, fresh = store.begin("alice", payload, protocol_version=2)
    assert not fresh and retried.run_id == original.run_id and retried.protocol_version == 1
    reopened = GenerationStore(SQLiteDatabase(tmp_path))
    assert reopened.get("alice", original.run_id).protocol_version == 1
    assert reopened.finish("alice", original.run_id, status="complete", text="done")
    assert reopened.events("alice", original.run_id)[-1][1]["generationProtocolVersion"] == 1
    with db.connect() as connection:
        row = connection.execute("SELECT state FROM runs WHERE id=?", (original.run_id,)).fetchone()
        state = json.loads(row["state"])
        state.pop("generationProtocolVersion")
        connection.execute("UPDATE runs SET state=? WHERE id=?", (json.dumps(state), original.run_id))
    assert reopened.get("alice", original.run_id).protocol_version == 1
