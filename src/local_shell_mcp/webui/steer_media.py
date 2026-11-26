"""Owner-scoped, transient model encoding for source Steer attachment parts.

Source: packages/api/src/agents/steering/media.ts:buildSteerMedia. The
public SSE receipt contains only DB-derived references, not encoded bytes.
"""
from __future__ import annotations

import asyncio
import base64
import os
import stat
from pathlib import Path

from .steering import merged_text

# An entire human turn still has to fit the 15-MiB SQLite graph checkpoint.
# Avoid unbounded base64 expansion (including multiple large uploaded images).
_MAX_INLINE_BYTES = 5 * 1024 * 1024
_MAX_ONE_INLINE_BYTES = 4 * 1024 * 1024
_MAX_TEXT_BYTES = 96 * 1024


def attachment_reference(path: str, name: str, mime: str = "") -> str:
    """Markdown link to the actual local path (not a browser download URL)."""
    label = "image" if mime.startswith("image/") or Path(name).suffix.lower() in {
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".svg",
    } else "file"
    # Angle-delimited Markdown permits spaces; escape delimiter/control bytes.
    target = path.replace("%", "%25").replace("<", "%3C").replace(">", "%3E")
    return f"[{label}](<{target}>)"


def _detected_type(blob: bytes) -> str | None:
    if blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if blob.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if blob[:6] in {b"GIF87a", b"GIF89a"}:
        return "image/gif"
    if blob.startswith(b"RIFF") and blob[8:12] == b"WEBP":
        return "image/webp"
    if blob.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def _load_owned_file(path: str, root: Path, limit: int) -> bytes:
    """Read trusted SQLite bytes; never trust client-supplied URL/path/MIME."""
    attachment_root = root / "attachments"
    candidate = Path(path)
    # Ownership was checked by the caller's SQLite query. Both legacy and
    # date-based directories are valid, but never follow storage symlinks.
    if (not candidate.is_relative_to(attachment_root) or
        candidate.resolve() != candidate):
        raise PermissionError("Attachment is outside the storage directory")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(candidate, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("Attachment exceeds the model inline budget")
        with os.fdopen(os.dup(fd), "rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Attachment exceeds the model inline budget")
        return data
    finally:
        os.close(fd)


async def encode_steer_media(database, owner: str, item: dict, state_dir: Path) -> list[dict]:
    """Assemble image/document and text context in original file order.

    Read from owned SQLite records at INJECTION, not enqueue time. Missing,
    revoked or oversized files are represented as text-only references, so
    failures never suppress the user's actual steering instruction.
    """
    text = merged_text(item)
    blocks: list[dict] = [{"type": "text", "text": text}] if text.strip() else []
    references = []
    remaining = _MAX_INLINE_BYTES
    for ref in item.get("files") or []:
        file_id = ref.get("file_id")
        if not isinstance(file_id, str):
            continue
        with database.connect() as db:
            row = db.execute("SELECT path,name,content_type FROM attachments WHERE id=? AND owner=?",
                             (file_id, owner)).fetchone()
        if row is None:
            continue
        name = row["name"]
        candidate = Path(row["path"])
        try:
            if candidate.is_relative_to(state_dir.resolve() / "attachments") and candidate.resolve() == candidate:
                references.append(attachment_reference(str(candidate), name, row["content_type"]))
            data = await asyncio.to_thread(_load_owned_file, row["path"], state_dir.resolve(),
                                           min(_MAX_ONE_INLINE_BYTES, remaining))
            detected = _detected_type(data)
            if detected is not None:
                # Store only canonical bytes and server-detected MIME, not the
                # browser's forgeable content-type or filepath metadata.
                encoded = base64.b64encode(data).decode("ascii")
                blocks.append({"type": "image_url", "image_url": {
                    "url": "data:" + detected + ";base64," + encoded,
                }} if detected.startswith("image/") else {
                    "type": "file", "file": {"filename": name,
                                              "file_data": "data:application/pdf;base64," + encoded},
                })
                remaining -= len(data)
            else:
                # Allow readable text context, never transmit arbitrary file
                # bytes as a fabricated image type.
                if len(data) > _MAX_TEXT_BYTES:
                    raise ValueError("Text attachment exceeds inline budget")
                text = data.decode("utf-8")
                if "\x00" in text:
                    raise ValueError("Binary attachment")
                blocks.append({"type": "text", "text": "Attachment " + name + ":\n" + text})
                remaining -= len(data)
        except (OSError, ValueError, PermissionError, UnicodeError, RuntimeError):
            blocks.append({"type": "text", "text": "Attachment " + name + " (" + file_id +
                           ") cannot be inlined; use authorized file tools if available."})
    if references:
        # Keep the reference separate from the original steering instruction.
        reference_block = {"type": "text", "text": "\n".join(references)}
        if not text.strip():
            blocks.insert(0, reference_block)
        else:
            blocks.append(reference_block)
    return blocks or [{"type": "text", "text": "Attachment is no longer available."}]


async def stamp_model_messages(database, owner: str, messages: list[dict], state_dir: Path) -> list[dict]:
    """Encode media just-in-time, never into LangGraph/SQLite checkpoints.

    A historical Steer part has the same trusted file IDs as a live part. The
    model adapter excludes non-provider `source` and `files` metadata.
    """
    result = []
    for message in messages:
        if message.get("role") == "user" and message.get("source") == "steer":
            payload = {key: val for key, val in message.items() if key != "files"}
            files = message.get("files") or []
            if files:
                payload["content"] = await encode_steer_media(
                    database, owner, {"text": str(message.get("content") or ""), "files": files},
                    state_dir,
                )
            result.append(payload)
        elif message.get("role") == "user" and message.get("source") == "attachment":
            payload = {key: val for key, val in message.items() if key != "files"}
            content = message.get("content")
            # Ordinary uploads already carry durable path references. Add
            # native image blocks from owned records, not client MIME/data.
            if not isinstance(content, list) or not any(
                part.get("type") in {"image", "image_url"} for part in content
            ):
                images = []
                remaining = _MAX_INLINE_BYTES
                for ref in message.get("files") or []:
                    with database.connect() as db:
                        row = db.execute("SELECT path,name,content_type FROM attachments WHERE id=? AND owner=?",
                                         (ref.get("file_id"), owner)).fetchone()
                    if row is None:
                        continue
                    if not (row["content_type"].startswith("image/") or
                            Path(row["name"]).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}):
                        continue
                    try:
                        data = await asyncio.to_thread(_load_owned_file, row["path"], state_dir.resolve(),
                                                       min(_MAX_ONE_INLINE_BYTES, remaining))
                        mime = _detected_type(data)
                        if mime and mime.startswith("image/"):
                            images.append({"type": "image_url", "image_url": {
                                "url": "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")}})
                            remaining -= len(data)
                    except (OSError, ValueError, PermissionError, RuntimeError):
                        continue
                if images:
                    payload["content"] = ([{"type": "text", "text": content}]
                                          if isinstance(content, str) else list(content or [])) + images
            result.append(payload)
        else:
            result.append(message)
    return result


def without_attachment_images(messages: list[dict]) -> tuple[list[dict], bool]:
    """Drop only images backed by owned attachment references; retain all text."""
    result = []
    changed = False
    for message in messages:
        content = message.get("content")
        if (message.get("role") == "user" and message.get("source") in {"steer", "attachment"}
                and isinstance(content, list) and any(
                    part.get("type") == "text" and "[image](" in part.get("text", "")
                    for part in content
                )):
            filtered = [part for part in content if part.get("type") not in {"image", "image_url"}]
            if len(filtered) != len(content):
                changed = True
                message = {**message, "content": filtered}
                if all(part.get("type") == "text" for part in filtered):
                    message["content"] = "\n".join(part["text"] for part in filtered if part.get("text"))
        result.append(message)
    return result, changed
