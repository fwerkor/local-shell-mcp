"""Canonical Chat Completions content parts -> native Anthropic/Gemini parts.

No client-originated media URLs are fetched. The only data URLs created by LSM
come from owner-checked SQLite attachment bytes at the generation boundary.
"""
from __future__ import annotations

import base64


def native_content_parts(content, provider: str) -> list[dict]:
    if isinstance(content, str):
        return ([{"type": "text", "text": content} if provider == "anthropic" else {"text": content}]
                if content else [])
    if not isinstance(content, list):
        return []
    result = []
    for part in content:
        if not isinstance(part, dict):
            continue
        kind = part.get("type")
        if kind == "text" and isinstance(part.get("text"), str):
            result.append({"type": "text", "text": part["text"]} if provider == "anthropic"
                          else {"text": part["text"]})
        elif kind in {"image_url", "file"}:
            data_url = ((part.get("image_url") or {}).get("url") if kind == "image_url"
                        else (part.get("file") or {}).get("file_data"))
            if not isinstance(data_url, str) or not data_url.startswith("data:") or ";base64," not in data_url:
                continue
            mime, data = data_url[5:].split(";base64,", 1)
            if mime not in {"image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"}:
                continue
            # A provider-compatible payload must contain canonical base64.
            try:
                if base64.b64encode(base64.b64decode(data, validate=True)).decode("ascii") != data:
                    continue
            except (ValueError, base64.binascii.Error):
                continue
            if provider == "anthropic":
                result.append({"type": "image" if mime.startswith("image/") else "document",
                               "source": {"type": "base64", "media_type": mime, "data": data}})
            else:
                result.append({"inlineData": {"mimeType": mime, "data": data}})
    return result
