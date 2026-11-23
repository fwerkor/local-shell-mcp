"""Persisted editable Skill tree, including empty folders and file contents.

Paths never escape a Skill namespace. Folder moves rename the complete subtree
inside one SQLite transaction, avoiding orphaned file paths.
"""
from __future__ import annotations

import mimetypes
import sqlite3
import uuid
from pathlib import PurePosixPath

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .auth import _same_origin, public_owner_id
from .routes import _body, _owner, _repo
from .skill_routes import _MAX_BODY, _enforce_skill_policy, _owned, _path
from .storage import _now, _stamp


def _format(row, kind, parent):
    item = {
        '_id': row['id'], 'skillId': row['skill_id'],
        'parentId': parent, 'type': kind, 'name': PurePosixPath(row['path']).name,
        'order': row['position'], 'author': public_owner_id(row['owner']),
        'createdAt': _stamp(row['created_at'] / 1_000_000),
        'updatedAt': _stamp(row['updated_at'] / 1_000_000),
    }
    if kind == 'file':
        item['fileId'] = row['id']
    return item


def _folder_map(db, sid):
    return {row['path']: row for row in db.execute(
        'SELECT * FROM webui_skill_folders WHERE skill_id=?', (sid,)).fetchall()}


def _ensure_folders(db, owner, sid, path):
    prefix = []
    for component in PurePosixPath(path).parts[:-1]:
        prefix.append(component)
        joined = '/'.join(prefix)
        if not db.execute('SELECT 1 FROM webui_skill_folders WHERE skill_id=? AND path=?',
                          (sid, joined)).fetchone():
            now = _now()
            db.execute('INSERT INTO webui_skill_folders(id,owner,skill_id,path,created_at,updated_at) '
                       'VALUES(?,?,?,?,?,?)',
                       (str(uuid.uuid4()), owner, sid, joined, now, now))


def _node(db, owner, sid, nid):
    for table, kind in [('webui_skill_folders', 'folder'), ('webui_skill_files', 'file')]:
        row = db.execute(f'SELECT * FROM {table} WHERE id=? AND skill_id=? AND owner=?',
                         (nid, sid, owner)).fetchone()
        if row is not None:
            return kind, row
    raise HTTPException(404, detail='Skill node not found')


def _parent_path(db, owner, sid, parent_id):
    if parent_id is None:
        return ''
    if not isinstance(parent_id, str) or not 1 <= len(parent_id) <= 128:
        raise HTTPException(400, detail='Invalid parent id')
    kind, row = _node(db, owner, sid, parent_id)
    if kind != 'folder':
        raise HTTPException(400, detail='Parent must be a folder')
    return row['path']


def _join_path(db, owner, sid, name, parent_id):
    if not isinstance(name, str) or not name or '/' in name or '\\' in name:
        raise HTTPException(400, detail='Invalid node name')
    parent = _parent_path(db, owner, sid, parent_id)
    return _path((parent + '/' if parent else '') + name)


def _unique_path(db, sid, path, *, old_path=None):
    for table in ('webui_skill_folders', 'webui_skill_files'):
        row = db.execute(f'SELECT path FROM {table} WHERE skill_id=? AND path=?',
                         (sid, path)).fetchone()
        if row is not None and row['path'] != old_path:
            raise HTTPException(409, detail='A Skill node with this name already exists')


