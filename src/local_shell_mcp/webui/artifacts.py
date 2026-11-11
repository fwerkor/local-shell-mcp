"""LibreChat packages/api/src/artifacts/update.ts, preserving UTF-16 offsets.

Artifact rendering remains in the retained React components. This module edits
only the selected persisted artifact and never evaluates its generated code.
"""
from __future__ import annotations

import copy
import re

ARTIFACT_START = ":::artifact"
ARTIFACT_END = ":::"
_JS_WS = "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"


def _units(text: str) -> str:
    data = text.encode("utf-16-le", "surrogatepass")
    return "".join(chr(int.from_bytes(data[i:i+2], "little")) for i in range(0, len(data), 2))


def _text(units: str) -> str:
    return b"".join(ord(char).to_bytes(2, "little") for char in units).decode("utf-16-le", "surrogatepass")


def _line_end(text: str, start: int) -> int:
    index = text.find("\n", start)
    return len(text) if index == -1 else index


def _next_line(text: str, end: int) -> int:
    return len(text) if end >= len(text) else end + 1


def _fence(line: str) -> tuple[str, int] | None:
    match = re.match(r"(`{3,}|~{3,})", line.lstrip(_JS_WS))
    return (match[1][0], len(match[1])) if match else None


def _closing_fence(line: str, fence: tuple[str, int]) -> bool:
    return bool(re.fullmatch(re.escape(fence[0]) + "{" + str(fence[1]) + ",}", line.strip(_JS_WS)))


def _close_range(text: str, start: int, end: int) -> tuple[int, int] | None:
    line = text[start:end]
    position = next((i for i, char in enumerate(line) if char not in _JS_WS), -1)
    if position == -1:
        return None
    marker = start + position
    if not text.startswith(ARTIFACT_END, marker) or text.startswith(ARTIFACT_START, marker):
        return None
    return marker, marker + len(ARTIFACT_END)


def _artifact_close(text: str, start: int) -> tuple[int, int] | None:
    current = _next_line(text, _line_end(text, start))
    fence = None
    fallback = None
    while current < len(text):
        end = _line_end(text, current)
        line = text[current:end]
        close = _close_range(text, current, end)
        if close:
            if not fence:
                return close
            fallback = fallback or close
        opening = _fence(line)
        if opening and not fence:
            fence = opening
        elif fence and _closing_fence(line, fence):
            fence = None
            fallback = None
        current = _next_line(text, end)
    return fallback if fence else None


def find_all_artifacts(message: dict) -> list[dict]:
    artifacts = []

    def collect(value: str, source: str, part_index: int | None = None) -> None:
        text = _units(value)
        current = 0
        while (start := text.find(ARTIFACT_START, current)) != -1:
            close = _artifact_close(text, start)
            end = close[1] if close else len(text)
            entry = {"start": start, "end": end, "source": source, "text": value}
            if part_index is not None:
                entry["partIndex"] = part_index
            artifacts.append(entry)
            current = end

    for index, part in enumerate(message.get("content") or []):
        if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
            collect(part["text"], "content", index)
    if not artifacts and isinstance(message.get("text"), str) and message["text"]:
        collect(message["text"], "text")
    return artifacts


def _search_range(content: str) -> tuple[int, int] | None:
    first_end = _line_end(content, content.find(ARTIFACT_START))
    if first_end >= len(content):
        return None
    start = _next_line(content, first_end)
    close = _artifact_close(content, 0)
    end = close[0] if close else len(content)
    first = next((i for i in range(start, end) if content[i] not in _JS_WS), -1)
    fence = _fence(content[first:_line_end(content, first)]) if first != -1 else None
    if not fence:
        return start, end
    body = _next_line(content, _line_end(content, first))
    current = body
    while current < end:
        line_end = _line_end(content, current)
        if _closing_fence(content[current:line_end], fence):
            if content[line_end:end].strip(_JS_WS):
                return start, end
            return body, current - 1 if current > 0 and content[current-1] == "\n" else current
        current = _next_line(content, line_end)
    return body, end


def _before_closing_fence(text: str, start: int) -> bool:
    if start >= len(text) or text[start] not in "`~":
        return False
    marker = text[start]
    end = start + 1
    while end < len(text) and text[end] == marker:
        end += 1
    if end - start < 3:
        return False
    newline = False
    for index in range(end, len(text)):
        if text[index] == "\n":
            newline = True
        elif text[index] not in _JS_WS:
            return newline and text.startswith(ARTIFACT_END, index)
    return False


def replace_artifact_content(original_text: str, artifact: dict, original: str, updated: str) -> str | None:
    text = _units(original_text)
    content = _units(artifact["text"])[artifact["start"]:artifact["end"]]
    search = _search_range(content)
    if search is None:
        return None
    start, end = search
    inner = content[start:end]
    original = _units(original)
    updated = _units(updated)
    if original.endswith("\n"):
        original = original[:-1]
    relative = -1 if original == "" and inner.strip(_JS_WS) else inner.find(original)
    if relative == -1:
        return None
    absolute = artifact["start"] + start + relative
    suffix = text[absolute+len(original):]
    separator = "" if suffix.startswith("\n") or updated.endswith("\n") else "\n"
    replaced = text[:absolute] + updated + separator + suffix
    normalized = re.sub(r"\n{2,}", lambda match: "\n" if _before_closing_fence(replaced, match.end()) else match[0], replaced)
    return _text(normalized)


def unescape_latex(text: str | None) -> str | None:
    if not isinstance(text, str) or not text:
        return text
    result = re.sub(r"\\{1,2}\$", "$", text)
    return re.sub(r"\$\$\\\\(ce|pu)\{([^}]*)\}\$\$", lambda match: "$\\" + match[1] + "{" + match[2] + "}$", result)


def edit_artifact(message: dict, index: int, original: str, updated: str) -> tuple[dict, str]:
    """Apply POST /api/messages/artifact/:messageId's content selection rules."""
    artifacts = find_all_artifacts(message)
    if index < 0 or index >= len(artifacts):
        raise ValueError("Artifact index out of bounds")
    target = artifacts[index]
    result = copy.deepcopy(message)
    # packages/api/src/utils/latex.ts unescapeLaTeX reverses the retained client's preprocessing.
    original = unescape_latex(original)
    updated = unescape_latex(updated)
    replaced = replace_artifact_content(target["text"], target, original, updated)
    if not replaced:
        raise ValueError("Original content not found in target artifact")
    if target["source"] == "content":
        result["content"][target["partIndex"]]["text"] = replaced
        path = f"/content/{target['partIndex']}/text"
    else:
        result["text"] = replaced
        path = "/text"
    paths = result.get("userSubmittedPaths")
    paths = paths if isinstance(paths, list) else []
    result["userSubmittedPaths"] = list(dict.fromkeys(
        entry for entry in [*paths, path]
        if isinstance(entry, str) and entry.startswith("/") and len(_units(entry)) <= 2048))
    return result, path
