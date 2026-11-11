"""Single model-history DTO for the Python WebUI and graph runtime.

Source: LibreChat e8f3be08 api/app/clients/prompts/formatMessages.js
(formatMessage / formatAgentMessages). Persist this ordered list separately from
UI-only content and never feed truncated run-step previews back into a model.

Wire adapters accept canonical {role, content, tool_calls, tool_call_id} with
optional {reasoning, artifact, name, provider_data}. Extra fields are local,
not provider-specific wire parameters.
"""
from __future__ import annotations

import copy
import json
import re

EMPTY_MESSAGE_PLACEHOLDER = "(no text)"


def _part_content(part):
    """Preserve image/file blocks, turning bare text blocks into model content."""
    if part.get("type") == "text":
        return {"type": "text", "text": part.get("text", "")}
    return copy.deepcopy(part)


def format_message(message: dict) -> dict:
    """Port formatMessage's structured-content priority and role inference."""
    role = message.get("role") or ("user" if str(message.get("sender", "")).lower() == "user" else "assistant")
    content = message.get("content")
    if content is None:
        content = message.get("text", "")
    images = message.get("image_urls")
    if role == "user" and isinstance(images, list) and images:
        blocks = [] if not isinstance(content, str) or not content.strip() else [{"type": "text", "text": content}]
        content = [*blocks, *copy.deepcopy(images)]
    if role == "user" and content == "" and message.get("files"):
        content = "Please refer to the attached file(s)."
    result = {"role": role, "content": copy.deepcopy(content)}
    name = message.get("_name") or message.get("name")
    if name:
        result["name"] = re.sub(r"[^a-zA-Z0-9_-]", "_", name)[:64]
    for key in ("tool_call_id", "tool_calls", "artifact", "reasoning", "provider_data"):
        if key in message:
            result[key] = copy.deepcopy(message[key])
    return result


def format_agent_messages(payload: list[dict]) -> list[dict]:
    """Rebuild ordered assistant/tool/steer steps from LibreChat UI message parts.

    Already-canonical DTOs (as emitted by the Python graph) pass through without
    reinterpreting tools. Tool-call anchors must appear before tool parts.
    """
    output: list[dict] = []
    for message in payload:
        content = message.get("content")
        if message.get("role") != "assistant":
            value = dict(message)
            if isinstance(content, str):
                value["content"] = [{"type": "text", "text": content}] if content.strip() else []
            formatted = format_message(value)
            if formatted.get("content") in ("", []):
                formatted["content"] = [{"type": "text", "text": EMPTY_MESSAGE_PLACEHOLDER}]
            output.append(formatted)
            continue
        if isinstance(content, str):
            content = [{"type": "text", "text": content}] if content.strip() else []
        if not isinstance(content, list):
            output.append(format_message(message))
            continue
        current: list[dict] = []
        anchor: dict | None = None
        has_reasoning = False
        signature_map = (message.get("metadata") or {}).get("thoughtSignatures") or {}
        for part in content:
            if not isinstance(part, dict):
                continue
            kind = part.get("type")
            if kind == "text" and "tool_call_ids" in part:
                if current:
                    output.append({"role": "assistant", "content": _collapse(current)})
                    current = []
                anchor = {"role": "assistant", "content": part.get("text") or "", "tool_calls": []}
                output.append(anchor)
            elif kind == "tool_call":
                if anchor is None:
                    raise ValueError("Invalid tool call structure: missing assistant call anchor")
                call = copy.deepcopy(part.get("tool_call") or {})
                args = call.get("args", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = {"input": args}
                call_id = call.get("id")
                if not call_id:
                    raise ValueError("Tool call ID is required")
                definition = {"id": call_id, "type": "function", "function": {
                    "name": call.get("name", ""), "arguments": json.dumps(args, ensure_ascii=False),
                }}
                signature = signature_map.get(call_id) if isinstance(signature_map, dict) else None
                if signature:
                    definition["provider_data"] = {"thoughtSignature": signature}
                anchor["tool_calls"].append(definition)
                output.append({"role": "tool", "tool_call_id": call_id,
                               "name": call.get("name", ""),
                               "content": copy.deepcopy(call.get("raw_output", call.get("output", ""))),
                               **({"artifact": copy.deepcopy(call["artifact"])} if "artifact" in call else {})})
            elif kind == "steer":
                if current:
                    output.append({"role": "assistant", "content": _collapse(current)})
                    current = []
                media = part.get("media")
                output.append({"role": "user", "content": copy.deepcopy(media) if media else part.get("steer", "") or EMPTY_MESSAGE_PLACEHOLDER,
                               "source": "steer"})
                anchor = None
            elif kind in {"error", "agent_update", "activity_label"}:
                continue
            elif kind == "think":
                # Reasoning is retained separately, never accidentally turned
                # into ordinary answer text for providers that forbid it.
                has_reasoning = True
            else:
                current.append(_part_content(part))
        if current:
            if has_reasoning:
                output.append({"role": "assistant", "content": "\n".join(
                    part.get("text", "") for part in current if part.get("type") == "text"
                ).strip()})
            else:
                output.append({"role": "assistant", "content": copy.deepcopy(current)})
    return output


def _collapse(parts: list[dict]):
    if all(p.get("type") == "text" for p in parts):
        return "\n".join(p.get("text", "") for p in parts).strip()
    return parts


def model_steps(messages: list[dict], start: int) -> list[dict]:
    """Take this run's exact ordered model steps, not its UI render snapshot."""
    return copy.deepcopy(messages[start:])
