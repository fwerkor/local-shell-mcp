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
    repo = WorkspaceRepository(SQLiteDatabase(tmp_path))
    for module in (routes, skill_routes, skill_tree_routes, tag_routes):
        monkeypatch.setattr(module, '_repo', lambda: repo)
        monkeypatch.setattr(module, '_owner', lambda request: request.headers.get('x-owner', 'alice'))
    server = Starlette(routes=[*tag_routes.tag_routes(), *skill_tree_routes.skill_tree_routes(),
                               *skill_routes.skill_routes(), Route('/api/convos', routes.conversations, methods=['GET'])])
    return server, repo


@pytest.mark.asyncio
async def test_folder_delete_matches_literal_underscore_and_percent(state):
    server, repo = state
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
    repo.create_conversation('alice', {'title': 'Other', 'tags': ['axb']})
    repo.create_conversation('bob', {'title': 'Foreign', 'tags': ['a_b']})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                 base_url='http://example.test') as c:
        response = await c.get('/api/convos?tags=a_b&limit=1')
        assert response.status_code == 200, response.text
        assert [r['conversationId'] for r in response.json()['conversations']] == [first['conversationId']]
        assert response.json()['nextCursor'] is None
        assert (await c.get('/api/convos?tags=axb')).json()['conversations'][0]['title'] == 'Other'


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
