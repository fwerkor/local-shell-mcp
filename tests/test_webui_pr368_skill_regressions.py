"""Regressions for PR #368 Skill and bookmark review findings."""
from __future__ import annotations

import io
import zipfile

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Route

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import routes, skill_routes, skill_tree_routes, tag_routes
from local_shell_mcp.webui.skill_runtime import active_skills, catalog, load
from local_shell_mcp.webui.storage import WorkspaceRepository, _json


@pytest.fixture
def state(tmp_path, monkeypatch):
    from local_shell_mcp.settings import get_settings

    monkeypatch.setenv('LOCAL_SHELL_MCP_WORKSPACE_ROOT', str(tmp_path))
    monkeypatch.setenv('LOCAL_SHELL_MCP_STATE_DIR', str(tmp_path / '.local-shell-mcp'))
    get_settings.cache_clear()
    repo = WorkspaceRepository(SQLiteDatabase(tmp_path))
    for module in (routes, skill_routes, skill_tree_routes, tag_routes):
        monkeypatch.setattr(module, '_repo', lambda: repo)
        monkeypatch.setattr(module, '_owner', lambda request: request.headers.get('x-owner', 'alice'))
    server = Starlette(routes=[*tag_routes.tag_routes(), *skill_tree_routes.skill_tree_routes(),
                               *skill_routes.skill_routes(), Route('/api/convos', routes.conversations, methods=['GET'])])
    yield server, repo
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_folder_delete_matches_literal_underscore_and_percent(state):
    server, repo = state
    from local_shell_mcp.webui.auth import public_owner_id

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                 base_url='http://example.test') as c:
        sid = (await c.post('/api/skills', json={
            'name': 'folders', 'description': 'test', 'body': 'Instructions',
        })).json()['_id']
        folders = {}
        for folder_name in ('a_b', 'axb', 'a%b', 'axyb'):
            result = await c.post(f'/api/skills/{sid}/tree', json={
                'type': 'folder', 'name': folder_name,
            })
            assert result.status_code == 201, result.text
            assert result.json()['author'] == public_owner_id('alice')
            folders[folder_name] = result.json()['_id']
            saved = await c.post(f'/api/skills/{sid}/tree', json={
                'type': 'file', 'name': 'one.txt', 'parentId': folders[folder_name],
            })
            assert saved.status_code == 201
        for folder_name in ('a_b', 'a%b'):
            assert (await c.delete(f'/api/skills/{sid}/tree/{folders[folder_name]}')).status_code == 200
        with repo.database.connect() as db:
            rows = db.execute('SELECT path FROM webui_skill_files WHERE skill_id=? ORDER BY path',
                              (sid,)).fetchall()
        assert [row['path'] for row in rows] == ['axb/one.txt', 'axyb/one.txt']


@pytest.mark.asyncio
async def test_raw_binary_and_runtime_supporting_files(state):
    server, repo = state
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                 base_url='http://example.test') as c:
        sid = (await c.post('/api/skills', json={
            'name': 'references', 'description': 'reference test', 'body': 'Read references/guide.md',
        })).json()['_id']
        content = await c.post(f'/api/skills/{sid}/files',
                               data={'relativePath': 'references/guide.md'},
                               files={'file': ('guide.md', b'Guide text', 'text/markdown')})
        assert content.status_code == 200
        assert load(repo.database, 'alice', None, 'references', path='references/guide.md') == 'Guide text'
        for denied in ('../secrets', '/etc/passwd', 'missing.md'):
            with pytest.raises(ValueError):
                load(repo.database, 'alice', None, 'references', path=denied)
        with pytest.raises(ValueError):
            load(repo.database, 'bob', None, 'references', path='references/guide.md')
        image = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
        uploaded = await c.post(f'/api/skills/{sid}/files',
                                data={'relativePath': 'assets/sample.png'},
                                files={'file': ('sample.png', image, 'image/png')})
        assert uploaded.status_code == 200
        raw = await c.get(f'/api/skills/{sid}/files/assets%2Fsample.png?raw=true')
        assert raw.content == image and raw.headers['content-type'] == 'image/png'
        assert (await c.get(f'/api/skills/{sid}/files/assets%2Fsample.png')).json()['isBinary']
        assert (await c.get(f'/api/skills/{sid}/files/assets%2Fsample.png?raw=true',
                            headers={'x-owner': 'bob'})).status_code == 404


