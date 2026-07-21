from __future__ import annotations

import asyncio
import hashlib
from typing import Any
from urllib.parse import urlsplit

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

import local_shell_mcp.jobs as jobs_module
import local_shell_mcp.tools as tools
from local_shell_mcp.fs_ops import delete_path, resolve_path
from local_shell_mcp.remote_transfer import remote_transfer_routes
from local_shell_mcp.settings import get_settings
from local_shell_mcp.transfer_ops import (
    transfer_abort_write,
    transfer_alloc_temp_path,
    transfer_begin_write,
    transfer_finish_write,
    transfer_pack_dir,
    transfer_read_chunk,
    transfer_stat,
    transfer_unpack_archive,
    transfer_write_bytes,
    transfer_write_chunk,
)


class FakeRemoteManager:
    def __init__(self) -> None:
        self.client = TestClient(Starlette(routes=remote_transfer_routes()))

    async def call(
        self,
        machine: str,
        tool: str,
        args: dict[str, Any],
        timeout_s: int | None = None,
    ) -> dict[str, Any]:
        del machine, timeout_s
        try:
            if tool == "transfer_stat":
                data = transfer_stat(args["path"], args.get("sha256", True))
            elif tool == "transfer_read_chunk":
                data = transfer_read_chunk(
                    args["path"], args.get("offset", 0), args.get("chunk_size")
                )
            elif tool == "transfer_begin_write":
                data = transfer_begin_write(
                    args["path"],
                    args.get("overwrite", True),
                    args.get("expected_bytes"),
                )
            elif tool == "transfer_write_chunk":
                data = transfer_write_chunk(
                    args["path"],
                    args["transfer_id"],
                    args["offset"],
                    args["data_b64"],
                    args.get("expected_sha256"),
                )
            elif tool == "transfer_finish_write":
                data = transfer_finish_write(
                    args["path"],
                    args["transfer_id"],
                    args.get("expected_bytes"),
                    args.get("expected_sha256"),
                )
            elif tool == "transfer_abort_write":
                data = transfer_abort_write(args["path"], args["transfer_id"])
            elif tool == "transfer_upload_url":
                source = resolve_path(args["path"], must_exist=True)
                offset = int(args.get("offset", 0))
                chunk_size = int(args.get("chunk_size") or source.stat().st_size or 1)
                with source.open("rb") as handle:
                    handle.seek(offset)
                    content = handle.read(chunk_size)
                end = offset + len(content)
                headers = {"X-Chunk-SHA256": hashlib.sha256(content).hexdigest()}
                if source.stat().st_size:
                    headers["Content-Range"] = f"bytes {offset}-{end - 1}/{source.stat().st_size}"
                response = await asyncio.to_thread(
                    self.client.put,
                    urlsplit(args["url"]).path,
                    content=content,
                    headers=headers,
                )
                payload = response.json()
                if response.status_code >= 400 or not payload.get("ok"):
                    raise RuntimeError(payload)
                data = payload["data"]
            elif tool == "transfer_download_url":
                response = await asyncio.to_thread(self.client.get, urlsplit(args["url"]).path)
                if response.status_code >= 400:
                    raise RuntimeError(response.json())
                begin = transfer_begin_write(
                    args["path"],
                    args.get("overwrite", True),
                    args["expected_bytes"],
                )
                try:
                    transfer_write_bytes(
                        args["path"],
                        begin["transfer_id"],
                        0,
                        response.content,
                    )
                    finish = transfer_finish_write(
                        args["path"],
                        begin["transfer_id"],
                        args["expected_bytes"],
                        args["expected_sha256"],
                    )
                except Exception:
                    transfer_abort_write(args["path"], begin["transfer_id"])
                    raise
                data = {**finish, "transport": "http-stream"}
            elif tool == "transfer_alloc_temp_path":
                data = transfer_alloc_temp_path(args.get("suffix", ".bin"))
            elif tool == "transfer_pack_dir":
                data = transfer_pack_dir(args["path"], args.get("compression", "gz"))
            elif tool == "transfer_unpack_archive":
                data = transfer_unpack_archive(
                    args["archive_path"],
                    args["dst_path"],
                    args.get("overwrite", True),
                    args.get("cleanup_archive", True),
                )
            elif tool == "delete_file_or_dir":
                data = delete_path(args["path"], args.get("recursive", False))
            else:
                raise ValueError(f"unsupported fake remote tool: {tool}")
            return {"ok": True, "message": "", "data": data}
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__, "message": str(exc)}


