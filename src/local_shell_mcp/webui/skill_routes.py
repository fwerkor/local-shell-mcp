"""Owner-scoped LibreChat Skills API using the shared Controller SQLite store.

Inline skills and bundled files are transactional; deployment Skills keep their
original read-only filesystem ownership and are loaded via LSM's secure scanner.
"""
from __future__ import annotations

import asyncio
import io
import json
import mimetypes
import re
import sqlite3
import uuid
import zipfile
from pathlib import PurePosixPath

import yaml
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..agent_bridge.skills import validate_skill_file_path
from ..skill_ops import list_installed_skills, load_installed_skill, read_installed_skill_file
from .auth import _same_origin, public_owner_id
from .content_filters import ContentFilterBlocked, ContentFragment, inspect_content
from .memory_protection import configured_filters
from .routes import _body, _owner, _repo
from .storage import _json, _now, _stamp

_NAME = re.compile(r'^[a-z0-9][a-z0-9-]*$')
_MAX_BODY = 512 * 1024
_MAX_FILES = 100
_MAX_UPLOAD = 10 * 1024 * 1024


def _validate(payload):
    name = payload.get('name')
    description = payload.get('description')
    body = payload.get('body')
    if not isinstance(name, str) or len(name) > 128 or not _NAME.fullmatch(name):
        raise HTTPException(400, detail='Skill name must be lowercase kebab-case')
    if not isinstance(description, str) or not 1 <= len(description) <= 500:
        raise HTTPException(400, detail='Skill description must contain 1–500 characters')
    if not isinstance(body, str) or len(body.encode('utf-8')) > _MAX_BODY:
        raise HTTPException(400, detail='Skill body is too large')
    title = payload.get('displayTitle')
    if title is not None and (not isinstance(title, str) or len(title) > 256):
        raise HTTPException(400, detail='Invalid display title')
    category = payload.get('category')
    if category is not None and (not isinstance(category, str) or len(category) > 128):
        raise HTTPException(400, detail='Invalid category')
    front = payload.get('frontmatter') or {}
    if not isinstance(front, dict) or len(_json(front).encode('utf-8')) > 32_768:
        raise HTTPException(400, detail='Invalid frontmatter')
    if type(payload.get('alwaysApply', False)) is not bool:
        raise HTTPException(400, detail='Invalid alwaysApply')
    return payload


def _enforce_skill_policy(repo, owner, *, description='', body='', references=()):
    filters = configured_filters(repo, owner)
    parts = [ContentFragment('skill', 'description', description),
             ContentFragment('skill', 'body', body)]
    parts += [ContentFragment('skill', 'body', content) for content in references]
    try:
        blocked = inspect_content(parts, filters)
    except ContentFilterBlocked:
        blocked = True
    if blocked:
        raise HTTPException(422, detail='Skill content blocked by configured content policy')


def _row(row, *, detail=False, file_count=0):
    rec = json.loads(row['record'])
    data = {key: value for key, value in rec.items() if key not in ('_id', 'author', 'version')}
    data.update(
        _id=row['id'], author=public_owner_id(row['owner']), authorName='local-shell-mcp',
        version=row['version'], source='inline', fileCount=file_count,
        userInvocable=rec.get('frontmatter', {}).get('user-invocable', True),
        disableModelInvocation=rec.get('frontmatter', {}).get('disable-model-invocation', False),
        allowedTools=rec.get('frontmatter', {}).get('allowed-tools', []),
        createdAt=_stamp(row['created_at'] / 1_000_000),
        updatedAt=_stamp(row['updated_at'] / 1_000_000),
    )
    if not detail:
        data.pop('body', None)
        data.pop('frontmatter', None)
    return data


def _deployment(name, *, detail=False, entry=None):
    try:
        loaded = load_installed_skill(name) if detail else None
    except (ValueError, OSError):
        return None
    if entry is None:
        entry = next((item for item in list_installed_skills()['skills']
                      if item['name'] == name), None)
    if entry is None:
        return None
    timestamp = '1970-01-01T00:00:00.000Z'
    result = dict(_id='deployment:' + name, name=name, displayTitle=name,
                  description=entry.get('description') or name, category='',
                  author='deployment', authorName='local-shell-mcp',
                  version=1, source='deployment', fileCount=len(entry.get('related_files') or []),
                  alwaysApply=False, userInvocable=True, disableModelInvocation=False,
                  allowedTools=[], createdAt=timestamp, updatedAt=timestamp)
    if detail:
        content = loaded.get('content', '')
        result.update(body=content, frontmatter={})
    return result


