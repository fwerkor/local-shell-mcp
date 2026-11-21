"""Original LibreChat detachedAction.ts parser differential with immutable SHA."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from local_shell_mcp.webui.detached_event_actions import (
    parse_completion_projection,
    parse_terminal_evidence,
)


@pytest.fixture
def cases():
    base = {"version": 1, "deliveryKey": "trigger_" + "a" * 64,
            "generationCreatedAt": 1734567890, "taskId": "tooltask_" + "b" * 64,
            "idempotencyKey": "c" * 64, "status": "succeeded",
            "result": "completed", "observedAt": 1734567999}
    projection = {"version": 1, "invocationId": base["deliveryKey"],
                  "generationCreatedAt": base["generationCreatedAt"],
                  "wakeGenerationCreatedAt": base["generationCreatedAt"],
                  "taskId": base["taskId"], "idempotencyKey": base["idempotencyKey"]}
    examples = [("terminal", base), ("projection", projection)]
    for name, values in (("terminal", base), ("projection", projection)):
        for field, wrong in (
            ("version", 0), ("version", True),
            ("generationCreatedAt", -1), ("generationCreatedAt", 1.5),
            ("generationCreatedAt", 2**53), ("generationCreatedAt", 5.0),
            ("taskId", ""), ("taskId", "a" * 129),
            ("idempotencyKey", "F" * 64), ("idempotencyKey", "a" * 63),
            ("idempotencyKey", "a" * 64),
            ("taskId", "🏠" * 65),
        ):
            examples.append((name, {**values, field: wrong}))
    for field, wrong in (("status", "running"), ("status", "failed"),
                         ("status", "cancelled"), ("result", 1),
                         ("result", "🛠" * 16385), ("error", "failed"),
                         ("observedAt", 2**53), ("observedAt", 3.0),
                         ("deliveryKey", ""), ("deliveryKey", "🎒" * 65)):
        examples.append(("terminal", {**base, field: wrong}))
    examples.extend([
        ("terminal", {**base, "status": "failed", "result": None, "error": "error"}),
        ("terminal", {**base, "status": "cancelled", "result": None, "error": "cancel"}),
        ("terminal", {**base, "status": "failed", "result": None, "error": "a" * 2049}),
        ("terminal", {**base, "status": "failed", "result": None, "error": "✔" * 2048}),
        ("terminal", {**base, "status": "failed", "result": None, "error": "🎉" * 1025}),
        ("terminal", {**base, "result": "a" * 32768}),
        ("terminal", {**base, "result": "🎉" * 16385}),
        ("projection", {**projection, "invocationId": "🐬" * 65}),
        ("projection", {**projection, "wakeGenerationCreatedAt": -1}),
        ("projection", {**projection, "wakeGenerationCreatedAt": 3.0}),
        ("terminal", None), ("projection", []),
    ])
    return examples


def test_original_detached_action_source_parsers_are_byte_locked_and_match_bun(cases):
    root = Path(__file__).parent / 'fixtures/librechat/original_agent_triggers'
    manifest = json.loads((Path(__file__).parent.parent/'ui/workspace/UPSTREAM_LOCK.json').read_text(encoding="utf-8"))
    name = 'packages/api/src/agents/triggers/detachedAction.ts'
    record = next(item for item in manifest['modules']
                  if item['repository'] == 'LibreChat' and item['path'] == name)
    assert hashlib.sha256((root/'triggers/detachedAction.ts').read_bytes()).hexdigest() == record['sha256']
    bun = shutil.which('bun')
    if bun is None:
        if os.environ.get('LSM_REQUIRE_SOURCE_ORACLES') == '1':
            pytest.fail('Byte-pinned original detachedAction.ts Bun differential is mandatory')
        pytest.skip('Bun unavailable outside original source oracle CI')
    completed = subprocess.run([bun, str(root/'detached_action_oracle.mjs')],
                               input=json.dumps(cases, ensure_ascii=False),
                               text=True, encoding='utf-8', errors='replace',
                               capture_output=True, check=True, timeout=25)
    observed = json.loads(completed.stdout)
    ours = [(parse_terminal_evidence(value) if kind == 'terminal'
             else parse_completion_projection(value)) for kind, value in cases]
    assert ours == observed
