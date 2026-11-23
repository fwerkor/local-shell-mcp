"""Owner-scoped bookmark and Skills API regression tests."""
from __future__ import annotations

import io
import zipfile

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.sqlite_store import SQLiteDatabase
from local_shell_mcp.webui import skill_routes, skill_tree_routes, tag_routes
from local_shell_mcp.webui.skill_runtime import catalog, load
from local_shell_mcp.webui.storage import WorkspaceRepository


@pytest.fixture
def app(tmp_path, monkeypatch):
    database = SQLiteDatabase(tmp_path)
    repo = WorkspaceRepository(database)
    for module in (skill_routes, skill_tree_routes, tag_routes):
        monkeypatch.setattr(module, '_repo', lambda: repo)
        monkeypatch.setattr(module, '_owner', lambda request: request.headers.get('x-owner', 'alice'))
    return Starlette(routes=[*tag_routes.tag_routes(), *skill_tree_routes.skill_tree_routes(),
                            *skill_routes.skill_routes()]), repo


@pytest.mark.asyncio
async def test_bookmarks_crud_metadata_references_and_owner_boundary(app):
    server, repo = app
    convo = repo.create_conversation('alice', {'title': 'A'})
    other = repo.create_conversation('bob', {'title': 'B', 'tags': ['work']})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                 base_url='http://example.test') as c:
        tag = await c.post('/api/tags', json={'tag': 'work', 'description': 'Work things'})
        assert tag.status_code == 201, tag.text
        assert tag.json()['count'] == 0
        attached = await c.put('/api/tags/convo/' + convo['conversationId'], json={'tags': ['work']})
        assert attached.status_code == 200 and attached.json() == ['work']
        assert repo.conversation('alice', convo['conversationId'])['tags'] == ['work']
        listed = await c.get('/api/tags')
        assert listed.json()[0]['count'] == 1
        renamed = await c.put('/api/tags/work', json={'tag': 'research', 'position': 2})
        assert renamed.status_code == 200 and renamed.json()['position'] == 2
        assert repo.conversation('alice', convo['conversationId'])['tags'] == ['research']
        assert repo.conversation('bob', other['conversationId'])['tags'] == ['work']
        assert (await c.post('/api/tags', json={'tag': 'research'})).status_code == 409
        assert (await c.get('/api/tags', headers={'x-owner': 'bob'})).json() == []
        assert (await c.put('/api/tags/convo/' + other['conversationId'],
                            json={'tags': ['research']})).status_code == 404
        assert (await c.delete('/api/tags/research')).status_code == 200
        assert repo.conversation('alice', convo['conversationId'])['tags'] == []


@pytest.mark.asyncio
async def test_skills_crud_conflict_runtime_and_bundle_import(app):
    server, repo = app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                 base_url='http://example.test') as c:
        created = await c.post('/api/skills', json={
            'name': 'test-skill', 'description': 'How to test a workflow.',
            'body': 'Always check the tests.', 'alwaysApply': True,
        })
        assert created.status_code == 201, created.text
        sid = created.json()['_id']
        assert created.json()['version'] == 1
        listed = (await c.get('/api/skills?search=test-skill')).json()
        assert any(s['_id'] == sid for s in listed['skills'])
        assert 'test-skill' in catalog(repo.database, 'alice', None)
        assert load(repo.database, 'alice', None, 'test-skill') == 'Always check the tests.'
        old = await c.patch('/api/skills/' + sid, json={
            'expectedVersion': 0, 'description': 'new',
        })
        assert old.status_code == 409
        changed = await c.patch('/api/skills/' + sid, json={
            'expectedVersion': 1, 'description': 'new',
        })
        assert changed.status_code == 200 and changed.json()['version'] == 2
        assert (await c.get('/api/skills/' + sid, headers={'x-owner': 'bob'})).status_code == 404
        file = await c.post('/api/skills/' + sid + '/files', data={'relativePath': 'references/help.md'},
                            files={'file': ('help.md', b'hello', 'text/markdown')})
        assert file.status_code == 200, file.text
        assert file.json()['relativePath'] == 'references/help.md'
        content = await c.get('/api/skills/' + sid + '/files/references%2Fhelp.md')
        assert content.status_code == 200 and content.json()['content'] == 'hello'
        assert len((await c.get('/api/skills/' + sid + '/files')).json()['files']) == 1
        assert (await c.delete('/api/skills/' + sid + '/files/references%2Fhelp.md')).status_code == 200
        assert (await c.post('/api/user/settings/skills/active',
                             json={'skillStates': {sid: False}})).status_code == 200
        assert 'test-skill' not in catalog(repo.database, 'alice', None)
        assert (await c.delete('/api/skills/' + sid)).json()['deleted']

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('demo/SKILL.md', '---\nname: demo\n'
                       'description: An imported demo.\n---\nFollow demo instructions.')
            z.writestr('demo/references/readme.md', 'additional context')
        imported = await c.post('/api/skills/import',
                                files={'file': ('demo.zip', archive.getvalue(), 'application/zip')})
        assert imported.status_code == 201, imported.text
        assert imported.json()['name'] == 'demo'
        assert imported.json()['fileCount'] == 1
        import_file = await c.get('/api/skills/' + imported.json()['_id'] +
                                  '/files/references%2Freadme.md')
        assert import_file.json()['content'] == 'additional context'


