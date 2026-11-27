"""Durable automatic prompt fragments, separate from client-editable metadata."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

from .memory import agent_partition
from .memory_protection import configured_filters
from .storage import WorkspaceRepository


def automatic_context(database, owner: str, conversation_id: str, authorization_id: str,
                      agent: dict | None, kind: str, build: Callable[[], str]) -> str:
    """Freeze even empty fragments. A new privacy scope gets its own snapshot.

    Build outside the write transaction because recall and Skill loading read
    the same database. The unique key and INSERT OR IGNORE choose one winner.
    Neither conversation metadata nor the public CRUD API exposes this table.
    """
    def scope_for(db):
        row = db.execute(
            "SELECT project_id FROM conversations WHERE id=? AND owner=?",
            (authorization_id, owner),
        ).fetchone()
        if row is None or not db.execute(
            "SELECT 1 FROM conversations WHERE id=? AND owner=?",
            (conversation_id, owner),
        ).fetchone():
            return None
        # Historical recall is project-scoped; never carry that snapshot into
        # another project or a different Agent's private memory partition.
        identity = [(agent or {}).get('id'), authorization_id,
                    row['project_id'] if kind == 'memory' else None,
                    agent_partition(agent) if kind == 'memory' else None]
        return identity

    repo = WorkspaceRepository(database)
    policy = configured_filters(repo, owner)
    # A changed content policy is an intentional security boundary, not a
    # memory/Skill CRUD event. It must not replay content admitted by old rules.
    policy_digest = hashlib.sha256(json.dumps(
        policy, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with database.connect() as db:
        identity = scope_for(db)
        if identity is None:
            return ''
        scope = json.dumps([*identity, policy_digest], ensure_ascii=False)
        row = db.execute(
            "SELECT content FROM webui_prompt_snapshots WHERE conversation_id=? AND kind=? AND scope=?",
            (conversation_id, kind, scope),
        ).fetchone()
        if row is not None:
            return row['content']
    content = build()
    with database.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if scope_for(db) != identity:
            # A concurrent project move/deletion must not freeze text from a
            # different authorization context. Retry on the next invocation.
            return ''
        db.execute(
            "INSERT OR IGNORE INTO webui_prompt_snapshots(conversation_id,kind,scope,content) VALUES(?,?,?,?)",
            (conversation_id, kind, scope, content),
        )
        return db.execute(
            "SELECT content FROM webui_prompt_snapshots WHERE conversation_id=? AND kind=? AND scope=?",
            (conversation_id, kind, scope),
        ).fetchone()['content']
