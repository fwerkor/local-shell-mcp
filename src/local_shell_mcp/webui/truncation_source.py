"""UTF-16-exact pure ports of the pinned agents@4.0.1 tool truncation helpers.

Source: src/utils/truncation.ts. This is the structured call-input/result
*text* projection. It does not replace the ToolContent provider-native block
serialization rules, and must not mutate the SQLite source of record.
"""
from __future__ import annotations

import json
import math


def _utf16_len(value: str) -> int:
    return len(value.encode('utf-16-le', 'surrogatepass')) // 2


def _js_slice(value: str, start: int, end: int | None = None) -> str:
    data = value.encode('utf-16-le', 'surrogatepass')
    size = len(data) // 2
    begin = min(size, max(0, start if start >= 0 else size + start))
    stop = size if end is None else min(size, max(0, end if end >= 0 else size + end))
    result = data[begin * 2: max(begin, stop) * 2].decode('utf-16-le', 'surrogatepass')
    if result and 0xDC00 <= ord(result[0]) <= 0xDFFF:
        result = result[1:]
    if result and 0xD800 <= ord(result[-1]) <= 0xDBFF:
        result = result[:-1]
    return result


def truncate_tool_input(value: str | object, max_chars: int) -> dict:
    serialized = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    original_length = _utf16_len(serialized)
    if original_length <= max_chars:
        return {'_truncated': serialized, '_originalChars': original_length}
    indicator = f'\n… [truncated: {original_length} chars exceeded {max_chars} limit] …\n'
    available = max_chars - _utf16_len(indicator)
    if available < 100:
        return {'_truncated': _js_slice(serialized, 0, max_chars) + indicator.rstrip(),
                '_originalChars': original_length}
    head = math.ceil(available * .7)
    tail = available - head
    return {'_truncated': _js_slice(serialized, 0, head) + indicator + _js_slice(serialized, -tail),
            '_originalChars': original_length}


def truncate_tool_result_content(content: str, max_chars: int) -> str:
    size = _utf16_len(content)
    if size <= max_chars:
        return content
    indicator = f'\n\n… [truncated: {size} chars exceeded {max_chars} limit] …\n\n'
    available = max_chars - _utf16_len(indicator)
    if available <= 0:
        return _js_slice(content, 0, max_chars)
    if available < 200:
        return _js_slice(content, 0, available) + indicator.rstrip()
    head_size = math.ceil(available * .7)
    tail_size = available - head_size
    head_end = head_size
    encoded = content.encode('utf-16-le', 'surrogatepass')
    # JS `String.lastIndexOf`/`indexOf` offset is UTF-16 code units.
    end = min(len(encoded), (head_size + 1) * 2)
    backward = encoded.rfind(b'\x0a\x00', 0, end)
    head_newline = backward // 2 if backward >= 0 else -1
    if head_newline > head_size - 200 and head_newline > 0:
        head_end = head_newline
    tail_start = size - tail_size
    forward = encoded.find(b'\x0a\x00', tail_start * 2)
    tail_newline = forward // 2 if forward >= 0 else -1
    if tail_newline > 0 and tail_newline < tail_start + 200:
        tail_start = tail_newline + 1
    return _js_slice(content, 0, head_end) + indicator + _js_slice(content, tail_start)