@pytest.mark.asyncio
async def test_skill_tree_actual_nodes_content_rename_and_restart(app):
    server, repo = app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                 base_url='http://example.test') as c:
        created = await c.post('/api/skills', json={
            'name': 'tree-skill', 'description': 'Tree persistence', 'body': '# Task',
        })
        assert created.status_code == 201
        sid = created.json()['_id']
        prefix = '/api/skills/' + sid + '/tree'
        folder = await c.post(prefix, json={'type': 'folder', 'name': 'references'})
        assert folder.status_code == 201, folder.text
        fid = folder.json()['_id']
        nested = await c.post(prefix, json={'type': 'file', 'name': 'guide.md', 'parentId': fid})
        assert nested.status_code == 201, nested.text
        nid = nested.json()['_id']
        assert nested.json()['parentId'] == fid
        saved = await c.put(prefix + '/' + nid + '/content', json={'content': 'Hello references'})
        assert saved.status_code == 200, saved.text
        content = await c.get(prefix + '/' + nid + '/content')
        assert content.json()['content'] == 'Hello references'
        assert len((await c.get(prefix)).json()['nodes']) == 2
        renamed = await c.patch(prefix + '/' + fid, json={'name': 'source'})
        assert renamed.status_code == 200, renamed.text
        with repo.database.connect() as db:
            item = db.execute('SELECT path FROM webui_skill_files WHERE id=?', (nid,)).fetchone()
            assert item['path'] == 'source/guide.md'
        assert (await c.get(prefix + '/' + nid + '/content',
                            headers={'x-owner': 'bob'})).status_code == 404
        assert (await c.post(prefix, json={'type': 'folder', 'name': '../escape'})).status_code == 400
        assert (await c.delete(prefix + '/' + fid)).status_code == 200
        assert (await c.get(prefix)).json()['nodes'] == []


@pytest.mark.asyncio
async def test_skill_file_replacement_fenced(app):
    server, _ = app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                 base_url='http://example.test') as c:
        created = (await c.post('/api/skills', json={
            'name': 'file-skill', 'description': 'File storage', 'body': '# Task',
        })).json()
        prefix = '/api/skills/' + created['_id'] + '/files'
        first = await c.post(prefix, data={'relativePath': 'references/a.md'},
                             files={'file': ('a.md', b'A', 'text/markdown')})
        assert first.status_code == 200
        identifier = first.json()['file_id']
        conflict = await c.post(prefix + '/references%2Fa.md',
                                data={'relativePath': 'references/a.md',
                                      'expectedFileId': 'stale'},
                                files={'file': ('a.md', b'B', 'text/markdown')})
        assert conflict.status_code == 409
        good = await c.post(prefix + '/references%2Fa.md',
                            data={'relativePath': 'references/a.md',
                                  'expectedFileId': identifier},
                            files={'file': ('a.md', b'B', 'text/markdown')})
        assert good.status_code == 200
        assert (await c.get(prefix + '/references%2Fa.md')).json()['content'] == 'B'