def _file_meta(row):
    path = row['path']
    if path.startswith('scripts/'):
        category = 'script'
    elif path.startswith('references/'):
        category = 'reference'
    elif path.startswith('assets/'):
        category = 'asset'
    else:
        category = 'other'
    return dict(_id=row['id'], skillId=row['skill_id'], relativePath=path,
                file_id=row['id'], filename=PurePosixPath(path).name, filepath=path,
                source='local', mimeType=row['mime'], bytes=len(row['data']),
                category=category, isExecutable=False, author=public_owner_id(row['owner']),
                createdAt=_stamp(row['created_at'] / 1_000_000),
                updatedAt=_stamp(row['updated_at'] / 1_000_000))


def _owned(db, owner, sid):
    row = db.execute('SELECT * FROM webui_skills WHERE id=? AND owner=?', (sid, owner)).fetchone()
    if row is None:
        raise HTTPException(404, detail='Skill not found')
    return row


async def skills(request: Request):
    if request.method != 'GET':
        _same_origin(request)
    owner = _owner(request)
    repo = _repo()
    if request.method == 'GET':
        qs = request.query_params
        query = (qs.get('search') or '').lower().strip()
        category = qs.get('category') or ''
        try:
            limit = max(1, min(100, int(qs.get('limit', '20'))))
            offset = max(0, int(qs.get('cursor', '0')))
        except ValueError as exc:
            raise HTTPException(400, detail='Invalid pagination arguments') from exc
        with repo.database.connect() as db:
            rows = db.execute('SELECT * FROM webui_skills WHERE owner=? ORDER BY updated_at DESC,id DESC',
                              (owner,)).fetchall()
            counts = {row['skill_id']: row['total'] for row in db.execute(
                'SELECT skill_id,COUNT(*) total FROM webui_skill_files WHERE owner=? GROUP BY skill_id',
                (owner,)).fetchall()}
        entries = [_row(r, file_count=counts.get(r['id'], 0)) for r in rows]
        # Do not rescan the filesystem for every item. The registry scan is
        # blocking IO, so keep it off the async request loop as well.
        deployed = await asyncio.to_thread(list_installed_skills)
        entries += [_deployment(item['name'], entry=item) for item in deployed['skills']]
        entries = [e for e in entries if e is not None and
                   (not category or e.get('category') == category) and
                   (not query or query in (e['name'] + ' ' + e['description'] + ' ' + e.get('displayTitle', '')).lower())]
        page = entries[offset:offset + limit]
        after = str(offset + limit) if offset + limit < len(entries) else None
        return JSONResponse({'skills': page, 'has_more': after is not None, 'after': after})
    data = _validate(await _body(request))
    _enforce_skill_policy(repo, owner, description=data['description'], body=data['body'])
    now = _now()
    identity = str(uuid.uuid4())
    try:
        with repo.database.connect() as db:
            db.execute('INSERT INTO webui_skills(id,owner,name,record,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                       (identity, owner, data['name'], _json(data), now, now))
            row = _owned(db, owner, identity)
            result = _row(row, detail=True)
        return JSONResponse(result, status_code=201)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, detail='Skill name already exists') from exc


