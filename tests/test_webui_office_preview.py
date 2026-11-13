"""Pinned LibreChat Office fixture vector, ZIP bomb and real SQLite tool replay tests."""
from __future__ import annotations

import io
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from local_shell_mcp.sqlite_store import shared_database
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.office_preview import (
    DOCX_MIME,
    MAX_ENTRY_BYTES,
    UnsafeOfficeArchive,
    buffer_to_office_html,
    office_html_bucket,
    publish_office_tool_output,
)
from local_shell_mcp.webui.storage import WorkspaceRepository

FIXTURES = Path(__file__).parent / "fixtures/librechat/office"


@pytest.mark.parametrize(('name', 'markers'), [
    ('sample.docx', ['This is a sample DOCX file.', 'lc-docx']),
    ('sample.xlsx', ['Data', 'On', 'Second', 'lc-sheet-panel-1']),
    ('sample.ods', ['Data', 'On', 'Second', 'lc-sheet-panel-1']),
    ('sample.xls', ['Data', 'on', 'first', 'sheet']),
    ('sample.pptx', ['LibreChat conversion fixture', 'Slide 1', 'lc-pptx-list']),
    ('empty.docx', ['lc-docx']),
])
def test_pinned_librechat_office_binary_samples(name, markers):
    rendered = buffer_to_office_html((FIXTURES / name).read_bytes(), name, 'application/octet-stream')
    assert rendered.startswith('<!DOCTYPE html>')
    assert '<script' not in rendered.lower()
    assert '<iframe' not in rendered.lower()
    assert len(rendered.encode('utf8')) <= 512 * 1024
    for marker in markers:
        assert marker in rendered


@pytest.mark.parametrize(('name', 'mime', 'bucket'), [
    ('report.docx', 'text/csv', 'docx'),
    ('deck.pptx', 'text/csv', 'presentation'),
    ('report.txt', DOCX_MIME, None),
    ('weird.bin', DOCX_MIME, None),
    ('noext', DOCX_MIME + '; charset=utf-8', 'docx'),
    ('report.CSV', 'application/octet-stream', 'csv'),
    ('noext', 'text/comma-separated-values', 'csv'),
    ('noext', 'application/x-ms-excel', 'spreadsheet'),
    ('noext', 'application/octet-stream', None),
])
def test_original_office_bucket_precedence(name, mime, bucket):
    assert office_html_bucket(name, mime) == bucket


def _archive_xml(path, payload):
    output = io.BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        archive.writestr(path, payload)
    return output.getvalue()


def test_office_preview_escapes_untrusted_content_and_avoids_script_or_url():
    malicious = 'Hello <script>alert(1)</script> & <img src=x onerror=alert(2)>'
    docx = _archive_xml('word/document.xml',
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
        '<w:p><w:r><w:t>' + malicious.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        + '</w:t></w:r></w:p></w:body></w:document>')
    rendered = buffer_to_office_html(docx, 'x.docx', DOCX_MIME)
    assert '&lt;script&gt;' in rendered and '&lt;img src=x onerror=' in rendered
    assert '<script' not in rendered and '<img' not in rendered
    csv_html = buffer_to_office_html(b'a,<script>alert(1)</script>\n', 'data.csv', 'text/csv')
    assert '&lt;script&gt;' in csv_html and '<script' not in csv_html


def test_office_rejects_xml_entities_and_inflation_and_unknown_binary():
    unsafe = _archive_xml('word/document.xml', '<!DOCTYPE foo [<!ENTITY x SYSTEM "file:///etc/passwd">]><foo/>')
    with pytest.raises(UnsafeOfficeArchive, match='DTD'):
        buffer_to_office_html(unsafe, 'x.docx', DOCX_MIME)
    bomb = _archive_xml('word/document.xml', b'a' * (MAX_ENTRY_BYTES+1024))
    with pytest.raises(UnsafeOfficeArchive, match='decompressed'):
        buffer_to_office_html(bomb, 'x.docx', DOCX_MIME)
    with pytest.raises(ValueError, match='non-ZIP'):
        buffer_to_office_html(b'not a real legacy XLS', 'sample.xls', 'application/vnd.ms-excel')
    assert buffer_to_office_html(b'arbitrary', 'report.txt', DOCX_MIME) is None


def test_office_csv_large_preview_is_truncated_with_banner():
    result = buffer_to_office_html(b'name,value\n' + b'example,1\n'*5100, 'report.csv', 'text/csv')
    assert 'Showing first 5,000 of 5,101 rows.' in result
    assert result.count('<tr>') <= 5000


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


