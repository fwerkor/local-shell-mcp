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
    transfer_refresh_stream_write,
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
        expected_lane = "interactive" if tool == "transfer_refresh_stream_write" else "transfer"
        assert lane == expected_lane
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
            elif tool == "transfer_refresh_stream_write":
                transfer_refresh_stream_write(args["path"], args["transfer_id"])
                data = {"refreshed": True}
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
                    if args.get("defer_commit", False):
                        data = {
                            "path": begin["path"],
                            "temp_path": begin["temp_path"],
                            "transfer_id": begin["transfer_id"],
                            "bytes": len(response.content),
                            "sha256": None,
                            "transport": "http-staged",
                        }
                    else:
                        finish = transfer_finish_write(
                            args["path"],
                            begin["transfer_id"],
                            args["expected_bytes"],
                            args["expected_sha256"],
                        )
                        data = {**finish, "transport": "http-stream"}
                except Exception:
                    transfer_abort_write(args["path"], begin["transfer_id"])
                    raise
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

    assert result["chunks"] == 6
    assert result["chunk_size"] == 1024
    assert result["transport"] == "controller-http-relay"
    assert result["bytes"] == len(data)
    assert calls == [
        "transfer_stat",
        *(["transfer_upload_url"] * 6),
        "transfer_download_url",
    ]
    assert "transfer_read_chunk" not in calls
    assert "transfer_write_chunk" not in calls
    assert "transfer_put_url" not in calls
    assert (root / "dst-machine" / "payload.bin").read_bytes() == data


