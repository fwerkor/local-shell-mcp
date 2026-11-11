"""LibreChat personal/Agent memory, persisted in the shared Controller SQLite DB.

Source parity: packages/data-schemas/src/methods/memory.ts,
packages/api/src/agents/memory.ts, schema/memory.ts (e8f3be08).
"""
from __future__ import annotations

import json
import re
import secrets
import sqlite3
import time
from datetime import UTC, datetime
from typing import Any

from .tokenizer import count_tokens

MEMORY_INSTRUCTIONS = ('Persistent memory is available across conversations within the current memory scope. '
                       'Saved memories, if any, are shown below. No entries shown here does not mean memory is '
                       'unavailable. Use memory tools only if provided; claim a memory was saved or deleted only '
                       'after the action is confirmed.')
MEMORY_TOOL_USAGE_GUARD = ('Only use the `set_memory` and `delete_memory` tools when the user explicitly asks you '
                           'to remember, update, or forget something (e.g. "remember that...", "don\'t forget...", '
                           '"forget..."). Never store information merely because the user mentioned it in conversation.')
_VALID_KEY = re.compile(r'^[a-z_]+$')


class MemoryLimitExceeded(OverflowError):
    """Serialized token-limit rejection carrying the source memory artifact."""

    def __init__(self, kind: str, amount: int, total: int, base: int, limit: int):
        self.kind, self.amount, self.total, self.base, self.limit = kind, amount, total, base, limit
        super().__init__(f'Memory storage would exceed limit of {limit} tokens')

    def artifact(self) -> dict:
        return {'memory': {'key': 'system', 'type': 'error', 'value': json.dumps({
            'errorType': self.kind, 'tokenCount': self.amount,
            'totalTokens': self.total, 'tokenLimit': self.limit}, separators=(',', ':')),
            'tokenCount': self.base}}



def _utf16_length(value: str) -> int:
    return len(value.encode('utf-16-le')) // 2


def agent_partition(agent: dict | None) -> str:
    """MemoryScope.agent only; shared personal pool otherwise."""
    if agent and agent.get('memory_scope') == 'agent':
        agent_id = agent.get('id')
        if isinstance(agent_id, str):
            # LibreChat strips decorated ephemeral IDs before partitioning.
            return agent_id.split('____', 1)[0]
    return ''


def memory_config(repo: Any, owner: str) -> dict | None:
    """A configured memory object is the deployment-level opt-in."""
    config = repo.setting(owner, 'webui.memory.config')
    if not isinstance(config, dict):
        endpoints = repo.setting(owner, 'endpoints', {})
        config = endpoints.get('memory') if isinstance(endpoints, dict) else None
    return config if isinstance(config, dict) and config.get('disabled') is not True else None


def memory_enabled(repo: Any, owner: str, *, tools: bool = False) -> bool:
    config = memory_config(repo, owner)
    if config is None or repo.setting(owner, 'user.memories', True) is False:
        return False
    if not tools:
        return True
    endpoints = repo.setting(owner, 'endpoints', {}) or {}
    agents = endpoints.get('agents') if isinstance(endpoints, dict) else {}
    caps = agents.get('capabilities') if isinstance(agents, dict) else []
    return isinstance(caps, list) and 'memory' in caps


def tool_definitions(valid_keys: list[str] | None = None) -> list[dict]:
    suffix = f'Must be one of: {", ".join(valid_keys)}' if valid_keys else None
    key_description = f'The key of the memory value. {suffix}' if suffix else 'The key identifier for this memory'
    deletion_description = f'The key of the memory to delete. {suffix}' if suffix else 'The key identifier of the memory to delete'
    return [
        {'type': 'function', 'function': {
            'name': 'set_memory', 'description': 'Saves important information about the user into memory.',
            'parameters': {'type': 'object', 'properties': {
                'key': {'type': 'string', 'description': key_description},
                'value': {'type': 'string', 'description': 'Value MUST be a complete sentence that fully describes relevant user information.'}},
                'required': ['key', 'value']}}},
        {'type': 'function', 'function': {
            'name': 'delete_memory', 'description': 'Deletes specific memory data about the user using the provided key. For updating existing memories, use the `set_memory` tool instead',
            'parameters': {'type': 'object', 'properties': {
                'key': {'type': 'string', 'description': deletion_description}}, 'required': ['key']}}},
    ]