@pytest.mark.asyncio
async def test_main_skill_document_is_readable_but_not_writable(state):
    server, _ = state
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                 base_url='http://example.test') as c:
        created = await c.post('/api/skills', json={
            'name': 'main-file', 'description': 'Visible source',
            'body': 'Main instructions\n', 'alwaysApply': True,
        })
        assert created.status_code == 201
        sid = created.json()['_id']
        # The file viewer renders SKILL.md even when other resources exist.
        upload = await c.post(f'/api/skills/{sid}/files',
                              data={'relativePath': 'references/readme.md'},
                              files={'file': ('readme.md', b'Reference', 'text/markdown')})
        assert upload.status_code == 200
        url = f'/api/skills/{sid}/files/SKILL.md'
        response = await c.get(url)
        assert response.status_code == 200
        assert response.json()['mimeType'] == 'text/markdown'
        source = response.json()['content']
        assert source.startswith('---\n')
        assert 'name: main-file' in source
        assert 'description: Visible source' in source
        assert 'always-apply: true' in source
        assert source.endswith('Main instructions\n')
        raw = await c.get(url + '?raw=true')
        assert raw.status_code == 200
        assert raw.text == source
        assert raw.headers['x-content-type-options'] == 'nosniff'
        assert raw.headers['content-type'].startswith('text/markdown')
        assert (await c.get(url, headers={'x-owner': 'bob'})).status_code == 404
        assert (await c.delete(url)).status_code == 400
        assert (await c.post(url, data={'relativePath': 'SKILL.md'},
                             files={'file': ('SKILL.md', b'overwrite')})).status_code == 400
        assert (await c.get(url)).json()['content'] == source


@pytest.mark.asyncio
async def test_deployment_main_skill_document_uses_installed_loader(state, monkeypatch):
    server, _ = state
    monkeypatch.setattr(skill_routes, 'load_installed_skill',
                        lambda name: {'content': '# Deployment instructions' + name})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                 base_url='http://example.test') as c:
        url = '/api/skills/deployment:example/files/SKILL.md'
        response = await c.get(url)
        assert response.status_code == 200
        assert response.json()['content'] == '# Deployment instructionsexample'
        raw = await c.get(url + '?raw=true')
        assert raw.status_code == 200
        assert raw.text == '# Deployment instructionsexample'
        assert (await c.delete(url)).status_code == 400


@pytest.mark.asyncio
async def test_imported_frontmatter_and_disabled_model_invocation(state):
    server, repo = state
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('demo/SKILL.md', '---\nname: demo\n'
                   'description: Demo\nalways-apply: true\n---\nUse demo')
        z.writestr('demo/references/helper.md', 'Use helper')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                 base_url='http://example.test') as c:
        resp = await c.post('/api/skills/import',
                            files={'file': ('demo.zip', archive.getvalue(), 'application/zip')})
        assert resp.status_code == 201, resp.text
        sid = resp.json()['_id']
        assert resp.json()['alwaysApply'] is True
        assert 'Use demo' in catalog(repo.database, 'alice', None)
        assert load(repo.database, 'alice', None, 'demo', path='references/helper.md') == 'Use helper'
        patch = await c.patch(f'/api/skills/{sid}', json={
            'expectedVersion': 1, 'frontmatter': {'disable-model-invocation': True},
        })
        assert patch.status_code == 200
        assert 'demo' not in catalog(repo.database, 'alice', None)
        with pytest.raises(ValueError):
            load(repo.database, 'alice', None, 'demo')


