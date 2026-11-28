"""Provider error envelopes and credential-safe streaming diagnostics."""
from __future__ import annotations

import re
from urllib.parse import quote, quote_plus

_TRANSIENT_ERROR_CODES = frozenset({
    "server_error", "internal_server_error", "rate_limit_exceeded",
    "rate_limit_error", "overloaded_error", "overloaded", "service_unavailable",
    "temporarily_unavailable", "timeout", "request_timeout", "gateway_timeout",
    "engine_overloaded", "model_overloaded", "internal_error",
    "cancelled", "canceled", "api_error", "resource_exhausted",
    "unavailable", "deadline_exceeded", "internal", "aborted",
})
_PERMANENT_ERROR_CODES = frozenset({
    "invalid_request_error", "invalid_request", "invalid_api_key",
    "authentication_error", "permission_denied", "insufficient_quota",
    "quota_exceeded", "billing_hard_limit_reached", "model_not_found",
    "context_length_exceeded", "content_filter", "content_policy_violation",
    "invalid_prompt", "unsupported_value", "invalid_value",
    "missing_required_parameter", "invalid_parameter", "usage_limit_reached",
    "invalid_argument", "unauthenticated", "not_found", "failed_precondition",
    "authorization_error", "request_too_large", "request_too_large_error",
    "not_found_error", "permission_error", "billing_error",
})


def request_credentials(response=None, credentials=()) -> tuple[str, ...]:
    secrets = list(credentials)
    try:
        request = response.request
        for name in ("authorization", "proxy-authorization", "x-api-key", "api-key", "x-goog-api-key", "cookie"):
            value = request.headers.get(name)
            if value:
                secrets.append(value)
                if name in {"authorization", "proxy-authorization"}:
                    secrets.append(value.split(" ", 1)[-1])
                elif name == "cookie":
                    secrets.extend(item.partition("=")[2].strip() for item in value.split(";"))
        for key, value in request.url.params.multi_items():
            if re.search(r"key|token|secret|password|auth|signature", key, re.I):
                secrets.append(value)
        secrets.extend(v for v in (request.url.username, request.url.password) if v)
    except (AttributeError, RuntimeError):
        pass
    return tuple(sorted(set(filter(None, secrets)), key=len, reverse=True))


def redact_provider_value(value: str, credentials=()) -> str:
    variants = {encoded for secret in credentials if secret for encoded in (secret, quote(secret, safe=""), quote_plus(secret))}
    for secret in sorted(variants, key=len, reverse=True):
        value = value.replace(secret, "[REDACTED]")
    value = re.sub(r"(?i)\bBearer\s+[^\s,;\"']+", "Bearer [REDACTED]", value)
    value = re.sub(r"(?i)([\w-]*(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|authorization|signature)[\w-]*[\"']?\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;\"'&}]+)", r"\1[REDACTED]", value)
    value = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{12,}|AIza[A-Za-z0-9_-]{30,})\b", "[REDACTED]", value)
    # Avoid terminal escapes and forged diagnostic lines, without discarding text.
    return ''.join(ch if ch.isprintable() else repr(ch)[1:-1] for ch in value)


def _classification(fields: dict) -> bool:
    # A concrete code takes precedence over generic error categories. Unknown
    # errors are retried within the existing budget, not silently discarded.
    for key in ("code", "status", "type"):
        value = fields.get(key)
        if value is None:
            continue
        code = str(value).strip().lower()
        if code in _TRANSIENT_ERROR_CODES or code in {"408", "429", "500", "502", "503", "504", "529"}:
            return True
        if code in _PERMANENT_ERROR_CODES or (len(code) == 3 and code.isascii() and code.isdecimal() and 400 <= int(code) < 500):
            return False
    return True


class ProviderStreamError(RuntimeError):
    """A structured SSE error. Only redacted provider fields are retained."""

    provider_label = "Model"

    def __init__(self, event_type: str, code: str | None = None, *, fields=None, credentials=()):
        values = dict(fields or {})
        if code is not None:
            values["code"] = code
        self.retryable = _classification(values)
        self.event_type = redact_provider_value(str(event_type), credentials)
        self.fields = {k: redact_provider_value(str(v), credentials) for k, v in values.items()}
        self.code = self.fields.get("code") or self.fields.get("status") or self.fields.get("type")
        detail = f"; code={self.code}" if self.code else "; no error code supplied"
        super().__init__(f"{self.provider_label} provider generation failed ({self.event_type}{detail})")

    @classmethod
    def from_event(cls, event: dict, *, event_type=None, response=None, credentials=()):
        nested = event.get("response")
        sources = (nested.get("error") if isinstance(nested, dict) else None, event.get("error"), event)
        fields = {}
        for source in sources:
            if isinstance(source, str):
                fields.setdefault("message", source)
            elif isinstance(source, dict):
                for key in ("code", "type", "status", "param", "message", "request_id"):
                    value = source.get(key)
                    if key == "type" and source is event and isinstance(value, str) and value in {"error", "response.failed", "response.cancelled", "response.canceled", "response.completed", "response.incomplete"}:
                        continue
                    if isinstance(value, (str, int)) and not isinstance(value, bool) and value != "":
                        fields.setdefault(key, value)
        if response is not None:
            request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
            if request_id:
                fields.setdefault("request_id", request_id)
        return cls(event_type or "error", fields=fields, credentials=request_credentials(response, credentials))


class ResponsesStreamError(ProviderStreamError):
    provider_label = "Responses"

    @classmethod
    def from_event(cls, event: dict, *, event_type=None, response=None, credentials=()):
        return super().from_event(event, event_type=event_type or event.get("type") or "error",
                                  response=response, credentials=credentials)