@pytest.mark.asyncio
async def test_remote_copy_defaults_to_64_mib_http_chunks(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    (root / "src-machine").mkdir()
    (root / "dst-machine").mkdir()
    payload = b"payload"
    (root / "src-machine" / "payload.bin").write_bytes(payload)
    upload_chunk_sizes: list[int] = []
    transfer = tools._remote_transfer_data

    async def record_transfer(machine, tool, args, timeout_s=None):
        if tool == "transfer_upload_url":
            upload_chunk_sizes.append(int(args["chunk_size"]))
        return await transfer(machine, tool, args, timeout_s)

    monkeypatch.setattr(tools, "_remote_transfer_data", record_transfer)

    result = await tools._copy_remote_file_to_remote(
        "src",
        "src-machine/payload.bin",
        "dst",
        "dst-machine/payload.bin",
        True,
    )

    assert upload_chunk_sizes == [64 * 1024 * 1024]
    assert result["chunks"] == 1
    assert result["transport"] == "controller-http-relay"
    assert (root / "dst-machine" / "payload.bin").read_bytes() == payload


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
async def test_staged_write_lease_refresh_uses_interactive_lane(monkeypatch):
    seen = asyncio.Event()

    class Manager:
        async def call(self, machine, tool, args, timeout_s=None, *, lane=None):
            assert machine == "worker-a"
            assert tool == "transfer_refresh_stream_write"
            assert args == {"path": "staged.bin", "transfer_id": "txn"}
            assert timeout_s == 30
            assert lane == "interactive"
            seen.set()
            return {"ok": True, "message": "", "data": {"refreshed": True}}

    monkeypatch.setattr(tools, "remote_manager", lambda: Manager())
    monkeypatch.setattr(tools, "_REMOTE_STAGED_LEASE_REFRESH_INTERVAL_S", 0.001)

    task = asyncio.create_task(
        tools._refresh_remote_staged_write_lease("worker-a", "staged.bin", "txn")
    )
    await asyncio.wait_for(seen.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


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

    digest = pack["sha256"]

    async def queued_download(machine, tool, args, timeout_s=None):
        del machine, timeout_s
        if tool == "transfer_download_url":
            assert await asyncio.to_thread(refreshed.wait, 2)
            return {
                "path": args["path"],
                "transfer_id": "staged",
                "bytes": pack["bytes"],
                "transport": "http-staged",
            }
        assert tool == "transfer_finish_write"
        return {"path": args["path"], "bytes": pack["bytes"], "sha256": digest}

    monkeypatch.setattr(tools, "refresh_temp_file_lease", record_refresh)
    monkeypatch.setattr(tools, "_remote_transfer_data", queued_download)
    monkeypatch.setattr(
        tools,
        "get_download_ticket_status",
        lambda token: {"completed": True, "sha256": digest},
    )

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
            put_tool="transfer_gui_temp_put_url",
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
    assert result["chunk_size"] == 1024
    assert manager.upload_calls == 3
    assert (root / "copied.bin").read_bytes() == payload


@pytest.mark.asyncio
async def test_chunked_upload_requires_verified_digest():
    with pytest.raises(tools.RemoteTransferError, match="requires a verified source digest"):
        await tools._stream_remote_file_to_upload_ticket(
            "source-worker",
            "source.bin",
            7,
            None,
            {"token": "ticket", "url": "http://testserver/upload/ticket"},
        )


@pytest.mark.asyncio
async def test_chunked_upload_rejects_unexpected_ack(monkeypatch):
    digest = hashlib.sha256(b"payload").hexdigest()

    async def upload(*args, **kwargs):
        del args, kwargs
        return {"received_bytes": 0}

    monkeypatch.setattr(tools, "_remote_transfer_data", upload)

    with pytest.raises(tools.RemoteTransferError, match="acknowledged offset 0, expected 7"):
        await tools._stream_remote_file_to_upload_ticket(
            "source-worker",
            "source.bin",
            7,
            digest,
            {"token": "ticket", "url": "http://testserver/upload/ticket"},
        )


@pytest.mark.asyncio
async def test_chunked_upload_retries_uncommitted_failure(monkeypatch):
    digest = hashlib.sha256(b"payload").hexdigest()
    upload_calls = 0
    status_calls = 0

    async def upload(*args, **kwargs):
        nonlocal upload_calls
        del args, kwargs
        upload_calls += 1
        if upload_calls == 1:
            raise RuntimeError("transient upload failure")
        return {"received_bytes": 7}

    def status(token):
        nonlocal status_calls
        assert token == "ticket"
        status_calls += 1
        if status_calls == 1:
            return {"received_bytes": 0, "completed": False}
        return {
            "received_bytes": 7,
            "completed": True,
            "sha256": digest,
        }

    async def no_sleep(delay):
        assert delay == 0.25

    monkeypatch.setattr(tools, "_remote_transfer_data", upload)
    monkeypatch.setattr(tools, "get_upload_ticket_status", status)
    monkeypatch.setattr(tools.asyncio, "sleep", no_sleep)

    result = await tools._stream_remote_file_to_upload_ticket(
        "source-worker",
        "source.bin",
        7,
        digest,
        {"token": "ticket", "url": "http://testserver/upload/ticket"},
    )

    assert upload_calls == 2
    assert result["completed"] is True
    assert result["chunks"] == 1


@pytest.mark.asyncio
async def test_chunked_upload_rejects_incomplete_final_status(monkeypatch):
    digest = hashlib.sha256(b"payload").hexdigest()

    async def upload(*args, **kwargs):
        del args, kwargs
        return {"received_bytes": 7}

    monkeypatch.setattr(tools, "_remote_transfer_data", upload)
    monkeypatch.setattr(
        tools,
        "get_upload_ticket_status",
        lambda token: {"received_bytes": 7, "completed": False},
    )

    with pytest.raises(tools.RemoteTransferError, match="upload did not complete"):
        await tools._stream_remote_file_to_upload_ticket(
            "source-worker",
            "source.bin",
            7,
            digest,
            {"token": "ticket", "url": "http://testserver/upload/ticket"},
        )


@pytest.mark.asyncio
async def test_legacy_stream_finalizes_staged_digest_from_worker(monkeypatch):
    digest = hashlib.sha256(b"payload").hexdigest()

    async def transfer(machine, tool, args, timeout_s=None):
        del machine, args, timeout_s
        assert tool == "transfer_gui_temp_put_url"
        return {"sha256": digest}

    monkeypatch.setattr(tools, "_remote_transfer_data", transfer)
    monkeypatch.setattr(
        tools,
        "get_upload_ticket_status",
        lambda token: {
            "received_bytes": 7,
            "completed": False,
            "staged": True,
            "sha256": digest,
        },
    )
    monkeypatch.setattr(
        tools,
        "finalize_upload_ticket",
        lambda token, expected_sha256: {
            "completed": True,
            "received_bytes": 7,
            "sha256": expected_sha256,
        },
    )

    result = await tools._stream_remote_file_to_upload_ticket(
        "source-worker",
        "source.bin",
        7,
        None,
        {"token": "ticket", "url": "http://testserver/upload/ticket"},
        put_tool="transfer_gui_temp_put_url",
    )

    assert result["completed"] is True
    assert result["sha256"] == digest


@pytest.mark.asyncio
async def test_legacy_stream_finalizes_staged_digest_from_source_stat(monkeypatch):
    digest = hashlib.sha256(b"payload").hexdigest()

    async def transfer(machine, tool, args, timeout_s=None):
        del machine, args, timeout_s
        if tool == "transfer_gui_temp_put_url":
            return {}
        assert tool == "transfer_gui_temp_stat"
        return {"size": 7, "sha256": digest}

    monkeypatch.setattr(tools, "_remote_transfer_data", transfer)
    monkeypatch.setattr(
        tools,
        "get_upload_ticket_status",
        lambda token: {
            "received_bytes": 7,
            "completed": False,
            "staged": True,
            "sha256": digest,
        },
    )
    monkeypatch.setattr(
        tools,
        "finalize_upload_ticket",
        lambda token, expected_sha256: {
            "completed": True,
            "received_bytes": 7,
            "sha256": expected_sha256,
        },
    )

    result = await tools._stream_remote_file_to_upload_ticket(
        "source-worker",
        "source.bin",
        7,
        None,
        {"token": "ticket", "url": "http://testserver/upload/ticket"},
        put_tool="transfer_gui_temp_put_url",
        stat_tool="transfer_gui_temp_stat",
    )

    assert result["sha256"] == digest


@pytest.mark.asyncio
async def test_legacy_stream_rejects_changed_source_during_finalize(monkeypatch):
    digest = hashlib.sha256(b"payload").hexdigest()

    async def transfer(machine, tool, args, timeout_s=None):
        del machine, args, timeout_s
        if tool == "transfer_gui_temp_put_url":
            return {}
        assert tool == "transfer_gui_temp_stat"
        return {"size": 8, "sha256": digest}

    monkeypatch.setattr(tools, "_remote_transfer_data", transfer)
    monkeypatch.setattr(
        tools,
        "get_upload_ticket_status",
        lambda token: {
            "received_bytes": 7,
            "completed": False,
            "staged": True,
            "sha256": digest,
        },
    )

    with pytest.raises(tools.RemoteTransferError, match="source changed"):
        await tools._stream_remote_file_to_upload_ticket(
            "source-worker",
            "source.bin",
            7,
            None,
            {"token": "ticket", "url": "http://testserver/upload/ticket"},
            put_tool="transfer_gui_temp_put_url",
            stat_tool="transfer_gui_temp_stat",
        )


@pytest.mark.asyncio
async def test_legacy_stream_rejects_staged_checksum_mismatch(monkeypatch):
    receiver_digest = hashlib.sha256(b"payload").hexdigest()
    source_digest = hashlib.sha256(b"different").hexdigest()

    async def transfer(*args, **kwargs):
        del args, kwargs
        return {"sha256": source_digest}

    monkeypatch.setattr(tools, "_remote_transfer_data", transfer)
    monkeypatch.setattr(
        tools,
        "get_upload_ticket_status",
        lambda token: {
            "received_bytes": 7,
            "completed": False,
            "staged": True,
            "sha256": receiver_digest,
        },
    )

    with pytest.raises(tools.RemoteTransferError, match="checksums differ"):
        await tools._stream_remote_file_to_upload_ticket(
            "source-worker",
            "source.bin",
            7,
            None,
            {"token": "ticket", "url": "http://testserver/upload/ticket"},
            put_tool="transfer_gui_temp_put_url",
        )


@pytest.mark.asyncio
async def test_legacy_stream_recovers_completed_status_after_worker_failure(monkeypatch):
    digest = hashlib.sha256(b"payload").hexdigest()

    async def fail(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("response lost")

    monkeypatch.setattr(tools, "_remote_transfer_data", fail)
    monkeypatch.setattr(
        tools,
        "get_upload_ticket_status",
        lambda token: {
            "received_bytes": 7,
            "completed": True,
            "sha256": digest,
        },
    )

    result = await tools._stream_remote_file_to_upload_ticket(
        "source-worker",
        "source.bin",
        7,
        digest,
        {"token": "ticket", "url": "http://testserver/upload/ticket"},
        put_tool="transfer_gui_temp_put_url",
    )

    assert result["completed"] is True


@pytest.mark.asyncio
async def test_legacy_stream_exhausts_retries_for_incomplete_upload(monkeypatch):
    attempts = 0

    async def upload(*args, **kwargs):
        nonlocal attempts
        del args, kwargs
        attempts += 1
        return {}

    async def no_sleep(delay):
        assert delay in {0.25, 0.5}

    monkeypatch.setattr(tools, "_remote_transfer_data", upload)
    monkeypatch.setattr(
        tools,
        "get_upload_ticket_status",
        lambda token: {
            "received_bytes": 0,
            "completed": False,
            "staged": False,
        },
    )
    monkeypatch.setattr(tools.asyncio, "sleep", no_sleep)

    with pytest.raises(tools.RemoteTransferError, match="upload did not complete"):
        await tools._stream_remote_file_to_upload_ticket(
            "source-worker",
            "source.bin",
            7,
            "0" * 64,
            {"token": "ticket", "url": "http://testserver/upload/ticket"},
            put_tool="transfer_gui_temp_put_url",
        )

    assert attempts == 3


@pytest.mark.asyncio
async def test_legacy_stream_raises_missing_ticket_after_successful_worker(monkeypatch):
    release_upload = asyncio.Event()

    async def succeed_after_poll(*args, **kwargs):
        del args, kwargs
        await release_upload.wait()
        return {"sha256": hashlib.sha256(b"payload").hexdigest()}

    def missing_status(token):
        del token
        release_upload.set()
        raise FileNotFoundError("ticket removed")

    monkeypatch.setattr(tools, "_remote_transfer_data", succeed_after_poll)
    monkeypatch.setattr(tools, "get_upload_ticket_status", missing_status)

    with pytest.raises(FileNotFoundError, match="ticket removed"):
        await tools._stream_remote_file_to_upload_ticket(
            "source-worker",
            "source.bin",
            7,
            None,
            {"token": "removed", "url": "http://testserver/upload/removed"},
            put_tool="transfer_gui_temp_put_url",
        )


@pytest.mark.asyncio
async def test_legacy_stream_reports_progress_while_worker_is_active(monkeypatch):
    digest = hashlib.sha256(b"payload").hexdigest()
    release_upload = asyncio.Event()
    status_calls = 0
    wait_calls = 0
    progress_updates: list[int] = []
    real_wait = asyncio.wait

    async def upload(*args, **kwargs):
        del args, kwargs
        await release_upload.wait()
        return {"sha256": digest}

    async def fake_wait(tasks, timeout=None):
        nonlocal wait_calls
        wait_calls += 1
        if wait_calls == 1:
            return set(), set(tasks)
        return await real_wait(tasks, timeout=timeout)

    def status(token):
        nonlocal status_calls
        assert token == "ticket"
        status_calls += 1
        if status_calls == 1:
            release_upload.set()
            return {"received_bytes": 3, "completed": False, "staged": False}
        return {"received_bytes": 7, "completed": True, "sha256": digest}

    async def report(progress, **kwargs):
        del progress
        progress_updates.append(int(kwargs["bytes_transferred"]))

    monkeypatch.setattr(tools, "_remote_transfer_data", upload)
    monkeypatch.setattr(tools, "get_upload_ticket_status", status)
    monkeypatch.setattr(tools.asyncio, "wait", fake_wait)
    monkeypatch.setattr(tools, "_report_transfer_progress", report)

    result = await tools._stream_remote_file_to_upload_ticket(
        "source-worker",
        "source.bin",
        7,
        digest,
        {"token": "ticket", "url": "http://testserver/upload/ticket"},
        put_tool="transfer_gui_temp_put_url",
    )

    assert result["completed"] is True
    assert 3 in progress_updates


@pytest.mark.asyncio
async def test_legacy_stream_retries_worker_failure_then_exhausts(monkeypatch):
    attempts = 0

    async def fail(*args, **kwargs):
        nonlocal attempts
        del args, kwargs
        attempts += 1
        raise RuntimeError("worker upload failed")

    async def no_sleep(delay):
        assert delay in {0.25, 0.5}

    monkeypatch.setattr(tools, "_remote_transfer_data", fail)
    monkeypatch.setattr(
        tools,
        "get_upload_ticket_status",
        lambda token: {
            "received_bytes": 0,
            "completed": False,
            "staged": False,
        },
    )
    monkeypatch.setattr(tools.asyncio, "sleep", no_sleep)

    with pytest.raises(RuntimeError, match="worker upload failed"):
        await tools._stream_remote_file_to_upload_ticket(
            "source-worker",
            "source.bin",
            7,
            "0" * 64,
            {"token": "ticket", "url": "http://testserver/upload/ticket"},
            put_tool="transfer_gui_temp_put_url",
        )

    assert attempts == 3


@pytest.mark.asyncio
async def test_legacy_stream_returns_completed_status_after_worker_success(monkeypatch):
    digest = hashlib.sha256(b"payload").hexdigest()

    async def upload(*args, **kwargs):
        del args, kwargs
        return {"sha256": digest}

    monkeypatch.setattr(tools, "_remote_transfer_data", upload)
    monkeypatch.setattr(
        tools,
        "get_upload_ticket_status",
        lambda token: {
            "received_bytes": 7,
            "completed": True,
            "sha256": digest,
        },
    )

    result = await tools._stream_remote_file_to_upload_ticket(
        "source-worker",
        "source.bin",
        7,
        digest,
        {"token": "ticket", "url": "http://testserver/upload/ticket"},
        put_tool="transfer_gui_temp_put_url",
    )

    assert result["completed"] is True


@pytest.mark.asyncio
async def test_legacy_stream_staged_incomplete_status_is_not_finalized(monkeypatch):
    digest = hashlib.sha256(b"payload").hexdigest()
    attempts = 0

    async def upload(*args, **kwargs):
        nonlocal attempts
        del args, kwargs
        attempts += 1
        return {"sha256": digest}

    async def no_sleep(delay):
        assert delay in {0.25, 0.5}

    monkeypatch.setattr(tools, "_remote_transfer_data", upload)
    monkeypatch.setattr(
        tools,
        "get_upload_ticket_status",
        lambda token: {
            "received_bytes": 6,
            "completed": False,
            "staged": True,
            "sha256": digest,
        },
    )
    monkeypatch.setattr(tools.asyncio, "sleep", no_sleep)

    with pytest.raises(tools.RemoteTransferError, match="upload did not complete"):
        await tools._stream_remote_file_to_upload_ticket(
            "source-worker",
            "source.bin",
            7,
            None,
            {"token": "ticket", "url": "http://testserver/upload/ticket"},
            put_tool="transfer_gui_temp_put_url",
        )

    assert attempts == 3


@pytest.mark.asyncio
async def test_wait_for_download_ticket_completion_times_out_after_poll(monkeypatch):
    class FakeLoop:
        def __init__(self):
            self.values = iter((0.0, 1.0, 6.0))

        def time(self):
            return next(self.values)

    loop = FakeLoop()
    sleeps: list[float] = []

    async def no_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(tools.asyncio, "get_running_loop", lambda: loop)
    monkeypatch.setattr(tools.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(
        tools,
        "get_download_ticket_status",
        lambda token: {"completed": False},
    )

    with pytest.raises(
        tools.RemoteTransferError,
        match="source stream ended before its digest was finalized",
    ):
        await tools._wait_for_download_ticket_completion("ticket")

    assert sleeps == [0.01]


@pytest.mark.asyncio
async def test_legacy_stream_preserves_worker_failure_when_status_ticket_is_missing(monkeypatch):
    async def fail(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("worker failed")

    monkeypatch.setattr(tools, "_remote_transfer_data", fail)
    monkeypatch.setattr(
        tools,
        "get_upload_ticket_status",
        lambda token: (_ for _ in ()).throw(FileNotFoundError(token)),
    )

    with pytest.raises(RuntimeError, match="worker failed"):
        await tools._stream_remote_file_to_upload_ticket(
            "source-worker",
            "source.bin",
            7,
            "0" * 64,
            {"token": "missing", "url": "http://testserver/upload/missing"},
            put_tool="transfer_gui_temp_put_url",
        )


@pytest.mark.asyncio
async def test_legacy_stream_finalizes_staged_status_after_worker_failure(monkeypatch):
    digest = hashlib.sha256(b"payload").hexdigest()

    async def transfer(machine, tool, args, timeout_s=None):
        del machine, args, timeout_s
        if tool == "transfer_gui_temp_put_url":
            raise RuntimeError("response lost after upload")
        assert tool == "transfer_gui_temp_stat"
        return {"size": 7, "sha256": digest}

    monkeypatch.setattr(tools, "_remote_transfer_data", transfer)
    monkeypatch.setattr(
        tools,
        "get_upload_ticket_status",
        lambda token: {
            "received_bytes": 7,
            "completed": False,
            "staged": True,
            "sha256": digest,
        },
    )
    monkeypatch.setattr(
        tools,
        "finalize_upload_ticket",
        lambda token, expected_sha256: {
            "completed": True,
            "received_bytes": 7,
            "sha256": expected_sha256,
        },
    )

    result = await tools._stream_remote_file_to_upload_ticket(
        "source-worker",
        "source.bin",
        7,
        None,
        {"token": "ticket", "url": "http://testserver/upload/ticket"},
        put_tool="transfer_gui_temp_put_url",
        stat_tool="transfer_gui_temp_stat",
    )

    assert result["completed"] is True
    assert result["sha256"] == digest


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
            "sha256": None,
        }

    async def transfer(machine, tool, args, timeout_s=None):
        del machine, timeout_s
        if tool == "transfer_download_url":
            assert args.get("defer_commit") is True
            assert "expected_sha256" not in args
            return {
                "path": args["path"],
                "transfer_id": "staged",
                "bytes": len(data),
                "transport": "http-staged",
            }
        assert tool == "transfer_finish_write"
        assert args["expected_sha256"] == digest
        return {"path": args["path"], "bytes": len(data), "sha256": digest}

    monkeypatch.setattr(tools, "create_stream_download_ticket", create_ticket)
    monkeypatch.setattr(
        tools,
        "get_download_ticket_status",
        lambda token: {"completed": True, "sha256": digest},
    )
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
            "sha256": None,
        }

    async def refresh_lease(source_path):
        assert source_path == "payload.bin"
        lease_failed.set()
        raise FileNotFoundError(source_path)

    async def transfer(machine, tool, args, timeout_s=None):
        del machine, timeout_s
        if tool == "transfer_download_url":
            await asyncio.wait_for(lease_failed.wait(), timeout=2)
            await asyncio.sleep(0)
            return {
                "path": args["path"],
                "transfer_id": "staged",
                "bytes": len(data),
                "transport": "http-staged",
            }
        assert tool == "transfer_finish_write"
        return {"path": args["path"], "bytes": len(data), "sha256": digest}

    monkeypatch.setattr(tools, "create_stream_download_ticket", create_ticket)
    monkeypatch.setattr(tools, "_refresh_controller_temp_lease", refresh_lease)
    monkeypatch.setattr(
        tools,
        "get_download_ticket_status",
        lambda token: {"completed": True, "sha256": digest},
    )
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