def test_skill_activation_scope_and_deployment_source(app, monkeypatch):
    from local_shell_mcp.webui import skill_runtime

    _, repo = app
    from local_shell_mcp.webui.storage import _json, _now

    with repo.database.connect() as db:
        db.execute('INSERT INTO webui_skills(id,owner,name,record,created_at,updated_at) '
                   'VALUES(?,?,?,?,?,?)',
                   ('owner-skill', 'alice', 'owner-skill', _json({
                       'name': 'owner-skill', 'description': 'User skill', 'body': 'Use tests',
                   }), _now(), _now()))
    monkeypatch.setattr(skill_runtime, 'list_installed_skills',
                        lambda: {'skills': [{'name': 'server-skill', 'description': 'Installed skill'}]})
    monkeypatch.setattr(skill_runtime, 'load_installed_skill',
                        lambda name: {'content': 'Server instructions'})
    catalog = skill_runtime.catalog(repo.database, 'alice', None)
    assert 'server-skill' in catalog and 'owner-skill' in catalog
    assert skill_runtime.load(repo.database, 'alice', None, 'server-skill') == 'Server instructions'
    assert skill_runtime.active_skills(repo.database, 'alice', {'skills_scope': 'none'}) == []
    selected = skill_runtime.active_skills(repo.database, 'alice', {
        'skills_enabled': True, 'skills_scope': 'selected', 'skills': ['owner-skill'],
    })
    assert len(selected) == 1 and selected[0]['name'] == 'owner-skill'
    assert skill_runtime.active_skills(repo.database, 'alice', {'skills_enabled': False}) == []
    repo.save_setting('alice', 'webui.skill.states', {'owner-skill': False})
    assert 'owner-skill' not in skill_runtime.catalog(repo.database, 'alice', None)
    with pytest.raises(ValueError, match='Invalid Skill'):
        skill_runtime.load(repo.database, 'alice', None, '')
    with pytest.raises(ValueError, match='not enabled'):
        skill_runtime.load(repo.database, 'alice', None, 'owner-skill')
    repo.save_setting('alice', 'webui.skill.states', 'bad')
    assert 'owner-skill' in skill_runtime.catalog(repo.database, 'alice', None)
    with repo.database.connect() as db:
        db.execute('UPDATE webui_skills SET record=? WHERE id=?',
                   (_json({'name': 'owner-skill', 'description': 'User skill',
                            'body': 'Hidden', 'frontmatter': {
                                'disable-model-invocation': True,
                            }}), 'owner-skill'))
    assert 'owner-skill' not in skill_runtime.catalog(repo.database, 'alice', None)


@pytest.mark.asyncio
async def test_bookmark_validation_atomic_attach_and_conflicting_rename(app):
    from local_shell_mcp.webui.tag_routes import _tags

    server, repo = app
    assert _tags('not-json') == []
    assert _tags('[]') == []
    assert _tags('{"tags":"bad"}') == []
    assert _tags('{"tags":["valid"]}') == ['valid']
    conversation = repo.create_conversation('alice', {'title': 'Tag target'})
    cid = conversation['conversationId']
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                 base_url='http://example.test') as client:
        for payload in (
            {}, {'tag': ''}, {'tag': 'a' * 129}, {'tag': 1},
            {'tag': 'good', 'description': 1}, {'tag': 'good', 'description': 'x' * 1049},
            {'tag': 'good', 'position': -1}, {'tag': 'good', 'position': 1.5},
        ):
            response = await client.post('/api/tags', json=payload)
            assert response.status_code == 400, (payload, response.text)
        bad_origin = await client.post('/api/tags', json={'tag': 'bad'},
                                       headers={'origin': 'https://different-site.example'})
        assert bad_origin.status_code == 403
        missing = await client.post('/api/tags', json={
            'tag': 'no-conversation', 'addToConversation': True,
            'conversationId': 'missing',
        })
        assert missing.status_code == 404
        assert (await client.get('/api/tags')).json() == []
        created = await client.post('/api/tags', json={
            'tag': 'one', 'addToConversation': True,
            'conversationId': cid,
        })
        assert created.status_code == 201
        assert repo.conversation('alice', cid)['tags'] == ['one']
        assert (await client.post('/api/tags', json={'tag': 'two'})).status_code == 201
        assert (await client.put('/api/tags/one', json={'tag': 'two'})).status_code == 409
        assert (await client.put('/api/tags/missing', json={'tag': 'two'})).status_code == 404
        assert (await client.delete('/api/tags/missing')).status_code == 404
        for requested in ({}, {'tags': 'one'}, {'tags': ['x' * 129]}, {'tags': [None]},
                          {'tags': ['one'] * 101}):
            assert (await client.put('/api/tags/convo/' + cid,
                                     json=requested)).status_code == 400
        assert (await client.put('/api/tags/convo/' + cid,
                                 json={'tags': ['unknown']})).status_code == 400
        assert len((await client.get('/api/tags/list')).json()) == 2
        assert (await client.put('/api/tags/convo/' + cid,
                                 json={'tags': ['one', 'one', 'two']})).json() == ['one', 'two']


