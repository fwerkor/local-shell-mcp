"""External Playwright session transport for frozen, dependency-light LSM binaries."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from .fs_ops import resolve_path
from .settings import get_settings
from .shell_environment import subprocess_env

_MAX_RESPONSE_BYTES = 64 * 1024 * 1024


class ExternalBrowserSessionManager:
    def __init__(self, state_dir: Path) -> None:
        self._state_dir = Path(state_dir)
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._next_request_id = 0
        self._lock = asyncio.Lock()

    @staticmethod
    def _service_path() -> Path:
        if getattr(sys, "frozen", False):
            return (
                Path(sys._MEIPASS)
                / "local_shell_mcp"
                / "browser_external"
                / "browser_external_service.py"
            )
        return Path(__file__).resolve().parent / "browser_external_service.py"

    async def _spawn(self) -> asyncio.subprocess.Process:
        process = self._process
        if process is not None:
            if process.returncode is None:
                return process
            if self._reader_task is not None:
                await self._reader_task
        settings = get_settings()
        environment = subprocess_env()
        environment["LOCAL_SHELL_MCP_WORKSPACE_ROOT"] = str(settings.workspace_root.resolve())
        try:
            process = await asyncio.create_subprocess_exec(
                str(settings.python_bin),
                "-u",
                str(self._service_path()),
                str(self._state_dir),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=environment,
            )
        except OSError as exc:
            raise RuntimeError(
                f"External Python is unavailable ({settings.python_bin}); "
                "configure LOCAL_SHELL_MCP_PYTHON_BIN and install playwright in that environment"
            ) from exc
        self._process = process
        self._reader_task = asyncio.create_task(self._read_responses(process))
        return process

    async def _read_responses(self, process: asyncio.subprocess.Process) -> None:
        error: Exception = RuntimeError("External browser process exited unexpectedly")
        try:
            assert process.stdout is not None
            while True:
                header = await process.stdout.readline()
                if not header:
                    break
                if len(header) > 16 or not header.endswith(b"\n"):
                    raise ValueError("Invalid browser RPC frame header")
                length = int(header)
                if not 0 < length <= _MAX_RESPONSE_BYTES:
                    raise ValueError("Browser RPC response exceeds maximum frame size")
                reply = json.loads(await process.stdout.readexactly(length))
                future = self._pending.pop(reply["id"], None)
                if future is not None and not future.done():
                    future.set_result(reply)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            error = RuntimeError(f"External browser RPC failed: {exc}")
        finally:
            if self._process is process:
                self._process = None
                self._reader_task = None
                for future in self._pending.values():
                    if not future.done():
                        future.set_exception(error)
                self._pending.clear()
            if process.returncode is None:
                process.kill()
            await process.wait()

    async def _discard(self) -> None:
        async with self._lock:
            process = self._process
            reader = self._reader_task
            self._process = None
            self._reader_task = None
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(RuntimeError("External browser process was stopped"))
            self._pending.clear()
            if reader is not None:
                reader.cancel()
            if process is not None and process.returncode is None:
                process.kill()
        if reader is not None:
            await asyncio.gather(reader, return_exceptions=True)
        if process is not None:
            await process.wait()

    async def _request(self, method: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        request_id: int | None = None
        future: asyncio.Future[dict[str, Any]] | None = None
        process: asyncio.subprocess.Process | None = None
        try:
            async with self._lock:
                process = await self._spawn()
                assert process.stdin is not None
                self._next_request_id += 1
                request_id = self._next_request_id
                future = asyncio.get_running_loop().create_future()
                self._pending[request_id] = future
                request = json.dumps(
                    {"id": request_id, "method": method, "args": args, "kwargs": kwargs},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                process.stdin.write(request.encode("utf-8") + b"\n")
                await process.stdin.drain()
        except asyncio.CancelledError:
            if request_id is not None:
                self._pending.pop(request_id, None)
            if future is not None:
                future.cancel()
            raise
        except Exception:
            if request_id is not None:
                self._pending.pop(request_id, None)
            if future is not None:
                future.cancel()
            if process is not None:
                await self._discard()
            raise

        assert request_id is not None and future is not None
        try:
            reply = await future
        except asyncio.CancelledError:
            self._pending.pop(request_id, None)
            future.cancel()
            raise
        if not reply["ok"]:
            message = reply.get("message") or "External browser request failed"
            if reply.get("error_type") == "ValueError":
                raise ValueError(message)
            raise RuntimeError(message)
        return reply["result"]

    @staticmethod
    def _resolve_storage_paths(kwargs: dict[str, Any], action: str) -> dict[str, Any]:
        result = kwargs.copy()
        if action == "start" and result.get("storage_state_path"):
            result["storage_state_path"] = str(
                resolve_path(result["storage_state_path"], must_exist=True)
            )
        if action == "close" and result.get("save_storage_state_path"):
            result["save_storage_state_path"] = str(resolve_path(result["save_storage_state_path"]))
        return result

    async def manage(self, **kwargs: Any) -> dict[str, Any]:
        return await self._request(
            "manage",
            **self._resolve_storage_paths(kwargs, str(kwargs.get("action", "")).strip().lower()),
        )

    async def start(self, **kwargs: Any) -> dict[str, Any]:
        return await self._request("start", **self._resolve_storage_paths(kwargs, "start"))

    async def close(
        self, session_id: str, *, save_storage_state_path: str | None = None
    ) -> dict[str, Any]:
        return await self._request(
            "close",
            session_id,
            **self._resolve_storage_paths(
                {"save_storage_state_path": save_storage_state_path}, "close"
            ),
        )

    async def snapshot(self, session_id: str, **kwargs: Any) -> dict[str, Any]:
        return await self._request("snapshot", session_id, **kwargs)

    async def act(
        self, session_id: str, actions: list[dict[str, Any]], **kwargs: Any
    ) -> dict[str, Any]:
        return await self._request("act", session_id, actions, **kwargs)