def _workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".local-shell-mcp"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "http://testserver")
    get_settings.cache_clear()
    monkeypatch.setattr(tools, "remote_manager", lambda: FakeRemoteManager())
    return tmp_path


@pytest.mark.asyncio
async def test_remote_copy_file_streams_between_workers(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    (root / "src-machine").mkdir()
    (root / "dst-machine").mkdir()
    data = bytes(range(256)) * 24
    (root / "src-machine" / "payload.bin").write_bytes(data)
    calls: list[str] = []
    transfer = tools._remote_transfer_data

    async def record_transfer(machine, tool, args, timeout_s=None):
        calls.append(tool)
        return await transfer(machine, tool, args, timeout_s)

    monkeypatch.setattr(tools, "_remote_transfer_data", record_transfer)

    result = await tools._copy_remote_file_to_remote(
        "src", "src-machine/payload.bin", "dst", "dst-machine/payload.bin", True, 1024
    )

    assert result["chunks"] == 7
    assert result["chunk_size"] == 1024
    assert result["transport"] == "http-chunks-via-controller"
    assert result["bytes"] == len(data)
    assert calls[0] == "transfer_stat"
    assert calls[1:7] == ["transfer_upload_url"] * 6
    assert calls[7] == "transfer_download_url"
    assert (root / "dst-machine" / "payload.bin").read_bytes() == data


@pytest.mark.asyncio
async def test_remote_upload_recovers_lost_chunk_acknowledgement(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    (root / "src-machine").mkdir()
    payload = bytes(range(256)) * 12
    (root / "src-machine" / "payload.bin").write_bytes(payload)

    class LostAckManager(FakeRemoteManager):
        def __init__(self):
            super().__init__()
            self.drop_next_ack = True
            self.upload_calls = 0

        async def call(self, machine, tool, args, timeout_s=None):
            result = await super().call(machine, tool, args, timeout_s)
            if tool == "transfer_upload_url":
                self.upload_calls += 1
                if self.drop_next_ack:
                    self.drop_next_ack = False
                    return {
                        "ok": False,
                        "error": "ConnectionError",
                        "message": "response lost after commit",
                    }
            return result

    manager = LostAckManager()
    monkeypatch.setattr(tools, "remote_manager", lambda: manager)

    result = await tools._copy_remote_file_to_local(
        "src",
        "src-machine/payload.bin",
        "copied.bin",
        True,
        1024,
    )

    assert result["transport"] == "http-chunks"
    assert result["chunks"] == 3
    assert manager.upload_calls == 3
    assert (root / "copied.bin").read_bytes() == payload


@pytest.mark.asyncio
async def test_streaming_transfer_preserves_chunk_size_validation(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    (root / "payload.bin").write_bytes(b"content")

    with pytest.raises(ValueError, match="chunk_size must be greater than zero"):
        await tools._copy_local_file_to_remote("payload.bin", "dst", "copied.bin", True, 0)


@pytest.mark.asyncio
async def test_transfer_path_starts_tracked_managed_job(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    (root / "src-machine").mkdir()
    payload = bytes(range(256)) * 12
    (root / "src-machine" / "payload.bin").write_bytes(payload)

    job = await tools._start_transfer_job(
        "src-machine/payload.bin",
        "copied.bin",
        source_machine="src",
        overwrite=True,
        chunk_size=1024,
    )

    assert job["kind"] == "managed"
    assert job["backend"] == "managed"
    assert job["status"] == "running"

    current = job
    for _ in range(100):
        await asyncio.sleep(0.01)
        current = (await jobs_module.list_jobs())["jobs"][0]
        if current["status"] != "running":
            break

    assert current["status"] == "succeeded"
    assert current["progress"]["phase"] == "completed"
    assert current["result"]["transport"] == "http-chunks"
    assert (root / "copied.bin").read_bytes() == payload
    tail = await jobs_module.tail_job(job["job_id"])
    assert "transfer started" in tail["output"]
    assert "transfer completed" in tail["output"]


@pytest.mark.asyncio
async def test_remote_copy_dir_packs_transfers_and_unpacks(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    (root / "src-machine" / "run" / "nested").mkdir(parents=True)
    (root / "dst-machine").mkdir()
    (root / "src-machine" / "run" / "nested" / "result.txt").write_text("ok", encoding="utf-8")

    result = await tools._copy_remote_dir_to_remote(
        "src", "src-machine/run", "dst", "dst-machine/run-copy", True, 256
    )

    assert result["entries"] >= 1
    assert (root / "dst-machine" / "run-copy" / "nested" / "result.txt").read_text(
        encoding="utf-8"
    ) == "ok"
