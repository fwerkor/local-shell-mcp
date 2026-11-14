"""LibreChat attachment deletion with SQLite-serialized Agent references.

Source: packages/api/src/files/deletion.ts (e8f3be08). Unlike the upstream
Mongo/filesystem split, local data uses a durable SQLite intent and same-volume
quarantine. A cross-process state lock serializes recoverers and deletions;
BEGIN IMMEDIATE serializes the final reference check with every Agent writer.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from pathlib import Path

from ..sqlite_store import SQLiteStateStore
from .storage import _json, _now

log = logging.getLogger(__name__)


def delete_response(result, message):
    result = result or {}
    deleted = result.get("deletedFileIds") or []
    failed = result.get("failedFileIds") or []
    return {"message": "Some files could not be deleted" if failed else message,
            "deletedFileIds": deleted, "failedFileIds": failed}


def partition_resource_files(requested, attached, files, resource, owner):
    """Port partitionAgentResourceFiles, including insertion order/deduplication."""
    attached = set(attached)
    by_id = {value["file_id"]: value for value in files}
    seen, owned, unlink = set(), [], []
    for ident in requested:
        if ident not in attached or ident in seen:
            continue
        seen.add(ident)
        value = by_id.get(ident)
        if value is not None and value.get("owner") == owner:
            owned.append(value)
        else:
            unlink.append({"tool_resource": resource, "file_id": ident})
    return {"ownedFiles": owned, "unlinkOnlyFiles": unlink}


def plan_resource_deletion(requested, attached, files, resource, owner, shared):
    partition = partition_resource_files(requested, attached, files, resource, owner)
    shared = set(shared)
    destroy, unlink = [], list(partition["unlinkOnlyFiles"])
    for value in partition["ownedFiles"]:
        if value["file_id"] in shared:
            unlink.append({"tool_resource": resource, "file_id": value["file_id"]})
        else:
            destroy.append(value["file"])
    return destroy, unlink


class AttachmentDeletionStore:
    """Durable per-file deletion; no snapshot may authorize a delete.

    All callers must use this store instead of deleting metadata directly.
    Agent writes already take SQLite BEGIN IMMEDIATE, including new references
    during an upload, so the *last* reference check is inside that same lock.
    """

    def __init__(self, database):
        self.database = database
        self.root = database.root.resolve() / "attachments"
        self._locks = SQLiteStateStore(database.root, migrate_files=False)

    def _path(self, raw):
        path = Path(raw)
        if not path.is_absolute() or path.is_symlink() or self.root not in path.resolve().parents:
            raise OSError("Attachment storage path is unsafe")
        return path

    @staticmethod
    def _sync_directory(path):
        if os.name == "nt":
            return
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _remove_references(db, identities):
        identities = set(identities)
        for row in db.execute("SELECT id,config FROM agents").fetchall():
            config = json.loads(row["config"])
            changed = False
            for value in config.get("tool_resources", {}).values():
                if not isinstance(value, dict) or not isinstance(value.get("file_ids"), list):
                    continue
                previous = value["file_ids"]
                value["file_ids"] = [ident for ident in previous if ident not in identities]
                changed = changed or previous != value["file_ids"]
            if changed:
                db.execute("UPDATE agents SET config=?,updated_at=? WHERE id=?",
                           (_json(config), _now(), row["id"]))

    def shared_resource_ids(self, db, identities, agent_id, resource):
        """Find all *other* durable holders under the same SQLite write lock.

        Agent resource links, user-message files and tool-produced attachments
        are all references. Even when the last Agent is unlinked, history may
        still depend on its original file. The owner-only global DELETE bypasses
        this check and explicitly retires all references.
        """
        shared = set()
        requested = set(identities)
        for row in db.execute("SELECT id,config FROM agents").fetchall():
            for key, value in json.loads(row["config"]).get("tool_resources", {}).items():
                if row["id"] == agent_id and key == resource:
                    continue
                if isinstance(value, dict) and isinstance(value.get("file_ids"), list):
                    shared.update(requested.intersection(value["file_ids"]))
        if not requested:
            return shared
        # Files published by tool executions remain in a canonical normalized
        # table. A competing link publisher uses BEGIN IMMEDIATE and therefore
        # cannot land between this final check and the deletion commit.
        ids = sorted(requested - shared)
        if ids:
            placeholders = ",".join("?" for _ in ids)
            rows = db.execute(
                "SELECT file_id FROM tool_attachment_links WHERE file_id IN ("
                + placeholders + ")", ids,
            ).fetchall()
            shared.update(row["file_id"] for row in rows)
        ids = sorted(requested - shared)
        if ids:
            # Legacy and new message metadata store file descriptors as JSON.
            # Their parent conversation owns the references. Querying them at
            # delete time also covers pre-migration history non-destructively.
            placeholders = ",".join("?" for _ in ids)
            rows = db.execute(
                "SELECT DISTINCT json_extract(j.value,'$.file_id') AS file_id "
                "FROM messages m JOIN json_each(m.metadata,'$.files') AS j "
                "WHERE m.role='user' AND json_extract(j.value,'$.file_id') IN ("
                + placeholders + ")", ids,
            ).fetchall()
            shared.update(row["file_id"] for row in rows if row["file_id"])
        return shared

    @staticmethod
    def _attached(db, owner, agent_id, resource, ident):
        if agent_id is None:
            return True
        agent = db.execute("SELECT config FROM agents WHERE id=? AND owner=?",
                           (agent_id, owner)).fetchone()
        if agent is None:
            raise KeyError("Agent not found")
        value = json.loads(agent["config"]).get("tool_resources", {}).get(resource, {})
        return isinstance(value, dict) and ident in value.get("file_ids", [])

    @staticmethod
    def _unlink(db, owner, agent_id, resource, ident):
        from .agents import AgentRepository

        AgentRepository._resource_key(resource)
        agent = db.execute("SELECT config FROM agents WHERE id=? AND owner=?",
                           (agent_id, owner)).fetchone()
        if agent is None:
            raise KeyError("Agent not found")
        config = json.loads(agent["config"])
        value = config.get("tool_resources", {}).get(resource)
        if isinstance(value, dict) and isinstance(value.get("file_ids"), list):
            value["file_ids"] = [file_id for file_id in value["file_ids"] if file_id != ident]
            db.execute("UPDATE agents SET config=?,updated_at=? WHERE id=? AND owner=?",
                       (_json(config), _now(), agent_id, owner))

    def _recover_one(self, row):
        original = self._path(row["original_path"])
        quarantine = self._path(row["quarantine_path"])
        if quarantine.parent != original.parent or not quarantine.name.startswith(".delete-"):
            raise OSError("Attachment quarantine path is unsafe")
        with self.database.connect() as db:
            present = db.execute("SELECT 1 FROM attachments WHERE id=?", (row["file_id"],)).fetchone()
        if present:
            if quarantine.exists():
                if original.exists():
                    if not original.samefile(quarantine):
                        raise OSError("Recovery collision: original exists; quarantine retained")
                else:
                    # Hardlink creation is atomic and refuses an existing
                    # destination. os.rename/os.replace may overwrite an
                    # independently recreated file, which is unacceptable.
                    os.link(quarantine, original, follow_symlinks=False)
                    self._sync_directory(original.parent)
                quarantine.unlink()
                self._sync_directory(original.parent)
            elif not original.exists():
                raise OSError("Missing both original and quarantine; preserve recovery evidence")
        elif quarantine.exists():
            quarantine.unlink()
            self._sync_directory(quarantine.parent)
        with self.database.connect() as db:
            db.execute("DELETE FROM attachment_deletions WHERE file_id=?", (row["file_id"],))

    def recover(self):
        """Recover interrupted operations; leave evidence and bytes on any collision."""
        recovered, failed = [], []
        with self._locks.lock("webui/attachment-deletion"):
            with self.database.connect() as db:
                rows = db.execute("SELECT * FROM attachment_deletions ORDER BY created_at,file_id").fetchall()
            for row in rows:
                try:
                    self._recover_one(row)
                    recovered.append(row["file_id"])
                except (OSError, sqlite3.DatabaseError):
                    log.exception("Attachment deletion recovery deferred")
                    failed.append(row["file_id"])
        return {"recoveredFileIds": recovered, "failedFileIds": failed}

    def _prepare(self, ident, owner, agent_id, resource):
        """Persist intent, but do not take filesystem action on an unlocked reference snapshot."""
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            attached = self._attached(db, owner, agent_id, resource, ident)
            if not attached:
                return None, "noop"
            row = db.execute("SELECT * FROM attachments WHERE id=?", (ident,)).fetchone()
            if row is None or row["owner"] != owner:
                if agent_id is not None:
                    self._unlink(db, owner, agent_id, resource, ident)
                    return None, "unlinked"
                if row is not None:
                    raise PermissionError("Attachment owner mismatch")
                return None, "noop"
            if agent_id is not None and ident in self.shared_resource_ids(db, [ident], agent_id, resource):
                self._unlink(db, owner, agent_id, resource, ident)
                return None, "unlinked"
            if db.execute("SELECT 1 FROM attachment_deletions WHERE file_id=?", (ident,)).fetchone():
                raise OSError("A deletion is pending recovery")
            original = self._path(row["path"])
            quarantine = original.with_name(".delete-" + uuid.uuid4().hex)
            db.execute("INSERT INTO attachment_deletions(file_id,owner,original_path,quarantine_path,phase) "
                       "VALUES(?,?,?,?,'prepared')", (ident, owner, str(original), str(quarantine)))
            return dict(row), "prepared"

    def _commit_metadata(self, ident, db):
        db.execute("DELETE FROM attachments WHERE id=?", (ident,))
        self._remove_references(db, [ident])
        db.execute("UPDATE attachment_deletions SET phase='committed' WHERE file_id=?", (ident,))

    @staticmethod
    def _after_commit(ident):
        """Fault-injection seam: SQLite committed but the response is not final."""
        return None

    def _finish(self, ident, owner, agent_id, resource):
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            intent = db.execute("SELECT * FROM attachment_deletions WHERE file_id=?", (ident,)).fetchone()
            if intent is None:
                raise OSError("Missing durable deletion intent")
            row = db.execute("SELECT * FROM attachments WHERE id=?", (ident,)).fetchone()
            if row is None or row["owner"] != owner:
                raise OSError("Attachment metadata changed before deletion")
            if agent_id is not None:
                if not self._attached(db, owner, agent_id, resource, ident):
                    db.execute("DELETE FROM attachment_deletions WHERE file_id=?", (ident,))
                    return "noop"
                if ident in self.shared_resource_ids(db, [ident], agent_id, resource):
                    self._unlink(db, owner, agent_id, resource, ident)
                    db.execute("DELETE FROM attachment_deletions WHERE file_id=?", (ident,))
                    return "unlinked"
            original = self._path(intent["original_path"])
            if row["path"] != intent["original_path"]:
                raise OSError("Attachment path changed before deletion")
            quarantine = self._path(intent["quarantine_path"])
            if quarantine.exists():
                raise OSError("Quarantine collision")
            try:
                os.replace(original, quarantine)
            except FileNotFoundError:
                if original.exists():
                    raise
            self._sync_directory(original.parent)
            self._commit_metadata(ident, db)
        # Database commit is complete when the context manager exits. An
        # interruption below is recovered by inspecting the committed metadata.
        self._after_commit(ident)
        try:
            quarantine.unlink(missing_ok=True)
            self._sync_directory(quarantine.parent)
            with self.database.connect() as db:
                db.execute("DELETE FROM attachment_deletions WHERE file_id=?", (ident,))
        except (OSError, sqlite3.DatabaseError):
            log.exception("Attachment quarantine cleanup deferred to recovery")
        return "deleted"

    def _delete_one(self, ident, owner, agent_id, resource):
        row, decision = self._prepare(ident, owner, agent_id, resource)
        if row is None:
            return decision
        try:
            return self._finish(ident, owner, agent_id, resource)
        except BaseException:
            # Commit acknowledgement can fail *after* metadata was committed.
            # Recover using durable SQLite state, not the exception type.
            try:
                with self.database.connect() as db:
                    intent = db.execute("SELECT * FROM attachment_deletions WHERE file_id=?",
                                        (ident,)).fetchone()
                    remaining = db.execute("SELECT 1 FROM attachments WHERE id=?", (ident,)).fetchone()
                if intent is not None:
                    self._recover_one(intent)
                if remaining is None:
                    return "deleted"
            except (OSError, sqlite3.DatabaseError):
                log.exception("Attachment recovery deferred after an interrupted delete")
            raise

    def delete(self, rows, *, owner=None, agent_id=None, resource=None):
        """Delete IDs using *current* metadata; never trust caller-supplied rows.

        Resource unlink and actual deletion share the same transaction as the
        final reference check; concurrent Agent publishers use BEGIN IMMEDIATE.
        """
        deleted, failed = [], []
        with self._locks.lock("webui/attachment-deletion"):
            for row in rows:
                ident = row if isinstance(row, str) else row["id"]
                principal = owner or (row["owner"] if not isinstance(row, str) else None)
                if not principal:
                    raise ValueError("Owner is required")
                try:
                    result = self._delete_one(ident, principal, agent_id, resource)
                    if result == "deleted":
                        deleted.append(ident)
                except (OSError, PermissionError):
                    log.exception("Attachment deletion failed")
                    failed.append(ident)
        return {"deletedFileIds": deleted, "failedFileIds": failed}
