"""Framed JSON browser-session RPC over private parent/child stdio.

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
    write_lock = asyncio.Lock()
    pending: set[asyncio.Task[None]] = set()
    inflight: dict[int, asyncio.Task[None]] = {}

    async def respond(line: bytes) -> None:
        request_id = None
        try:
            request = json.loads(line)
            request_id = request["id"]
            method = request["method"]
            if method not in _ALLOWED_METHODS:
                raise ValueError(f"unsupported browser method: {method}")
            result = await getattr(manager, method)(*request["args"], **request["kwargs"])
            response = {"id": request_id, "ok": True, "result": result}
        except Exception as exc:
            response = {
                "id": request_id,
                "ok": False,
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
        # ASCII escaping is necessary when the child uses a non-UTF-8 pipe encoding.
        payload = json.dumps(response, ensure_ascii=True, separators=(",", ":"))
        async with write_lock:
            output_stream.write(f"{len(payload)}\n{payload}")
            output_stream.flush()

    def on_done(task: asyncio.Task[None], request_id: int | None) -> None:
        pending.discard(task)
        if request_id is not None and inflight.get(request_id) is task:
            inflight.pop(request_id, None)

    try:
        while line := await asyncio.to_thread(input_stream.readline):
            try:
                message = json.loads(line)
            except (ValueError, TypeError):
                message = None
            if isinstance(message, dict) and isinstance(message.get("cancel"), int):
                task = inflight.get(message["cancel"])
                if task is not None:
                    task.cancel()
                continue
            request_id = message.get("id") if isinstance(message, dict) else None
            task = asyncio.create_task(respond(line))
            pending.add(task)
            if isinstance(request_id, int):
                inflight[request_id] = task
            task.add_done_callback(lambda done, rid=request_id: on_done(done, rid))
    finally:
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await manager.manage(action="cleanup")


if __name__ == "__main__":
    asyncio.run(_serve(Path(sys.argv[1])))