def format_memory_context(memory: str | None) -> str | None:
    if memory is None:
        return None
    return MEMORY_INSTRUCTIONS + ('\n\n# Existing memory about the user:\n' + memory if memory else '')


class MemoryRepository:
    def __init__(self, database: Any):
        self.database = database

    @staticmethod
    def _from_row(row: Any) -> dict:
        return {'_id': row['id'], 'userId': row['owner'], 'key': row['key'],
                'value': row['value'], 'tokenCount': row['token_count'],
                'updated_at': datetime.fromtimestamp(row['updated_at'] / 1_000_000, tz=UTC).isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
                **({'agentId': row['agent_id']} if row['agent_id'] else {})}

    def list(self, owner: str, agent_id: str | None = None) -> list[dict]:
        with self.database.connect() as db:
            if agent_id is None:
                rows = db.execute('SELECT * FROM webui_memories WHERE owner=? ORDER BY updated_at DESC,id DESC', (owner,)).fetchall()
            else:
                rows = db.execute('SELECT * FROM webui_memories WHERE owner=? AND agent_id=? ORDER BY updated_at,id', (owner, agent_id)).fetchall()
        return [self._from_row(row) for row in rows]

    def formatted(self, owner: str, agent_id: str = '') -> dict:
        try:
            memories = sorted(self.list(owner, agent_id), key=lambda entry: entry['updated_at'])
        except sqlite3.Error:
            return {'withKeys': None, 'withoutKeys': None, 'totalTokens': 0,
                    'tokenCountsByKey': {}, 'readFailed': True}
        counts = {entry['key']: entry['tokenCount'] for entry in memories}
        with_keys, without_keys = [], []
        for i, entry in enumerate(memories, 1):
            stamp = entry['updated_at'][:10]
            token_info = f" [{entry['tokenCount']} tokens]" if entry['tokenCount'] else ''
            with_keys.append(f'{i}. [{stamp}]. ["key": "{entry["key"]}"]{token_info}. ["value": "{entry["value"]}"]')
            without_keys.append(f'{i}. [{stamp}]. {entry["value"]}')
        return {'withKeys': '\n\n'.join(with_keys), 'withoutKeys': '\n\n'.join(without_keys),
                'totalTokens': sum(counts.values()), 'tokenCountsByKey': counts}

    @staticmethod
    def _check(key: str, value: str | None = None, *, char_limit: int = 10000) -> None:
        if not isinstance(key, str) or not _VALID_KEY.fullmatch(key) or _utf16_length(key) > 1000 or key == 'nothing':
            raise ValueError('Invalid memory key')
        if value is not None and (not isinstance(value, str) or not value.strip() or _utf16_length(value) > char_limit):
            raise ValueError('Invalid memory value')

    def write(self, owner: str, key: str, value: str, *, agent_id: str = '',
              char_limit: int = 10000, token_limit: int | None = None, create: bool = False,
              existing_id: str | None = None) -> dict:
        """Serialized limit validation + upsert/rename; rollback on every conflict."""
        self._check(key, value, char_limit=char_limit)
        token_count = count_tokens(value, exact=False)
        with self.database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM webui_memories WHERE owner=? AND agent_id=? AND key=?',
                                  (owner, agent_id, key)).fetchone()
            previous = None
            if existing_id is not None:
                previous = db.execute('SELECT * FROM webui_memories WHERE id=? AND owner=? AND agent_id=?',
                                      (existing_id, owner, agent_id)).fetchone()
                if previous is None:
                    raise KeyError('Memory not found')
            if create and existing:
                raise FileExistsError('Memory with this key already exists')
            if existing_id and existing and existing['id'] != existing_id:
                raise FileExistsError('Memory with this key already exists')
            old = previous if previous is not None else existing
            if token_limit:
                total = db.execute('SELECT coalesce(sum(token_count),0) FROM webui_memories WHERE owner=? AND agent_id=?',
                                   (owner, agent_id)).fetchone()[0]
                base = total - (old['token_count'] if old is not None else 0)
                remaining = token_limit - base
                if remaining <= 0:
                    raise MemoryLimitExceeded('already_exceeded', abs(remaining), base, base, token_limit)
                new_total = base + token_count
                if new_total > token_limit:
                    raise MemoryLimitExceeded('would_exceed', new_total - token_limit,
                                              new_total, base, token_limit)
            identity = old['id'] if old is not None else secrets.token_hex(12)
            now = time.time_ns() // 1000
            if old is not None:
                db.execute('UPDATE webui_memories SET key=?, value=?,token_count=?,updated_at=? WHERE id=?',
                           (key, value, token_count, now, identity))
            else:
                db.execute('INSERT INTO webui_memories(id,owner,agent_id,key,value,token_count,updated_at) VALUES(?,?,?,?,?,?,?)',
                           (identity, owner, agent_id, key, value, token_count, now))
            return self._from_row(db.execute('SELECT * FROM webui_memories WHERE id=?', (identity,)).fetchone())

    def delete(self, owner: str, *, key: str | None = None, entry_id: str | None = None,
               agent_id: str = '') -> bool:
        if key is None and entry_id is None:
            raise ValueError('Memory key or id required')
        with self.database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if entry_id is not None:
                result = db.execute('DELETE FROM webui_memories WHERE owner=? AND agent_id=? AND id=?',
                                    (owner, agent_id, entry_id))
            else:
                result = db.execute('DELETE FROM webui_memories WHERE owner=? AND agent_id=? AND key=?',
                                    (owner, agent_id, key))
            return result.rowcount > 0

    def delete_all(self, owner: str) -> int:
        with self.database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            return db.execute('DELETE FROM webui_memories WHERE owner=?', (owner,)).rowcount


