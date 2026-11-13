"""Opt-in automatic MemoryRun from pinned LibreChat memory.ts and client.js.

Uses the existing Controller model transport and SQLite memory tools, rather
than creating an independent runtime, database, or long-lived background owner.
"""
from __future__ import annotations

import logging
import time

from .agents import AgentRepository
from .memory import (
    MemoryRepository,
    agent_partition,
    execute_memory_tool,
    memory_config,
    memory_enabled,
    tool_definitions,
)
from .memory_protection import configured_filters, inspect_memory_content
from .providers import ModelToolCall, provider_config
from .storage import WorkspaceRepository
from .tokenizer import count_tokens

_log = logging.getLogger(__name__)

def _default_instructions(keys: list[str], token_limit: int | None) -> str:
    """Port packages/api/src/agents/memory.ts:getDefaultInstructions."""
    instructions = """Use the `set_memory` tool to save important information about the user, but ONLY when the user has requested you to remember something.

The `delete_memory` tool should only be used in two scenarios:
  1. When the user explicitly asks to forget or remove specific information
  2. When updating existing memories, use the `set_memory` tool instead of deleting and re-adding the memory.

1. ONLY use memory tools when the user requests memory actions with phrases like:
   - "Remember [that] [I]..."
   - "Don't forget [that] [I]..."
   - "Please remember..."
   - "Store this..."
   - "Forget [that] [I]..."
   - "Delete the memory about..."

2. NEVER store information just because the user mentioned it in conversation.

3. NEVER use memory tools when the user asks you to use other tools or invoke tools in general.

4. Memory tools are ONLY for memory requests, not for general tool usage.

5. If the user doesn't ask you to remember or forget something, DO NOT use any memory tools.
"""
    if keys:
        instructions += '\nVALID KEYS: ' + ', '.join(keys) + '\n'
    if token_limit:
        instructions += f'\nTOKEN LIMIT: Maximum {token_limit} tokens across all memory values.\n'
    return instructions + "\nWhen in doubt, and the user hasn't asked to remember or forget anything, END THE TURN IMMEDIATELY."


def _automatic_agent(config: dict, owner: str, database) -> dict | None:
    selected = config.get('agent')
    if not isinstance(selected, dict) or selected.get('enabled') is not True:
        return None
    if isinstance(selected.get('id'), str) and selected['id']:
        return AgentRepository(database).get(owner, selected['id'])
    if (isinstance(selected.get('provider'), str) and isinstance(selected.get('model'), str)
            and selected['provider'] and selected['model']):
        return selected
    return None