async def skill(request: Request):
    if request.method != 'GET':
        _same_origin(request)
    owner = _owner(request)
    sid = request.path_params['id']
    repo = _repo()
    if sid.startswith('deployment:'):
        if request.method != 'GET':
            raise HTTPException(403, detail='Deployment Skills are read-only')
        result = _deployment(sid[len('deployment:'):], detail=True)
        if result is None:
            raise HTTPException(404, detail='Skill not found')
        return JSONResponse(result)
    with repo.database.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = _owned(db, owner, sid)
        if request.method == 'GET':
            count = db.execute('SELECT COUNT(*) FROM webui_skill_files WHERE skill_id=?', (sid,)).fetchone()[0]
            return JSONResponse(_row(row, detail=True, file_count=count))
        if request.method == 'DELETE':
            db.execute('DELETE FROM webui_skills WHERE id=? AND owner=?', (sid, owner))
            return JSONResponse({'id': sid, 'deleted': True, 'cleanupComplete': True})
        patch = await _body(request)
        if type(patch.get('expectedVersion')) is not int:
            raise HTTPException(400, detail='expectedVersion required')
        if patch['expectedVersion'] != row['version']:
            return JSONResponse({'error': 'skill_version_conflict', 'current': _row(row, detail=True)},
                                status_code=409)
        record = json.loads(row['record'])
        for field in ('name', 'displayTitle', 'description', 'body', 'frontmatter', 'category', 'alwaysApply'):
            if field in patch:
                record[field] = patch[field]
        _validate(record)
        _enforce_skill_policy(repo, owner, description=record['description'], body=record['body'])
        try:
            db.execute('UPDATE webui_skills SET name=?,record=?,version=version+1,updated_at=? '
                       'WHERE id=? AND owner=?', (record['name'], _json(record), _now(), sid, owner))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, detail='Skill name already exists') from exc
        row = _owned(db, owner, sid)
        return JSONResponse(_row(row, detail=True))


async def states(request: Request):
    if request.method != 'GET':
        _same_origin(request)
    owner = _owner(request)
    repo = _repo()
    if request.method == 'GET':
        return JSONResponse(repo.setting(owner, 'webui.skill.states', {}))
    body = await _body(request)
    values = body.get('skillStates')
    if (not isinstance(values, dict) or len(values) > 500
            or any(not isinstance(k, str) or type(v) is not bool for k, v in values.items())):
        raise HTTPException(400, detail='Invalid skill states')
    repo.save_setting(owner, 'webui.skill.states', values)
    return JSONResponse(values)


def _path(raw, *, allow_main=False):
    try:
        result = validate_skill_file_path(raw).as_posix()
    except ValueError as exc:
        raise HTTPException(400, detail='Invalid file path') from exc
    if result == 'SKILL.md' and not allow_main:
        raise HTTPException(400, detail='Edit the main skill body instead')
    return result


async def files(request: Request):
    if request.method != 'GET':
        _same_origin(request)
    owner = _owner(request)
    sid = request.path_params['id']
    repo = _repo()
    if sid.startswith('deployment:'):
        if request.method != 'GET':
            raise HTTPException(403, detail='Deployment Skills are read-only')
        name = sid[len('deployment:'):]
        source = _deployment(name)
        if source is None:
            raise HTTPException(404, detail='Skill not found')
        return JSONResponse({'files': []})
    if request.method == 'GET':
        with repo.database.connect() as db:
            _owned(db, owner, sid)
            rows = db.execute('SELECT * FROM webui_skill_files WHERE owner=? AND skill_id=? ORDER BY path',
                              (owner, sid)).fetchall()
        return JSONResponse({'files': [_file_meta(row) for row in rows]})
    if int(request.headers.get('content-length') or 0) > _MAX_UPLOAD * 2:
        raise HTTPException(413, detail='Skill upload too large')
    form = await request.form()
    blob = form.get('file')
    if blob is None or not hasattr(blob, 'read'):
        raise HTTPException(400, detail='file required')
    supplied = form.get('relativePath') or blob.filename or ''
    endpoint_path = request.path_params.get('path')
    if endpoint_path is not None and _path(endpoint_path) != _path(supplied):
        raise HTTPException(400, detail='Skill file path mismatch')
    path = _path(endpoint_path or supplied)
    raw = await blob.read(_MAX_UPLOAD + 1)
    if len(raw) > _MAX_UPLOAD:
        raise HTTPException(413, detail='Skill file too large')
    try:
        reference_text = raw.decode('utf-8')
    except UnicodeError:
        reference_text = None
    if reference_text is not None:
        _enforce_skill_policy(repo, owner, references=[reference_text])
    expected = form.get('expectedFileId')
    with repo.database.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        _owned(db, owner, sid)
        prior = db.execute('SELECT id FROM webui_skill_files WHERE skill_id=? AND path=?', (sid, path)).fetchone()
        if expected is not None and (prior['id'] if prior else None) != expected:
            raise HTTPException(409, detail='Skill file was modified concurrently')
        if prior is None and db.execute('SELECT COUNT(*) FROM webui_skill_files WHERE skill_id=?',
                                        (sid,)).fetchone()[0] >= _MAX_FILES:
            raise HTTPException(400, detail='Skill file count limit reached')
        fid = str(uuid.uuid4())
        now = _now()
        from .skill_tree_routes import _ensure_folders

        _ensure_folders(db, owner, sid, path)
        db.execute('INSERT INTO webui_skill_files(id,owner,skill_id,path,data,mime,created_at,updated_at) '
                   'VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(skill_id,path) DO UPDATE SET '
                   'id=excluded.id,data=excluded.data,mime=excluded.mime,updated_at=excluded.updated_at',
                   (fid, owner, sid, path, raw, blob.content_type or 'application/octet-stream', now, now))
        row = db.execute('SELECT * FROM webui_skill_files WHERE skill_id=? AND path=?', (sid, path)).fetchone()
        return JSONResponse(_file_meta(row))


