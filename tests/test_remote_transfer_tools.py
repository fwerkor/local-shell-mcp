from __future__ import annotations

import asyncio
import hashlib
import os
import threading
import time
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
        *,
        lane: str | None = None,
    ) -> dict[str, Any]:
        del machine, timeout_s
        assert lane == "transfer"
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
            elif tool == "transfer_put_url":
                source = resolve_path(args["path"], must_exist=True)
                response = await asyncio.to_thread(
                    self.client.put,
                    urlsplit(args["url"]).path,
                    content=source.read_bytes(),
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

    assert result["chunks"] == 1
    assert result["chunk_size"] == len(data)
    assert result["transport"] == "controller-http-relay"
    assert result["bytes"] == len(data)
    assert calls == ["transfer_stat", "transfer_put_url", "transfer_download_url"]
    assert "transfer_read_chunk" not in calls
    assert "transfer_write_chunk" not in calls
    assert "transfer_upload_url" not in calls
    assert (root / "dst-machine" / "payload.bin").read_bytes() == data


@pytest.mark.asyncio
async def test_remote_cleanup_file_stays_on_transfer_lane(monkeypatch):
    captured = {}

    class Manager:
        async def call(self, machine, tool, args, timeout_s=None, *, lane=None):
            captured.update(
                machine=machine,
                tool=tool,
                args=args,
                timeout_s=timeout_s,
                lane=lane,
            )
            return {"ok": True, "message": "", "data": {"deleted": True}}

    monkeypatch.setattr(tools, "remote_manager", Manager)

    await tools._remote_cleanup_file("worker-a", "/tmp/archive.tar.gz")  # noqa: SLF001

    assert captured == {
        "machine": "worker-a",
        "tool": "delete_file_or_dir",
        "args": {"path": "/tmp/archive.tar.gz", "recursive": False},
        "timeout_s": None,
        "lane": "transfer",
    }


@pytest.mark.asyncio
async def test_cancelled_remote_unpack_cleans_destination_archive(monkeypatch):
    cleaned: list[tuple[str, str]] = []

    async def transfer(machine, tool, args, timeout_s=None):
        del timeout_s
        if tool == "transfer_alloc_temp_path":
            return {"path": "remote-transfer.tar.gz"}
        if tool == "transfer_unpack_archive":
            raise asyncio.CancelledError
        raise AssertionError((machine, tool, args))

    async def copy_local(*args, **kwargs):
        del args, kwargs
        return {"chunks": 1}

    async def cleanup(machine, path):
        cleaned.append((machine, path))

    monkeypatch.setattr(tools, "_remote_transfer_data", transfer)
    monkeypatch.setattr(tools, "_copy_local_file_to_remote", copy_local)
    monkeypatch.setattr(tools, "_remote_cleanup_file", cleanup)

    pack = {
        "path": "src",
        "archive_path": "source.tar.gz",
        "bytes": 1,
        "sha256": "digest",
    }
    with pytest.raises(asyncio.CancelledError):
        await tools._copy_packed_dir_to_remote(pack, None, "worker-a", "dst", True, None)

    assert cleaned == [("worker-a", "remote-transfer.tar.gz")]


def test_controller_relay_staging_prunes_interrupted_transaction_files(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    relay_dir = root / ".local-shell-mcp" / "transfer-relay"
    relay_dir.mkdir(parents=True)
    stale_files = [
        relay_dir / "relay-dead.bin",
        relay_dir / ".relay-dead.bin.local-shell-mcp-transfer-txn.tmp",
        relay_dir / ".relay-dead.bin.local-shell-mcp-transfer-txn.tmp.json",
    ]
    cutoff = time.time() - 100_000
    for path in stale_files:
        path.write_bytes(b"stale")
        os.utime(path, (cutoff, cutoff))
    fresh = relay_dir / ".relay-live.bin.local-shell-mcp-transfer-txn.tmp"
    fresh.write_bytes(b"active")

    tools._controller_relay_staging_path()

    assert all(not path.exists() for path in stale_files)
    assert fresh.exists()


def test_controller_relay_staging_rejects_symlink(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    state_dir = root / ".local-shell-mcp"
    state_dir.mkdir(parents=True, exist_ok=True)
    external = tmp_path.parent / f"{tmp_path.name}-external-relay"
    external.mkdir()
    victim = external / "relay-victim.bin"
    victim.write_bytes(b"keep")
    relay_dir = state_dir / "transfer-relay"
    try:
        relay_dir.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(ValueError, match="must not be a symlink"):
        tools._controller_relay_staging_path()

    assert victim.read_bytes() == b"keep"


@pytest.mark.asyncio
async def test_local_stream_download_refreshes_temp_archive_lease(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    source_dir = root / "archive-source"
    source_dir.mkdir()
    (source_dir / "payload.bin").write_bytes(b"payload")
    pack = transfer_pack_dir("archive-source")
    archive = resolve_path(pack["archive_path"], must_exist=True)
    refreshed = threading.Event()
    original_refresh = tools.refresh_temp_file_lease

    def record_refresh(path, *, create=True):
        if path == archive:
            refreshed.set()
        return original_refresh(path, create=create)

    async def queued_download(machine, tool, args, timeout_s=None):
        del machine, args, timeout_s
        assert tool == "transfer_download_url"
        assert await asyncio.to_thread(refreshed.wait, 2)
        return {"path": "destination/archive.tar.gz"}

    monkeypatch.setattr(tools, "refresh_temp_file_lease", record_refresh)
    monkeypatch.setattr(tools, "_remote_transfer_data", queued_download)

    result = await tools._copy_local_file_to_remote(
        pack["archive_path"],
        "worker-a",
        "destination/archive.tar.gz",
    )

    assert result["transport"] == "http-stream"
    assert refreshed.is_set()
    delete_path(pack["archive_path"], False)


@pytest.mark.asyncio
async def test_remote_stream_upload_preserves_failure_when_ticket_is_removed(monkeypatch):
    calls = 0

    async def fail_upload(*args, **kwargs):
        nonlocal calls
        del args, kwargs
        calls += 1
        raise RuntimeError("stream upload failed with HTTP 400")

    monkeypatch.setattr(tools, "_remote_transfer_data", fail_upload)
    monkeypatch.setattr(
        tools,
        "get_upload_ticket_status",
        lambda token: (_ for _ in ()).throw(FileNotFoundError(token)),
    )

    with pytest.raises(RuntimeError, match="stream upload failed with HTTP 400"):
        await tools._stream_remote_file_to_upload_ticket(
            "source-worker",
            "source.bin",
            7,
            hashlib.sha256(b"payload").hexdigest(),
            {"token": "removed", "url": "http://testserver/upload/removed"},
            None,
        )

    assert calls == 1


@pytest.mark.asyncio
async def test_remote_stream_upload_preserves_worker_failure_when_poll_loses_ticket(monkeypatch):
    release_upload = asyncio.Event()

    async def fail_after_poll(*args, **kwargs):
        del args, kwargs
        await release_upload.wait()
        raise RuntimeError("receiver rejected streamed checksum")

    def missing_status(token):
        del token
        release_upload.set()
        raise FileNotFoundError("ticket removed")

    monkeypatch.setattr(tools, "_remote_transfer_data", fail_after_poll)
    monkeypatch.setattr(tools, "get_upload_ticket_status", missing_status)

    with pytest.raises(RuntimeError, match="receiver rejected streamed checksum"):
        await tools._stream_remote_file_to_upload_ticket(
            "source-worker",
            "source.bin",
            7,
            hashlib.sha256(b"payload").hexdigest(),
            {"token": "removed", "url": "http://testserver/upload/removed"},
            None,
        )


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

        async def call(self, machine, tool, args, timeout_s=None, *, lane=None):
            result = await super().call(machine, tool, args, timeout_s, lane=lane)
            if tool == "transfer_put_url":
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

    assert result["transport"] == "http-stream"
    assert result["chunks"] == 1
    assert manager.upload_calls == 1
    assert (root / "copied.bin").read_bytes() == payload


@pytest.mark.asyncio
async def test_streaming_transfer_preserves_chunk_size_validation(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    (root / "payload.bin").write_bytes(b"content")

    with pytest.raises(ValueError, match="chunk_size must be greater than zero"):
        await tools._copy_local_file_to_remote("payload.bin", "dst", "copied.bin", True, 0)


@pytest.mark.asyncio
async def test_local_to_remote_streams_source_without_snapshot(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    data = b"content"
    (root / "payload.bin").write_bytes(data)
    created: list[str] = []
    revoked: list[str] = []
    digest = hashlib.sha256(data).hexdigest()

    def create_ticket(source_path):
        created.append(source_path)
        return {
            "token": "ticket",
            "url": "http://testserver/remote/transfer/download/ticket",
            "path": source_path,
            "bytes": len(data),
            "sha256": digest,
        }

    async def transfer(machine, tool, args, timeout_s=None):
        del machine, timeout_s
        assert tool == "transfer_download_url"
        return {
            "path": args["path"],
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    monkeypatch.setattr(tools, "create_stream_download_ticket", create_ticket)
    monkeypatch.setattr(
        tools,
        "revoke_transfer_ticket",
        lambda token: revoked.append(token) or {"revoked": True},
    )
    monkeypatch.setattr(tools, "_remote_transfer_data", transfer)

    result = await tools._copy_local_file_to_remote("payload.bin", "dst", "copied.bin")

    assert result["transport"] == "http-stream"
    assert created == ["payload.bin"]
    assert result["sha256"] == digest
    assert revoked == ["ticket"]


@pytest.mark.asyncio
async def test_local_to_remote_revokes_ticket_when_lease_refresh_loses_source(
    tmp_path, monkeypatch
):
    root = _workspace(tmp_path, monkeypatch)
    data = b"content"
    (root / "payload.bin").write_bytes(data)
    lease_failed = asyncio.Event()
    revoked: list[str] = []
    digest = hashlib.sha256(data).hexdigest()

    def create_ticket(source_path):
        return {
            "token": "ticket",
            "url": "http://testserver/remote/transfer/download/ticket",
            "path": source_path,
            "bytes": len(data),
            "sha256": digest,
        }

    async def refresh_lease(source_path):
        assert source_path == "payload.bin"
        lease_failed.set()
        raise FileNotFoundError(source_path)

    async def transfer(machine, tool, args, timeout_s=None):
        del machine, timeout_s
        assert tool == "transfer_download_url"
        await asyncio.wait_for(lease_failed.wait(), timeout=2)
        await asyncio.sleep(0)
        return {
            "path": args["path"],
            "bytes": len(data),
            "sha256": digest,
        }

    monkeypatch.setattr(tools, "create_stream_download_ticket", create_ticket)
    monkeypatch.setattr(tools, "_refresh_controller_temp_lease", refresh_lease)
    monkeypatch.setattr(
        tools,
        "revoke_transfer_ticket",
        lambda token: revoked.append(token) or {"revoked": True},
    )
    monkeypatch.setattr(tools, "_remote_transfer_data", transfer)

    result = await tools._copy_local_file_to_remote("payload.bin", "dst", "copied.bin")

    assert result["transport"] == "http-stream"
    assert revoked == ["ticket"]


@pytest.mark.asyncio
async def test_cancelled_local_to_remote_stream_revokes_ticket(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    (root / "payload.bin").write_bytes(b"content")
    started = asyncio.Event()
    revoked: list[str] = []

    def create_ticket(source_path):
        return {
            "token": "ticket",
            "url": "http://testserver/remote/transfer/download/ticket",
            "path": source_path,
            "bytes": len(b"content"),
            "sha256": hashlib.sha256(b"content").hexdigest(),
        }

    async def transfer(machine, tool, args, timeout_s=None):
        del machine, tool, args, timeout_s
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(tools, "create_stream_download_ticket", create_ticket)
    monkeypatch.setattr(
        tools,
        "revoke_transfer_ticket",
        lambda token: revoked.append(token) or {"revoked": True},
    )
    monkeypatch.setattr(tools, "_remote_transfer_data", transfer)

    task = asyncio.create_task(
        tools._copy_local_file_to_remote("payload.bin", "dst", "copied.bin")
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert revoked == ["ticket"]


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
    assert current["result"]["transport"] == "http-stream"
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
