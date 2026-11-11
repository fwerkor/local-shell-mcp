"""LibreChat ActionRequest/RequestExecutor behavior with connect-pinned SSRF checks.

This is a distinct HTTP Action backend, not a new LSM native or MCP tool.
Model tools remain subject to Agent selection and the runner's approval gate.
"""
from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import os
import socket
from urllib.parse import quote, urlsplit, urlunsplit

from .actions import ActionRepository

_MAX_RESPONSE = 256 * 1024
_TIMEOUT_S = 20.0
_METHODS = {"get", "post", "put", "patch", "delete"}


def _allowed_local(host: str, port: int) -> bool:
    # Operator-controlled environment, never request-supplied data. Unlike a
    # wildcard allowlist it is explicit to each host:port (SSRF exemption).
    allowed = {item.strip().lower() for item in os.getenv("LSM_ACTION_ALLOWED_ADDRESSES", "").split(",")}
    return (host.lower() + ":" + str(port)) in allowed


def _allowed_domain(host: str) -> bool:
    allow = [item.strip().lower() for item in os.getenv("LSM_ACTION_ALLOWED_DOMAINS", "").split(",") if item.strip()]
    return not allow or host.lower() in allow


def _resolve_address(host: str, port: int) -> str:
    """Pin a validated IP for the actual connection; no post-validation DNS lookup."""
    if not _allowed_domain(host):
        raise PermissionError("Action domain not allowed")
    answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not answers:
        raise ConnectionError("Action DNS resolution failed")
    approved = []
    for answer in answers:
        address = answer[4][0]
        if not _allowed_local(host, port) and not ipaddress.ip_address(address).is_global:
            raise PermissionError("Action target address not allowed")
        approved.append(address)
    return approved[0]