@pytest.mark.asyncio
async def test_skill_policy_blocks_writes_and_projects_legacy_records(state):
    server, repo = state
    repo.save_setting('alice', 'webui.filters.config', {
        'skills': {'pii': {'starterPatterns': ['sk_prefix'], 'action': 'block'}},
    })
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                 base_url='http://example.test') as c:
        forbidden = await c.post('/api/skills', json={
            'name': 'blocked', 'description': 'test', 'body': 'sk-prohibited-token',
        })
        assert forbidden.status_code == 422
        resp = await c.post('/api/skills', json={
            'name': 'clean', 'description': 'test', 'body': 'Clean',
        })
        assert resp.status_code == 201
        sid = resp.json()['_id']
        assert (await c.patch(f'/api/skills/{sid}', json={
            'expectedVersion': 1, 'body': 'sk-prohibited-token',
        })).status_code == 422
        forbidden_file = await c.post(f'/api/skills/{sid}/files',
                                      data={'relativePath': 'references/secret.md'},
                                      files={'file': ('secret.md', b'sk-prohibited-token', 'text/markdown')})
        assert forbidden_file.status_code == 422
    with repo.database.connect() as db:
        db.execute('UPDATE webui_skills SET record=? WHERE id=?',
                   (_json({'name': 'clean', 'description': 'test', 'body': 'sk-prohibited-token'}), sid))
    assert active_skills(repo.database, 'alice', None) == [] or all(
        item['id'] != sid for item in active_skills(repo.database, 'alice', None))


@pytest.mark.asyncio
async def test_bookmark_filter_before_pagination(state):
    server, repo = state
    first = repo.create_conversation('alice', {'title': 'Tagged', 'tags': ['a_b']})
    second = repo.create_conversation('alice', {'title': 'Other', 'tags': ['axb']})
    repo.create_conversation('bob', {'title': 'Foreign', 'tags': ['a_b']})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                 base_url='http://example.test') as c:
        response = await c.get('/api/convos?tags=a_b&limit=1')
        assert response.status_code == 200, response.text
        assert [r['conversationId'] for r in response.json()['conversations']] == [first['conversationId']]
        assert response.json()['nextCursor'] is None
        assert (await c.get('/api/convos?tags=axb')).json()['conversations'][0]['title'] == 'Other'
        # A multi-select bookmark filter is a union, not an intersection.
        combined = await c.get('/api/convos?tags=a_b&tags=axb&limit=10')
        assert combined.status_code == 200, combined.text
        assert {r['conversationId'] for r in combined.json()['conversations']} == {
            first['conversationId'], second['conversationId']}
        # Filtering must also precede cursor pagination.
        page = await c.get('/api/convos?tags=a_b&tags=axb&limit=1')
        assert len(page.json()['conversations']) == 1
        assert page.json()['nextCursor'] is not None
        next_page = await c.get('/api/convos', params={
            'tags': ['a_b', 'axb'], 'limit': 1, 'cursor': page.json()['nextCursor']})
        assert len(next_page.json()['conversations']) == 1
        assert {page.json()['conversations'][0]['conversationId'],
                next_page.json()['conversations'][0]['conversationId']} == {
                    first['conversationId'], second['conversationId']}