@pytest.mark.asyncio
async def test_skill_tree_invalid_moves_and_binary_guard(app):
    server, _ = app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                 base_url='http://example.test') as c:
        sid = (await c.post('/api/skills', json={
            'name': 'tree-edges', 'description': 'File validation', 'body': 'Keep safe',
        })).json()['_id']
        base = '/api/skills/' + sid + '/tree'
        assert (await c.post(base, json={'type': 'not-a-node', 'name': 'a'})).status_code == 400
        assert (await c.post(base, json={'type': 'file', 'name': ''})).status_code == 400
        assert (await c.post(base, json={'type': 'folder', 'name': 'a',
                                         'order': -5})).status_code == 400
        assert (await c.post(base, json={'type': 'file', 'name': '../escape'})).status_code == 400
        assert (await c.post(base, json={'type': 'file', 'name': 'a',
                                         'parentId': []})).status_code == 400
        first = await c.post(base, json={'type': 'file', 'name': 'readme.md'})
        assert first.status_code == 201, first.text
        file_id = first.json()['_id']
        assert (await c.post(base, json={'type': 'file', 'name': 'readme.md'})).status_code == 409
        assert (await c.post(base, json={'type': 'folder', 'name': 'folder',
                                         'parentId': file_id})).status_code == 400
        directory = await c.post(base, json={'type': 'folder', 'name': 'docs'})
        assert directory.status_code == 201
        folder_id = directory.json()['_id']
        assert (await c.patch(base + '/' + folder_id, json={'parentId': folder_id})).status_code == 400
        assert (await c.patch(base + '/' + file_id,
                              json={'name': 'README.md', 'parentId': folder_id,
                                    'order': 7})).status_code == 200
        assert (await c.put(base + '/' + file_id + '/content',
                            json={'content': 42})).status_code == 400
        assert (await c.get(base + '/' + folder_id + '/content')).status_code == 400
        assert (await c.get(base + '/does-not-exist/content')).status_code == 404
        assert (await c.patch(base + '/' + file_id,
                              json={'order': -1})).status_code == 400
        assert (await c.patch(base + '/' + file_id,
                              json={'name': 42})).status_code == 400
        assert (await c.patch(base + '/' + file_id,
                              json={'parentId': []})).status_code == 400
        assert (await c.patch(base + '/does-not-exist',
                              json={'name': 'x'})).status_code == 404
        assert (await c.patch(base + '/' + file_id,
                              json={'name': 'test'},
                              headers={'origin': 'https://malicious.example'})).status_code == 403
        blob = await c.post('/api/skills/' + sid + '/files',
                            data={'relativePath': 'assets/image.bin'},
                            files={'file': ('image.bin', b'\xff\xfe', 'application/octet-stream')})
        assert blob.status_code == 200
        blob_id = blob.json()['_id']
        assert (await c.get(base + '/' + blob_id + '/content')).status_code == 415
        assert (await c.delete(base + '/' + blob_id)).status_code == 200
        assert (await c.delete(base + '/' + file_id)).status_code == 200
        assert (await c.delete(base + '/' + folder_id)).status_code == 200
        remaining = (await c.get(base)).json()['nodes']
        assert len(remaining) == 1 and remaining[0]['name'] == 'assets'
        assert (await c.delete(base + '/' + remaining[0]['_id'])).status_code == 200
        assert (await c.get(base)).json()['nodes'] == []
        assert (await c.get('/api/skills/deployment:system-skill/tree')).json()['nodes'] == []
        assert (await c.post('/api/skills/deployment:system-skill/tree',
                             json={'type': 'file', 'name': 'x'})).status_code == 403


