"""Owner-validated native Office output tool/SQLite lifecycle and approval replay tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from local_shell_mcp.sqlite_store import shared_database
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.office_preview import DOCX_MIME, publish_office_tool_output
from local_shell_mcp.webui.storage import WorkspaceRepository

FIXTURES = Path(__file__).parent / "fixtures/librechat/office"


@pytest.mark.asyncio
async def test_office_tool_publisher_atomic_sse_final_history_idempotent_and_owner(tmp_path, monkeypatch):
    from local_shell_mcp.settings import get_settings

    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    get_settings.cache_clear()
    db = shared_database(tmp_path / 'state')
    repo = WorkspaceRepository(db)
    store = GenerationStore(db)
    owner = 'local'
    generation, _ = store.begin(owner, {'text': 'Generate a DOCX'})
    content = (FIXTURES / 'sample.docx').read_bytes()
    kwargs = dict(database=db, state_dir=tmp_path / 'state')

    first = await publish_office_tool_output(owner, generation.run_id, 'call_docx',
                                             'report.docx', DOCX_MIME, content, **kwargs)
    assert first['file_id'] and first['status'] == 'ready'
    assert first['textFormat'] == 'html'
    assert 'This is a sample DOCX file.' in first['text']
    events = [entry for _, entry in store.events(owner, generation.run_id)]
    artifact_events = [event for event in events if event.get('event') == 'attachment']
    assert len(artifact_events) == 1
    data = artifact_events[0]['data']
    assert data['file_id'] == first['file_id']
    assert data['toolCallId'] == 'call_docx'
    assert data['messageId'] == generation.response_message_id
    assert data['conversationId'] == generation.conversation_id
    assert not any(key in data for key in ('owner','path','user'))
    with db.connect() as conn:
        file = conn.execute('SELECT path FROM attachments WHERE id=?', (first['file_id'],)).fetchone()
        assert Path(file['path']).read_bytes() == content

    # A restart/replayed tool completion must not duplicate its SQLite link,
    # SSE attachment or physical original file.
    another = await publish_office_tool_output(owner, generation.run_id, 'call_docx',
                                               'report.docx', DOCX_MIME, content, **kwargs)
    assert another['file_id'] == first['file_id']
    assert len([event for _, event in store.events(owner, generation.run_id)
                if event.get('event') == 'attachment']) == 1
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM attachments').fetchone()[0] == 1

    assert store.finish(owner, generation.run_id, status='complete', text='Report attached')
    final = [event for _, event in store.events(owner, generation.run_id) if event.get('final')][-1]
    assert final['responseMessage']['attachments'][0]['file_id'] == first['file_id']
    messages = repo.messages(owner, generation.conversation_id)['messages']
    assert next(item for item in messages if item['role'] == 'assistant')['attachments'][0]['file_id'] == first['file_id']
    with pytest.raises(PermissionError):
        await publish_office_tool_output('other', generation.run_id, 'call_docx',
                                         'stolen.docx', DOCX_MIME, content, **kwargs)
    with pytest.raises(PermissionError):
        await publish_office_tool_output(owner, generation.run_id, 'later',
                                         'report2.docx', DOCX_MIME, content, **kwargs)
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM attachments').fetchone()[0] == 1


@pytest.mark.asyncio
async def test_office_tool_invalid_binary_retains_original_as_download_and_failed_preview(tmp_path, monkeypatch):
    from local_shell_mcp.settings import get_settings

    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    get_settings.cache_clear()
    db = shared_database(tmp_path / 'state')
    store = GenerationStore(db)
    generation, _ = store.begin('local', {'text': 'Generate invalid XLS'})
    invalid_source = b'not a real legacy XLS'
    values = await publish_office_tool_output('local', generation.run_id, 'call_xls',
                                             'legacy.xls', 'application/vnd.ms-excel',
                                             invalid_source,
                                             database=db, state_dir=tmp_path / 'state')
    assert values['status'] == 'failed'
    assert values['previewError'] == 'unsupported'
    assert 'textFormat' not in values
    with db.connect() as conn:
        original = conn.execute('SELECT path FROM attachments WHERE id=?', (values['file_id'],)).fetchone()
        assert Path(original['path']).read_bytes() == invalid_source


@pytest.mark.asyncio
async def test_native_file_write_tool_success_auto_publishes_verified_office_output(tmp_path, monkeypatch):
    """Real original registered LSM native file writer -> Agent callback -> SSE/history."""
    import base64
    import json

    from local_shell_mcp.settings import get_settings
    from local_shell_mcp.webui.agent_runner import AgentRunner
    from local_shell_mcp.webui.lsm_tool_registry import call_tool
    from local_shell_mcp.webui.providers import ModelToolCall

    for key, value in {'STATE_DIR': str(tmp_path / 'state'),
                       'WORKSPACE_ROOT': str(tmp_path), 'REMOTE_ENABLED': 'false',
                       'AUTH_MODE': 'none'}.items():
        monkeypatch.setenv('LOCAL_SHELL_MCP_'+key, value)
    get_settings.cache_clear()
    database = shared_database(tmp_path / 'state')
    store = GenerationStore(database)
    generation, _ = store.begin('local', {'text': 'Create and render native DOCX'})
    repo = WorkspaceRepository(database)
    repo.save_setting('local', 'agent.machine_policy.conversation.'+generation.conversation_id,
                      {'local': 'write'})
    original = (FIXTURES / 'sample.docx').read_bytes()
    call = ModelToolCall('native-office', 'file_write', {
        'path': 'render.docx', 'content': base64.b64encode(original).decode('ascii'), 'encoding': 'base64',
    })
    output = await call_tool('local', generation.conversation_id, call,
                             granted_scopes={'shell:read', 'shell:write', 'shell:execute'})
    native = json.loads(output)
    assert native['ok'] is True
    assert (tmp_path / 'render.docx').read_bytes() == original
    # Call the actual Agent on-completion callback; only checkpoint writes
    # are stubbed because this isolated test does not start a model graph.
    runner = AgentRunner.__new__(AgentRunner)
    runner.owner, runner.generation, runner.database, runner.store = ('local', generation, database, store)
    runner.namespace = ''
    runner.active_config = {'configurable': {'checkpoint_id': 'test'}}
    class _Saver:
        def put_writes(self, *_args, **_kwargs):
            return None
    runner.saver = _Saver()
    await runner._completed(call, {'output': output})
    artifacts = [e['data'] for _, e in store.events('local', generation.run_id)
                 if e.get('event') == 'attachment']
    assert len(artifacts) == 1
    # Original base64 remains intact for native execution/idempotency but is
    # never copied into the size-limited React SSE tool-call preview.
    steps = [event for _, event in store.events('local', generation.run_id)
             if event.get('event') == 'on_run_step_completed']
    assert steps[0]['data']['result']['tool_call']['args']['content'].startswith('[omitted')
    assert call.arguments['content'] == base64.b64encode(original).decode('ascii')
    assert artifacts[0]['toolCallId'] == call.call_id
    assert artifacts[0]['textFormat'] == 'html'
    assert 'sample DOCX' in artifacts[0]['text']
    assert store.finish('local', generation.run_id, status='complete', text='Created')
    reply = next(message for message in repo.messages('local', generation.conversation_id)['messages']
                 if message['role'] == 'assistant')
    assert reply['attachments'][0]['file_id'] == artifacts[0]['file_id']
    with database.connect() as db:
        record = db.execute('SELECT path FROM attachments WHERE id=?', (artifacts[0]['file_id'],)).fetchone()
    assert Path(record['path']).read_bytes() == original
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_native_file_write_artifact_does_not_accept_forged_results(tmp_path, monkeypatch):
    import base64
    import hashlib
    import json

    from local_shell_mcp.settings import get_settings
    from local_shell_mcp.webui.office_preview import publish_native_file_write
    from local_shell_mcp.webui.providers import ModelToolCall

    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    get_settings.cache_clear()
    db = shared_database(tmp_path / 'state')
    store = GenerationStore(db)
    generation, _ = store.begin('local', {'text': 'Attempt spoofing output'})
    original = (FIXTURES / 'sample.xlsx').read_bytes()
    args = {'path': 'output.xlsx', 'content': base64.b64encode(original).decode(), 'encoding': 'base64'}
    good = json.dumps({'ok': True, 'data': {'path': 'output.xlsx', 'bytes': len(original),
                                           'sha256': hashlib.sha256(original).hexdigest()}})
    kwargs = dict(database=db, state_dir=tmp_path / 'state')
    async def published(arguments=args, output=good, name='file_write'):
        return await publish_native_file_write('local', generation,
                                               ModelToolCall('output', name, arguments),
                                               output, **kwargs)
    assert await published(name='run_shell') is None
    assert await published(arguments={**args, 'machine': 'remote'}) is None
    assert await published(arguments={**args, 'machine': ['local']}) is None
    assert await published(arguments={**args, 'machine': {'name':'local'}}) is None
    assert await published(arguments={**args, 'encoding': []}) is None
    assert await published(output='invalid json') is None
    assert await published(output='{"ok":false}') is None
    assert await published(output='{"ok":true,"data":{}}') is None
    assert await published(output=good.replace('output.xlsx', 'output.txt')) is None
    assert await published(arguments={**args, 'content': 'broken'}) is None
    assert await published(arguments={**args, 'encoding': 'bogus'}) is None
    assert await published(arguments={**args, 'encoding': 'base64', 'content': '@@@'}) is None
    assert await published(arguments={**args, 'content': base64.b64encode(b'wrong').decode()}) is None
    assert await published(output=good.replace('"bytes": '+str(len(original)), '"bytes": 0')) is None
    assert await published(output=good.replace('"ok": true', '"ok": 1')) is None
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM attachments').fetchone()[0] == 0
    get_settings.cache_clear()


def test_native_file_write_ui_payload_does_not_exceed_persisted_sse_event_limit():
    import json

    from local_shell_mcp.webui.agent_runner import AgentRunner
    from local_shell_mcp.webui.providers import ModelToolCall

    raw = 'A' * 500000
    call = ModelToolCall('real', 'file_write', {'path': 'data.xlsx', 'content': raw, 'encoding': 'base64'})
    projection = AgentRunner._visible_tool_args(call)
    assert len(json.dumps(projection)) < 20000
    assert call.arguments['content'] == raw
    assert len(AgentRunner._visible_tool_args(ModelToolCall(
        'plain', 'file_write', {'path': 'small.csv', 'content': 'data'}))['content']) == 4
    assert AgentRunner._visible_tool_args(ModelToolCall('other', 'run_shell', {'command': raw}))['command'] == raw


@pytest.mark.asyncio
async def test_office_publisher_rejects_invalid_server_identity(tmp_path):
    db = shared_database(tmp_path / 'state')
    values = dict(database=db, state_dir=tmp_path / 'state')
    with pytest.raises(ValueError, match='non-empty'):
        await publish_office_tool_output('local', 'run', 'call', 'report.docx', DOCX_MIME, b'', **values)
    with pytest.raises(ValueError, match='identity'):
        await publish_office_tool_output('local', '', 'call', 'report.docx', DOCX_MIME, b'data', **values)
    with pytest.raises(ValueError, match='identity'):
        await publish_office_tool_output('local', 'run', 'x'*257, 'report.docx', DOCX_MIME, b'data', **values)
    with pytest.raises(PermissionError, match='no longer active'):
        await publish_office_tool_output('local', 'run', 'call', 'report.docx', DOCX_MIME, b'data', **values)


@pytest.mark.asyncio
async def test_invalid_csv_field_does_not_abort_tool_output_publication(tmp_path, monkeypatch):
    from local_shell_mcp.settings import get_settings

    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    get_settings.cache_clear()
    database = shared_database(tmp_path / 'state')
    store = GenerationStore(database)
    run, _ = store.begin('local', {'text': 'Export unusually long CSV field'})
    # CPython csv.reader raises csv.Error above its default field-size cap.
    original = b'column\n' + b'v' * 140000 + b'\n'
    attachment = await publish_office_tool_output(
        'local', run.run_id, 'call_csv', 'export.csv', 'text/csv', original,
        database=database, state_dir=tmp_path / 'state',
    )
    assert attachment['status'] == 'failed'
    assert attachment['previewError'] == 'unsupported'
    with database.connect() as db:
        row = db.execute('SELECT path FROM attachments WHERE id=?', (attachment['file_id'],)).fetchone()
        assert Path(row['path']).read_bytes() == original
    assert store.finish('local', run.run_id, status='complete', text='Export complete')
    message = next(m for m in WorkspaceRepository(database).messages('local', run.conversation_id)['messages']
                   if m['role'] == 'assistant')
    assert message['attachments'][0]['file_id'] == attachment['file_id']
    assert message['attachments'][0]['status'] == 'failed'
    get_settings.cache_clear()