def _synthetic_xlsx(entries: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        for name, source in entries.items():
            archive.writestr(name, source)
    return output.getvalue()


def test_office_empty_tables_missing_docx_body_and_slides():
    from local_shell_mcp.webui.office_preview import _sheets

    assert 'no sheets' in _sheets([])
    docx = _archive_xml('word/document.xml', '<w:document xmlns:w="urn:docx"/>')
    assert '<article class="lc-docx"></article>' in buffer_to_office_html(docx, 'test.docx', DOCX_MIME)
    slides = _archive_xml('ppt/theme/theme1.xml', '<theme/>')
    assert 'no readable slides' in buffer_to_office_html(slides, 'empty.pptx', 'application/octet-stream')


def test_office_html_cap_and_row_char_budget(monkeypatch):
    from local_shell_mcp.webui import office_preview as preview

    with pytest.raises(ValueError, match='512 KiB'):
        preview._document('X' * preview.OFFICE_HTML_OUTPUT_CAP)
    rows = list(preview._bounded_rows([['A'*preview.MAX_VISIBLE_CHARS, 'after'], ['ignored']]))
    assert rows == [['A'*preview.MAX_VISIBLE_CHARS]]
    monkeypatch.setattr(preview, 'MAX_VISIBLE_CHARS', 3)
    assert list(preview._bounded_rows([['xy', 'zzz'], ['ignored']])) == [['xy', 'z']]


def test_office_docx_table_and_truncation_banner():
    text = '<w:p><w:r><w:t>' + 'A'*180000 + '</w:t></w:r></w:p>'
    rows = '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>table cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
    docx = _archive_xml('word/document.xml',
        '<w:document xmlns:w="urn:docx"><w:body>' + rows + text + '<w:p/></w:body></w:document>')
    result = buffer_to_office_html(docx, 'table.docx', DOCX_MIME)
    assert '<td>table cell</td>' in result
    assert 'Preview truncated' in result


def test_office_synthetic_xlsx_inline_unindexed_numeric_missing_relations():
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    workbook = f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' \
               '<sheet name="test" r:id="rId1"/>' \
               '<sheet name="missing" r:id="rId2"/></sheets></workbook>'
    sheet = (f'<worksheet xmlns="{ns}"><sheetData>'
             '<row><c t="inlineStr"><is><t>INLINE</t></is></c>'
             '<c r="ZZ5000"><v>ignored</v></c>'
             '<c r="B2" t="s"><v>99</v></c>'
             '<c r="C2"><v>42</v></c></row><row/>'
             '</sheetData></worksheet>')
    archive = _synthetic_xlsx({'xl/workbook.xml': workbook, 'xl/worksheets/sheet1.xml': sheet,
                               'xl/sharedStrings.xml': f'<sst xmlns="{ns}"><si><t>value</t></si></sst>'})
    result = buffer_to_office_html(archive, 'sheet.xlsx', 'application/octet-stream')
    assert 'INLINE' in result and '<td>42</td>' in result
    assert '<td></td>' in result
    assert 'ignored' not in result
    assert 'missing' not in result


def test_office_synthetic_xlsx_malicious_relation_and_missing_rows():
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    workbook = f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' \
               '<sheets><sheet name="Odd" r:id="r1"/></sheets></workbook>'
    rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="r1" Target="../private.xml"/></Relationships>')
    archive = _synthetic_xlsx({'xl/workbook.xml': workbook,
                               'xl/_rels/workbook.xml.rels': rels,
                               'xl/worksheets/sheet1.xml': f'<worksheet xmlns="{ns}"/>'})
    rendered = buffer_to_office_html(archive, 'safe.xlsx', 'application/octet-stream')
    assert 'Odd' not in rendered  # Single-sheet label omitted by original UI.
    assert '<table' in rendered


def test_office_synthetic_ods_repeated_rows_and_value_fallback():
    xml = ('<office:document-content '
           'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
           'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
           'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
           '<office:body><office:spreadsheet><table:table table:name="Money">'
           '<table:table-row table:number-rows-repeated="3">'
           '<table:table-cell office:value="42" table:number-columns-repeated="2" />'
           '<table:covered-table-cell/>'
           '<table:cell-hidden/>'
           '</table:table-row></table:table></office:spreadsheet></office:body></office:document-content>')
    data = _archive_xml('content.xml', xml)
    rendered = buffer_to_office_html(data, 'data.ods', 'application/octet-stream')
    assert rendered.count('<tr>') == 3
    assert rendered.count('<td>42</td>') == 6


def test_office_synthetic_pptx_multislide_bullets_and_empty():
    slides = _synthetic_xlsx({
        'ppt/slides/slide2.xml': '<p:sld xmlns:p="urn:p" xmlns:a="urn:a">'
                                 '<a:p><a:r><a:t>Second</a:t></a:r></a:p>'
                                 '<a:p><a:r><a:t>Bullet 1</a:t></a:r></a:p>'
                                 '<a:p/></p:sld>',
        'ppt/slides/slide1.xml': '<p:sld xmlns:p="urn:p"><p:spTree/></p:sld>',
        'ppt/media/image.png': 'ignored',
    })
    result = buffer_to_office_html(slides, 'deck.pptx', 'application/octet-stream')
    assert result.find('Slide 1') < result.find('Slide 2')
    assert '(empty slide)' in result
    assert '<li>Bullet 1</li>' in result
    assert 'image.png' not in result


def test_office_invalid_zip_and_reject_entry_over_max(monkeypatch):
    from local_shell_mcp.webui import office_preview as preview

    with pytest.raises(ValueError, match='Malformed Office'):
        preview.buffer_to_office_html(b'PK-broken', 'report.docx', DOCX_MIME)
    payload = _archive_xml('word/document.xml', '<doc/>')
    monkeypatch.setattr(preview, 'MAX_ENTRY_BYTES', 2)
    with pytest.raises(UnsafeOfficeArchive, match='size limit'):
        preview.buffer_to_office_html(payload, 'report.docx', DOCX_MIME)


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