@pytest.mark.asyncio
async def test_delegated_agent_receives_only_its_selected_skill_catalog(state, monkeypatch):
    from local_shell_mcp.webui import lsm_tool_registry
    from local_shell_mcp.webui.agent_runner import AgentRunner
    from local_shell_mcp.webui.generations import GenerationStore
    from local_shell_mcp.webui.providers import ProviderConfig

    _server, repo = state
    monkeypatch.setattr(lsm_tool_registry, 'available_tools', lambda *args, **kwargs: [])
    db = repo.database
    selected = None
    for name, body in (('selected-skill', 'Always use selected instructions'),
                       ('other-skill', 'Do not inject these instructions')):
        with db.connect() as con:
            from local_shell_mcp.webui.storage import _now

            instant = _now()
            identity = 'chosen' if name == 'selected-skill' else 'other'
            con.execute('INSERT INTO webui_skills(id,owner,name,record,created_at,updated_at) '
                        'VALUES(?,?,?,?,?,?)',
                        (identity, 'alice', name, _json({
                            'name': name, 'description': name, 'body': body,
                            'alwaysApply': True,
                        }), instant, instant))
        if name == 'selected-skill':
            selected = identity
    store = GenerationStore(db)
    generation, _ = store.begin('alice', {'text': 'Research a topic'})
    model_messages = []

    async def model(profile, messages, **kwargs):
        model_messages.append(messages)
        yield 'Result'

    async def send(_):
        pass

    agent = {'id': 'child', 'skills_enabled': True, 'skills': [selected],
             'tools': ['skill'], 'name': 'Child'}
    runner = AgentRunner(
        'alice', generation, db, store, scopes=set(), grant_expires=None,
        stream_tools=model, stream_text=model, on_text=send,
        agent=agent, namespace='/subagent:call-1', child_configs=[],
        profile=ProviderConfig('openai', 'mock', 'http://example.test/v1', ''),
    )
    await runner.run([{'role': 'system', 'content': 'Child system message'},
                      {'role': 'user', 'content': 'Question'}])
    assert model_messages
    first = model_messages[0][0]['content']
    assert 'Child system message' in first
    assert 'Always use selected instructions' in first
    assert 'Do not inject these instructions' not in first


@pytest.mark.asyncio
async def test_windows_skill_import_author_identity_and_slash_bookmark(state):
    from local_shell_mcp.webui.auth import public_owner_id

    server, _repo = state
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                 base_url='http://example.test') as c:
        windows = b'---\r\nname: windows\r\ndescription: CRLF metadata\r\n' \
                  b'always-apply: true\r\n---\r\nWindows body'
        imported = await c.post('/api/skills/import',
                                files={'file': ('fallback.md', windows, 'text/markdown')})
        assert imported.status_code == 201, imported.text
        skill = imported.json()
        assert skill['name'] == 'windows' and skill['description'] == 'CRLF metadata'
        assert skill['alwaysApply'] is True
        assert skill['author'] == public_owner_id('alice')
        tag = await c.post('/api/tags', json={'tag': 'work/personal'})
        assert tag.status_code == 201
        renamed = await c.put('/api/tags/work%2Fpersonal', json={'tag': 'work/professional'})
        assert renamed.status_code == 200, renamed.text
        deleted = await c.delete('/api/tags/work%2Fprofessional')
        assert deleted.status_code == 200, deleted.text