@pytest.mark.asyncio
async def test_skills_validation_versions_and_pagination(app):
    server, _ = app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                 base_url='http://example.test') as c:
        valid = {'name': 'valid-skill', 'description': 'Skill description.', 'body': 'Body'}
        cases = [
            {'name': 'Invalid Case'}, {'name': 'x' * 129}, {'name': ''},
            {'description': ''}, {'description': 1},
            {'description': 'a' * 501},
            {'body': None}, {'body': 'x' * 524289},
            {'displayTitle': 3}, {'displayTitle': 'y' * 257},
            {'category': 1}, {'category': 'z' * 129},
            {'frontmatter': 'bad'}, {'alwaysApply': 'true'},
        ]
        for patch in cases:
            response = await c.post('/api/skills', json={**valid, **patch})
            assert response.status_code == 400, (patch, response.text)
        blocked = await c.post('/api/skills', json=valid,
                               headers={'origin': 'https://evil.example'})
        assert blocked.status_code == 403
        first = await c.post('/api/skills', json=valid)
        assert first.status_code == 201
        sid = first.json()['_id']
        assert (await c.post('/api/skills', json=valid)).status_code == 409
        other = await c.post('/api/skills', json={
            'name': 'other-skill', 'description': 'Something', 'body': 'Hello',
        })
        assert other.status_code == 201
        assert (await c.get('/api/skills?cursor=NaN')).status_code == 400
        assert (await c.get('/api/skills?limit=bad')).status_code == 400
        pages = (await c.get('/api/skills?limit=1')).json()
        assert len(pages['skills']) == 1 and pages['has_more'] and pages['after'] == '1'
        second_page = (await c.get('/api/skills?limit=1&cursor=1')).json()
        assert second_page['skills'][0]['_id'] != pages['skills'][0]['_id']
        filtered = (await c.get('/api/skills?category=missing')).json()
        assert filtered['skills'] == []
        assert (await c.patch('/api/skills/' + sid,
                              json={'name': 'invalid', 'expectedVersion': '1'})).status_code == 400
        assert (await c.patch('/api/skills/' + sid,
                              json={'name': 'other-skill', 'expectedVersion': 1})).status_code == 409
        assert (await c.get('/api/skills/' + sid)).status_code == 200
        assert (await c.get('/api/skills/no-id')).status_code == 404
        assert (await c.delete('/api/skills/no-id')).status_code == 404
        assert (await c.post('/api/user/settings/skills/active',
                             json={'skillStates': 'invalid'})).status_code == 400
        assert (await c.post('/api/user/settings/skills/active',
                             json={'skillStates': {'x': 1}})).status_code == 400
        assert (await c.get('/api/user/settings/skills/active')).json() == {}
        assert (await c.delete('/api/skills/' + sid)).status_code == 200


@pytest.mark.asyncio
async def test_skills_deployment_readonly_and_file_failures(app, monkeypatch):
    server, _ = app
    monkeypatch.setattr(skill_routes, 'list_installed_skills',
                        lambda: {'skills': [{'name': 'system', 'description': 'Deployed Skill',
                                             'related_files': ['references/note.md']}]})
    monkeypatch.setattr(skill_routes, 'load_installed_skill',
                        lambda name: {'content': '# System Skill'})
    monkeypatch.setattr(skill_routes, 'read_installed_skill_file',
                        lambda name, path: {'content': 'Reference'})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                 base_url='http://example.test') as c:
        imported = await c.get('/api/skills/deployment:system')
        assert imported.status_code == 200 and imported.json()['body'] == '# System Skill'
        assert (await c.patch('/api/skills/deployment:system',
                              json={'expectedVersion': 1, 'body': 'New'})).status_code == 403
        assert (await c.get('/api/skills/deployment:nonexistent')).status_code == 404
        assert (await c.get('/api/skills/deployment:system/files')).json() == {'files': []}
        assert (await c.get('/api/skills/deployment:system/files/references%2Fnote.md')).json()[
            'content'] == 'Reference'
        assert (await c.delete('/api/skills/deployment:system/files/references%2Fnote.md')).status_code == 403
        assert (await c.post('/api/skills/deployment:system/files',
                             data={'relativePath': 'x'},
                             files={'file': ('x', b'data')})).status_code == 403
        assert (await c.get('/api/skills/deployment:nonexistent/files')).status_code == 404
        monkeypatch.setattr(skill_routes, 'load_installed_skill',
                            lambda name: (_ for _ in ()).throw(ValueError('gone')))
        assert (await c.get('/api/skills/deployment:system')).status_code == 404
        monkeypatch.setattr(skill_routes, 'read_installed_skill_file',
                            lambda name, path: (_ for _ in ()).throw(ValueError('gone')))
        assert (await c.get('/api/skills/deployment:system/files/references%2Fnote.md')).status_code == 404


