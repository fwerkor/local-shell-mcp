"""Personal bookmarks for persisted messages, independent of conversation tags."""
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .auth import _same_origin
from .routes import _body, _owner, _repo
from .storage import _now, _stamp

_SELECT = """
SELECT b.message_id, b.title, b.created_at, m.conversation_id, m.role,
       substr(m.text, 1, 500) AS preview, c.title AS conversation_title
FROM webui_message_bookmarks b
JOIN messages m ON m.id=b.message_id
JOIN conversations c ON c.id=m.conversation_id AND c.owner=b.owner
WHERE b.owner=?
"""


def _record(row):
    return {
        'messageId': row['message_id'], 'conversationId': row['conversation_id'],
        'title': row['title'], 'preview': row['preview'], 'role': row['role'],
        'conversationTitle': row['conversation_title'],
        'createdAt': _stamp(row['created_at'] / 1_000_000),
    }


async def list_bookmarks(request: Request):
    owner = _owner(request)
    with _repo().database.connect() as db:
        rows = db.execute(_SELECT + ' ORDER BY b.created_at DESC,b.message_id', (owner,))
        return JSONResponse([_record(row) for row in rows])


async def bookmark(request: Request):
    _same_origin(request)
    owner = _owner(request)
    message_id = request.path_params['message_id']
    if request.method == 'DELETE':
        with _repo().database.connect() as db:
            db.execute('DELETE FROM webui_message_bookmarks WHERE owner=? AND message_id=?',
                       (owner, message_id))
        return JSONResponse({'deleted': True})
    payload = await _body(request)
    title = payload.get('title')
    if title is not None and (not isinstance(title, str) or len(title) > 256):
        raise HTTPException(400, detail='Invalid bookmark title')
    with _repo().database.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute(
            'SELECT 1 FROM messages m JOIN conversations c ON c.id=m.conversation_id '
            'WHERE m.id=? AND c.owner=?', (message_id, owner)
        ).fetchone():
            raise HTTPException(404, detail='Message not found')
        db.execute(
            'INSERT INTO webui_message_bookmarks(owner,message_id,title,created_at) VALUES(?,?,?,?) '
            'ON CONFLICT(owner,message_id) DO UPDATE SET title=COALESCE(?,title)',
            (owner, message_id, (title or '').strip(), _now(),
             title.strip() if title is not None else None),
        )
        row = db.execute(_SELECT + ' AND b.message_id=?', (owner, message_id)).fetchone()
        return JSONResponse(_record(row))


def message_bookmark_routes() -> list[Route]:
    return [
        Route('/api/message-bookmarks', list_bookmarks, methods=['GET']),
        Route('/api/message-bookmarks/{message_id}', bookmark, methods=['PUT', 'DELETE']),
    ]
