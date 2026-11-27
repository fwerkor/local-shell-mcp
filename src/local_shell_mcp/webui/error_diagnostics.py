"""Safe, inspectable diagnostics for WebUI generation failures.

Do not send untrusted exception messages, HTTP headers, model prompts, or
credentials to the browser. Stack *locations* are useful for debugging and do
not include local variables or arbitrary upstream response bodies.
"""

from __future__ import annotations

import json
import traceback
from pathlib import Path

from .agent_runtime import RuntimeSafetyError
from .compaction import CompactionFailed
from .provider_responses import ResponsesStreamError

_KNOWN_SAFETY_REASONS = frozenset({
    "Authentication grant expired",
    "WebUI session expired or was signed out",
    "Tool is not enabled for the current Agent",
    "Memory tools are disabled",
    "Agent graph is no longer available",
    "Checkpoint Agent is no longer available",
    "Action execution requires a saved Agent",
    "Action is not bound to this Agent",
    "OAuth Action authorization was revoked before dispatch",
    "Assembled model context was blocked by content protection",
    "Summary context was blocked by content protection",
    "Generation actor lease expired or was replaced",
})


def generation_failure(exc: Exception, run_id: str) -> str:
    """Produce a versioned error part with a readable cause and stack frames."""
    kind = type(exc).__name__
    if isinstance(exc, RuntimeSafetyError):
        reason = str(exc) if str(exc) in _KNOWN_SAFETY_REASONS else "A runtime authorization or safety boundary rejected this operation"
        if reason in {"Authentication grant expired", "WebUI session expired or was signed out"}:
            headline = "WebUI authorization expired or was revoked. Sign in again to continue."
        else:
            headline = f"LSM stopped this operation: {reason}."
    elif isinstance(exc, CompactionFailed):
        reason = "Context compaction did not complete; the original history is preserved"
        headline = "Context compaction failed. Model generation stopped; retry to continue."
    elif isinstance(exc, ResponsesStreamError):
        reason = str(exc)  # Typed exception contains only classified fields.
        headline = reason
    elif isinstance(exc, TimeoutError):
        reason = "The operation timed out"
        headline = "The model request or runtime operation timed out."
    elif kind in {"RemoteProtocolError", "ConnectError", "ReadError", "ReadTimeout", "APIConnectionError"}:
        reason = "The upstream connection failed"
        headline = "The model provider connection failed."
    elif kind in {"HTTPStatusError", "APIStatusError", "AuthenticationError", "BadRequestError",
                  "RateLimitError", "NotFoundError", "PermissionDeniedError", "UnprocessableEntityError",
                  "InternalServerError"}:
        reason = "The provider rejected or could not complete the request"
        headline = f"The model provider request failed ({kind})."
    else:
        reason = "An unexpected generation error occurred"
        headline = f"LSM could not finish this generation ({kind})."

    # Raw Python tracebacks can embed a provider's error text or secret-bearing
    # repr. Render only the file/function/line of each frame, with no locals.
    frames = traceback.extract_tb(exc.__traceback__)[-32:]
    stack = "\n".join(f"  at {Path(f.filename).name}:{f.lineno} in {f.name}" for f in frames)
    details = f"Run: {run_id}\nException: {kind}\nReason: {reason}"
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None) if response is not None else getattr(exc, "status_code", None)
    if type(status) is int and 100 <= status <= 599:
        details += f"\nHTTP status: {status}"
    if stack:
        details += "\nStack (most recent call last):\n" + stack
    return json.dumps({
        "type": "lsm_generation_error",
        "message": headline,
        "exception": kind,
        "runId": run_id,
        "details": details,
    }, ensure_ascii=False)
