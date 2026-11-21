"""SQLite CAS ownership for every foreground HTTP generation actor.

Only one Controller may generate or invoke tools for an owned run at a time.
All lease identity comes from the server's persistent run, never client input.
Recovery requires a newly authenticated request; a startup task never silently
inherits machine permissions from a dead process.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import time
from dataclasses import dataclass

_LEASE_MS = 120_000
_RENEW_S = 20


def _now() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class ActorLease:
    database: object
    owner: str
    run_id: str
    token: str

    @classmethod
    def claim(cls, database, owner: str, run_id: str):
        token = secrets.token_hex(24)
        now = _now()
        with database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            match = db.execute(
                "SELECT 1 FROM runs r JOIN conversations c ON c.id=r.conversation_id "
                "WHERE r.id=? AND c.owner=? AND r.status='running'", (run_id, owner),
            ).fetchone()
            if match is None:
                return None
            db.execute("INSERT INTO generation_actor_leases(run_id,owner,token,expires_at) "
                       "VALUES(?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET "
                       "owner=excluded.owner,token=excluded.token,expires_at=excluded.expires_at "
                       "WHERE generation_actor_leases.expires_at<=?",
                       (run_id, owner, token, now + _LEASE_MS, now))
            row = db.execute("SELECT token FROM generation_actor_leases WHERE run_id=? AND owner=?",
                             (run_id, owner)).fetchone()
            return cls(database, owner, run_id, token) if row and row["token"] == token else None

    def is_current(self, db=None):
        if db is None:
            with self.database.connect() as connection:
                return self.is_current(connection)
        return db.execute(
            "SELECT 1 FROM generation_actor_leases l JOIN runs r ON r.id=l.run_id "
            "JOIN conversations c ON c.id=r.conversation_id WHERE l.run_id=? AND l.owner=? "
            "AND l.token=? AND l.expires_at>? AND r.status='running' AND c.owner=l.owner",
            (self.run_id, self.owner, self.token, _now()),
        ).fetchone() is not None

    def assert_current(self, db=None):
        if not self.is_current(db):
            from .agent_runtime import RuntimeSafetyError

            raise RuntimeSafetyError("Generation actor lease expired or was replaced")

    def renew(self) -> bool:
        now = _now()
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(
                "UPDATE generation_actor_leases SET expires_at=? WHERE run_id=? AND owner=? "
                "AND token=? AND expires_at>? AND EXISTS(SELECT 1 FROM runs "
                "WHERE runs.id=generation_actor_leases.run_id AND runs.status='running')",
                (now + _LEASE_MS, self.run_id, self.owner, self.token, now),
            )
            return cursor.rowcount == 1

    def release(self) -> None:
        with self.database.connect() as db:
            db.execute("DELETE FROM generation_actor_leases WHERE run_id=? AND owner=? AND token=?",
                       (self.run_id, self.owner, self.token))

    async def keep_alive(self) -> None:
        while True:
            await asyncio.sleep(_RENEW_S)
            if not await asyncio.to_thread(self.renew):
                return


def active_run_ids(database) -> set[str]:
    with database.connect() as db:
        return {row["run_id"] for row in db.execute(
            "SELECT l.run_id FROM generation_actor_leases l JOIN runs r ON r.id=l.run_id "
            "WHERE l.expires_at>? AND r.status='running'", (_now(),),
        )}


def resumable_run_ids(database, *, excludes: set[str] | None = None) -> set[str]:
    """Exclude checkpointed runs from eager orphan termination on boot.

    A subsequent *authenticated* resume/SSE request must supply fresh grants;
    no machine actions are run during startup.
    """
    from .checkpoints import SQLiteCheckpointSaver

    excluded = excludes or set()
    with database.connect() as db:
        rows = db.execute(
            "SELECT r.id,r.conversation_id,c.owner,r.state FROM runs r "
            "JOIN conversations c ON c.id=r.conversation_id WHERE r.status='running'"
        ).fetchall()
    candidates = set()
    for row in rows:
        if row["id"] in excluded:
            continue
        # A persisted steer part is itself a durable recovery log even if
        # the first model checkpoint did not reach SQLite before the crash.
        if (json.loads(row["state"]).get("steerParts") or []):
            candidates.add(row["id"])
            continue
        saver = SQLiteCheckpointSaver(database, row["owner"])
        own = saver.config(row["conversation_id"], row["id"], event_actor=True)
        graph = saver.config(row["conversation_id"], row["id"] + ":graph:", event_actor=True)
        if saver.get_tuple(own) is not None or saver.get_tuple(graph) is not None:
            candidates.add(row["id"])
    return candidates
