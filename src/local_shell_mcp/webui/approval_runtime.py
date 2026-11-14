"""LibreChat approval batch planning and ToolNode decision execution.

Source: LibreChat e8f3be08 agents/hitl/policy.ts and agents SDK 4.0.1
ToolNode.ts decision handling. This adapter deliberately receives the existing
LSM dispatcher; approving a proposal never grants machine or OAuth access.
Durable checkpoint claims and graph hook replay remain owned by the caller.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .providers import ModelToolCall
from .tool_approval import resolve_tool_approval_resume

_DEFAULT_DECISIONS = ("approve", "reject", "edit")
_ALL_DECISIONS = frozenset((*_DEFAULT_DECISIONS, "respond"))


def approval_policy_decision(policy: Mapping | None, tool_name: str) -> dict | None:
    """Port the LC enabled gate and SDK createToolPolicyHook's static policy."""
    if not policy or policy.get("enabled") is not True:
        return None

    def matches(patterns: Any) -> bool:
        return any(re.fullmatch(re.escape(pattern).replace(r"\*", ".*"), tool_name)
                   for pattern in patterns or ())

    if matches(policy.get("deny")):
        decision = "deny"
    elif matches(policy.get("ask")):
        decision = "ask"
    elif matches(policy.get("allow")) or policy.get("mode") == "bypass":
        decision = "allow"
    elif policy.get("mode") == "dontAsk":
        decision = "deny"
    else:
        decision = "ask"
    result = {"decision": decision}
    if decision != "allow" and policy.get("reason") is not None:
        result["reason"] = policy["reason"].replace("{tool}", tool_name)
    return result


def ask_user_approval_policy(policy: Mapping | None) -> Mapping | None:
    """Port LibreChat policy.ts:exemptAskUserQuestionFromApproval.

    The tool remains optional; a configured exact ask/deny/allow entry wins
    over the default bypass added for a side-effect-free question.
    """
    if policy is None:
        return None
    name = "ask_user_question"
    if any(name in (policy.get(key) or []) for key in ("allow", "ask", "deny")):
        return policy
    return {**policy, "allow": [*(policy.get("allow") or []), name]}


def build_approval_payload(calls: Sequence[ModelToolCall], *,
                           decisions_by_tool_name: Mapping[str, Sequence[str]] | None = None,
                           descriptions: Mapping[str, str] | None = None) -> dict:
    """Port LC buildToolApprovalPayload; only the paused ask subset is supplied."""
    payload: dict[str, Any] = {"type": "tool_approval", "action_requests": [], "review_configs": []}
    decisions = decisions_by_tool_name or {}
    for call in calls:
        request = {"name": call.name, "arguments": json.loads(_json(call.arguments)),
                   "tool_call_id": call.call_id}
        if descriptions is not None and call.call_id in descriptions:
            request["description"] = descriptions[call.call_id]
        payload["action_requests"].append(request)
        payload["review_configs"].append({
            "action_name": call.name, "tool_call_id": call.call_id,
            "allowed_decisions": list(decisions.get(call.name, _DEFAULT_DECISIONS)),
        })
    _validate_review_shape(payload)
    return payload


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _validate_review_shape(payload: Any) -> None:
    """Port SDK approvalReview.hasValidApprovalShape at the execution boundary."""
    if not isinstance(payload, dict) or payload.get("type") != "tool_approval":
        raise ValueError("Invalid tool approval payload")
    requests = payload.get("action_requests")
    reviews = payload.get("review_configs")
    if not isinstance(requests, list) or not isinstance(reviews, list) or len(requests) != len(reviews):
        raise ValueError("Invalid tool approval payload")
    seen = set()
    for request, review in zip(requests, reviews, strict=True):
        if not isinstance(request, dict) or not isinstance(review, dict):
            raise ValueError("Invalid tool approval payload")
        identity, name = request.get("tool_call_id"), request.get("name")
        allowed = review.get("allowed_decisions")
        if (not isinstance(identity, str) or not identity or identity in seen or
            not isinstance(name, str) or not name or not isinstance(request.get("arguments"), dict) or
            request.get("description") is not None and not isinstance(request["description"], str) or
            review.get("tool_call_id") != identity or review.get("action_name") != name or
            not isinstance(allowed, list) or any(not isinstance(value, str) or value not in _ALL_DECISIONS
                                                 for value in allowed)):
            raise ValueError("Invalid tool approval payload")
        seen.add(identity)


@dataclass(frozen=True)
class ApprovalEntry:
    """Immutable reviewed proposal plus its SDK-mapped decision."""

    call_id: str
    name: str
    arguments_json: str
    decision_json: str
    description: str | None = None

    @property
    def decision(self) -> dict:
        return json.loads(self.decision_json)

    def tool_call(self) -> ModelToolCall:
        decision = self.decision
        arguments = (decision["updatedInput"] if decision["type"] == "edit"
                     else json.loads(self.arguments_json))
        return ModelToolCall(self.call_id, self.name, arguments)


