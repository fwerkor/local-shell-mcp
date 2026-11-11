"""Provider-visible SDK artifact projection for JSON-native MCP image results.

Source: agents 4.0.1 messages/core.ts projectArtifactPayload and
projectAnthropicArtifactContent. The original raw native JSON remains in owned
checkpoint writes; parsed ToolMessage artifacts remain in graph history. Only
this temporary projection is serialized to a model provider. Full provenance
and non-MCP artifact families belong to their separate Graph/Artifacts ports.
"""
from __future__ import annotations

import copy
import json
import math
import re

from .approval_runtime import truncate_approval_result
from .mcp_content import format_tool_content, mcp_result_envelope

HARD_MAX_TOOL_RESULT_CHARS = 400000
_ARTIFACT_PLACEHOLDER = "Tool response is included in the next message as a Human message"


def _length(value: str) -> int:
    return len(value.encode("utf-16-le", errors="surrogatepass")) // 2


def _compact_json(value) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    text = text.encode("utf-16-le", errors="surrogatepass").decode("utf-16-le", errors="surrogatepass")
    return re.sub(r"[\ud800-\udfff]", lambda match: "\\u" + format(ord(match[0]), "04x"), text)


def _count(value) -> int:
    if isinstance(value, str):
        return _length(value)
    if isinstance(value, list) and all(isinstance(block, dict) and block.get("type") == "text"
                                      and isinstance(block.get("text"), str) for block in value):
        return sum(_length(block["text"]) for block in value) + max(0, len(value) - 1)
    return _length(_compact_json(value))


def _compact_segment(value, budget):
    """The source compactToolContent branches reached by parser image artifacts."""
    if isinstance(value, str):
        return truncate_approval_result(value, budget)
    if len(value) != 1 or value[0].get("type") not in {"image_url", "text"}:
        raise ValueError("Unsupported non-MCP artifact content")
    if _count(value) <= budget:
        return copy.deepcopy(value)
    block = value[0]
    if block["type"] == "text":
        return truncate_approval_result(block["text"], budget)
    # A single image that cannot fit its own segment cannot fit half of that
    # budget either. Mirror the SDK atomic-omission and structural allowance.
    preview = truncate_approval_result("[omitted 1 oversized atomic tool-content block: image_url]", max(0, budget - 32))
    if preview:
        return [{"type": "text", "text": preview}]
    return "[" if budget == 1 else []


class _Accumulator:
    def __init__(self, max_chars):
        self.blocks = []
        self.has_content = False
        self.remaining = max(0, math.floor(max_chars)) if math.isfinite(max_chars) else 9007199254740991

    def append(self, value):
        if isinstance(value, list):
            for block in value:
                self._segment([block])
                if self.remaining <= int(self.has_content):
                    break
        else:
            self._segment(value)

    def _segment(self, value):
        separator = int(self.has_content)
        available = self.remaining - separator
        if _count(value) <= 0 or available <= 0:
            return
        compacted = _compact_segment(value, available)
        appended = min(available, _count(compacted))
        if appended <= 0:
            return
        self.blocks.extend([{"type": "text", "text": compacted}] if isinstance(compacted, str) else compacted)
        self.has_content = True
        self.remaining -= separator + appended


def project_artifact_messages(messages: list[dict], provider: str, max_chars=HARD_MAX_TOOL_RESULT_CHARS) -> list[dict]:
    """Project all completed tool batches at their original history positions.

    The SDK projects immediately after each ToolMessage in a live graph. A
    reloaded conversation ends in the *next* HumanMessage, so testing only
    messages[-1] would silently lose all earlier images on SQLite replay.
    The stored DTO is never mutated.
    """
    projected = []
    changed = False
    index = 0
    while index < len(messages):
        message = messages[index]
        projected.append(message)
        index += 1
        if message.get("role") != "assistant" or not message.get("tool_calls"):
            continue
        call_ids = {call.get("id") for call in message["tool_calls"]}
        batch = []
        while index < len(messages) and messages[index].get("role") == "tool" and messages[index].get("tool_call_id") in call_ids:
            batch.append(messages[index])
            index += 1
        with_artifacts = [msg for msg in batch if isinstance(msg.get("artifact"), dict) and msg["artifact"].get("content")]
        if not with_artifacts:
            projected.extend(batch)
            continue
        changed = True
        aggregate = _Accumulator(max_chars)
        for item in batch:
            artifact = item.get("artifact")
            if not isinstance(artifact, dict) or not artifact.get("content"):
                projected.append(item)
                continue
            clone = copy.deepcopy(item)
            clone["artifact"] = {**copy.deepcopy(artifact), "content": []}
            if provider == "anthropic":
                current = _Accumulator(max_chars)
                base = item.get("content", "")
                if base == "":
                    current.blocks.append({"type": "text", "text": ""})
                    current.has_content = True
                else:
                    current.append(base)
                current.append(artifact["content"])
                clone["content"] = current.blocks
            else:
                aggregate.append(item.get("content", ""))
                clone["content"] = _ARTIFACT_PLACEHOLDER
                aggregate.append(artifact["content"])
            projected.append(clone)
        if provider != "anthropic" and aggregate.has_content:
            projected.append({"role": "user", "content": aggregate.blocks})
    return projected if changed else messages


def _mcp_envelope(value, name):
    if isinstance(value, dict) and isinstance(value.get("content"), list) and all(
            isinstance(block, dict) and isinstance(block.get("type"), str) for block in value["content"]):
        return value
    return mcp_result_envelope(value, name)


def mcp_tool_history_message(call, raw: str, provider: str, max_chars=HARD_MAX_TOOL_RESULT_CHARS) -> dict:
    """Split a real native MCP envelope before any text-only context clipping."""
    # Raw tool output is retained for audit, restart and model projections.
    message = {"role": "tool", "tool_call_id": call.call_id, "content": raw, "raw_result": raw}
    try:
        envelope = _mcp_envelope(json.loads(raw), call.name)
    except (ValueError, TypeError):
        return message
    if envelope is None:
        return message
    text, artifact = format_tool_content(envelope, provider)
    message["content"] = text
    message["is_error"] = bool(envelope.get("isError", envelope.get("is_error", False)))
    if artifact is not None:
        message["artifact"] = artifact
    return message


def openai_wire_messages(messages: list[dict]) -> list[dict]:
    """Provider serialization drops checkpoint-local artifact/id/provenance."""
    result = []
    for message in project_artifact_messages(messages, "openai"):
        item = {key: copy.deepcopy(message[key]) for key in ("role", "content", "name", "tool_call_id") if key in message}
        if message.get("role") == "tool" and isinstance(item.get("content"), str):
            # Source @librechat/agents utils/truncation.ts: bounded model
            # ingestion. The persisted raw result remains completely intact.
            item["content"] = truncate_approval_result(item["content"], HARD_MAX_TOOL_RESULT_CHARS)
        if message.get("tool_calls"):
            item["tool_calls"] = [{"id": call["id"], "type": "function", "function": copy.deepcopy(call["function"])}
                                  for call in message["tool_calls"]]
        result.append(item)
    return result
