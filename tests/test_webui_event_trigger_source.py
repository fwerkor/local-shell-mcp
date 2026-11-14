"""True Bun execution of byte-identical LibreChat trigger envelope.ts source."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from local_shell_mcp.webui.event_triggers import delivery_key, prepare_source_event

_ROOT = Path(__file__).parent
_ORIGINAL = _ROOT / 'fixtures/librechat/original_agent_triggers'
_LOCK = _ROOT.parent / 'ui/workspace/UPSTREAM_LOCK.json'


def test_exact_original_trigger_envelope_idempotency_and_fields():
    modules = json.loads(_LOCK.read_text())['modules']
    originals = [
        ('packages/api/src/agents/triggers/envelope.ts', _ORIGINAL / 'triggers/envelope.ts'),
        ('packages/api/src/agents/json.ts', _ORIGINAL / 'json.ts'),
    ]
    for name, file in originals:
        source = next((entry for entry in modules
                       if entry['repository'] == 'LibreChat' and entry['path'] == name), None)
        assert source, f'SHA-pinned original source mapping is required for {name}'
        assert hashlib.sha256(file.read_bytes()).hexdigest() == source['sha256']
    bun = shutil.which('bun')
    if not bun:
        if os.environ.get('LSM_REQUIRE_SOURCE_ORACLES') == '1':
            pytest.fail('Original LibreChat Bun TypeScript source oracle is mandatory')
        pytest.skip('Bun unavailable')

    cases = []
    for mode in ('fire', 'steer', 'continue'):
        for text in ('resource ready', '未来事件', 'All done!'):
            body = {'mode':mode,
                    'event':{'id':'evt-42','type':'resource.ready','occurredAt':1786967999000,
                             'payload':{'resourceId':'item-a', 'unicode':text}},
                    'target':{'agentId':'agent_0123'},'input':text}
            if mode == 'continue':
                body['target'].update({'conversationId':'c-123',
                    'parentMessageId':'00000000-0000-0000-0000-000000000000',
                    'bindingId':'evtbind_'+'a'*48})
            if mode == 'steer':
                body['target'].update({'conversationId':'c-123','generationCreatedAt':12345})
            original, _ = prepare_source_event('alice', 'eventkey_abc', 'event-source-42',
                                               body, received_at=12_345)
            inputs = {'version':1,'mode':mode,'requestId':original['requestId'],
                      'deliveryId':original['deliveryId'],'receivedAt':original['receivedAt'],
                      'principal':{'id':'alice'}, 'event':original['event'],
                      'target':original['target'], 'input':text}
            # The caller's source is already trusted and overwritten by ingress.
            inputs['event']['source'] = {'id':'eventkey_abc','type':'remote_api_key'}
            cases.append((inputs, original))
    process = subprocess.run([bun, str(_ORIGINAL / 'oracle.mjs')],
                             input=json.dumps([item[0] for item in cases], ensure_ascii=False),
                             text=True, encoding='utf-8', errors='replace',
                             capture_output=True, timeout=20, check=True)
    oracle = json.loads(process.stdout)
    for result, (_, python) in zip(oracle, cases, strict=True):
        assert 'error' not in result, result
        assert result['key'] == delivery_key(python)
        assert result['envelope'] == python
