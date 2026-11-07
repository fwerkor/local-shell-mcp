"""Line-oriented JSON browser-session RPC over private parent/child stdio.

Run this file with a system Python that has Playwright installed. It imports
browser_sessions.py as a plain source file, with no LSM runtime dependencies.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

if __package__:
    from .browser_sessions import BrowserSessionManager
else:
    from browser_sessions import BrowserSessionManager

_ALLOWED_METHODS = {"manage", "start", "close", "snapshot", "act"}


async def _serve(state_dir: Path, *, input_stream=None, output_stream=None) -> None:  # noqa: ANN001
    manager = BrowserSessionManager(state_dir)
    input_stream = input_stream if input_stream is not None else sys.stdin.buffer
    output_stream = output_stream if output_stream is not None else sys.stdout
    try:
        while line := await asyncio.to_thread(input_stream.readline):
            try:
                request = json.loads(line)
                method = request["method"]
                if method not in _ALLOWED_METHODS:
                    raise ValueError(f"unsupported browser method: {method}")
                result = await getattr(manager, method)(*request["args"], **request["kwargs"])
                response = {"ok": True, "result": result}
            except Exception as exc:
                response = {"ok": False, "error_type": type(exc).__name__, "message": str(exc)}
            output_stream.write(
                json.dumps(response, ensure_ascii=True, separators=(",", ":")) + "\n"
            )
            output_stream.flush()
    finally:
        await manager.manage(action="cleanup")


if __name__ == "__main__":
    asyncio.run(_serve(Path(sys.argv[1])))
