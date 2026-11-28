"""Conversation, project, agent and message persistence in the controller DB.

The repository speaks in LibreChat's camelCase identifiers and preserves
unknown non-private fields to avoid destroying information during migrations.
"""

from __future__ import annotations

import base64
import json
import secrets
import threading
from collections import OrderedDict
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..sqlite_store import SQLiteDatabase


def _stamp(value: int | float) -> str:
    return datetime.fromtimestamp(value, tz=UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _now() -> int:
    return time.time_ns() // 1000


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode(value: str | bytes) -> dict:
    parsed = json.loads(value)
    return parsed if isinstance(parsed, dict) else {}


def _cursor_encode(timestamp: int, identifier: str) -> str:
    return base64.urlsafe_b64encode(_json({"stamp": timestamp, "id": identifier}).encode()).decode()


def _cursor_decode(cursor: str | None) -> tuple[int, str] | None:
    if cursor is None:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        return int(data["stamp"]), str(data["id"])
    except (ValueError, KeyError, UnicodeDecodeError, TypeError) as exc:
        raise ValueError("Invalid pagination cursor") from exc


# Revision-keyed and bounded: warm history opens do not parse old tool results
# again, and no message text/content is held by the server cache.
_HISTORY_METRICS_LIMIT = 8192
_history_metrics_cache: OrderedDict[tuple[str, str, int], dict] = OrderedDict()
_history_metrics_lock = threading.Lock()


class WorkspaceRepository:
    def __init__(self, database: SQLiteDatabase):
        self.database = database

    @staticmethod
    def _convo(row: Any) -> dict:
        data = _decode(row["metadata"])
        data.update(
            conversationId=row["id"], title=row["title"],
            projectId=row["project_id"], chatProjectId=row["project_id"], agent_id=row["agent_id"],
            model=row["model"], endpoint=row["endpoint"],
            isArchived=bool(row["archived"]), pinned=bool(row["pinned"]),
            createdAt=_stamp(row["created_at"] / 1_000_000),
            updatedAt=_stamp(row["updated_at"] / 1_000_000),
        )
        # Retained convoSchema permits an absent Agent but rejects null.
        if row["agent_id"] is None:
            data.pop("agent_id", None)
        return data

    @staticmethod
    def _project(row: Any) -> dict:
        data = _decode(row["metadata"])
        data.update(
            _id=row["id"], id=row["id"], user=row["owner"],
            name=row["name"], description=row["description"],
            createdAt=_stamp(row["created_at"] / 1_000_000),
            updatedAt=_stamp(row["updated_at"] / 1_000_000),
        )
        return data

    @staticmethod
    def _message(row: Any) -> dict:
        data = _decode(row["metadata"])
        data.update(
            messageId=row["id"], conversationId=row["conversation_id"],
            parentMessageId=row["parent_id"], role=row["role"],
            text=row["text"],
            createdAt=_stamp(row["created_at"] / 1_000_000),
            updatedAt=_stamp(row["updated_at"] / 1_000_000),
        )
        content = json.loads(row["content"])
        if isinstance(content, (dict, list)) and content:
            data["content"] = content
        return data

    def create_conversation(self, owner: str, payload: dict) -> dict:
        conversation_id = str(payload.get("conversationId") or uuid.uuid4())
        title = str(payload.get("title") or "New chat")[:500]
        metadata = {key: value for key, value in payload.items()
                    if key not in {"conversationId", "title", "projectId", "agent_id", "model", "endpoint", "isArchived", "pinned"}}
        now = _now()
        with self.database.connect() as db:
            existing = db.execute("SELECT 1 FROM conversations WHERE id=?", (conversation_id,)).fetchone()
            if existing:
                raise ValueError("Conversation already exists")
            db.execute(
                "INSERT INTO conversations(id,owner,title,project_id,agent_id,model,endpoint,archived,pinned,metadata,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (conversation_id, owner, title, payload.get("projectId"), payload.get("agent_id"),
                 payload.get("model"), payload.get("endpoint"), int(bool(payload.get("isArchived"))),
                 int(bool(payload.get("pinned"))), _json(metadata), now, now),
            )
            return self._convo(db.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone())

    def conversation(self, owner: str, conversation_id: str) -> dict | None:
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM conversations WHERE id=? AND owner=?", (conversation_id, owner)).fetchone()
            if row is None:
                return None
            result = self._convo(row)
            usage = db.execute(
                'SELECT * FROM webui_conversation_usage WHERE conversation_id=?',
                (conversation_id,),
            ).fetchone()
            result['recordedUsage'] = ({
                'inputTokens': usage['input_tokens'],
                'outputTokens': usage['output_tokens'],
                'cacheReadTokens': usage['cache_read_tokens'],
                'cacheKnownInputTokens': usage['cache_known_input_tokens'],
                'calls': usage['calls'],
            } if usage else None)
            return result

    def conversations(self, owner: str, *, archived: bool = False, pinned: bool = False,
                      project_id: str | None = None, search: str | None = None,
                      tags: list[str] | None = None,
                      cursor: str | None = None, limit: int = 25) -> dict:
        limit = max(1, min(int(limit), 100))
        filters = ["owner=?", "archived=?"]
        params: list[Any] = [owner, int(archived)]
        if pinned:
            filters.append("pinned=1")
        if project_id == "unassigned":
            filters.append("project_id IS NULL")
        elif project_id:
            filters.append("project_id=?")
            params.append(project_id)
        if tags:
            # Bookmark filtering must happen before cursor pagination. JSON
            # array membership avoids substring/LIKE wildcard collisions.
            # Multiple selected bookmarks are an OR filter, matching the
            # conversation sidebar's existing filter semantics.
            placeholders = ",".join("?" for _ in tags)
            filters.append("EXISTS (SELECT 1 FROM json_each(conversations.metadata, '$.tags') "
                           f"WHERE json_each.value IN ({placeholders}))")
            params.extend(tags)
        if search:
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            filters.append("(title LIKE ? ESCAPE '\\' OR id IN "
                           "(SELECT conversation_id FROM messages WHERE text LIKE ? ESCAPE '\\'))")
            params += [f"%{escaped}%", f"%{escaped}%"]
        last = _cursor_decode(cursor)
        if last:
            filters.append("(updated_at < ? OR (updated_at = ? AND id < ?))")
            params.extend([last[0], last[0], last[1]])
        sql = "SELECT * FROM conversations WHERE " + " AND ".join(filters) + " ORDER BY updated_at DESC, id DESC LIMIT ?"
        with self.database.connect() as db:
            rows = db.execute(sql, [*params, limit + 1]).fetchall()
        has_next = len(rows) > limit
        result = rows[:limit]
        return {
            "conversations": [self._convo(r) for r in result],
            "nextCursor": _cursor_encode(result[-1]["updated_at"], result[-1]["id"]) if has_next and result else None,
        }

    def update_conversation(self, owner: str, conversation_id: str, changes: dict) -> dict | None:
        allowed = {
            "title": "title", "projectId": "project_id", "agent_id": "agent_id",
            "model": "model", "endpoint": "endpoint",
            "isArchived": "archived", "pinned": "pinned",
        }
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM conversations WHERE id=? AND owner=?", (conversation_id, owner)).fetchone()
            if row is None:
                return None
            updates = {allowed[k]: int(bool(v)) if k in {"isArchived", "pinned"} else v
                       for k, v in changes.items() if k in allowed}
            metadata = _decode(row["metadata"])
            metadata.update({key: value for key, value in changes.items() if key not in allowed and key != "conversationId"})
            updates["metadata"] = _json(metadata)
            updates["updated_at"] = _now()
            values = list(updates.values())
            db.execute("UPDATE conversations SET " + ",".join(f"{name}=?" for name in updates)
                       + " WHERE id=? AND owner=?", [*values, conversation_id, owner])
            return self._convo(db.execute("SELECT * FROM conversations WHERE id=? AND owner=?",
                                          (conversation_id, owner)).fetchone())

    def delete_conversation(self, owner: str, conversation_id: str) -> bool:
        with self.database.connect() as db:
            result = db.execute("DELETE FROM conversations WHERE owner=? AND id=?", (owner, conversation_id))
            return result.rowcount > 0

    def add_message(self, owner: str, conversation_id: str, payload: dict) -> dict:
        message_id = str(payload.get("messageId") or uuid.uuid4())
        metadata = {key: value for key, value in payload.items()
                    if key not in {"messageId", "conversationId", "parentMessageId", "role", "text", "content"}}
        now = _now()
        with self.database.connect() as db:
            if not db.execute("SELECT 1 FROM conversations WHERE id=? AND owner=?", (conversation_id, owner)).fetchone():
                raise KeyError("Conversation not found")
            db.execute(
                "INSERT INTO messages(id,conversation_id,parent_id,role,text,content,metadata,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (message_id, conversation_id, payload.get("parentMessageId"), str(payload.get("role", "user")),
                 str(payload.get("text") or ""), _json(payload.get("content") or {}), _json(metadata), now, now),
            )
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id))
            return self._message(db.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone())

    def delete_message_turn(self, owner: str, conversation_id: str, message_id: str) -> list[str]:
        """Remove one prompt and its replies, splicing all surviving branches."""
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM conversations WHERE id=? AND owner=?",
                              (conversation_id, owner)).fetchone():
                raise KeyError("Conversation not found")
            rows = db.execute("SELECT id,parent_id,role,text,content,metadata FROM messages WHERE conversation_id=?",
                              (conversation_id,)).fetchall()
            by_id = {row["id"]: row for row in rows}
            selected = by_id.get(message_id)
            if selected is None:
                raise KeyError("Message not found")
            prompt = selected if selected["role"] == "user" else by_id.get(selected["parent_id"])
            if prompt is None or prompt["role"] != "user":
                raise ValueError("Message is not part of a user turn")
            if db.execute("SELECT 1 FROM runs WHERE conversation_id=? AND status IN ('running','requires_action')",
                          (conversation_id,)).fetchone():
                raise ValueError("Cannot delete a turn during a generation")
            removed = {prompt["id"], *(row["id"] for row in rows
                        if row["parent_id"] == prompt["id"] and row["role"] == "assistant")}
            children: dict[str, list[str]] = {}
            for row in rows:
                children.setdefault(row["parent_id"], []).append(row["id"])
            affected = set(removed)
            pending = list(removed)
            while pending:
                for child in children.get(pending.pop(), []):
                    if child not in affected:
                        affected.add(child)
                        pending.append(child)

            # Keep detached job ownership and audit state intact. Deleted runs
            # must no longer be offered for reconnect/replay in the chat UI.
            for ident in removed:
                db.execute("UPDATE runs SET state=json_set(state,'$.historyDeleted',json('true')) "
                           "WHERE conversation_id=? AND (json_extract(state,'$.responseMessageId')=? "
                           "OR (json_extract(state,'$.userMessageId')=? "
                           "AND coalesce(json_extract(state,'$.manualCompaction'),0)=0))",
                           (conversation_id, ident, ident))
                db.execute("UPDATE messages SET parent_id=? WHERE conversation_id=? AND parent_id=?",
                           (prompt["parent_id"], conversation_id, ident))
                db.execute("DELETE FROM messages WHERE conversation_id=? AND id=?", (conversation_id, ident))

            # A descendant checkpoint may summarize the removed turn. Drop it
            # and reconstruct history from the surviving canonical model steps.
            for ident in affected - removed:
                row = by_id[ident]
                content = json.loads(row["content"])
                metadata = _decode(row["metadata"])
                filtered = ([part for part in content if not isinstance(part, dict)
                             or part.get("type") != "summary"] if isinstance(content, list) else content)
                if filtered != content or "summary" in metadata:
                    for key in ("summary", "summaryTokenCount", "tokenCount"):
                        metadata.pop(key, None)
                    db.execute("UPDATE messages SET content=?,metadata=? WHERE id=?",
                               (_json(filtered), _json(metadata), ident))
                    from .compaction import find_checkpoint_summary_part

                    checkpoint = find_checkpoint_summary_part(content)
                    for run in db.execute(
                        "SELECT id,state FROM runs WHERE conversation_id=? "
                        "AND json_extract(state,'$.responseMessageId')=?",
                        (conversation_id, ident),
                    ).fetchall():
                        state = json.loads(run["state"])
                        # A live checkpoint stores canonical steps from AFTER
                        # its retained tail. Restore just this turn's suffix,
                        # never earlier user turns that the deletion invalidated.
                        if checkpoint and type(state.get("postCompactionHistoryStart")) is int:
                            tail = checkpoint.get("retainedTail")
                            if isinstance(tail, list):
                                current = []
                                for message in tail:
                                    if not isinstance(message, dict):
                                        continue
                                    role = message.get("role")
                                    if role == "user" and message.get("source") != "steer":
                                        current = []
                                    elif role in {"assistant", "tool"} or (
                                        role == "user" and message.get("source") == "steer"
                                    ):
                                        current.append(message)
                                steps = state.get("modelSteps")
                                if isinstance(steps, list):
                                    restored = [*current, *steps]
                                    # Earlier summarized assistant prose can
                                    # still be recovered from the visible text.
                                    visible = row["text"] or ""
                                    replayed = "".join(
                                        message["content"] for message in restored
                                        if isinstance(message, dict) and message.get("role") == "assistant"
                                        and isinstance(message.get("content"), str)
                                    )
                                    if visible and visible.endswith(replayed) and len(visible) > len(replayed):
                                        restored.insert(0, {"role": "assistant",
                                                            "content": visible[:len(visible)-len(replayed)]})
                                    state["modelSteps"] = restored
                        state.pop("summaryCheckpoint", None)
                        db.execute("UPDATE runs SET state=? WHERE id=?", (_json(state), run["id"]))
            return sorted(removed)

    def messages(self, owner: str, conversation_id: str, *, limit: int = 100, cursor: str | None = None) -> dict:
        limit = max(1, min(int(limit), 200))
        with self.database.connect() as db:
            if not db.execute("SELECT 1 FROM conversations WHERE id=? AND owner=?", (conversation_id, owner)).fetchone():
                raise KeyError("Conversation not found")
            params: list[Any] = [conversation_id]
            where = "conversation_id=?"
            if cursor:
                previous = _cursor_decode(cursor)
                where += " AND (created_at < ? OR (created_at=? AND id < ?))"
                params.extend([previous[0], previous[0], previous[1]])
            rows = db.execute(f"SELECT * FROM messages WHERE {where} ORDER BY created_at DESC,id DESC LIMIT ?",
                              [*params, limit + 1]).fetchall()
            has_next = len(rows) > limit
            page = rows[:limit]
            messages = self._serialize_message_rows(db, owner, list(reversed(page)))
        return {"messages": messages,
                "nextCursor": _cursor_encode(page[-1]["created_at"], page[-1]["id"]) if has_next else None}

    def _serialize_message_rows(self, db, owner: str, rows: list) -> list[dict]:
        from .tool_attachments import response_attachments, visible_response_attachments

        current = response_attachments(
            db, owner, [row["id"] for row in rows if row["role"] == "assistant"])
        messages = []
        for row in rows:
            message = self._message(row)
            if row["role"] == "assistant" and (
                row["id"] in current or "attachments" in message
            ):
                message["attachments"] = visible_response_attachments(
                    current.get(row["id"], []), message.get("attachments"))
            messages.append(message)
        return messages

    @staticmethod
    def _history_metrics(text: str, content: str) -> dict:
        """Mirror the UI's character-based context estimate without transferring bodies."""
        def length(value):
            return len(value.encode("utf-16-le", errors="surrogatepass")) // 2

        parts = json.loads(content)
        chars = length(text)
        tool_chars = result_chars = 0
        if isinstance(parts, list) and parts:
            chars = 0
            for part in parts:
                if not isinstance(part, dict) or part.get("type") in ("think", "error"):
                    continue
                if part.get("type") == "tool_call":
                    call = part.get("tool_call")
                    if not isinstance(call, dict):
                        continue
                    name, args, output = (call.get(key) for key in ("name", "args", "output"))
                    name_chars = length(name) if isinstance(name, str) else 0
                    args_chars = (length(args) if isinstance(args, str) else
                                  length(json.dumps(args, ensure_ascii=False, separators=(",", ":")))
                                  if args is not None else 0)
                    output_chars = length(output) if isinstance(output, str) else 0
                    chars += name_chars + args_chars + output_chars
                    tool_chars += name_chars + args_chars + output_chars
                    if "args" in call and args is None:
                        tool_chars += 4
                    result_chars += output_chars
                else:
                    value = part.get("text")
                    if isinstance(value, dict):
                        value = value.get("value")
                    if isinstance(value, str):
                        chars += length(value)
        return {"chars": chars, "toolChars": tool_chars, "resultChars": result_chars}

    def compact_message_history(self, owner: str, conversation_id: str, recent: int = 30) -> list[dict]:
        """Keep branch topology and usage metadata, defer historical assistant bodies.

        The latest rows remain complete for the ordinary append/resume paths.
        The client hydrates visible turns and their parents before offering
        editing or regeneration. No history is modified on disk.
        """
        recent = max(1, min(int(recent), 100))
        with self.database.connect() as db:
            # Keep the index, revisions and usage metrics in one read snapshot.
            db.execute("BEGIN")
            if not db.execute("SELECT 1 FROM conversations WHERE id=? AND owner=?",
                              (conversation_id, owner)).fetchone():
                raise KeyError("Conversation not found")
            rows = db.execute("""
                WITH recent AS (
                    SELECT id FROM messages WHERE conversation_id=?
                    ORDER BY created_at DESC,id DESC LIMIT ?
                )
                SELECT m.id,m.conversation_id,m.parent_id,m.role,m.metadata,
                       m.created_at,m.updated_at,
                       CASE WHEN r.id IS NULL
                            THEN substr(m.text,1,512) ELSE m.text END AS text,
                       CASE WHEN r.id IS NULL
                            THEN '{}' ELSE m.content END AS content,
                       (r.id IS NULL) AS history_stub
                FROM messages m LEFT JOIN recent r ON r.id=m.id
                WHERE m.conversation_id=? ORDER BY m.created_at,m.id
            """, (conversation_id, recent, conversation_id)).fetchall()
            full_rows = [row for row in rows if not row["history_stub"]]
            full = {message["messageId"]: message
                    for message in self._serialize_message_rows(db, owner, full_rows)}
            # Read only cache misses. Old body payloads are streamed and
            # released one at a time; the bounded cache retains just counts.
            metrics = {}
            missing = []
            database_key = str(self.database.path)
            with _history_metrics_lock:
                for row in rows:
                    if not row["history_stub"]:
                        continue
                    key = (database_key, row["id"], row["updated_at"])
                    cached = _history_metrics_cache.get(key)
                    if cached is None:
                        missing.append(row["id"])
                    else:
                        metrics[row["id"]] = cached
                        _history_metrics_cache.move_to_end(key)
            for start in range(0, len(missing), 100):
                ids = missing[start:start + 100]
                placeholders = ",".join("?" for _ in ids)
                for old in db.execute(
                    f"SELECT id,text,content,updated_at FROM messages "
                    f"WHERE conversation_id=? AND id IN ({placeholders})",
                    [conversation_id, *ids],
                ):
                    counts = self._history_metrics(old["text"], old["content"])
                    metrics[old["id"]] = counts
                    key = (database_key, old["id"], old["updated_at"])
                    with _history_metrics_lock:
                        _history_metrics_cache[key] = counts
                        _history_metrics_cache.move_to_end(key)
                        while len(_history_metrics_cache) > _HISTORY_METRICS_LIMIT:
                            _history_metrics_cache.popitem(last=False)
            result = []
            for row in rows:
                if row["history_stub"]:
                    message = self._message(row)
                    # Attachments are reconciled only when the complete body is read.
                    message.pop("attachments", None)
                    message["historyStub"] = True
                    message["historyMetrics"] = metrics[row["id"]]
                    result.append(message)
                else:
                    result.append(full[row["id"]])
            return result

    def message_bodies(self, owner: str, conversation_id: str, ids: list[str]) -> list[dict]:
        """Hydrate selected bodies, scoped to the owning conversation."""
        if not ids or len(ids) > 100:
            raise ValueError("Expected 1 to 100 message ids")
        with self.database.connect() as db:
            if not db.execute("SELECT 1 FROM conversations WHERE id=? AND owner=?",
                              (conversation_id, owner)).fetchone():
                raise KeyError("Conversation not found")
            placeholders = ",".join("?" for _ in ids)
            rows = db.execute(
                f"SELECT * FROM messages WHERE conversation_id=? AND id IN ({placeholders}) "
                "ORDER BY created_at,id", [conversation_id, *ids]).fetchall()
            return self._serialize_message_rows(db, owner, rows)

    def search_messages(self, owner: str, query: str, limit: int = 30) -> list[dict]:
        if not query.strip():
            return []
        with self.database.connect() as db:
            if len(query.strip()) < 3 or not getattr(self.database, "fts_enabled", False):
                rows = db.execute(
                    "SELECT m.* FROM messages m JOIN conversations c ON c.id=m.conversation_id "
                    "WHERE c.owner=? AND m.text LIKE ? ORDER BY m.created_at DESC LIMIT ?",
                    (owner, f"%{query}%", min(limit, 100)),
                ).fetchall()
            else:
                # MATCH can interpret operators; quote the literal user search term.
                escaped = '"' + query.replace('"', '""') + '"'
                rows = db.execute(
                    "SELECT m.* FROM message_search s JOIN messages m ON m.id=s.message_id "
                    "JOIN conversations c ON c.id=m.conversation_id "
                    "WHERE c.owner=? AND s.text MATCH ? LIMIT ?",
                    (owner, escaped, min(limit, 100)),
                ).fetchall()
        return [self._message(row) for row in rows]

    def create_project(self, owner: str, name: str, description: str = "", **metadata: Any) -> dict:
        name = name.strip()[:160]
        if not name:
            raise ValueError("Project name is required")
        project_id = secrets.token_hex(12)
        now = _now()
        with self.database.connect() as db:
            db.execute("INSERT INTO projects(id,owner,name,description,metadata,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                       (project_id, owner, name, description[:4000], _json(metadata), now, now))
            return self._project(db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())

    def project(self, owner: str, project_id: str) -> dict | None:
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM projects WHERE owner=? AND id=?", (owner, project_id)).fetchone()
            return self._project(row) if row else None

    def projects(self, owner: str, *, limit: int = 30, search: str | None = None) -> dict:
        with self.database.connect() as db:
            if search:
                rows = db.execute("SELECT * FROM projects WHERE owner=? AND (name LIKE ? OR description LIKE ?) "
                                  "ORDER BY updated_at DESC LIMIT ?", (owner, f"%{search}%", f"%{search}%", min(limit, 100))).fetchall()
            else:
                rows = db.execute("SELECT * FROM projects WHERE owner=? ORDER BY updated_at DESC LIMIT ?",
                                  (owner, min(limit, 100))).fetchall()
        return {"projects": [self._project(row) for row in rows], "nextCursor": None}

    def update_project(self, owner: str, project_id: str, payload: dict) -> dict | None:
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM projects WHERE owner=? AND id=?", (owner, project_id)).fetchone()
            if not row:
                return None
            metadata = _decode(row["metadata"])
            metadata.update({key: value for key, value in payload.items() if key not in {"name", "description"}})
            name = str(payload.get("name", row["name"])).strip()[:160]
            if not name:
                raise ValueError("Project name is required")
            db.execute("UPDATE projects SET name=?,description=?,metadata=?,updated_at=? WHERE id=? AND owner=?",
                       (name, str(payload.get("description", row["description"]))[:4000], _json(metadata), _now(), project_id, owner))
            return self._project(db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())

    def delete_project(self, owner: str, project_id: str) -> bool:
        with self.database.connect() as db:
            return db.execute("DELETE FROM projects WHERE id=? AND owner=?", (project_id, owner)).rowcount > 0

    def save_setting(self, owner: str, key: str, value: Any) -> None:
        with self.database.connect() as db:
            db.execute("INSERT INTO settings(owner,key,value) VALUES(?,?,?) ON CONFLICT(owner,key) "
                       "DO UPDATE SET value=excluded.value", (owner, key, _json(value)))

    def merge_setting(self, owner: str, key: str, changes: dict, *, max_bytes: int) -> dict:
        """Merge a preference patch without losing concurrent updates to other keys."""
        with self.database.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM settings WHERE owner=? AND key=?",
                             (owner, key)).fetchone()
            current = json.loads(row[0]) if row else {}
            merged = {**(current if isinstance(current, dict) else {}), **changes}
            encoded = _json(merged)
            if len(encoded.encode("utf-8")) > max_bytes:
                raise ValueError("Preferences are too large")
            db.execute("INSERT INTO settings(owner,key,value) VALUES(?,?,?) ON CONFLICT(owner,key) "
                       "DO UPDATE SET value=excluded.value", (owner, key, encoded))
            return merged

    def setting(self, owner: str, key: str, default: Any = None) -> Any:
        with self.database.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE owner=? AND key=?", (owner, key)).fetchone()
            return json.loads(row[0]) if row else default
