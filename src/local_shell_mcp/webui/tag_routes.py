"""LibreChat conversation bookmarks (tags) on the Controller's SQLite database.

The title of a bookmark is its tag identifier, exactly as the existing React
client expects. All renames and deletions update conversation references in the
same transaction; foreign owners' conversations are never touched.
"""
from __future__ import annotations

import json
import sqlite3
import uuid

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .auth import _same_origin
from .routes import _body, _owner, _repo
from .storage import _json, _now, _stamp


def _record(row, count=0):
    return {
        '_id': row['id'], 'user': row['owner'], 'tag': row['tag'],
        'description': row['description'], 'position': row['position'],
        'count': count,
        'createdAt': _stamp(row['created_at'] / 1_000_000),
        'updatedAt': _stamp(row['updated_at'] / 1_000_000),
    }


def _tags(raw):
    try:
        tags = json.loads(raw).get('tags') or []
    except (TypeError, ValueError, AttributeError):
        return []
    return tags if isinstance(tags, list) else []


def _validate(payload, *, old=None):
    tag = payload.get('tag', old)
    if not isinstance(tag, str) or not tag.strip() or len(tag) > 128:
        raise HTTPException(400, detail='Tag must contain 1–128 characters')
    desc = payload.get('description', '')
    if not isinstance(desc, str) or len(desc) > 1048:
        raise HTTPException(400, detail='Invalid tag description')
    position = payload.get('position', 0)
    if type(position) is not int or position < 0 or position > 100_000:
        raise HTTPException(400, detail='Invalid tag position')
    return tag.strip(), desc, position


def _touch_references(db, owner, old, new=None):
    conversations = db.execute('SELECT id,metadata FROM conversations WHERE owner=?', (owner,)).fetchall()
    for convo in conversations:
        tags = _tags(convo['metadata'])
        if old not in tags:
            continue
        tags = list(dict.fromkeys(new if value == old else value
                                  for value in tags if new is not None or value != old))
        metadata = json.loads(convo['metadata'])
        metadata['tags'] = tags
        db.execute('UPDATE conversations SET metadata=?,updated_at=? WHERE id=? AND owner=?',
                   (_json(metadata), _now(), convo['id'], owner))


async def tags(request: Request):
    if request.method != 'GET':
        _same_origin(request)
    owner = _owner(request)
    repo = _repo()
    if request.method == 'GET':
        with repo.database.connect() as db:
            rows = db.execute('SELECT * FROM webui_tags WHERE owner=? ORDER BY position,created_at',
                              (owner,)).fetchall()
            convos = db.execute('SELECT metadata FROM conversations WHERE owner=?', (owner,)).fetchall()
        counts = {row['tag']: 0 for row in rows}
        for convo in convos:
            for tag in set(_tags(convo['metadata'])):
                if tag in counts:
                    counts[tag] += 1
        return JSONResponse([_record(row, counts[row['tag']]) for row in rows])
    payload = await _body(request)
    tag, desc, position = _validate(payload)
    now = _now()
    try:
        with repo.database.connect() as db:
            db.execute('INSERT INTO webui_tags(id,owner,tag,description,position,created_at,updated_at) '
                       'VALUES(?,?,?,?,?,?,?)', (str(uuid.uuid4()), owner, tag, desc, position, now, now))
            if payload.get('addToConversation') is True:
                cid = payload.get('conversationId')
                convo = db.execute('SELECT metadata FROM conversations WHERE owner=? AND id=?',
                                   (owner, cid)).fetchone()
                if convo is None:
                    raise HTTPException(404, detail='Conversation not found')
                metadata = json.loads(convo['metadata'])
                metadata['tags'] = list(dict.fromkeys([*_tags(convo['metadata']), tag]))
                db.execute('UPDATE conversations SET metadata=? WHERE id=? AND owner=?',
                           (_json(metadata), cid, owner))
            row = db.execute('SELECT * FROM webui_tags WHERE owner=? AND tag=?', (owner, tag)).fetchone()
        return JSONResponse(_record(row), status_code=201)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, detail='Tag already exists') from exc


async def tag(request: Request):
    if request.method != 'GET':
        _same_origin(request)
    owner = _owner(request)
    old = request.path_params['tag']
    repo = _repo()
    with repo.database.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM webui_tags WHERE owner=? AND tag=?', (owner, old)).fetchone()
        if row is None:
            raise HTTPException(404, detail='Tag not found')
        previous = _record(row)
        if request.method == 'DELETE':
            _touch_references(db, owner, old)
            db.execute('DELETE FROM webui_tags WHERE id=? AND owner=?', (row['id'], owner))
            return JSONResponse(previous)
        payload = await _body(request)
        name, desc, position = _validate({**previous, **payload}, old=old)
        if name != old:
            if db.execute('SELECT 1 FROM webui_tags WHERE owner=? AND tag=?', (owner, name)).fetchone():
                raise HTTPException(409, detail='Tag already exists')
            _touch_references(db, owner, old, name)
        db.execute('UPDATE webui_tags SET tag=?,description=?,position=?,updated_at=? WHERE id=? AND owner=?',
                   (name, desc, position, _now(), row['id'], owner))
        result = db.execute('SELECT * FROM webui_tags WHERE id=?', (row['id'],)).fetchone()
        return JSONResponse(_record(result))


async def tags_in_conversation(request: Request):
    if request.method != 'GET':
        _same_origin(request)
    owner = _owner(request)
    cid = request.path_params['conversation_id']
    payload = await _body(request)
    requested = payload.get('tags')
    if (not isinstance(requested, list) or len(requested) > 100
            or any(not isinstance(tag, str) or len(tag) > 128 for tag in requested)):
        raise HTTPException(400, detail='Invalid conversation tags')
    tags_list = list(dict.fromkeys(requested))
    repo = _repo()
    with repo.database.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        convo = db.execute('SELECT metadata FROM conversations WHERE id=? AND owner=?', (cid, owner)).fetchone()
        if convo is None:
            raise HTTPException(404, detail='Conversation not found')
        known = {row['tag'] for row in db.execute('SELECT tag FROM webui_tags WHERE owner=?', (owner,))}
        if not set(tags_list).issubset(known):
            raise HTTPException(400, detail='Unknown bookmark')
        metadata = json.loads(convo['metadata'])
        metadata['tags'] = tags_list
        db.execute('UPDATE conversations SET metadata=?,updated_at=? WHERE id=? AND owner=?',
                   (_json(metadata), _now(), cid, owner))
        return JSONResponse(tags_list)


def tag_routes() -> list[Route]:
    return [
        Route('/api/tags', tags, methods=['GET', 'POST']),
        Route('/api/tags/list', tags, methods=['GET']),
        Route('/api/tags/convo/{conversation_id}', tags_in_conversation, methods=['PUT']),
        Route('/api/tags/{tag}', tag, methods=['PUT', 'DELETE']),
    ]
