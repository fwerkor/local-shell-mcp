"""Owner-scoped, transient model encoding for source Steer attachment parts.

Source: packages/api/src/agents/steering/media.ts:buildSteerMedia. The
public SSE receipt contains only DB-derived references, not encoded bytes.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import stat
from pathlib import Path

from .steering import merged_text

# An entire human turn still has to fit the 15-MiB SQLite graph checkpoint.
# Avoid unbounded base64 expansion (including multiple large uploaded images).
_MAX_INLINE_BYTES = 5 * 1024 * 1024
_MAX_ONE_INLINE_BYTES = 4 * 1024 * 1024
_MAX_TEXT_BYTES = 96 * 1024


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


def _load_owned_file(path: str, root: Path, owner: str, limit: int) -> bytes:
    """Read trusted SQLite bytes; never trust client-supplied URL/path/MIME."""
    attachment_root = root / "attachments"
    owner_dir = attachment_root / hashlib.sha256(owner.encode()).hexdigest()[:32]
    candidate = Path(path)
    if (attachment_root.is_symlink() or owner_dir.is_symlink() or candidate.is_symlink() or
        not candidate.resolve().is_relative_to(owner_dir)):
        raise PermissionError("Attachment is outside the owner directory")
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
    blocks: list[dict] = [{"type": "text", "text": merged_text(item)}]
    remaining = _MAX_INLINE_BYTES
    for ref in item.get("files") or []:
        file_id = ref.get("file_id")
        if not isinstance(file_id, str):
            continue
        with database.connect() as db:
            row = db.execute("SELECT path,name FROM attachments WHERE id=? AND owner=?",
                             (file_id, owner)).fetchone()
        if row is None:
            continue
        name = row["name"]
        try:
            data = await asyncio.to_thread(_load_owned_file, row["path"], state_dir.resolve(), owner,
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
        except (OSError, ValueError, PermissionError, UnicodeError):
            blocks.append({"type": "text", "text": "Attachment " + name + " (" + file_id +
                           ") cannot be inlined; use authorized file tools if available."})
    return blocks


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
        else:
            result.append(message)
    return result
