"""Offline o200k_base encoding for WebUI, lazy-loaded only when counting tokens.

Port of LibreChat packages/api/src/utils/tokenizer.ts with the official OpenAI
BPE rank file shipped as package data rather than downloaded at runtime.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

_HASH = '446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d'
_PATTERN = '|'.join((
    r"[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]*[\p{Ll}\p{Lm}\p{Lo}\p{M}]+(?i:'s|'t|'re|'ve|'m|'ll|'d)?",
    r"[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]+[\p{Ll}\p{Lm}\p{Lo}\p{M}]*(?i:'s|'t|'re|'ve|'m|'ll|'d)?",
    r"\p{N}{1,3}", r" ?[^\s\p{L}\p{N}]+[\r\n/]*",
    r"\s*[\r\n]+", r"\s+(?!\S)", r"\s+",
))


@lru_cache(maxsize=1)
def _encoding():
    import base64
    import gzip
    import hashlib

    import tiktoken  # optional WebUI dependency; not used by Worker startup

    # The official rank file is compressed in the release artifact to avoid
    # committing 199,998 lines of upstream BPE data as an enormous text diff.
    # Decode in memory (no tempfile and no runtime downloader or cache URL).
    source = Path(__file__).parent / 'encodings' / 'o200k_base.tiktoken.gz'
    raw = gzip.decompress(source.read_bytes())
    if hashlib.sha256(raw).hexdigest() != _HASH:
        raise ValueError('Bundled o200k_base token ranks failed integrity validation')
    ranks = {}
    for line in raw.splitlines():
        token, rank = line.split()
        ranks[base64.b64decode(token)] = int(rank)
    return tiktoken.Encoding(name='o200k_base', pat_str=_PATTERN,
                             mergeable_ranks=ranks,
                             special_tokens={'<|endoftext|>': 199999, '<|endofprompt|>': 200018})


@lru_cache(maxsize=1)
def _warn_missing_encoding() -> None:
    _LOGGER.warning(
        "WebUI tokenizer dependencies are unavailable; using conservative UTF-8 byte "
        "counts until local-shell-mcp[webui] is installed"
    )


def count_tokens(text: str, *, exact: bool = True) -> int:
    """Count offline BPE tokens, or conservatively bound them without WebUI extras.

    o200k_base is byte-level BPE: every encoded byte is at most one token.
    When tiktoken or its regex dependency is unavailable, counting UTF-8 bytes
    may prune earlier, but must not underestimate the model's token budget or
    abort a chat, memory update, or background generation with ImportError.
    The ``exact`` flag only applies when the real tokenizer is available.
    """
    try:
        encoding = _encoding()
    except ImportError:
        _warn_missing_encoding()
        return len(text.encode('utf-8', 'surrogatepass'))
    if exact:
        return len(encoding.encode(text, disallowed_special=()))
    # LibreChat's TypeScript tokenizer slices UTF-16 code units, not Python
    # Unicode code points. Avoid splitting a surrogate pair at either seam.
    units = memoryview(text.encode('utf-16-le', 'surrogatepass')).cast('H')
    js_space = frozenset((9, 10, 11, 12, 13, 32, 0x00A0, 0x1680, *range(0x2000, 0x200B),
                         0x2028, 0x2029, 0x202F, 0x205F, 0x3000, 0xFEFF))
    total = 0
    offset = 0
    while offset < len(units):
        end = min(offset + 4096, len(units))
        last_whitespace = False
        run = 0
        for index in range(offset, end):
            whitespace = units[index] in js_space
            run = run + 1 if whitespace == last_whitespace else 1
            last_whitespace = whitespace
            if run >= 256:
                end = index + 1
                break
        if end < len(units) and 0xD800 <= units[end - 1] <= 0xDBFF and 0xDC00 <= units[end] <= 0xDFFF:
            end -= 1
        chunk = units[offset:end].tobytes().decode('utf-16-le', 'surrogatepass')
        total += len(encoding.encode(chunk, disallowed_special=()))
        offset = end
    return total
