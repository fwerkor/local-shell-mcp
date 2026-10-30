from __future__ import annotations

from io import BytesIO
from typing import BinaryIO

import zstandard as zstd

ZstdError = zstd.ZstdError


def stream_writer(destination: BinaryIO, *, level: int):
    return zstd.ZstdCompressor(level=level).stream_writer(destination, closefd=False)


def compress_bytes(value: bytes, *, level: int = 6) -> bytes:
    """Create an independently readable, checksummed zstd frame."""
    return zstd.ZstdCompressor(level=level, write_checksum=True).compress(value)


def decompress_bytes(value: bytes) -> bytes:
    # stream_reader supports frames without a known uncompressed content size.
    with zstd.ZstdDecompressor().stream_reader(BytesIO(value)) as reader:
        return reader.read()