async def tree(request: Request):
    if request.method != 'GET':
        _same_origin(request)
    owner = _owner(request)
    sid = request.path_params['id']
    if sid.startswith('deployment:'):
        if request.method != 'GET':
            raise HTTPException(403, detail='Deployment Skills are read-only')
        return JSONResponse({'nodes': []})
    db_ref = _repo().database
    if request.method == 'GET':
        with db_ref.connect() as db:
            _owned(db, owner, sid)
            folders = _folder_map(db, sid)
            files = db.execute('SELECT * FROM webui_skill_files WHERE skill_id=? AND owner=? ORDER BY path',
                               (sid, owner)).fetchall()
            nodes = []
            for row in sorted(folders.values(), key=lambda f: (f['path'].count('/'), f['path'])):
                parent = str(PurePosixPath(row['path']).parent)
                nodes.append(_format(row, 'folder', folders[parent]['id'] if parent in folders else None))
            for row in files:
                parent = str(PurePosixPath(row['path']).parent)
                nodes.append(_format(row, 'file', folders[parent]['id'] if parent in folders else None))
        return JSONResponse({'nodes': nodes})
    if request.headers.get('content-type', '').startswith('multipart/'):
        form = await request.form()
        data = dict(form)
        uploaded = form.get('file')
        content = await uploaded.read(_MAX_BODY + 1) if uploaded is not None else b''
    else:
        data = await _body(request)
        content = b''
    kind = data.get('type')
    if kind not in {'file', 'folder'}:
        raise HTTPException(400, detail='Invalid node type')
    if len(content) > _MAX_BODY:
        raise HTTPException(413, detail='Skill node file too large')
    if kind == 'file':
        try:
            reference_text = content.decode('utf-8')
        except UnicodeError:
            reference_text = None
        if reference_text is not None:
            _enforce_skill_policy(_repo(), owner, references=[reference_text])
    order = data.get('order', 0)
    if type(order) is not int or not 0 <= order <= 100_000:
        raise HTTPException(400, detail='Invalid node order')
    now = _now()
    nid = str(uuid.uuid4())
    with db_ref.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        _owned(db, owner, sid)
        path = _join_path(db, owner, sid, data.get('name'), data.get('parentId'))
        _unique_path(db, sid, path)
        if kind == 'folder':
            db.execute('INSERT INTO webui_skill_folders(id,owner,skill_id,path,position,created_at,updated_at)'
                       ' VALUES(?,?,?,?,?,?,?)', (nid, owner, sid, path, order, now, now))
        else:
            db.execute('INSERT INTO webui_skill_files(id,owner,skill_id,path,data,mime,position,created_at,updated_at) '
                       'VALUES(?,?,?,?,?,?,?,?,?)', (nid, owner, sid, path, content,
                       getattr(data.get('file'), 'content_type', None) or
                       mimetypes.guess_type(path)[0] or 'text/plain', order, now, now))
        row = db.execute('SELECT * FROM webui_skill_' + ('folders' if kind == 'folder' else 'files') +
                         ' WHERE id=?', (nid,)).fetchone()
        return JSONResponse(_format(row, kind, data.get('parentId')), status_code=201)