def _main_document(record):
    # The main file is stored as structured metadata plus body; reconstruct
    # a normal SKILL.md for the read-only file viewer.
    front = {'name': record['name'], 'description': record['description']}
    front.update(record.get('frontmatter') or {})
    if 'always-apply' in front:
        front['always-apply'] = bool(record.get('alwaysApply', False))
    elif 'alwaysApply' in front:
        front['alwaysApply'] = bool(record.get('alwaysApply', False))
    elif record.get('alwaysApply'):
        front['always-apply'] = True
    return '---\n' + yaml.safe_dump(front, allow_unicode=True, sort_keys=False) + '---\n' + record['body']


async def file_by_path(request: Request):
    if request.method != 'GET':
        _same_origin(request)
    if request.method == 'POST':
        return await files(request)
    owner = _owner(request)
    sid = request.path_params['id']
    path = _path(request.path_params['path'], allow_main=request.method == 'GET')
    if sid.startswith('deployment:'):
        if request.method != 'GET':
            raise HTTPException(403, detail='Deployment Skills are read-only')
        try:
            loaded = (load_installed_skill(sid[len('deployment:'):]) if path == 'SKILL.md'
                      else read_installed_skill_file(sid[len('deployment:'):], path))
        except (ValueError, OSError) as exc:
            raise HTTPException(404, detail='File not found') from exc
        if request.query_params.get('raw') in {'true', '1'}:
            return Response(loaded['content'].encode('utf-8'), media_type='text/plain',
                            headers={'X-Content-Type-Options': 'nosniff'})
        return JSONResponse({'content': loaded['content'], 'mimeType': 'text/plain'})
    repo = _repo()
    with repo.database.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        skill = _owned(db, owner, sid)
        if path == 'SKILL.md':
            document = _main_document(json.loads(skill['record']))
            if request.query_params.get('raw') in {'true', '1'}:
                return Response(document.encode('utf-8'), media_type='text/markdown',
                                headers={'X-Content-Type-Options': 'nosniff'})
            return JSONResponse({'content': document, 'mimeType': 'text/markdown'})
        row = db.execute('SELECT * FROM webui_skill_files WHERE owner=? AND skill_id=? AND path=?',
                         (owner, sid, path)).fetchone()
        if row is None:
            raise HTTPException(404, detail='Skill file not found')
        if request.method == 'DELETE':
            db.execute('DELETE FROM webui_skill_files WHERE id=?', (row['id'],))
            return JSONResponse({'skillId': sid, 'relativePath': path, 'deleted': True})
        if request.query_params.get('raw') in {'true', '1'}:
            # Avoid scriptable assets executing in the application origin.
            mime = row['mime'] if row['mime'] in {'image/png', 'image/jpeg', 'image/gif',
                      'image/webp', 'image/avif'} else 'application/octet-stream'
            disposition = 'inline' if mime.startswith('image/') else 'attachment'
            return Response(row['data'], media_type=mime,
                            headers={'X-Content-Type-Options': 'nosniff',
                                     'Content-Disposition': disposition})
        try:
            content = row['data'].decode('utf-8')
        except UnicodeError:
            return JSONResponse({'fileId': row['id'], 'mimeType': row['mime'], 'isBinary': True})
        return JSONResponse({'fileId': row['id'], 'content': content, 'mimeType': row['mime']})