def execute_memory_tool(repo: MemoryRepository, owner: str, agent: dict, name: str,
                        arguments: dict, config: dict) -> tuple[str, dict | None]:
    """ToolNode result and memory artifact; errors never masquerade as writes."""
    key = arguments.get('key')
    if not isinstance(key, str):
        return ('Invalid key', None)
    keys = config.get('validKeys')
    if isinstance(keys, list) and keys and key not in keys:
        return (f'Invalid key "{key}". Must be one of: {", ".join(keys)}', None)
    agent_id = agent_partition(agent)
    try:
        if name == 'delete_memory':
            deleted = repo.delete(owner, key=key, agent_id=agent_id)
            if not deleted:
                return (f'Failed to delete memory for key "{key}"', None)
            return (f'Memory deleted for key "{key}"', {'memory': {'key': key, 'type': 'delete',
                                                                   **({'agentId': agent_id} if agent_id else {})}})
        value = arguments.get('value')
        if not isinstance(value, str):
            return (f'Error setting memory for key "{key}"', None)
        if _utf16_length(key) > 1000:
            return ('Key exceeds maximum length of 1000 characters.', None)
        limit = config.get('charLimit') or 10000
        if _utf16_length(value) > limit:
            return (f'Value exceeds maximum length of {limit} characters.', None)
        record = repo.write(owner, key, value, agent_id=agent_id,
                            char_limit=limit, token_limit=config.get('tokenLimit'))
        tokens = record['tokenCount']
        return (f'Memory set for key "{key}" ({tokens} tokens)', {'memory': {
            'key': key, 'value': value, 'tokenCount': tokens, 'type': 'update',
            **({'agentId': agent_id} if agent_id else {})}})
    except MemoryLimitExceeded as exc:
        if exc.kind == 'already_exceeded':
            return ('Memory storage exceeded. Cannot save new memories.', exc.artifact())
        return ('Memory storage would exceed limit. Cannot save this memory.', exc.artifact())
    except OverflowError:
        return ('Memory storage would exceed limit. Cannot save this memory.', None)
    except (ValueError, sqlite3.IntegrityError, KeyError):
        return (f'Failed to set memory for key "{key}"' if name == 'set_memory' else f'Failed to delete memory for key "{key}"', None)
    except Exception:
        return (f'Error setting memory for key "{key}"' if name == 'set_memory' else f'Error deleting memory for key "{key}"', None)
