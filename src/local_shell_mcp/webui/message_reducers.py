"""LangGraph 1.4.8 messagesStateReducer on LSM's canonical message dictionaries.

LibreChat MultiAgentGraph.createWorkflow uses this reducer for ``messages`` and
last-value replacement for ``agentMessages``. Transport coercion into LangChain
classes is intentionally outside this seam: providers and checkpoint storage
already exchange canonical Python dictionaries. The reducer assigns missing
IDs to those message objects, as the original does to BaseMessage instances.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

REMOVE_ALL_MESSAGES = "__remove_all__"


def _id_key(value: Any) -> tuple:
    # JavaScript Map keeps booleans distinct from numbers, and object IDs use
    # object identity. In ordinary graph history the IDs are strings.
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, (int, float)):
        return ("number", value)
    if isinstance(value, str):
        return ("string", value)
    return ("object", id(value))


def _messages(value: list[dict] | dict) -> list[dict]:
    result = value if isinstance(value, list) else [value]
    # LibreChat src/messages/reducer.ts skips null stream fragments.
    result = [message for message in result if message is not None]
    if any(not isinstance(message, dict) for message in result):
        raise TypeError("Graph channel requires canonical message dictionaries")
    return result


def messages_state_reducer(left: list[dict] | dict, right: list[dict] | dict, *,
                           id_factory: Callable[[], str] | None = None) -> list[dict]:
    """Replace by ID, append new IDs, apply removals and the last clear marker.

    Removing then replacing the same ID restores it in its previous position.
    The last remove-all marker returns the suffix verbatim, including any later
    removal records; this deliberate source behavior must not be reinterpreted
    as a sequence of further removals.
    """
    make_id = id_factory or (lambda: str(uuid.uuid4()))
    left_messages, right_messages = _messages(left), _messages(right)
    for message in left_messages:
        if message.get("id") is None:
            message["id"] = make_id()
    remove_all_index = None
    for index, message in enumerate(right_messages):
        if message.get("id") is None:
            message["id"] = make_id()
        if (message.get("type") == "remove" or message.get("role") == "remove") and message["id"] == REMOVE_ALL_MESSAGES:
            remove_all_index = index
    if remove_all_index is not None:
        return right_messages[remove_all_index + 1:]
    merged = list(left_messages)
    indices = {_id_key(message["id"]): index for index, message in enumerate(merged)}
    removed = set()
    for message in right_messages:
        key = _id_key(message["id"])
        index = indices.get(key)
        if index is not None:
            if (message.get("type") == "remove" or message.get("role") == "remove"):
                removed.add(key)
            else:
                removed.discard(key)
                merged[index] = message
        else:
            if (message.get("type") == "remove" or message.get("role") == "remove"):
                raise ValueError(f"Attempting to delete a message with an ID that doesn't exist ('{message['id']}')")
            indices[key] = len(merged)
            merged.append(message)
    return [message for message in merged if _id_key(message["id"]) not in removed]


def create_remove_all_message() -> dict:
    """SDK src/messages/reducer.ts createRemoveAllMessage (wire representation)."""
    return {"role": "remove", "type": "remove", "id": REMOVE_ALL_MESSAGES}


def agent_messages_reducer(_current: Any, update: Any) -> Any:
    """The source agentMessages channel replaces rather than concatenates."""
    return update
