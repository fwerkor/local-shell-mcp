"""Safe, inspectable diagnostics for WebUI generation failures.

Preserve exception chains and stack locations without serializing local variables,
request headers, or arbitrary request bodies. Provider error envelopes are
reported separately with known credentials redacted.
"""

from __future__ import annotations

import json
import re
import traceback
from pathlib import Path

from .agent_runtime import RuntimeSafetyError
from .compaction import CompactionFailed, SummaryResponseError
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
    "Web search is disabled for this conversation",
    "run_in_background was not enabled for this tool",
    "Background execution is disabled in this child context",
    "Agent session authorization has expired",
    "Agent generation has been cancelled",
    "Agent authorization is no longer available",
    "Approved tool checkpoint is missing persisted outcomes",
    "Handoff commands require an active StateGraph node",
})


def _classify(exc: BaseException) -> tuple[str, str]:
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
    elif isinstance(exc, SummaryResponseError):
        reason = str(exc)
        headline = reason
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

    return headline, reason


def _http_status(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None) if response is not None else getattr(exc, "status_code", None)
    return status if type(status) is int and 100 <= status <= 599 else None


def _provider_details(exc: BaseException, credentials: tuple[str, ...]) -> list[str]:
    response = getattr(exc, "response", None)
    if response is None or _http_status(exc) is None:
        return []
    try:
        payload = response.json()
    except (ValueError, AttributeError, RuntimeError):
        return []
    if not isinstance(payload, dict):
        return []
    envelope = payload.get("error", payload)
    if not isinstance(envelope, dict):
        return []
    secrets = list(credentials)
    # The actual request can use a refreshed OAuth token or a different channel.
    try:
        request = getattr(exc, "request", None) or response.request
        for name in ("authorization", "x-api-key", "api-key", "x-goog-api-key", "cookie"):
            value = request.headers.get(name)
            if value:
                secrets.append(value)
                if name == "authorization":
                    secrets.append(value.split(" ", 1)[-1])
                elif name == "cookie":
                    secrets.extend(item.partition("=")[2].strip() for item in value.split(";"))
        for key, value in request.url.params.multi_items():
            if re.search(r"key|token|secret|password|auth|signature", key, re.I):
                secrets.append(value)
    except (AttributeError, RuntimeError):
        pass

    def redact(value: str) -> str:
        for secret in sorted(set(filter(None, secrets)), key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?i)\bBearer\s+[^\s,;\"']+", "Bearer [REDACTED]", value)
        value = re.sub(r"(?i)([\w-]*(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|authorization)[\w-]*[\"']?\s*[:=]\s*[\"']?)[^\s,;\"'&}]+", r"\1[REDACTED]", value)
        return value

    return [f"Provider {key}: {redact(str(envelope[key]))}"
            for key in ("type", "code", "param", "message")
            if isinstance(envelope.get(key), (str, int))]


def _exception_details(exc: BaseException, credentials: tuple[str, ...]) -> list[str]:
    _, reason = _classify(exc)
    lines = [f"Exception: {type(exc).__name__}", f"Reason: {reason}"]
    status = _http_status(exc)
    if status is not None:
        lines.append(f"HTTP status: {status}")
        lines.extend(_provider_details(exc, credentials))
    frames = traceback.extract_tb(exc.__traceback__)
    if frames:
        lines.append("Stack (most recent call last):")
        lines.extend(f"  at {Path(f.filename).name}:{f.lineno} in {f.name}" for f in frames)
    return lines


def generation_failure(exc: Exception, run_id: str, *, credentials: tuple[str, ...] = ()) -> str:
    """Serialize the visible exception chain, including each cause's own stack."""
    headline, _ = _classify(exc)
    lines = [f"Run: {run_id}"]
    current: BaseException | None = exc
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        lines.extend(_exception_details(current, credentials))
        if isinstance(current, CompactionFailed):
            lines.extend(current.diagnostics)
        previous = getattr(current, "summary_attempts", ())
        if previous:
            lines.append("Earlier summary attempts:")
            for attempt in previous:
                lines.extend(_exception_details(attempt, credentials))
        if current.__cause__ is not None:
            current = current.__cause__
            label = "Caused by:"
        elif not current.__suppress_context__:
            current = current.__context__
            label = "During handling of:"
        else:
            current = None
        if current is not None and id(current) not in seen:
            lines.extend(("", label))
    return json.dumps({
        "type": "lsm_generation_error",
        "message": headline,
        "exception": type(exc).__name__,
        "runId": run_id,
        "details": "\n".join(lines),
    }, ensure_ascii=False)
