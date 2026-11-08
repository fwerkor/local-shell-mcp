"""LibreChat-compatible agent authoring and revision tracking in SQLite.

Single-user access remains keyed to the authenticated LSM principal; no
MongoDB, autonomous Node service, or independent authorization database.
"""

from __future__ import annotations

import copy
import json
import secrets
from typing import Any

from .agent_validation import (
    clean_agent_config,
    replace_agent_references,
    sanitize_model_parameters,
)
from .storage import _cursor_decode, _cursor_encode, _json, _now


class AgentRepository:
    def __init__(self, database: Any):
        self.database = database

    @staticmethod
    def _clean(payload: dict, *, create: bool = False) -> dict:
        payload = copy.deepcopy(payload)
        resources = payload.get("tool_resources")
        if isinstance(resources, dict):
            for key in ("image_edit", "execute_code", "file_search", "context", "ocr"):
                resource = resources.get(key)
                if not isinstance(resource, dict):
                    continue
                ids = list(resource["file_ids"]) if isinstance(resource.get("file_ids"), list) else []
                if isinstance(resource.get("files"), list):
                    for file in resource["files"]:
                        if isinstance(file, dict) and isinstance(file.get("file_id"), str) and file["file_id"] not in ids:
                            ids.append(file["file_id"])
                if ids or isinstance(resource.get("file_ids"), list):
                    resource["file_ids"] = ids
                resource.pop("files", None)
        return clean_agent_config(payload, create=create)

    @staticmethod
    def _references(db: Any, owner: str, values: dict, own_id: str) -> None:
        for resource in values.get("tool_resources", {}).values():
            if "file_ids" in resource:
                resource["file_ids"] = [identity for identity in resource["file_ids"] if db.execute(
                    "SELECT 1 FROM attachments WHERE id=? AND owner=?", (identity, owner),
                ).fetchone()]
        references = set()
        for edge in values.get("edges", []):
            for key in ("from", "to"):
                references.update(edge[key] if isinstance(edge[key], list) else [edge[key]])
        subagents = values.get("subagents", {})
        if subagents.get("enabled") is True:
            references.update(subagents.get("agent_ids", []))
            for graph in subagents.get("graphs", []):
                references.update(graph["agent_ids"])
        for identity in sorted(references - {own_id}):
            row = db.execute("SELECT owner FROM agents WHERE id=?", (identity,)).fetchone()
            if row is None:
                raise ValueError("Referenced Agent does not exist")
            if row["owner"] != owner:
                raise PermissionError("Referenced Agent is not accessible")

    @staticmethod
    def _from_row(row: Any) -> dict:
        value = json.loads(row["config"])
        value.update({
            "id": row["id"], "_id": row["id"], "author": row["owner"],
            "name": row["name"], "description": row["description"],
            "created_at": int(row["created_at"] / 1_000_000),
            "createdAt": int(row["created_at"] / 1_000_000),
            "updatedAt": int(row["updated_at"] / 1_000_000),
            "version": int(value.get("_version", 1)),
            "isEditable": True,
        })
        value.pop("_version", None)
        return value

    def create(self, owner: str, body: dict) -> dict:
        values = self._clean(body, create=True)
        agent_id = "agent_" + secrets.token_hex(12)
        now = _now()
        values = replace_agent_references(values, "", agent_id)
        values.setdefault("model_parameters", {})
        values.setdefault("edges", [])
        values.setdefault("tool_resources", {})
        values.setdefault("conversation_starters", [])
        values.setdefault("category", "general")
        values["category"] = values["category"].strip()
        values["model_parameters"] = sanitize_model_parameters(values["model_parameters"])
        values["_version"] = 1
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._references(db, owner, values, agent_id)
            db.execute(
                "INSERT INTO agents(id,owner,name,description,config,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (agent_id, owner, str(values.get("name") or ""),
                 str(values.get("description") or ""), _json(values), now, now),
            )
            db.execute("INSERT INTO agent_versions(agent_id,version,snapshot,created_at) VALUES(?,?,?,?)",
                       (agent_id, 1, _json(values), now))
            return self._from_row(db.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone())

    def get(self, owner: str, agent_id: str) -> dict | None:
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM agents WHERE owner=? AND id=?", (owner, agent_id)).fetchone()
            return self._from_row(row) if row else None

    def list(self, owner: str, *, limit: int = 25, cursor: str | None = None,
             category: str | None = None, search: str | None = None) -> dict:
        limit = max(1, min(int(limit), 100))
        filters = ["owner=?"]
        params: list[Any] = [owner]
        if category:
            filters.append("json_extract(config,'$.category')=?")
            params.append(category)
        if search:
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            filters.append("(name LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\')")
            params.extend(["%" + escaped + "%"] * 2)
        if cursor:
            stamp, ident = _cursor_decode(cursor)
            filters.append("(updated_at<? OR (updated_at=? AND id<?))")
            params.extend([stamp, stamp, ident])
        with self.database.connect() as db:
            rows = db.execute("SELECT * FROM agents WHERE " + " AND ".join(filters)
                              + " ORDER BY updated_at DESC,id DESC LIMIT ?", (*params, limit + 1)).fetchall()
        values = [self._from_row(row) for row in rows[:limit]]
        has_more = len(rows) > limit
        return {
            "object": "list", "data": values,
            "first_id": values[0]["id"] if values else "",
            "last_id": values[-1]["id"] if values else "",
            "has_more": has_more,
            **({"after": _cursor_encode(rows[limit - 1]["updated_at"], rows[limit - 1]["id"])}
               if has_more else {}),
        }

    def update(self, owner: str, agent_id: str, changes: dict) -> dict | None:
        values = self._clean(changes)
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM agents WHERE owner=? AND id=?", (owner, agent_id)).fetchone()
            if row is None:
                return None
            values = replace_agent_references(values, "", agent_id)
            self._references(db, owner, values, agent_id)
            if "model_parameters" in values:
                values["model_parameters"] = sanitize_model_parameters(values["model_parameters"])
            if "category" in values:
                values["category"] = values["category"].strip()
            config = json.loads(row["config"])
            config.update(values)
            version = int(config.get("_version", 1)) + 1
            config["_version"] = version
            now = _now()
            db.execute("UPDATE agents SET name=?,description=?,config=?,updated_at=? WHERE id=? AND owner=?",
                       (str(config.get("name") or ""), str(config.get("description") or ""),
                        _json(config), now, agent_id, owner))
            db.execute("INSERT INTO agent_versions(agent_id,version,snapshot,created_at) VALUES(?,?,?,?)",
                       (agent_id, version, _json(config), now))
            return self._from_row(db.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone())

    def versions(self, owner: str, agent_id: str) -> list[dict] | None:
        with self.database.connect() as db:
            row = db.execute("SELECT 1 FROM agents WHERE owner=? AND id=?", (owner, agent_id)).fetchone()
            if row is None:
                return None
            versions = db.execute(
                "SELECT snapshot FROM agent_versions WHERE agent_id=? ORDER BY version DESC", (agent_id,)
            ).fetchall()
        snapshots = []
        for version in versions:
            payload = json.loads(version[0])
            payload["id"] = agent_id
            payload["version"] = payload.pop("_version", 1)
            snapshots.append(payload)
        return snapshots

    def revert(self, owner: str, agent_id: str, version_index: int) -> dict | None:
        snapshots = self.versions(owner, agent_id)
        if snapshots is None:
            return None
        if not 0 <= version_index < len(snapshots):
            raise ValueError("Unknown agent version")
        return self.update(owner, agent_id, snapshots[version_index])

    def delete(self, owner: str, agent_id: str) -> bool:
        with self.database.connect() as db:
            return db.execute("DELETE FROM agents WHERE id=? AND owner=?", (agent_id, owner)).rowcount > 0

    def duplicate(self, owner: str, agent_id: str) -> dict | None:
        current = self.get(owner, agent_id)
        if current is None:
            return None
        values = self._clean(current)
        values = replace_agent_references(values, agent_id, "")
        values["name"] = (values.get("name") or "Agent") + " (copy)"
        duplicate = self.create(owner, values)
        return {"agent": duplicate, "actions": []}