def _parse_skill_text(text, fallback):
    # Normalize Windows line endings before locating YAML frontmatter fences.
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    fm = {}
    body = text
    if text.startswith('---\n'):
        _, sep, remaining = text.partition('\n---\n')
        if sep:
            front = yaml.safe_load(text[4:text.index('\n---\n')]) or {}
            fm = front if isinstance(front, dict) else {}
            body = remaining
    name = fm.pop('name', fallback)
    description = fm.pop('description', 'Imported Skill')
    data = dict(name=name, description=description, body=body, frontmatter=fm)
    always_apply = fm.get('always-apply')
    if type(always_apply) is not bool:
        always_apply = fm.get('alwaysApply')
    if type(always_apply) is bool:
        data['alwaysApply'] = always_apply
    return _validate(data)


async def import_skill(request: Request):
    if request.method != 'GET':
        _same_origin(request)
    owner = _owner(request)
    if int(request.headers.get('content-length') or 0) > _MAX_UPLOAD * 2:
        raise HTTPException(413, detail='Skill import too large')
    form = await request.form()
    upload = form.get('file')
    if upload is None or not hasattr(upload, 'read'):
        raise HTTPException(400, detail='Skill file required')
    contents = await upload.read(_MAX_UPLOAD + 1)
    if len(contents) > _MAX_UPLOAD:
        raise HTTPException(413, detail='Skill archive too large')
    parts = {}
    if zipfile.is_zipfile(io.BytesIO(contents)):
        with zipfile.ZipFile(io.BytesIO(contents)) as archive:
            entries = [item for item in archive.infolist() if not item.is_dir()]
            roots = [item for item in entries if item.filename.endswith('/SKILL.md') or item.filename == 'SKILL.md']
            if not roots:
                raise HTTPException(422, detail='SKILL.md is missing')
            prefix = roots[0].filename.removesuffix('SKILL.md')
            if len(entries) > _MAX_FILES + 1 or sum(item.file_size for item in entries) > _MAX_UPLOAD:
                raise HTTPException(413, detail='Skill archive exceeds limits')
            for info in entries:
                if not info.filename.startswith(prefix):
                    raise HTTPException(422, detail='Archive must contain one Skill directory')
                relative = info.filename[len(prefix):]
                if relative != 'SKILL.md':
                    _path(relative)
                if info.file_size > _MAX_BODY:
                    raise HTTPException(413, detail='Skill entry exceeds per-file limit')
                parts[relative] = archive.read(info, pwd=None)
    else:
        parts = {'SKILL.md': contents}
    if 'SKILL.md' not in parts:
        raise HTTPException(422, detail='SKILL.md is missing')
    try:
        text = parts.pop('SKILL.md').decode('utf-8')
        stem = (upload.filename or 'skill').split('.')[0].lower().replace('_', '-')
        data = _parse_skill_text(text, stem)
    except (UnicodeError, yaml.YAMLError, ValueError) as exc:
        raise HTTPException(422, detail='Invalid SKILL.md') from exc
    now = _now()
    sid = str(uuid.uuid4())
    repo = _repo()
    reference_texts = []
    for content in parts.values():
        try:
            reference_texts.append(content.decode('utf-8'))
        except UnicodeError:
            continue
    _enforce_skill_policy(repo, owner, description=data['description'], body=data['body'],
                          references=reference_texts)
    try:
        with repo.database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO webui_skills(id,owner,name,record,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                       (sid, owner, data['name'], _json(data), now, now))
            from .skill_tree_routes import _ensure_folders

            for path, content in parts.items():
                _ensure_folders(db, owner, sid, path)
                db.execute('INSERT INTO webui_skill_files(id,owner,skill_id,path,data,mime,created_at,updated_at) '
                           'VALUES(?,?,?,?,?,?,?,?)',
                           (str(uuid.uuid4()), owner, sid, path, content,
                            mimetypes.guess_type(path)[0] or 'application/octet-stream', now, now))
            return JSONResponse(_row(_owned(db, owner, sid), detail=True, file_count=len(parts)), status_code=201)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, detail='Skill name already exists') from exc


def skill_routes() -> list[Route]:
    return [
        Route('/api/skills', skills, methods=['GET', 'POST']),
        Route('/api/skills/import', import_skill, methods=['POST']),
        Route('/api/user/settings/skills/active', states, methods=['GET', 'POST']),
        Route('/api/skills/{id}/files', files, methods=['GET', 'POST']),
        Route('/api/skills/{id}/files/{path:path}', file_by_path, methods=['GET', 'DELETE', 'POST']),
        Route('/api/skills/{id}', skill, methods=['GET', 'PATCH', 'DELETE']),
    ]
