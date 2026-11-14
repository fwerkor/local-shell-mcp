"""Transient source Steer media: actual owned SQLite files and native providers."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from local_shell_mcp.settings import get_settings
from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import generation_routes
from local_shell_mcp.webui.generations import GenerationStore
from local_shell_mcp.webui.provider_multimodal import native_content_parts
from local_shell_mcp.webui.provider_tool_protocols import native_messages
from local_shell_mcp.webui.providers import ProviderConfig, _messages_for_google, stream_model
from local_shell_mcp.webui.steer_media import encode_steer_media
from local_shell_mcp.webui.steering import SteeringStore


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / '.state'))
    monkeypatch.setenv('LOCAL_SHELL_MCP_AUTH_MODE', 'none')
    get_settings.cache_clear()
    db = SQLiteDatabase(tmp_path / '.state')
    store = GenerationStore(db)
    job, _ = store.begin('local', {'text': 'Original task'})
    monkeypatch.setattr(generation_routes, '_database', lambda: db)
    yield db, store, job, tmp_path / '.state'
    get_settings.cache_clear()


def insert_file(db, root: Path, name: str, data: bytes, mimetype: str = 'image/png'):
    folder = root / 'attachments' / hashlib.sha256(b'local').hexdigest()[:32]
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / name
    dest.write_bytes(data)
    with db.connect() as connection:
        connection.execute('INSERT INTO attachments(id,owner,name,path,content_type,metadata) '
                           'VALUES(?,?,?,?,?,?)', ('f-' + name, 'local', name,
                                                   str(dest), mimetype, '{}'))
    return {'file_id': 'f-' + name}


@pytest.mark.asyncio
async def test_owned_png_and_pdf_transient_model_parts(context):
    db, _, _, root = context
    image = insert_file(db, root, 'photo.png', b'\x89PNG\r\n\x1a\n' + b'media', 'text/plain')
    pdf = insert_file(db, root, 'handout.pdf', b'%PDF-1.4\nexample', 'application/octet-stream')
    item = {'text': 'Analyze', 'quotes': ['A quoted passage'], 'files': [image, pdf]}
    blocks = await encode_steer_media(db, 'local', item, root)
    assert blocks[0]['text'].endswith('Analyze')
    assert '> A quoted passage' in blocks[0]['text']
    assert blocks[1]['image_url']['url'].startswith('data:image/png;base64,')
    assert blocks[2]['file']['file_data'].startswith('data:application/pdf;base64,')
    assert native_content_parts(blocks, 'anthropic')[1]['source']['media_type'] == 'image/png'
    assert native_content_parts(blocks, 'anthropic')[2]['type'] == 'document'
    assert native_content_parts(blocks, 'google')[1]['inlineData']['mimeType'] == 'image/png'
    assert native_content_parts(blocks, 'google')[2]['inlineData']['mimeType'] == 'application/pdf'
    assert _messages_for_google([{'role': 'user', 'content': blocks}])[0][0]['parts'][1]['inlineData']
    assert native_messages([{'role': 'user', 'content': blocks}], 'anthropic')[0][0]['content'][2]['type'] == 'document'
    assert native_messages([{'role': 'user', 'content': blocks}], 'google')[0][0]['parts'][2]['inlineData']


@pytest.mark.asyncio
async def test_owned_file_enforcement_and_missing_media_fallback(context, tmp_path):
    db, _, _, root = context
    outside = tmp_path / 'secret.png'
    outside.write_bytes(b'\x89PNG\r\n\x1a\nPRIVATE')
    folder = root / 'attachments' / hashlib.sha256(b'local').hexdigest()[:32]
    folder.mkdir(parents=True, exist_ok=True)
    symlink = folder / 'bad.png'
    symlink.symlink_to(outside)
    with db.connect() as connection:
        connection.execute('INSERT INTO attachments(id,owner,name,path,content_type,metadata) '
                           'VALUES(?,?,?,?,?,?)', ('bad', 'local', 'bad.png', str(symlink), 'image/png', '{}'))
    parts = await encode_steer_media(db, 'local', {'text': 'Keep my instruction',
                                                    'files': [{'file_id': 'bad'}, {'file_id': 'deleted'}]}, root)
    assert parts[0]['text'] == 'Keep my instruction'
    assert len(parts) == 2 and parts[1]['type'] == 'text'
    assert 'PRIVATE' not in str(parts)
    assert not any(p.get('type') == 'image_url' for p in parts)


@pytest.mark.asyncio
async def test_live_steering_attaches_native_content_without_leaking_sse_bytes(context, monkeypatch):
    db, store, job, root = context
    file = insert_file(db, root, 'pictured.png', b'\x89PNG\r\n\x1a\n' + b'safe content')
    seen = []

    async def model(profile, messages, **kwargs):
        seen.append(messages)
        if len(seen) == 1:
            SteeringStore(db).enqueue('local', {'conversationId': job.conversation_id,
                'generationCreatedAt': job.generation_created_at,
                'clientSteerId': 'image-steer', 'text': 'What is in this image?', 'files': [file]},
                preempt_capable=True)
            yield 'The beginning.'
        else:
            assert messages[-1]['role'] == 'user'
            assert messages[-1]['content'][1]['image_url']['url'].startswith('data:image/png;base64,')
            yield 'I can see the image.'

    monkeypatch.setattr(generation_routes, 'stream_model_with_tools', model)
    await generation_routes._run_model('local', job, ProviderConfig('openai', 'stub', 'http://localhost:10', ''))
    assert len(seen) == 2
    events = [event for _, event in store.events('local', job.run_id)]
    applied = next(e for e in events if e.get('event') == 'on_steer_applied')
    assert applied['data']['part']['files'][0]['file_id'] == file['file_id']
    assert 'base64' not in json.dumps(applied)
    assert any(e.get('responseMessage', {}).get('text', '').endswith('I can see the image.') for e in events)


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['openai', 'anthropic', 'google'])
async def test_native_provider_http_payload_contains_inline_images(monkeypatch, provider):
    from local_shell_mcp.webui.providers import stream_model_with_tools

    encoded = base64.b64encode(b'\x89PNG\r\n\x1a\nFILE').decode()
    parts = [{'type': 'text', 'text': 'Describe'},
             {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + encoded}}]
    seen = []

    def handler(request):
        data = json.loads(request.content)
        seen.append(data)
        return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                              text='data: [DONE]\n\n')

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(
        transport=httpx.MockTransport(handler), **kwargs))
    config = ProviderConfig(provider, 'mock', 'https://provider.example.test/chat', 'key')
    messages = [{'role': 'user', 'content': parts}]
    if provider == 'openai':
        assert [s async for s in stream_model(config, messages)] == []
        assert seen[0]['messages'][0]['content'][1]['image_url']['url'].endswith(encoded)
        return
    assert [s async for s in stream_model(config, messages)] == []
    assert [s async for s in stream_model_with_tools(config, messages, tools=[{
        'type': 'function', 'function': {'name': 'example', 'parameters': {'type': 'object'}}
    }])] == []
    for body in seen:
        block = (body['messages'][0]['content'][1] if provider == 'anthropic'
                 else body['contents'][0]['parts'][1])
        assert (block['source']['data'] if provider == 'anthropic' else block['inlineData']['data']) == encoded


@pytest.mark.asyncio
async def test_prior_steer_media_reencoded_without_persisting_binary(context, monkeypatch):
    from local_shell_mcp.webui.steer_media import stamp_model_messages

    db, store, job, root = context
    file = insert_file(db, root, 'historical.png', b'\x89PNG\r\n\x1a\nHISTORY')
    steering = SteeringStore(db)
    steering.enqueue('local', {
        'conversationId': job.conversation_id, 'generationCreatedAt': job.generation_created_at,
        'text': 'Previous image', 'clientSteerId': 'history-image', 'files': [file],
    }, preempt_capable=True)
    assert len(steering.drain('local', job.run_id, boundary='terminal')) == 1
    assert store.finish('local', job.run_id, status='complete', text='I saw it.')
    next_job, _ = store.begin('local', {'conversationId': job.conversation_id,
        'text': 'What was the image?', 'parentMessageId': job.response_message_id})
    history = store.history('local', job.conversation_id, message_id=next_job.user_message_id)
    steer = next(item for item in history if item.get('source') == 'steer')
    assert steer['files'][0]['file_id'] == file['file_id']
    assert 'base64' not in json.dumps(history)
    model_history = await stamp_model_messages(db, 'local', history, root)
    assert next(item for item in model_history if item.get('source') == 'steer')['content'][1][
        'image_url']['url'].startswith('data:image/png;base64,')
    assert 'base64' not in json.dumps(store.history('local', job.conversation_id,
                                                    message_id=next_job.user_message_id))


def test_openai_payload_strips_steering_metadata():
    from local_shell_mcp.webui.providers import _openai_messages

    payload = _openai_messages([{'role': 'user', 'source': 'steer',
        'files': [{'file_id': 'f1'}], 'content': 'Please correct the answer.'}])
    assert payload == [{'role': 'user', 'content': 'Please correct the answer.'}]


def test_native_media_validation_rejects_untrusted_or_malformed_payloads():
    """Cover malformed parts while retaining genuine source-formatted text."""
    assert native_content_parts('Plain message', 'anthropic') == [
        {'type': 'text', 'text': 'Plain message'}]
    assert native_content_parts('', 'google') == []
    assert native_content_parts(None, 'google') == []
    assert native_content_parts(['text', None, {}, {'type': 'audio'},
                                 {'type': 'text', 'text': None}], 'google') == []
    cases = [
        {'type': 'image_url', 'image_url': {'url': 'https://untrusted.invalid/x.png'}},
        {'type': 'image_url', 'image_url': {'url': 123}},
        {'type': 'image_url'},
        {'type': 'file'},
        {'type': 'image_url', 'image_url': 'not-an-object'},
        {'type': 'file', 'file': 'not-an-object'},
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + 'x' * (8 * 1024 * 1024)}},
        {'type': 'image_url', 'image_url': {'url': 'data:image/svg+xml;base64,YQ=='}},
        {'type': 'file', 'file': {'file_data': 'data:application/pdf;base64,!!'}},
        {'type': 'file', 'file': {'file_data': 'data:application/pdf;base64,YQ==='}},
    ]
    assert native_content_parts(cases, 'anthropic') == []
    assert native_content_parts(cases, 'google') == []
    assert native_content_parts([{'type': 'text', 'text': 'Valid'}], 'anthropic') == [
        {'type': 'text', 'text': 'Valid'}]


@pytest.mark.asyncio
async def test_media_magic_variants_and_text_binary_size_guards(context, tmp_path):
    from local_shell_mcp.webui.steer_media import _detected_type

    db, _, _, root = context
    assert _detected_type(b'\xff\xd8\xffJPG') == 'image/jpeg'
    assert _detected_type(b'GIF87a' + b'a') == 'image/gif'
    assert _detected_type(b'GIF89a' + b'a') == 'image/gif'
    assert _detected_type(b'RIFF0000WEBPVP8') == 'image/webp'
    assert _detected_type(b'Unrecognized') is None
    txt = insert_file(db, root, 'notes.txt', b'Human-readable context', 'text/plain')
    nul = insert_file(db, root, 'binary.bin', b'\x00binary', 'application/octet-stream')
    large = insert_file(db, root, 'too-large.txt', b'x' * 100_000, 'text/plain')
    image = insert_file(db, root, 'jpeg.jpg', b'\xff\xd8\xffvery-minimal', 'image/png')
    result = await encode_steer_media(db, 'local', {
        'text': 'Please consult attachments',
        'files': [txt, nul, large, image, {'file_id': 412}, {'file_id': 'not-available'}],
    }, root)
    assert len(result) == 5
    assert result[1]['text'].endswith('Human-readable context')
    assert result[2]['text'].endswith('use authorized file tools if available.')
    assert result[3]['text'].endswith('use authorized file tools if available.')
    assert result[4]['image_url']['url'].startswith('data:image/jpeg;base64,')
    assert all('\\x00binary' not in str(part) for part in result)

    # The server's legitimate SQLite path cannot be used as a traversal/SSRF
    # escape even if an old row had been tampered with or the upload moved.
    secret = tmp_path / 'outside.txt'
    secret.write_text('owner-secret', encoding='utf-8')
    with db.connect() as conn:
        conn.execute('UPDATE attachments SET path=? WHERE id=?', (str(secret), txt['file_id']))
    failed = await encode_steer_media(db, 'local', {'text': 'Still answer', 'files': [txt]}, root)
    assert failed[0]['text'] == 'Still answer'
    assert 'owner-secret' not in str(failed)


@pytest.mark.asyncio
async def test_media_budget_and_storage_move_degrade_without_losing_steer(context):
    db, _, _, root = context
    too_large = insert_file(db, root, 'big.png', b'\x89PNG\r\n\x1a\n' + b'a' * (4 * 1024 * 1024), 'image/png')
    result = await encode_steer_media(db, 'local', {
        'text': 'Always keep instruction', 'files': [too_large]}, root)
    assert len(result) == 2 and result[0]['text'] == 'Always keep instruction'
    assert result[1]['type'] == 'text'
    assert 'data:' not in str(result)
    # Valid recorded file path but bytes missing after deferred removal.
    folder = root / 'attachments' / hashlib.sha256(b'local').hexdigest()[:32]
    (folder / 'big.png').unlink()
    assert len(await encode_steer_media(db, 'local', {
        'text': 'Unchanged', 'files': [too_large]}, root)) == 2


@pytest.mark.asyncio
async def test_steer_without_file_and_plain_untouched_history(context):
    from local_shell_mcp.webui.steer_media import stamp_model_messages

    db, _, _, root = context
    history = [{'role': 'system', 'content': 'System'},
               {'role': 'user', 'source': 'steer', 'content': 'New request'},
               {'role': 'assistant', 'content': 'Previous answer'}]
    assert await stamp_model_messages(db, 'local', history, root) == history
