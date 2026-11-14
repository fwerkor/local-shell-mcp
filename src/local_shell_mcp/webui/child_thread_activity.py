"""Shared SQLite guard for live child conversations before lineage is materialized.

LibreChat guard.ts blocks three sources: reserved child IDs, persisted lineage,
and active child execution from its owning task store. This is the live-task
bridge for the Python graph host, scoped to authenticated owner and parent run.
It does not infer child ownership from arbitrary model-supplied UUIDs.
"""

from __future__ import annotations

from .storage import _now


class ActiveChildThreads:
    def __init__(self, database):
        self.database = database

    def activate(self, owner: str, child_thread: str, parent_run: str) -> None:
        """Register before exposing/creating the child thread, in the shared DB."""
        if not owner or not child_thread or not parent_run:
            raise ValueError("A trusted owner, child thread, and parent run are required")
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            parent = db.execute(
                "SELECT r.conversation_id,r.status FROM runs r "
                "JOIN conversations c ON r.conversation_id=c.id "
                "WHERE r.id=? AND c.owner=?",
                (parent_run, owner),
            ).fetchone()
            if parent is None or parent["status"] not in {"running", "requires_action"}:
                raise PermissionError("Parent generation is not active for this owner")
            if child_thread == parent["conversation_id"]:
                raise ValueError("A child thread must not be the parent conversation")
            occupied = db.execute(
                "SELECT owner FROM conversations WHERE id=?", (child_thread,)
            ).fetchone()
            if occupied is not None and occupied["owner"] != owner:
                raise PermissionError("Cannot claim another owner's conversation")
            existing = db.execute(
                "SELECT parent_run_id FROM active_subagent_threads WHERE owner=? AND thread_id=?",
                (owner, child_thread),
            ).fetchone()
            if existing is not None and existing["parent_run_id"] != parent_run:
                raise PermissionError("A different parent run owns this child thread")
            db.execute(
                "INSERT INTO active_subagent_threads(owner,thread_id,parent_run_id,active,updated_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(owner,thread_id) DO UPDATE SET "
                "active=1,updated_at=excluded.updated_at",
                (owner, child_thread, parent_run, 1, _now()),
            )

    def reserve_for_completed_parent(self, owner: str, child_thread: str,
                                     parent_run: str, parent_reply: str) -> None:
        """Reserve an immutable Event Actor child after its parent reply settled.

        Source event bindings attach to a *completed* authoritative assistant
        reply, whereas normal subagent spawn attaches to a running parent.
        Both must register the same permanent Artifacts child-write fence
        before the child conversation becomes visible.
        """
        if not all(isinstance(item, str) and item for item in
                   (owner, child_thread, parent_run, parent_reply)):
            raise ValueError("A trusted owner, child, run and parent reply are required")
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            parent = db.execute(
                "SELECT r.conversation_id,r.state,r.status FROM runs r "
                "JOIN conversations c ON c.id=r.conversation_id WHERE r.id=? AND c.owner=?",
                (parent_run, owner),
            ).fetchone()
            if parent is None or parent["status"] != "complete":
                raise PermissionError("Event Actor parent generation must be completed")
            import json

            if json.loads(parent["state"]).get("responseMessageId") != parent_reply:
                raise PermissionError("Event Actor parent reply is not the completed run's output")
            reply = db.execute("SELECT 1 FROM messages WHERE id=? AND conversation_id=? "
                               "AND role='assistant'", (parent_reply, parent["conversation_id"])).fetchone()
            if reply is None or child_thread == parent["conversation_id"]:
                raise PermissionError("Event Actor child has an invalid parent reply or thread")
            occupied = db.execute("SELECT owner FROM conversations WHERE id=?", (child_thread,)).fetchone()
            if occupied is not None:
                raise PermissionError("Reserved Event Actor child conversation already exists")
            prior = db.execute("SELECT parent_run_id FROM active_subagent_threads "
                               "WHERE owner=? AND thread_id=?", (owner, child_thread)).fetchone()
            if prior is not None and prior["parent_run_id"] != parent_run:
                raise PermissionError("Event Actor child belongs to another parent run")
            db.execute("INSERT INTO active_subagent_threads(owner,thread_id,parent_run_id,active,updated_at) "
                       "VALUES(?,?,?,?,?) ON CONFLICT(owner,thread_id) DO UPDATE SET "
                       "updated_at=excluded.updated_at",
                       (owner, child_thread, parent_run, 0, _now()))

    def settle(self, owner: str, child_thread: str, parent_run: str) -> bool:
        """Mark inactive while retaining immutable child identity after execution."""
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(
                "UPDATE active_subagent_threads SET active=0,updated_at=? "
                "WHERE owner=? AND thread_id=? AND parent_run_id=? AND active=1",
                (_now(), owner, child_thread, parent_run),
            )
            return cursor.rowcount == 1


def is_registered_child_thread(db, owner: str, thread_id: str) -> bool:
    """Block registered children for life, even without committed lineage metadata.

    The owner-scoped registry also covers the pre-conversation active window.
    Query within the same BEGIN IMMEDIATE transaction as an editor mutation.
    """
    return (
        db.execute(
            "SELECT 1 FROM active_subagent_threads "
            "WHERE owner=? AND thread_id=? LIMIT 1",
            (owner, thread_id),
        ).fetchone()
        is not None
    )
