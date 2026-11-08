"""Source port of LibreChat HITL approval validation and decision mapping.

LibreChat e8f3be08: agents/hitl/policy.ts:isToolApprovalPayloadValid and
agents/hitl/resume.ts:resolveToolApprovalResume/mapToolApprovalResolutions.
The original functions are transpiled into development-only differential
fixtures by scripts/export-librechat-reference.cjs. Runtime policy admission,
graph interrupts and checkpoint ownership are separate porting modules.
"""
from __future__ import annotations


def is_tool_approval_payload_valid(payload: dict) -> bool:
    requests = payload.get("action_requests")
    reviews = payload.get("review_configs")
    if not isinstance(requests, list) or not isinstance(reviews, list) or len(requests) != len(reviews):
        return False
    requested = set()
    for request in requests:
        identity = request.get("tool_call_id") if isinstance(request, dict) else None
        if not isinstance(identity, str) or len(identity) == 0 or identity in requested:
            return False
        requested.add(identity)
    reviewed = set()
    for review in reviews:
        identity = review.get("tool_call_id") if isinstance(review, dict) else None
        if not isinstance(identity, str) or len(identity) == 0 or identity in reviewed or identity not in requested:
            return False
        reviewed.add(identity)
    return True


def map_tool_approval_resolutions(resolutions: list[dict]) -> dict:
    decisions = {}
    for resolution in resolutions:
        kind = resolution.get("decision")
        if kind == "approve":
            value = {"type": "approve"}
        elif kind == "reject":
            value = {"type": "reject"}
            if "reason" in resolution:
                value["reason"] = resolution["reason"]
        elif kind == "edit":
            value = {"type": "edit", "updatedInput": resolution.get("editedArguments") or {}}
        elif kind == "respond":
            value = {"type": "respond", "responseText": resolution.get("responseText") or ""}
        else:
            value = {"type": "reject", "reason": "Unrecognized approval decision"}
        decisions[resolution["tool_call_id"]] = value
    return decisions


def resolve_tool_approval_resume(payload: dict, resolutions: list[dict]) -> dict:
    """Validate in the same order and return the original HTTP error shape."""
    if not is_tool_approval_payload_valid(payload):
        return {"status": 400, "error": "Invalid tool approval payload"}
    requested = {item["tool_call_id"] for item in payload["action_requests"]}
    seen = set()
    for resolution in resolutions:
        identity = resolution.get("tool_call_id")
        if identity in seen or identity not in requested:
            return {"status": 400, "error": "Invalid tool approval decisions"}
        seen.add(identity)
    undecided = [item["tool_call_id"] for item in payload["action_requests"] if item["tool_call_id"] not in seen]
    if undecided:
        return {"status": 400, "error": "Every paused tool call must be decided", "undecided": undecided}
    allowed = {item["tool_call_id"]: item["allowed_decisions"] for item in payload["review_configs"]}
    disallowed = [item["tool_call_id"] for item in resolutions if item.get("decision") not in allowed.get(item["tool_call_id"], [])]
    if disallowed:
        return {"status": 403, "error": "Decision not permitted for one or more tools", "disallowed": disallowed}
    incomplete = []
    for resolution in resolutions:
        if resolution.get("decision") == "edit" and not isinstance(resolution.get("editedArguments"), dict):
            incomplete.append(resolution["tool_call_id"])
        if resolution.get("decision") == "respond" and (
            not isinstance(resolution.get("responseText"), str) or len(resolution["responseText"]) == 0
        ):
            incomplete.append(resolution["tool_call_id"])
    if incomplete:
        return {"status": 400, "error": "edit requires editedArguments and respond requires responseText", "incomplete": incomplete}
    return {"resumeValue": map_tool_approval_resolutions(resolutions)}