def _memory_window(history: list[dict], *, window_size: int, max_tokens: int) -> str:
    """The original Memory Agent starts its window at a user-led turn."""
    dialog = [message for message in history if message.get('role') in {'user', 'assistant'}
              and not message.get('skillPrime')]
    if len(dialog) > window_size:
        for index in range(len(dialog) - window_size, -1, -1):
            if dialog[index].get('role') == 'user':
                dialog = dialog[index:index + window_size]
                break
        else:
            dialog = dialog[-window_size:]
    lines = []
    for message in dialog:
        body = message.get('content')
        if isinstance(body, list):
            body = '\n'.join(part.get('text', '') for part in body
                             if isinstance(part, dict) and part.get('type') == 'text'
                             and isinstance(part.get('text'), str))
        if not isinstance(body, str):
            continue
        lines.append(('Human' if message['role'] == 'user' else 'AI') + ': ' + body)
    result = '# Current Chat:\n\n' + '\n'.join(lines)
    prefix = '[Earlier chat content omitted due to memory input limit]\n\n'
    # Source keeps the END of the input. Keep the prefix separate from that
    # suffix: otherwise appending another prefix at each retry can loop forever.
    body = result[-max_tokens * 8:] if len(result) > max_tokens * 8 else result
    truncated = len(body) < len(result)
    result = (prefix if truncated else '') + body
    while count_tokens(result, exact=False) > max_tokens and body:
        truncated = True
        body = body[max(1, len(body) // 5):]
        result = prefix + body
    return result


async def run_automatic_memory(owner: str, generation, database, history: list[dict],
                               *, root_agent: dict | None, stream_tools,
                               grant_expires: int | None = None) -> int:
    """Run the configured summarize-only memory graph with tool-end semantics.

    Errors are isolated from the visible answer, as in upstream processMemory;
    every successful memory mutation remains a serialized SQLite transaction.
    """
    settings = WorkspaceRepository(database)
    if (grant_expires is not None and grant_expires <= time.time()) or not memory_enabled(settings, owner):
        return 0
    config = memory_config(settings, owner) or {}
    agent = _automatic_agent(config, owner, database)
    if agent is None:
        return 0
    try:
        chosen = provider_config(agent.get('provider', 'openai'), agent.get('model'))
    except (ValueError, KeyError, TypeError):
        _log.warning('Automatic Memory model is not available')
        return 0
    scope = agent_partition(root_agent)
    store = MemoryRepository(database)
    filters = configured_filters(settings, owner)
    existing = store.formatted(owner, scope, filters=filters)
    if existing.get('readFailed'):
        return 0  # Never assume quota is empty on a read failure.
    allowed_keys = config.get('validKeys')
    if not isinstance(allowed_keys, list):
        allowed_keys = []
    user_messages = [item for item in history if item.get('role') == 'user']
    if not user_messages:
        return 0
    # Model-bound admission also protects memories from user-submitted content
    # that is prohibited for the memory source under the current policy.
    if any(inspect_memory_content({'value': str(item.get('content') or '')}, filters)
           for item in user_messages):
        return 0
    size = config.get('messageWindowSize', 5)
    size = size if isinstance(size, int) and not isinstance(size, bool) and 1 <= size <= 100 else 5
    max_tokens = config.get('maxInputTokens', 4096)
    max_tokens = max_tokens if isinstance(max_tokens, int) and 32 <= max_tokens <= 32768 else 4096
    window = _memory_window(history, window_size=size, max_tokens=max_tokens)
    remaining = config.get('tokenLimit')
    status = '# Existing memory:\n' + (existing['withKeys'] or 'No existing memories')
    if isinstance(remaining, int) and remaining > 0:
        status = ('# Memory Status:\nCurrent memory usage: '
                  + str(existing['totalTokens']) + ' tokens\nToken limit: '
                  + str(remaining) + ' tokens\nRemaining capacity: '
                  + str(max(0, remaining - existing['totalTokens'])) + ' tokens\n\n' + status)
    instructions = (agent.get('instructions') or _default_instructions(
        allowed_keys, remaining if isinstance(remaining, int) else None)) + '\n\n' + status
    messages = [{'role': 'system', 'content': instructions},
                {'role': 'user', 'content': window}]
    writes = 0
    try:
        async for event in stream_tools(chosen, messages, tools=tool_definitions(allowed_keys),
                                        max_tokens=1024, temperature=None):
            if not isinstance(event, ModelToolCall):
                continue
            if event.name not in {'set_memory', 'delete_memory'}:
                continue
            from .generations import GenerationStore

            latest = GenerationStore(database).get(owner, generation.run_id)
            if (latest is None or latest.status != 'running' or not memory_enabled(settings, owner)
                    or (grant_expires is not None and grant_expires <= time.time())):
                break
            # Re-evaluate the live deployment filter before every mutation.
            latest_filters = configured_filters(settings, owner)
            outcome, artifact = execute_memory_tool(store, owner, root_agent or {},
                event.name, event.arguments, {**config, 'filters': latest_filters})
            if artifact is not None:
                settings_entry = artifact.get('memory')
                if isinstance(settings_entry, dict) and settings_entry.get('type') != 'error':
                    writes += 1
                # Original callback sends memory artifacts as generation
                # attachments. Persist the same shape for SSE replay.
                GenerationStore(database).append(owner, generation.run_id, {
                    'event': 'attachment', 'data': {
                        'type': 'memory', 'toolCallId': event.call_id,
                        'messageId': generation.response_message_id,
                        'conversationId': generation.conversation_id,
                        'memory': settings_entry,
                    },
                })
            else:
                _log.debug('Automatic Memory tool skipped: %s', outcome[:80])
            # Original MemoryRun has toolEnd: true and returns after executing
            # one model-generated tool batch, rather than answering the chat.
    except Exception as exc:
        _log.warning('Automatic Memory extraction failed (%s)', type(exc).__name__)
    return writes
