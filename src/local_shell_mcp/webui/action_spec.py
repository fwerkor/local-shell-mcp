"""LibreChat e8f3be08 data-provider/actions.ts OpenAPI Action mapping.

This module is importable without the optional YAML dependency; the browser
uses the original TypeScript implementation for preview and validation.
"""
from __future__ import annotations

import base64
import json
import re
from urllib.parse import urlsplit

DELIMITER = "_action_"
METHODS = {"get", "post", "put", "patch", "delete"}
ALL_METHODS = METHODS | {"head", "options", "trace"}
_DOMAIN_LENGTH = 10


def parse_spec(raw: str) -> dict:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 512 * 1024:
        raise ValueError("Invalid OpenAPI specification")
    try:
        try:
            spec = json.loads(raw)
        except json.JSONDecodeError:
            import yaml  # optional; deferred for worker bootstrap

            spec = yaml.safe_load(raw)
    except Exception as exc:
        raise ValueError("Error parsing OpenAPI spec.") from exc
    if not isinstance(spec, dict):
        raise ValueError("Error parsing OpenAPI spec.")
    servers = spec.get("servers")
    if not isinstance(servers, list) or not servers or not isinstance(servers[0], dict) or not servers[0].get("url"):
        raise ValueError("Could not find a valid URL in servers")
    paths = spec.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise ValueError("No paths found in the OpenAPI spec.")
    if len(paths) > 256:
        raise ValueError("Too many OpenAPI paths")
    return spec


def _ref(obj: object, components: dict, *, depth: int = 0) -> dict:
    if not isinstance(obj, dict):
        return {}
    if "$ref" not in obj:
        return obj
    if depth > 24:
        raise ValueError("Circular OpenAPI reference")
    path = obj["$ref"]
    if not isinstance(path, str) or not path.startswith("#/components/"):
        raise ValueError("Unsupported OpenAPI reference")
    found: object = components
    for component in path[len("#/components/"):].split("/"):
        key = component.replace("~1", "/").replace("~0", "~")
        if not isinstance(found, dict) or key not in found:
            raise ValueError("Could not resolve reference: " + path)
        found = found[key]
    return _ref(found, components, depth=depth + 1)


def operations(spec: dict) -> dict[str, dict]:
    """Return function schemas and execution configuration for each operation."""
    result: dict[str, dict] = {}
    for path, methods in spec["paths"].items():
        if not isinstance(path, str) or not path.startswith("/") or not isinstance(methods, dict):
            raise ValueError("Invalid OpenAPI path")
        for method, operation in methods.items():
            if method.lower() not in ALL_METHODS:
                continue
            if not isinstance(operation, dict):
                continue
            name = operation.get("operationId") or re.sub(r"[^a-zA-Z0-9_-]", "", method + "_" + path)
            if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", name):
                raise ValueError("Invalid OpenAPI operationId")
            if name in result:
                raise ValueError("Duplicate OpenAPI operationId")
            params: dict = {"type": "object", "properties": {}, "required": []}
            locations: dict[str, str] = {}
            for param in operation.get("parameters") or []:
                value = _ref(param, spec.get("components") or {})
                param_name = value.get("name")
                if not isinstance(param_name, str) or not isinstance(value.get("schema"), dict):
                    continue
                params["properties"][param_name] = _ref(value["schema"], spec.get("components") or {})
                if value.get("required"):
                    params["required"].append(param_name)
                place = value.get("in")
                locations[param_name] = place if place in {"query", "path", "header", "body"} else "query"
            content_type = ""
            if operation.get("requestBody"):
                body = _ref(operation["requestBody"], spec.get("components") or {})
                content = body.get("content") or {}
                if isinstance(content, dict) and content:
                    content_type = next(iter(content))
                    entry = content[content_type] or {}
                    schema = _ref(entry.get("schema"), spec.get("components") or {})
                    for prop, val in (schema.get("properties") or {}).items():
                        params["properties"][prop] = val
                        locations[prop] = "body"
                    params["required"].extend(schema.get("required") or [])
            strict = bool(operation.get("x-strict", False))
            if strict:
                params["additionalProperties"] = False
            result[name] = {
                "name": name, "method": method.lower(), "path": path,
                "description": operation.get("summary") or operation.get("description") or "",
                "parameters": params, "locations": locations,
                "content_type": content_type,
                "consequential": bool(operation.get("x-openai-isConsequential", False)),
                "strict": strict,
            }
    return result


def encoded_domain(domain: str) -> str:
    parsed = urlsplit(domain)
    host = parsed.netloc if parsed.scheme else domain.split("/")[0]
    if len(host) <= _DOMAIN_LENGTH:
        return host.replace(".", "---")
    return base64.b64encode(host.encode()).decode()[:_DOMAIN_LENGTH]


def legacy_domain(domain: str) -> str:
    if len(domain) <= _DOMAIN_LENGTH:
        return domain.replace(".", "---")
    return base64.b64encode(domain.encode()).decode()[:_DOMAIN_LENGTH]


def tool_name(operation_id: str, domain: str) -> str:
    return operation_id + DELIMITER + encoded_domain(domain)


def normalize_action_tool_name(name: str) -> str:
    """Port of data-provider/agentToolOptions.ts; normalize suffix only."""
    if not is_action_tool(name):
        return name
    idx = name.rfind(DELIMITER) + len(DELIMITER)
    return name[:idx] + name[idx:].replace("---", "_")


def is_action_tool(name: str) -> bool:
    idx = name.find(DELIMITER)
    mcp_idx = name.find("_mcp_")
    return idx >= 0 and (mcp_idx < 0 or mcp_idx < idx)


def validate_domain(domain: str, server: str) -> None:
    if not isinstance(domain, str) or not domain:
        raise ValueError("No domain provided")
    server_url = urlsplit(server)
    if server_url.scheme not in {"http", "https"} or not server_url.hostname:
        raise ValueError("Invalid OpenAPI server URL")
    if server_url.username or server_url.password or server_url.fragment:
        raise ValueError("Invalid OpenAPI server URL")
    client_url = urlsplit(domain if "://" in domain else "https://" + domain)
    if client_url.scheme not in {"http", "https"} or not client_url.hostname:
        raise ValueError("Invalid Action domain")
    if client_url.username or client_url.password or client_url.path not in {"", "/"} or client_url.query:
        raise ValueError("Invalid Action domain")
    if (server_url.hostname.lower() != client_url.hostname.lower()
            or (client_url.scheme != server_url.scheme and "://" in domain)
            or (client_url.scheme != server_url.scheme and
                not _ip_literal(client_url.hostname))):
        raise ValueError("Domain mismatch: The domain in the OpenAPI spec does not match the provided domain")
    if client_url.port is not None and client_url.port != (server_url.port or (443 if server_url.scheme == "https" else 80)):
        raise ValueError("Domain mismatch: port differs from OpenAPI server URL")


def _ip_literal(host: str) -> bool:
    import ipaddress
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False
