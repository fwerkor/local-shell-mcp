"""Archive recovery must accept both sized and streaming zstd frames."""
from io import BytesIO

import pytest

from local_shell_mcp import audit_archive_codec as codec


def test_checksummed_frame_roundtrip_and_corruption():
    payload = b"audit event\n" * 100
    encoded = codec.compress_bytes(payload)
    assert codec.decompress_bytes(encoded) == payload
    damaged = encoded[:-1] + bytes([encoded[-1] ^ 1])
    with pytest.raises(codec.ZstdError):
        codec.decompress_bytes(damaged)


def test_streaming_frame_without_content_size():
    target = BytesIO()
    with codec.stream_writer(target, level=3) as writer:
        writer.write(b"first\n")
        writer.write(b"second\n")
    assert codec.decompress_bytes(target.getvalue()) == b"first\nsecond\n"
