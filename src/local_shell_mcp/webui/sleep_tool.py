"""Controller-local, cancellable waiting for Agent tool loops."""
from __future__ import annotations

import asyncio
import json
import time

SLEEP_TOOLS = [{"type": "function", "function": {
    "name": "sleep",
    "description": (
        "Wait without running a model or worker. Use before polling an external service "
        "or retrying a transient failure; avoid busy polling. For long-running recurring "
        "work, prefer scheduled conversations."
    ),
    "parameters": {"type": "object", "properties": {
        "seconds": {"type": "number", "minimum": 0, "maximum": 300, "default": 10,
                    "description": "Seconds to wait (default 10, maximum 300)."},
    }, "additionalProperties": False},
}}]


def sleep_seconds(arguments):
    seconds = arguments.get("seconds", 10)
    if (set(arguments) - {"seconds"} or type(seconds) not in (int, float)
            or not 0 <= seconds <= 300):
        raise ValueError("seconds must be a number between 0 and 300")
    return seconds


async def invoke_sleep(seconds, check_grant):
    start = time.monotonic()
    deadline = start + seconds
    while True:
        check_grant()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        # Cancellation propagates immediately. Recheck leases during longer waits.
        await asyncio.sleep(min(remaining, 5))
    return json.dumps({"slept_seconds": round(time.monotonic() - start, 3)})