def _validate(value: object, schema: dict, *, prefix: str = "arguments") -> None:
    typ = schema.get("type")
    if typ == "object":
        if not isinstance(value, dict):
            raise ValueError(prefix + " must be an object")
        for name in schema.get("required") or []:
            if name not in value:
                raise ValueError(prefix + " is missing required parameter")
        properties = schema.get("properties") or {}
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            raise ValueError(prefix + " contains unknown parameters")
        for key, item in value.items():
            if key in properties and isinstance(properties[key], dict):
                _validate(item, properties[key], prefix=prefix + "." + key)
    elif typ == "array":
        if not isinstance(value, list):
            raise ValueError(prefix + " must be an array")
        for element in value:
            _validate(element, schema.get("items") or {}, prefix=prefix + "[]")
    elif typ == "string":
        if not isinstance(value, str):
            raise ValueError(prefix + " must be a string")
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 100_000):
            raise ValueError(prefix + " invalid string length")
    elif typ in ("integer", "number"):
        if type(value) not in (float, int) or (typ == "integer" and not isinstance(value, int)):
            raise ValueError(prefix + " must be numeric")
        if "minimum" in schema and value < schema["minimum"]:
            raise ValueError(prefix + " is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValueError(prefix + " is above maximum")
    elif typ == "boolean" and not isinstance(value, bool):
        raise ValueError(prefix + " must be boolean")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(prefix + " invalid enum member")


def _request(op: dict, args: dict) -> tuple[str, dict, dict, dict]:
    if op["method"] not in _METHODS:
        raise ValueError("Unsupported HTTP method")
    _validate(args, op["parameters"])
    path = op["path"]
    values = dict(args)
    for key, val in args.items():
        if op["locations"].get(key) == "path":
            needle = "{" + key + "}"
            if needle in path:
                path = path.replace(needle, quote(str(val), safe=""))
                values.pop(key, None)
    if "{" in path or "}" in path:
        raise ValueError("Missing required path parameter")
    query, body, headers = {}, {}, {}
    for key, val in values.items():
        place = op["locations"].get(key, "query" if op["method"] == "get" else "body")
        if place == "query":
            query[key] = val
        elif place == "body":
            body[key] = val
        elif place == "header":
            if key.lower() in {"authorization", "host", "cookie", "content-length", "connection",
                               "transfer-encoding", "proxy-authorization"}:
                raise ValueError("Reserved Action request header")
            headers[key] = str(val)
    return path, query, body, headers


def _full_url(server: str, path: str) -> str:
    # Original createURL: domain (OpenAPI servers[0].url) + path, not urljoin.
    base = urlsplit(server)
    if base.scheme not in {"http", "https"} or not base.hostname or base.username or base.password:
        raise ValueError("Invalid Action server URL")
    if not path.startswith("/") or path.startswith("//"):
        raise ValueError("Invalid Action path")
    if "?" in path or "#" in path:
        raise ValueError("Action path must not supply URL query or fragment")
    return urlunsplit((base.scheme, base.netloc, base.path.rstrip("/") + path, "", ""))


def _authorization(meta: dict, creds: dict) -> dict:
    auth = meta.get("auth") or {}
    kind = auth.get("type", "none")
    if kind == "none":
        return {}
    if kind == "oauth":
        # Interactive OAuth flow and refresh use a separate token lifecycle,
        # never silently downgrade an OAuth Action to unauthenticated access.
        raise RuntimeError("OAuth Action authorization required; interactive flow unavailable")
    if kind != "service_http" or not creds.get("api_key"):
        raise ValueError("Action credentials unavailable")
    key = creds["api_key"]
    if auth.get("authorization_type") == "basic":
        return {"Authorization": "Basic " + base64.b64encode(key.encode()).decode()}
    if auth.get("authorization_type") == "bearer":
        return {"Authorization": "Bearer " + key}
    if auth.get("authorization_type") == "custom":
        return {auth["custom_auth_header"]: key}
    raise ValueError("Invalid Action authentication")


async def execute_action(metadata: dict, creds: dict, operation: dict, arguments: dict) -> str:
    """Return JSON as text exactly as LibreChat Action tools expose response.data."""
    import httpx  # defer on Worker-only installations

    path, query, body, headers = _request(operation, arguments)
    url = _full_url(operation["server"], path)
    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    # Include a nondefault port in Host, but preserve full original authority.
    ip = await asyncio.to_thread(_resolve_address, parsed.hostname, port)
    ip_authority = "[" + ip + "]" if ":" in ip else ip
    if parsed.port:
        ip_authority += ":" + str(parsed.port)
    pinned_url = urlunsplit((parsed.scheme, ip_authority, parsed.path, parsed.query, ""))
    auth_headers = _authorization(metadata, creds)
    req_headers = {"Host": parsed.netloc, **headers, **auth_headers}
    if operation["content_type"]:
        req_headers["Content-Type"] = operation["content_type"]
    # TLS verify uses original server hostname, not pinned IP. trust_env=False
    # prevents HTTP(S)_PROXY from causing a second, unverified lookup.
    def scrub_response(text: str) -> str:
        # An echoing API cannot put our Authorization credentials into the
        # model-visible tool result or its persisted SSE step result.
        for secret in creds.values():
            if not isinstance(secret, str) or not secret:
                continue
            text = text.replace(secret, "[redacted]")
            text = text.replace(base64.b64encode(secret.encode()).decode(), "[redacted]")
        return text

    try:
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False,
                                     timeout=httpx.Timeout(_TIMEOUT_S), verify=True) as client:
            kwargs = {"headers": req_headers, "params": query, "extensions": {"sni_hostname": parsed.hostname}}
            if operation["method"] != "get":
                kwargs["json"] = body
            async with client.stream(operation["method"].upper(), pinned_url, **kwargs) as response:
                if not 200 <= response.status_code < 300:
                    return "API call failed (HTTP " + str(response.status_code) + ")"
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > _MAX_RESPONSE:
                        return "API call failed (response too large)"
                raw = bytes(chunks)
                if not raw:
                    return ""
                try:
                    value = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    return scrub_response(raw.decode("utf-8", errors="replace"))
                rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":")) if isinstance(value, (dict, list)) else str(value)
                return scrub_response(rendered)
    except asyncio.CancelledError:
        raise  # No retry, audit output or SSE on cancellation.
    except httpx.TimeoutException:
        return "API call failed (timeout)"
    except httpx.RequestError:
        return "API call failed (network error)"


async def invoke_action(owner: str, agent_id: str, tool: str, arguments: dict, database) -> str:
    record = ActionRepository(database).get_for_tool(owner, agent_id, tool)
    if record is None:
        raise PermissionError("Action is not bound to this Agent")
    meta, creds, operation = record
    try:
        return await execute_action(meta, creds, operation, arguments)
    except asyncio.CancelledError:
        raise
    except (PermissionError, ValueError) as exc:
        # Validation messages never echo model arguments or credentials.
        return "API call failed (" + type(exc).__name__ + ")"
    except Exception:
        return "API call failed (execution error)"