@pytest.mark.asyncio
async def test_skills_upload_validation_binary_and_limit(app, monkeypatch):
    server, _ = app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                 base_url='http://example.test') as c:
        sid = (await c.post('/api/skills', json={
            'name': 'upload-guard', 'description': 'Files', 'body': 'Test',
        })).json()['_id']
        root = '/api/skills/' + sid + '/files'
        assert (await c.post(root, data={'relativePath': 'scripts/a.py'})).status_code == 400
        assert (await c.post(root, data={'relativePath': 'SKILL.md'},
                             files={'file': ('SKILL.md', b'x')})).status_code == 400
        assert (await c.post(root, data={'relativePath': '../secret'},
                             files={'file': ('x', b'x')})).status_code == 400
        assert (await c.post(root + '/references%2Fa.md',
                             data={'relativePath': 'assets/a.md'},
                             files={'file': ('a.md', b'x')})).status_code == 400
        assert (await c.get(root + '/not-found')).status_code == 404
        monkeypatch.setattr(skill_routes, '_MAX_FILES', 1)
        first = await c.post(root, data={'relativePath': 'scripts/hello.py'},
                             files={'file': ('hello.py', b'print("Hello")', 'text/plain')})
        assert first.status_code == 200
        assert first.json()['category'] == 'script'
        assert (await c.post(root, data={'relativePath': 'other.txt'},
                             files={'file': ('other.txt', b'x')})).status_code == 400
        assert (await c.get(root + '/scripts%2Fhello.py')).status_code == 200
        listing = (await c.get(root)).json()['files']
        assert len(listing) == 1 and listing[0]['category'] == 'script'
        monkeypatch.setattr(skill_routes, '_MAX_UPLOAD', 1024)
        oversized = await c.post(root, data={'relativePath': 'scripts/hello.py'},
                                 files={'file': ('hello.py', b'x' * 1300)})
        assert oversized.status_code == 413
        binary = await c.post(root, data={'relativePath': 'scripts/hello.py'},
                              files={'file': ('hello.py', b'\xff\xfe')})
        assert binary.status_code == 200
        assert (await c.get(root + '/scripts%2Fhello.py')).json()['isBinary']
        assert (await c.delete(root + '/scripts%2Fhello.py')).status_code == 200
        assert (await c.delete(root + '/scripts%2Fhello.py')).status_code == 404
        assert (await c.get(root, headers={'x-owner': 'bob'})).status_code == 404


@pytest.mark.asyncio
async def test_skill_import_error_paths_and_plain_markdown(app, monkeypatch):
    server, _ = app

    def compressed(items):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            for path, body in items.items():
                archive.writestr(path, body)
        return output.getvalue()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server),
                                 base_url='http://example.test') as c:
        assert (await c.post('/api/skills/import', data={'name': 'bad'})).status_code == 400
        for content in (
            b'\xff\xfe', b'---\nname: BAD_NAME\ndescription: test\n---\nBody',
            b'---\nname: invalid\n: bad yaml\n---\nBody',
        ):
            result = await c.post('/api/skills/import',
                                  files={'file': ('bad.md', content, 'text/markdown')})
            assert result.status_code in (400, 422), result.text
        imported = await c.post('/api/skills/import',
                                files={'file': ('simple.md', b'Just instructions', 'text/markdown')})
        assert imported.status_code == 201
        assert imported.json()['name'] == 'simple'
        assert (await c.post('/api/skills/import',
                             files={'file': ('simple.md', b'Again', 'text/markdown')})).status_code == 409
        no_skill = compressed({'root/readme.txt': 'not a skill'})
        assert (await c.post('/api/skills/import',
                             files={'file': ('archive.zip', no_skill)})).status_code == 422
        wrong_root = compressed({'root/SKILL.md': 'Hello', 'other/file.md': 'Bad root'})
        assert (await c.post('/api/skills/import',
                             files={'file': ('wrong.zip', wrong_root)})).status_code == 422
        traversal = compressed({'root/SKILL.md': 'Hello', 'root/../secret': 'escape'})
        assert (await c.post('/api/skills/import',
                             files={'file': ('unsafe.zip', traversal)})).status_code == 400
        monkeypatch.setattr(skill_routes, '_MAX_FILES', 1)
        too_many = compressed({'root/SKILL.md': 'Hello',
                               'root/docs/a.md': 'a', 'root/docs/b.md': 'b'})
        assert (await c.post('/api/skills/import',
                             files={'file': ('overflow.zip', too_many)})).status_code == 413
        monkeypatch.setattr(skill_routes, '_MAX_BODY', 12)
        large_entry = compressed({'root/SKILL.md': 'Hello', 'root/docs/large.md': 'x' * 100})
        assert (await c.post('/api/skills/import',
                             files={'file': ('large.zip', large_entry)})).status_code == 413
