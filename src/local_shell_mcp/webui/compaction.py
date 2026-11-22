"""LibreChat compaction checkpoints and SDK summarization carriers.

Behavior ported from packages/api/src/agents/compaction.ts (e8f3be08)
and agents/src/summarization/shared.ts (c4ffb9b1); no local summary heuristics.
"""
from __future__ import annotations

from typing import Any

_JS_WHITESPACE = "\u0009\u000a\u000b\u000c\u000d \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
class CompactionFailed(ValueError):
    code = "COMPACTION_FAILED"


COMPACTION_FAILED_ERROR = '{"type":"compaction_failed"}'
SUMMARY_CARRIER_INSTRUCTION = "This is your own checkpoint: you wrote it to preserve context after compaction. Pick up where you left off based on the summary above. Do not repeat prior tasks, information or acknowledge this checkpoint message directly."


def _trim(text: str) -> str:
    return text.strip(_JS_WHITESPACE)


def _truthy(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0 and value == value
    return value != "" if isinstance(value, str) else True


def get_summary_part_text(part: Any) -> str:
    if not isinstance(part, dict) or part.get("type") != "summary":
        return ""
    content = part.get("content")
    if isinstance(content, str):
        return _trim(content)
    if isinstance(content, list):
        return _trim("".join(block["text"] for block in content
                             if isinstance(block, dict) and isinstance(block.get("text"), str)))
    text = part.get("text")
    return _trim(text) if isinstance(text, str) else ""


def is_usable_summary_part(part: Any) -> bool:
    return bool(isinstance(part, dict) and part.get("type") == "summary"
                and part.get("failed") is not True and part.get("summarizing") is not True
                and not (isinstance(part.get("content"), list) and part.get("boundary") is None)
                and get_summary_part_text(part))


def find_checkpoint_summary_part(content: Any) -> dict | None:
    if not isinstance(content, list):
        return None
    return next((part for part in reversed(content) if is_usable_summary_part(part)), None)


def resolve_checkpoint_message(message: dict) -> dict | None:
    summary = find_checkpoint_summary_part(message.get("content"))
    if summary is not None:
        index = next(i for i in range(len(message["content"]) - 1, -1, -1)
                     if message["content"][i] is summary)
        if not index:
            return message
        result = {**message, "content": message["content"][index:]}
        result.pop("tokenCount", None)
        return result
    if not _truthy(message.get("summary")):
        return None
    result = {**message, "role": "system", "content": [{"type": "text", "text": message["summary"]}]}
    count = message.get("summaryTokenCount")
    if count is None:
        count = message.get("tokenCount")
    if count is None:
        result.pop("tokenCount", None)
    else:
        result["tokenCount"] = count
    return result


def resolve_failed_turn_content(request_body: dict | None, error_text: str) -> dict:
    if not isinstance(request_body, dict) or request_body.get("compact") is not True:
        return {}
    return {"content": [{"type": "error", "error": error_text, "initiatedBy": "user"}]}


def mark_compaction_outcome(parts: list, *, aborted: bool = False) -> None:
    summary = next((part for part in parts if is_usable_summary_part(part)), None)
    if summary is not None:
        summary["initiatedBy"] = "user"
        return
    failures = [part for part in parts if isinstance(part, dict) and part.get("type") == "error"]
    if failures:
        for part in failures:
            part["initiatedBy"] = "user"
        return
    if aborted:
        raise CompactionFailed(COMPACTION_FAILED_ERROR)
    parts[:] = [part for part in parts if not isinstance(part, dict) or part.get("type") != "summary"]
    parts.append({"type": "error", "error": COMPACTION_FAILED_ERROR, "initiatedBy": "user"})


def _without_unusable(content: list) -> list:
    filtered = [part for part in content if is_usable_summary_part(part)
                or not get_summary_part_text(part)]
    return content if len(content) == len(filtered) else filtered


def drop_unusable_summary_parts(message: dict) -> bool:
    content = message.get("content")
    if not isinstance(content, list):
        return False
    filtered = _without_unusable(content)
    if filtered is content:
        return False
    message["content"] = filtered
    return True


def strip_unusable_summary_parts(payload: Any) -> Any:
    if not isinstance(payload, list):
        return payload
    changed = False
    result = []
    for message in payload:
        content = message.get("content") if isinstance(message, dict) else None
        filtered = _without_unusable(content) if isinstance(content, list) else content
        if filtered is content:
            result.append(message)
        else:
            changed = True
            result.append({**message, "content": filtered})
    return result if changed else payload


def build_summary_carrier_text(summary_text: str) -> str:
    return "<summary>\n" + summary_text + "\n</summary>\n\n" + SUMMARY_CARRIER_INSTRUCTION


def separate_summarization_parameters(parameters: dict) -> dict:
    result = {"llmParams": {key: value for key, value in parameters.items() if key != "maxSummaryTokens"}}
    count = parameters.get("maxSummaryTokens")
    if isinstance(count, (int, float)) and not isinstance(count, bool) and count > 0:
        result["maxSummaryTokens"] = count
    return result


def build_summarization_instruction(prompt_text: str, update_prompt_text: str | None,
                                    prior_summary_text: str | None = None,
                                    semantic_index_appendix: str = "") -> str:
    prior = _trim(prior_summary_text or "")
    prompt = (update_prompt_text if update_prompt_text is not None else prompt_text) if prior else prompt_text
    text = semantic_index_appendix + "\n\n" + prompt if semantic_index_appendix else prompt
    return text + "\n\n<previous-summary>\n" + prior + "\n</previous-summary>" if prior else text


DEFAULT_SUMMARIZATION_PROMPT = "Hold on, before you continue I need you to write me a checkpoint of everything so far. Your context window is filling up and this checkpoint replaces the messages above, so capture everything you need to pick right back up.\n\nDon't second-guess or fact-check anything you did, your tool results reflect exactly what happened. If a tool result appears truncated, that's just a display artifact from context management: the tool executed fully. Just record what you did and what you observed. Only the checkpoint, don't respond to me or continue the conversation.\n\n## Checkpoint\n\n## Goal\nWhat I asked you to do and any sub-goals you identified.\n\n## Constraints & Preferences\nAny rules, preferences, or configuration I established.\n\n## Progress\n### Done\n- What you completed and the outcomes\n\n### In Progress\n- What you're currently working on\n\n## Key Decisions\nDecisions you made and why.\n\n## Next Steps\nConcrete task actions remaining, in priority order.\n\n## Critical Context\nExact identifiers, names, error messages, URLs, and details you need to preserve verbatim.\n\nRules:\n- Record what you did and observed, don't judge or re-evaluate it\n- For each tool call: the tool name, key inputs, and the outcome\n- Preserve exact identifiers, names, errors, and references verbatim\n- Short declarative sentences\n- Skip empty sections"
DEFAULT_UPDATE_SUMMARIZATION_PROMPT = 'Hold on again, update your checkpoint. Merge the new messages into your existing checkpoint and give me a single consolidated replacement.\n\nKeep it roughly the same length as your last checkpoint. Compress older details to make room for what\'s new, don\'t just append. Give recent actions more detail, compress older items to one-liners.\n\nDon\'t fact-check or second-guess anything, your tool results are ground truth. If a tool result appears truncated, that\'s just a display artifact: the tool executed fully. Only the checkpoint, don\'t respond to me or continue the conversation.\n\nRules:\n- Merge new progress into existing sections, don\'t duplicate headers\n- Compress older completed items into one-line entries\n- Move items from "In Progress" to "Done" when you completed them\n- Update "Next Steps" to reflect current task priorities.\n- For each new tool call: the tool name, key inputs, and the outcome\n- Preserve exact identifiers, names, errors, and references verbatim\n- Skip empty sections'
