"""LibreChat MCP result formatter (packages/api/src/mcp/parsers.ts).

Raw CallToolResult is never discarded. These fields are an additional model/UI
projection. Image bytes are checked against the original parser's 10 MiB
configurable limit, not arbitrary Agent call-argument limits.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os


def _line(value):
    return str(value).replace("\r", " ").replace("\n", " ").replace("\u2028", " ").replace("\u2029", " ")


def _limit():
    try:
        value = int(os.environ.get("MCP_IMAGE_DATA_MAX_BYTES", "10485760"))
        return value if value > 0 else 10485760
    except ValueError:
        return 10485760


def _image(item):
    data = item["data"]
    if not data.startswith(("https://", "http://")):
        if (len(data) * 3 // 4) - (2 if data.endswith("==") else 1 if data.endswith("=") else 0) > _limit():
            raise ValueError("MCP image result exceeds maximum size")
        data = "data:" + item["mimeType"] + ";base64," + data
    return {"type": "image_url", "image_url": {"url": data}}


def _resource_body(resource):
    if resource.get("text"):
        return resource["text"], None, False
    if not resource.get("blob"):
        return None, None, False
    if str(resource.get("mimeType", "")).lower().startswith("image/"):
        return None, {"type": "image", "data": resource["blob"], "mimeType": resource["mimeType"]}, False
    binary = base64.b64decode(resource["blob"])
    try:
        value = binary.decode("utf-8")
        if "\x00" not in value:
            return value, None, False
    except UnicodeError:
        pass
    return f"Resource Content: {len(binary)} bytes of binary data (omitted; not UTF-8 text)", None, True


def format_tool_content(result: dict, provider: str = "openai") -> tuple[str, dict | None]:
    recognized = provider in {"openai", "azureopenai", "openrouter", "xai", "deepseek", "ollama", "bedrock", "anthropic", "google"}
    blocks = result.get("content") or []
    if not blocks:
        return "(No response)", None
    texts = []
    images = []
    ui = []
    for item in blocks:
        kind = item.get("type")
        if kind == "text":
            texts.append(item.get("text", ""))
        elif kind == "image":
            if recognized:
                images.append(_image(item))
            else:
                texts.append(json.dumps(item, ensure_ascii=False, indent=2))
        elif kind == "resource":
            resource = item.get("resource") or {}
            uri = resource.get("uri", "")
            details = []
            if recognized and uri.startswith("ui://"):
                content_to_hash = resource.get("text") or uri
                marker = hashlib.sha256(content_to_hash.encode()).hexdigest()[:10]
                ui.append({**resource, "resourceId": marker})
                details.extend([f"UI Resource ID: {marker}", "UI Resource Marker: \\ui{" + marker + "}"])
            else:
                body, image, binary = _resource_body(resource)
                if image and recognized:
                    images.append(_image(image))
                elif body:
                    details.append("Resource Text: " + body if recognized and not binary else body)
            if uri:
                details.append("Resource URI: " + _line(uri))
            if resource.get("mimeType"):
                details.append(("Resource MIME Type: " if recognized else "Type: ") + _line(resource["mimeType"]))
            if details:
                texts.append("\n".join(details))
        elif kind == "resource_link":
            details = []
            for key, label in (("name", "Resource Name"), ("title", "Resource Title"),
                               ("description", "Resource Description"), ("uri", "Resource URI"),
                               ("mimeType", "Resource MIME Type"), ("size", "Resource Size")):
                if key in item and item[key] is not None:
                    details.append(f"{label}: {_line(item[key])}" + (" bytes" if key == "size" else ""))
            if details:
                texts.append("\n".join(details))
        else:
            texts.append(json.dumps(item, ensure_ascii=False, indent=2))
    if ui:
        texts.append("UI Resource Markers Available:\n- Each resource above includes a stable ID and a marker hint like `\\ui{abc123}`\n- You should usually introduce what you're showing before placing the marker\n- For a single resource: \\ui{resource-id}\n- For multiple resources shown separately: \\ui{resource-id-a} \\ui{resource-id-b}\n- For multiple resources in a carousel: \\ui{resource-id-a,resource-id-b,resource-id-c}\n- The UI will be rendered inline where you place the marker\n- Format: \\ui{resource-id} or \\ui{id1,id2,id3} using the IDs provided above")
    artifacts = {}
    if images:
        artifacts["content"] = images
    if ui:
        artifacts["ui_resources"] = {"data": ui}
    text = "\n\n".join(filter(None, texts))
    return text or ("" if artifacts else "(No response)"), artifacts or None


def mcp_result_envelope(raw, tool_name):
    """Find a native LSM result while retaining the complete outer envelope."""
    if not isinstance(raw, dict):
        return None
    if isinstance(raw.get("content"), list) and all(isinstance(p, dict) and "type" in p for p in raw["content"]):
        return raw
    if tool_name == "mcp_tool_call" and isinstance(raw.get("data"), dict):
        return mcp_result_envelope(raw["data"].get("result"), "")
    return None