@dataclass(frozen=True)
class ApprovalBatch:
    entries: tuple[ApprovalEntry, ...]


def prepare_approval_batch(payload: dict, resolutions: list[dict]) -> ApprovalBatch:
    """Validate the entire batch before a caller consumes its one-shot DB claim."""
    _validate_review_shape(payload)
    if not isinstance(resolutions, list) or any(not isinstance(item, dict) for item in resolutions):
        raise ValueError("Invalid tool approval decisions")
    resolved = resolve_tool_approval_resume(payload, resolutions)
    if "error" in resolved:
        if resolved["status"] == 403:
            raise PermissionError(resolved["error"])
        raise ValueError(resolved["error"])
    return ApprovalBatch(tuple(ApprovalEntry(
        call_id=request["tool_call_id"], name=request["name"],
        arguments_json=_json(request["arguments"]),
        decision_json=_json(resolved["resumeValue"][request["tool_call_id"]]),
        description=request.get("description"),
    ) for request in payload["action_requests"]))


@dataclass(frozen=True)
class ApprovalResult:
    call: ModelToolCall
    content: str
    status: str
    decision: str
    raw_content: str | None = None

    def history_message(self) -> dict:
        # Provider adapters consume the original call ID. Error status belongs
        # in run events/checkpoints, not an unsupported OpenAI message field.
        return {"role": "tool", "tool_call_id": self.call.call_id, "content": self.content}


def truncate_approval_result(content: str, max_chars: int) -> str:
    """Port SDK truncateToolResultContent, including UTF-16-safe boundaries."""
    encoded = content.encode("utf-16-le", errors="surrogatepass")
    if len(encoded) // 2 <= max_chars:
        return content
    units = "".join(chr(int.from_bytes(encoded[index:index + 2], "little"))
                    for index in range(0, len(encoded), 2))

    def sliced(start: int, end: int | None = None) -> str:
        value = units[start:end]
        if value and 0xDC00 <= ord(value[0]) <= 0xDFFF:
            value = value[1:]
        if value and 0xD800 <= ord(value[-1]) <= 0xDBFF:
            value = value[:-1]
        return b"".join(ord(unit).to_bytes(2, "little") for unit in value).decode(
            "utf-16-le", errors="surrogatepass")

    indicator = f"\n\n… [truncated: {len(units)} chars exceeded {max_chars} limit] …\n\n"
    available = max_chars - len(indicator)
    if available <= 0:
        return sliced(0, max_chars)
    if available < 200:
        return sliced(0, available) + indicator.rstrip()
    # Math.ceil(available * .7), expressed with integer arithmetic.
    head_size = (available * 7 + 9) // 10
    tail_size = available - head_size
    head_end = head_size
    head_newline = units.rfind("\n", 0, head_size + 1)
    if head_newline > head_size - 200 and head_newline > 0:
        head_end = head_newline
    tail_start = len(units) - tail_size
    tail_newline = units.find("\n", tail_start)
    if tail_newline > 0 and tail_newline < tail_start + 200:
        tail_start = tail_newline + 1
    return sliced(0, head_end) + indicator + sliced(tail_start)


async def execute_approval_batch(
    batch: ApprovalBatch, *, dispatch: Callable[[ModelToolCall], Awaitable[str]],
    on_completed: Callable[[ApprovalResult], Awaitable[None]] | None = None,
    max_result_chars: int = 400_000,
) -> list[ApprovalResult]:
    """Apply source decisions, dispatching only approve/edit via the native executor.

    The dispatcher is responsible for current ownership, selected tools,
    machine ACLs, OAuth expiry and durable per-call checkpoint/idempotency.
    It is called separately for each real execution, after argument edits.
    Cancellation propagates; completed call IDs can be persisted by the callback
    and reused by a checkpoint-aware dispatcher when the graph is resumed.
    """
    results = []
    for entry in batch.entries:
        decision = entry.decision
        kind = decision["type"]
        call = entry.tool_call()
        if kind == "reject":
            reason = decision.get("reason")
            if reason is None:
                reason = entry.description if entry.description is not None else "Rejected by user"
            result = ApprovalResult(call, "Blocked: " + str(reason), "error", kind)
        elif kind == "respond":
            result = ApprovalResult(call, truncate_approval_result(decision["responseText"], max_result_chars), "success", kind)
        else:
            # No exception wrapper here: cancellation / checkpoint interruption
            # must unwind to the runtime, rather than fabricate a completed call.
            raw_content = await dispatch(call)
            result = ApprovalResult(call, truncate_approval_result(raw_content, max_result_chars),
                                    "success", kind, raw_content=raw_content)
        if on_completed is not None:
            await on_completed(result)
        results.append(result)
    return results