@pytest.mark.asyncio
async def test_manual_skill_selection_survives_storage_and_reaches_model(state, monkeypatch):
    from local_shell_mcp.webui import lsm_tool_registry
    from local_shell_mcp.webui.agent_runner import AgentRunner
    from local_shell_mcp.webui.generations import GenerationStore
    from local_shell_mcp.webui.providers import ProviderConfig
    from local_shell_mcp.webui.storage import _now

    server, repo = state
    monkeypatch.setattr(lsm_tool_registry, 'available_tools', lambda *args, **kwargs: [])
    db = repo.database
    with db.connect() as conn:
        now = _now()
        conn.execute('INSERT INTO webui_skills(id,owner,name,record,created_at,updated_at) '
                     'VALUES(?,?,?,?,?,?)',
                     ('manual-id', 'alice', 'manual-only', _json({
                         'name': 'manual-only', 'description': 'Explicit choice',
                         'body': 'Perform the manually selected task.',
                         'frontmatter': {'disable-model-invocation': True},
                     }), now, now))
    agent = {'id': 'selected-agent', 'skills_enabled': True, 'skills_scope': 'selected',
             'skills': ['manual-id'], 'tools': ['skill']}
    store = GenerationStore(db)
    selected_payload = {'text': 'Use the manual Skill', 'manualSkills': ['manual-id']}
    for invalid in (['missing'], ['manual-id', 'manual-id'], ['manual-id'] * 17,
                    'manual-id', {'manual-id': True}, 123):
        with pytest.raises(ValueError):
            store.begin('alice', {**selected_payload, 'manualSkills': invalid}, agent)
    with pytest.raises(ValueError):
        store.begin('alice', selected_payload, {'id': 'disabled', 'skills_enabled': False})
    with pytest.raises(ValueError):
        store.begin('bob', selected_payload, None)
    generation, fresh = store.begin('alice', selected_payload, agent)
    assert fresh
    with db.connect() as conn:
        metadata = conn.execute('SELECT metadata FROM messages WHERE id=?',
                                (generation.user_message_id,)).fetchone()['metadata']
    import json

    assert json.loads(metadata)['manualSkills'] == ['manual-id']
    captured = []

    async def model(profile, messages, **kwargs):
        captured.append(messages)
        yield 'Done'

    async def send(_):
        pass

    runner = AgentRunner(
        'alice', generation, db, store, scopes=set(), grant_expires=None,
        stream_tools=model, stream_text=model, on_text=send, agent=agent,
        profile=ProviderConfig('openai', 'mock', 'http://example.test/v1', ''),
    )
    await runner.run([{'role': 'user', 'content': 'Use the manual Skill'}])
    assert captured
    assert 'Perform the manually selected task.' in captured[0][0]['content']
    assert 'Manually selected Skills' in captured[0][0]['content']
    # A non-selected turn does not inherit the previous turn's transient catalog.
    assert not any('Perform the manually selected task.' in (str(message.get('content')))
                   for message in store.history('alice', generation.conversation_id))


@pytest.mark.asyncio
async def test_manual_skill_selection_respects_user_invocable_flag(state):
    from local_shell_mcp.webui.generations import GenerationStore
    from local_shell_mcp.webui.storage import _now

    _, repo = state
    with repo.database.connect() as db:
        now = _now()
        db.execute('INSERT INTO webui_skills(id,owner,name,record,created_at,updated_at) '
                   'VALUES(?,?,?,?,?,?)',
                   ('auto-only', 'alice', 'auto-only', _json({
                       'name': 'auto-only', 'description': 'Not manually invocable',
                       'body': 'Automatic only.',
                       'frontmatter': {'user-invocable': False},
                   }), now, now))
    with pytest.raises(ValueError):
        GenerationStore(repo.database).begin('alice',
                                            {'text': 'Try it', 'manualSkills': ['auto-only']}, None)


def test_skill_runtime_manual_and_deployment_guard_branches(state, monkeypatch):
    from local_shell_mcp.webui import skill_runtime

    _, repo = state
    db = repo.database
    disabled = {'id': 'disabled', 'skills_enabled': True, 'skills_scope': 'none'}
    assert active_skills(db, 'alice', disabled) == []
    assert skill_runtime.manual_context(db, 'alice', disabled, []) == ''
    with pytest.raises(ValueError, match='Use the Skill name'):
        load(db, 'alice', None, 'unknown', path='SKILL.md')

    monkeypatch.setattr(skill_runtime, 'list_installed_skills',
                        lambda: {'skills': [{'name': 'deployed', 'description': 'test deployment'}]})
    monkeypatch.setattr(skill_runtime, 'load_installed_skill',
                        lambda name: {'content': 'Deployed documentation'})
    monkeypatch.setattr(skill_runtime, 'read_installed_skill_file',
                        lambda name, path: {'content': 'Supporting deployment text'})
    assert load(db, 'alice', None, 'deployed') == 'Deployed documentation'
    assert load(db, 'alice', None, 'deployed',
                path='references/guide.md') == 'Supporting deployment text'
    assert 'Deployed documentation' in skill_runtime.manual_context(
        db, 'alice', None, ['deployment:deployed'])

    repo.save_setting('alice', 'webui.skill.states', {'deployment:deployed': False})
    assert all(item['id'] != 'deployment:deployed' for item in active_skills(db, 'alice', None))
    repo.save_setting('alice', 'webui.skill.states', {})
    allowed = skill_runtime._policy_allows
    monkeypatch.setattr(skill_runtime, '_policy_allows',
                        lambda filters, **kwargs: False if (
                            'deployment' in kwargs.get('description', '') or
                            kwargs.get('body', '') == 'Deployed documentation'
                        ) else allowed(filters, **kwargs))
    assert all(item['id'] != 'deployment:deployed' for item in active_skills(db, 'alice', None))
    monkeypatch.setattr(skill_runtime, '_policy_allows', allowed)
    monkeypatch.setattr(skill_runtime, 'inspect_content',
                        lambda *a, **kw: (_ for _ in ()).throw(
                            skill_runtime.ContentFilterBlocked('skill', 'body')))
    assert skill_runtime._policy_allows({}) is False


