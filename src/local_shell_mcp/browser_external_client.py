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


class ExternalBrowserSessionManager:
    def __init__(self, state_dir: Path) -> None:
        self._state_dir = Path(state_dir)
        self._process: asyncio.subprocess.Process | None = None
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
        if process is not None and process.returncode is None:
            return process
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
                limit=4 * 1024 * 1024,
            )
        except OSError as exc:
            raise RuntimeError(
                f"External Python is unavailable ({settings.python_bin}); "
                "configure LOCAL_SHELL_MCP_PYTHON_BIN and install playwright in that environment"
            ) from exc
        self._process = process
        return process

    async def _discard(self) -> None:
        process = self._process
        self._process = None
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()

    async def _request(self, method: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        async with self._lock:
            process = await self._spawn()
            assert process.stdin is not None and process.stdout is not None
            request = json.dumps(
                {"method": method, "args": args, "kwargs": kwargs},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            try:
                process.stdin.write(request.encode("utf-8") + b"\n")
                await process.stdin.drain()
                line = await process.stdout.readline()
                if not line:
                    raise RuntimeError("External browser process exited unexpectedly")
                reply = json.loads(line)
            except (Exception, asyncio.CancelledError):
                await self._discard()
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
