"""LibreChat-compatible agent authoring and revision tracking in SQLite.

Single-user access remains keyed to the authenticated LSM principal; no
MongoDB, autonomous Node service, or independent authorization database.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

from .storage import _cursor_decode, _cursor_encode, _json, _now

# Explicit allowlist prevents an arbitrary browser object from being persisted
# as executable configuration or leaking API credentials into the database.
_AGENT_FIELDS = frozenset({
    "name", "description", "avatar", "instructions", "additional_instructions",
    "provider", "model", "model_parameters", "tools", "tool_kwargs", "tool_resources",
    "file_ids", "agent_ids", "edges", "end_after_tools", "hide_sequential_outputs",
    "stateful_code_sessions", "stateful_code_environment", "code_environment_id",
    "code_workspace_id", "repositoryInstructions", "git_identity", "artifacts",
    "recursion_limit", "category", "support_contact", "owner_contact",
    "tool_options", "actions", "skills", "skills_enabled", "skill_authoring_enabled",
    "skills_scope", "subagents", "memory_scope", "conversation_starters",
})


class AgentRepository:
    def __init__(self, database: Any):
        self.database = database

    @staticmethod
    def _clean(payload: dict) -> dict:
        values = {key: value for key, value in payload.items() if key in _AGENT_FIELDS}
        if "name" in values and values["name"] is not None:
            values["name"] = str(values["name"]).strip()[:200]
        if "description" in values and values["description"] is not None:
            values["description"] = str(values["description"])[:3000]
        if "instructions" in values and values["instructions"] is not None:
            values["instructions"] = str(values["instructions"])[:80000]
        if "tools" in values and not isinstance(values["tools"], list):
            raise ValueError("Agent tools must be an array")
        if "model_parameters" in values and not isinstance(values["model_parameters"], dict):
            raise ValueError("Model parameters must be an object")
        return values

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
        values = self._clean(body)
        if not values.get("provider") or not isinstance(values.get("provider"), str):
            raise ValueError("Agent provider is required")
        agent_id = "agent_" + secrets.token_hex(12)
        now = _now()
        values.setdefault("model", None)
        values.setdefault("model_parameters", {})
        values["_version"] = 1
        with self.database.connect() as db:
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
        values["name"] = (values.get("name") or "Agent") + " (copy)"
        duplicate = self.create(owner, values)
        return {"agent": duplicate, "actions": []}