async def node(request: Request):
    if request.method != 'GET':
        _same_origin(request)
    owner = _owner(request)
    sid = request.path_params['id']
    nid = request.path_params['node_id']
    if sid.startswith('deployment:'):
        raise HTTPException(403, detail='Deployment Skills are read-only')
    db_ref = _repo().database
    with db_ref.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        _owned(db, owner, sid)
        kind, row = _node(db, owner, sid, nid)
        table = 'webui_skill_folders' if kind == 'folder' else 'webui_skill_files'
        if request.method == 'DELETE':
            if kind == 'folder':
                # LIKE treats literal underscores and percent signs in folder names
                # as wildcards. Match exact path bytes before deleting descendants.
                prefix = row['path'] + '/'
                db.execute('DELETE FROM webui_skill_files WHERE skill_id=? '
                           'AND substr(path,1,?)=?', (sid, len(prefix), prefix))
                db.execute('DELETE FROM webui_skill_folders WHERE skill_id=? AND '
                           '(path=? OR substr(path,1,?)=?)',
                           (sid, row['path'], len(prefix), prefix))
            else:
                db.execute('DELETE FROM webui_skill_files WHERE id=? AND owner=?', (nid, owner))
            return JSONResponse({'deleted': True})
        payload = await _body(request)
        if not isinstance(payload, dict):
            raise HTTPException(400, detail='Invalid node update')
        parent = payload.get('parentId')
        old = row['path']
        old_parent = str(PurePosixPath(old).parent)
        if 'parentId' not in payload:
            parent_path = '' if old_parent == '.' else old_parent
        else:
            parent_path = _parent_path(db, owner, sid, parent)
        name = payload.get('name', PurePosixPath(old).name)
        if not isinstance(name, str) or not name or '/' in name or '\\' in name:
            raise HTTPException(400, detail='Invalid node name')
        candidate = _path((parent_path + '/' if parent_path else '') + name)
        if kind == 'folder' and (candidate.startswith(old + '/') or candidate == old + '/' or
                                 parent_path.startswith(old + '/') or parent_path == old):
            raise HTTPException(400, detail='Cannot move folder into itself')
        if candidate != old:
            _unique_path(db, sid, candidate, old_path=old)
            if kind == 'folder':
                prefix = old + '/'
                for child_table in ('webui_skill_files', 'webui_skill_folders'):
                    rows = db.execute(f'SELECT id,path FROM {child_table} WHERE skill_id=?',
                                      (sid,)).fetchall()
                    for descendant in rows:
                        if descendant['path'].startswith(prefix):
                            new_path = candidate + descendant['path'][len(old):]
                            _unique_path(db, sid, new_path, old_path=descendant['path'])
                            db.execute(f'UPDATE {child_table} SET path=?,updated_at=? WHERE id=?',
                                       (new_path, _now(), descendant['id']))
        order = payload.get('order', row['position'])
        if type(order) is not int or not 0 <= order <= 100_000:
            raise HTTPException(400, detail='Invalid node order')
        try:
            db.execute(f'UPDATE {table} SET path=?,position=?,updated_at=? WHERE id=? AND owner=?',
                       (candidate, order, _now(), nid, owner))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, detail='Skill node already exists') from exc
        latest = db.execute(f'SELECT * FROM {table} WHERE id=?', (nid,)).fetchone()
        parent_path = str(PurePosixPath(candidate).parent)
        folders = _folder_map(db, sid)
        return JSONResponse(_format(latest, kind,
                                   folders[parent_path]['id'] if parent_path in folders else None))


async def node_content(request: Request):
    if request.method != 'GET':
        _same_origin(request)
    owner = _owner(request)
    sid = request.path_params['id']
    nid = request.path_params['node_id']
    if sid.startswith('deployment:'):
        raise HTTPException(403, detail='Deployment Skills are read-only')
    db_ref = _repo().database
    with db_ref.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        _owned(db, owner, sid)
        kind, row = _node(db, owner, sid, nid)
        if kind != 'file':
            raise HTTPException(400, detail='Folder has no text content')
        if request.method == 'GET':
            try:
                value = row['data'].decode('utf-8')
            except UnicodeError:
                raise HTTPException(415, detail='File is binary') from None
            return JSONResponse({'content': value, 'mimeType': row['mime']})
        payload = await _body(request)
        value = payload.get('content')
        if not isinstance(value, str) or len(value.encode('utf-8')) > _MAX_BODY:
            raise HTTPException(400, detail='Invalid file content')
        _enforce_skill_policy(_repo(), owner, references=[value])
        db.execute('UPDATE webui_skill_files SET data=?,updated_at=? WHERE id=? AND owner=?',
                   (value.encode('utf-8'), _now(), nid, owner))
        result = db.execute('SELECT * FROM webui_skill_files WHERE id=?', (nid,)).fetchone()
        parent = str(PurePosixPath(result['path']).parent)
        folders = _folder_map(db, sid)
        return JSONResponse(_format(result, 'file', folders[parent]['id'] if parent in folders else None))


def skill_tree_routes():
    return [
        Route('/api/skills/{id}/tree', tree, methods=['GET', 'POST']),
        Route('/api/skills/{id}/tree/{node_id}/content', node_content, methods=['GET', 'PUT']),
        Route('/api/skills/{id}/tree/{node_id}', node, methods=['PATCH', 'DELETE']),
    ]
