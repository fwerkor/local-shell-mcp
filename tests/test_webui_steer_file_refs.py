"""Steer-upload ownership remains referenced after Agent resource unlink."""

from __future__ import annotations

import json

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui.agents import AgentRepository
from local_shell_mcp.webui.file_deletion import AttachmentDeletionStore
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.steering import SteeringStore


def test_queued_and_applied_steer_file_refs_protect_agent_resource_unlink(tmp_path):
    db = SQLiteDatabase(tmp_path / 'state')
    root = db.root / 'attachments'
    root.mkdir(parents=True, exist_ok=True)
    blob = root / 'retained.txt'
    blob.write_text('Steered attachment is still needed', encoding='utf-8')
    with db.connect() as conn:
        conn.execute('INSERT INTO attachments(id,owner,name,path,content_type,metadata) '
                     'VALUES(?,?,?,?,?,?)',
                     ('steer-file', 'local', 'retained.txt', str(blob), 'text/plain', '{}'))
    agent = AgentRepository(db).create('local', {'name': 'Steering Agent',
                                                'provider': 'openAI', 'model': 'mock'})
    repo = AgentRepository(db)
    repo.add_resource_file('local', agent['id'], 'context', 'steer-file')
    store = GenerationStore(db)
    job, _ = store.begin('local', {'text': 'Use the attached file'}, agent)
    steering = SteeringStore(db)
    acknowledgement = steering.enqueue('local', {'conversationId': job.conversation_id,
        'generationCreatedAt': job.generation_created_at, 'clientSteerId': 'file-steer',
        'text': 'Compare this attached file', 'files': [{'file_id': 'steer-file'}]},
        preempt_capable=False)
    with db.connect() as conn:
        assert 'steer-file' in AttachmentDeletionStore(db).shared_resource_ids(
            conn, ['steer-file'], agent['id'], 'context')
    result = AttachmentDeletionStore(db).delete(['steer-file'], owner='local',
                                                agent_id=agent['id'], resource='context')
    assert result['deletedFileIds'] == []
    assert blob.exists()
    assert repo.get('local', agent['id'])['tool_resources']['context']['file_ids'] == []
    repo.add_resource_file('local', agent['id'], 'context', 'steer-file')
    applied = steering.drain('local', job.run_id, boundary='terminal')
    assert applied[0]['steerId'] == acknowledgement['steerId']
    assert store.finish('local', job.run_id, status='complete', text='Done')
    result = AttachmentDeletionStore(db).delete(['steer-file'], owner='local',
                                                agent_id=agent['id'], resource='context')
    assert result['deletedFileIds'] == [] and blob.exists()
    with db.connect() as conn:
        row = conn.execute('SELECT state FROM runs WHERE id=?', (job.run_id,)).fetchone()
    assert json.loads(row['state'])['steerParts'][0]['files'][0]['file_id'] == 'steer-file'