@pytest.mark.asyncio
async def test_managed_supporting_file_binary_content_cannot_inject(state):
    from local_shell_mcp.webui import skill_runtime

    server, repo = state
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                 base_url='http://example.test') as c:
        sid = (await c.post('/api/skills', json={
            'name': 'binary-check', 'description': 'binary check', 'body': 'Safe',
        })).json()['_id']
        posted = await c.post(f'/api/skills/{sid}/files',
                              data={'relativePath': 'references/binary.dat'},
                              files={'file': ('binary.dat', b'\xff\xfe', 'application/octet-stream')})
        assert posted.status_code == 200
    with pytest.raises(ValueError, match='binary'):
        skill_runtime.load(repo.database, 'alice', None, 'binary-check',
                           path='references/binary.dat')


@pytest.mark.asyncio
async def test_deployment_list_scans_once_outside_request_loop(state, monkeypatch):
    server, _ = state
    scans = []

    def installed():
        scans.append(True)
        return {'skills': [{'name': f'deployed-{i}', 'description': 'Demo',
                            'related_files': []} for i in range(100)]}

    monkeypatch.setattr(skill_routes, 'list_installed_skills', installed)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                 base_url='http://example.test') as c:
        result = await c.get('/api/skills?limit=1')
    assert result.status_code == 200
    assert result.json()['has_more'] is True
    assert len(result.json()['skills']) == 1
    assert len(scans) == 1


@pytest.mark.asyncio
async def test_colliding_deployment_and_managed_skills_are_both_loadable(state, monkeypatch):
    from local_shell_mcp.webui import skill_runtime

    server, repo = state
    monkeypatch.setattr(skill_runtime, 'list_installed_skills',
                        lambda: {'skills': [{'name': 'collision', 'description': 'Deployed version'}]})
    monkeypatch.setattr(skill_runtime, 'load_installed_skill',
                        lambda name: {'content': 'Deployment-specific instructions'})
    monkeypatch.setattr(skill_runtime, 'read_installed_skill_file',
                        lambda name, path: {'content': 'Deployment reference'})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                 base_url='http://example.test') as c:
        created = await c.post('/api/skills', json={
            'name': 'collision', 'description': 'Managed version',
            'body': 'Managed-specific instructions',
        })
        assert created.status_code == 201
        managed_id = created.json()['_id']
    listing = catalog(repo.database, 'alice', None)
    assert managed_id + ': Managed version' in listing
    assert 'deployment:collision: Deployed version' in listing
    assert load(repo.database, 'alice', None, managed_id) == 'Managed-specific instructions'
    assert load(repo.database, 'alice', None, 'deployment:collision') == 'Deployment-specific instructions'
    assert load(repo.database, 'alice', None, 'deployment:collision',
                path='references/guide.md') == 'Deployment reference'
    with pytest.raises(ValueError, match='Ambiguous'):
        load(repo.database, 'alice', None, 'collision')
