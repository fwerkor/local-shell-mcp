"""Port of LibreChat controllers/agents/protocol.js at e8f3be08.

Request markers may only lower a job's immutable negotiated protocol. Keeping
this separate from transport lets SQLite retries and SSE share the same rule.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

GENERATION_PROTOCOL_HEADER = "x-librechat-generation-protocol"


def parse_protocol_version(value: Any) -> int | None:
    # JavaScript strict equality accepts numeric 1/2, but never booleans or
    # arrays. Python's bool is an int subclass, so it must be excluded.
    if type(value) in (int, float, str):
        if value in (1, "1"):
            return 1
        if value in (2, "2"):
            return 2
    return None


def requested_generation_protocol(body: Mapping | None = None,
                                  query: Mapping | None = None,
                                  headers: Mapping | None = None) -> int:
    advertised = [value for value in (
        (body or {}).get("generationProtocolVersion"),
        (query or {}).get("generationProtocolVersion"),
        (headers or {}).get(GENERATION_PROTOCOL_HEADER),
    ) if value is not None]
    if not advertised:
        return 1
    return 2 if all(parse_protocol_version(value) == 2 for value in advertised) else 1


def job_generation_protocol(metadata: Mapping | None = None) -> int:
    return parse_protocol_version((metadata or {}).get("generationProtocolVersion")) or 1


def negotiate_generation_protocol(body: Mapping | None = None,
                                  query: Mapping | None = None,
                                  headers: Mapping | None = None,
                                  *, metadata: Mapping | None = None) -> int:
    requested = requested_generation_protocol(body, query, headers)
    return min(requested, 2 if metadata is None else job_generation_protocol(metadata))


def request_protocol(request: Any, body: Mapping | None = None, *,
                     stored_version: int | None = None) -> int:
    # Duplicate markers remain arrays (invalid), matching Express query
    # parsing rather than silently accepting the last advertised version.
    def markers(values: Any, key: str) -> dict:
        items = values.getlist(key)
        return {key: items[0] if len(items) == 1 else items} if items else {}

    return negotiate_generation_protocol(
        body,
        markers(request.query_params, "generationProtocolVersion"),
        markers(request.headers, GENERATION_PROTOCOL_HEADER),
        metadata=None if stored_version is None else {"generationProtocolVersion": stored_version},
    )
