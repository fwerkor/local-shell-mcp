from __future__ import annotations

import asyncio
import hashlib
import os
import threading
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

import local_shell_mcp.remote_transfer as remote_transfer
from local_shell_mcp.auth import RequestBodyLimitMiddleware
from local_shell_mcp.remote_transfer import (
    _content_disposition,
    create_download_ticket,
    create_upload_ticket,
    remote_transfer_routes,
    revoke_transfer_ticket,
)
from local_shell_mcp.settings import get_settings
from local_shell_mcp.transfer_ops import transfer_finish_write


def _client(tmp_path, monkeypatch, *, request_limit: int = 1024) -> TestClient:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "http://testserver")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_HTTP_REQUEST_BYTES", str(request_limit))
    get_settings.cache_clear()
    app = Starlette(routes=remote_transfer_routes())
    app.add_middleware(RequestBodyLimitMiddleware)
    return TestClient(app)


def test_stream_upload_bypasses_json_body_limit_and_retains_status(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, request_limit=1024)
    data = (b"streamed-binary-data" * 131072)[:2_000_000]
    digest = hashlib.sha256(data).hexdigest()
    ticket = create_upload_ticket("artifact.bin", len(data), digest)

    response = client.put(ticket["url"], content=data)

    assert response.status_code == 200
    assert response.json()["data"]["transport"] == "http-stream"
    assert (tmp_path / "artifact.bin").read_bytes() == data
    repeated = client.put(ticket["url"], content=data)
    assert repeated.status_code == 200
    assert repeated.json()["data"]["completed"] is True
    assert revoke_transfer_ticket(ticket["token"])["revoked"] is True
    assert client.get(ticket["url"]).status_code == 404


def test_chunk_upload_tracks_offset_and_rejects_overlap(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    first = b"first-half"
    second = b"second-half"
    data = first + second
    ticket = create_upload_ticket("artifact.bin", len(data), hashlib.sha256(data).hexdigest())
    path = ticket["url"]

    response = client.put(
        path,
        content=first,
        headers={
            "Content-Range": f"bytes 0-{len(first) - 1}/{len(data)}",
            "X-Chunk-SHA256": hashlib.sha256(first).hexdigest(),
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["received_bytes"] == len(first)
    assert response.json()["data"]["completed"] is False
    assert client.get(path).json()["data"]["received_bytes"] == len(first)

    overlap = client.put(
        path,
        content=first,
        headers={
            "Content-Range": f"bytes 0-{len(first) - 1}/{len(data)}",
            "X-Chunk-SHA256": hashlib.sha256(first).hexdigest(),
        },
    )
    assert overlap.status_code == 409
    assert overlap.json()["data"]["received_bytes"] == len(first)

    response = client.put(
        path,
        content=second,
        headers={
            "Content-Range": f"bytes {len(first)}-{len(data) - 1}/{len(data)}",
            "X-Chunk-SHA256": hashlib.sha256(second).hexdigest(),
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["completed"] is True
    assert (tmp_path / "artifact.bin").read_bytes() == data
    revoke_transfer_ticket(ticket["token"])


@pytest.mark.parametrize(
    "content_range",
    [
        "invalid",
        "bytes 0-0/2",
        "bytes 1-0/1",
        "bytes 0-1/1",
    ],
)
def test_chunk_upload_rejects_invalid_ranges(tmp_path, monkeypatch, content_range):
    client = _client(tmp_path, monkeypatch)
    data = b"x"
    ticket = create_upload_ticket("artifact.bin", len(data), hashlib.sha256(data).hexdigest())

    response = client.put(
        ticket["url"],
        content=data,
        headers={"Content-Range": content_range},
    )

    assert response.status_code == 400
    assert revoke_transfer_ticket(ticket["token"])["revoked"] is True


def test_chunk_upload_rejects_bad_hash_and_oversized_legacy_request(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    data = b"payload"
    ticket = create_upload_ticket("artifact.bin", len(data), hashlib.sha256(data).hexdigest())

    response = client.put(
        ticket["url"],
        content=data,
        headers={
            "Content-Range": f"bytes 0-{len(data) - 1}/{len(data)}",
            "X-Chunk-SHA256": "0" * 64,
        },
    )
    assert response.status_code == 400
    revoke_transfer_ticket(ticket["token"])

    oversized_data = b"x" * (remote_transfer.MAX_TRANSFER_CHUNK_BYTES + 1)
    ticket = create_upload_ticket(
        "oversized.bin",
        len(oversized_data),
        hashlib.sha256(oversized_data).hexdigest(),
    )
    response = client.put(ticket["url"], content=oversized_data)
    assert response.status_code == 200
    assert response.json()["data"]["transport"] == "http-stream"
    assert (tmp_path / "oversized.bin").read_bytes() == oversized_data
    revoke_transfer_ticket(ticket["token"])


def test_upload_status_and_claim_conflicts(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    data = b"payload"
    upload = create_upload_ticket("artifact.bin", len(data), hashlib.sha256(data).hexdigest())
    remote_transfer._claim_ticket(upload["token"], "upload")
    try:
        response = client.put(upload["url"], content=data)
        assert response.status_code == 409
    finally:
        remote_transfer._release_ticket(upload["token"])
        revoke_transfer_ticket(upload["token"])

    source = tmp_path / "source.bin"
    source.write_bytes(data)
    download = create_download_ticket("source.bin", len(data), hashlib.sha256(data).hexdigest())
    status_url = download["url"].replace("/download/", "/upload/")
    assert client.get(status_url).status_code == 409
    revoke_transfer_ticket(download["token"])


def test_ticket_creation_failures_cleanup_transactions(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    digest = hashlib.sha256(b"payload").hexdigest()

    def fail_create(*args, **kwargs):  # noqa: ARG001
        raise RuntimeError("ticket creation failed")

    monkeypatch.setattr(remote_transfer, "_create_ticket", fail_create)
    with pytest.raises(RuntimeError, match="ticket creation failed"):
        create_upload_ticket("upload.bin", 7, digest)
    assert not list(tmp_path.glob(".upload.bin.local-shell-mcp-transfer-*.tmp"))

    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    with pytest.raises(RuntimeError, match="ticket creation failed"):
        create_download_ticket("source.bin", 7, digest)
    transfer_dir = tmp_path / ".state" / "remote-transfers"
    assert not transfer_dir.exists() or not list(transfer_dir.iterdir())


def test_stream_upload_hash_failure_is_transactional(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    expected = b"expected"
    actual = b"modified"
    ticket = create_upload_ticket(
        "artifact.bin",
        len(actual),
        hashlib.sha256(expected).hexdigest(),
    )

    response = client.put(ticket["url"], content=actual)

    assert response.status_code == 400
    assert not (tmp_path / "artifact.bin").exists()
    assert not list(tmp_path.glob(".artifact.bin.local-shell-mcp-transfer-*.tmp"))
    revoke_transfer_ticket(ticket["token"])


def test_stream_download_is_exact_and_one_time(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    data = b"download" * 65536
    source = tmp_path / "source.bin"
    source.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    ticket = create_download_ticket("source.bin", len(data), digest)

    response = client.get(ticket["url"])

    assert response.status_code == 200
    assert response.content == data
    assert response.headers["content-length"] == str(len(data))
    assert response.headers["x-content-sha256"] == digest
    assert client.get(ticket["url"]).status_code == 404





def test_stream_ticket_creation_does_not_read_source(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    source = tmp_path / "source.bin"
    source.write_bytes(b"x" * (remote_transfer._TRANSFER_CHUNK_BYTES + 17))
    original_open = Path.open
    reads = 0

    class TrackedFile:
        def __init__(self, handle):
            self._handle = handle

        def read(self, *args, **kwargs):
            nonlocal reads
            reads += 1
            return self._handle.read(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._handle, name)

    def tracked_open(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        if path == source and args and args[0] == "rb":
            return TrackedFile(handle)
        return handle

    monkeypatch.setattr(Path, "open", tracked_open)

    ticket = remote_transfer.create_stream_download_ticket("source.bin")

    assert ticket["sha256"] is None
    assert reads == 0
    revoke_transfer_ticket(ticket["token"])


def test_stream_ticket_reports_digest_computed_by_actual_download(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    data = b"single-pass-download" * 65536
    (tmp_path / "source.bin").write_bytes(data)
    ticket = remote_transfer.create_stream_download_ticket("source.bin")

    response = client.get(ticket["url"])
    status = remote_transfer.get_download_ticket_status(ticket["token"])

    assert response.status_code == 200
    assert response.content == data
    assert "x-content-sha256" not in response.headers
    assert status["completed"] is True
    assert status["sha256"] == hashlib.sha256(data).hexdigest()
    assert client.get(ticket["url"]).status_code == 404
    revoke_transfer_ticket(ticket["token"])


def test_stream_download_ticket_validates_expected_metadata(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    data = b"validated-stream"
    source = tmp_path / "source.bin"
    source.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()

    with pytest.raises(ValueError, match="must be provided together"):
        remote_transfer.create_stream_download_ticket("source.bin", expected_bytes=len(data))
    with pytest.raises(ValueError, match="size mismatch"):
        remote_transfer.create_stream_download_ticket("source.bin", len(data) + 1, digest)
    ticket_info = remote_transfer.create_stream_download_ticket(
        "source.bin",
        len(data),
        hashlib.sha256(b"different").hexdigest(),
    )
    ticket = remote_transfer._claim_ticket(ticket_info["token"], "download")
    _, handle = remote_transfer._open_download(ticket)
    iterator = remote_transfer._download_iterator(ticket_info["token"], ticket, handle)
    with pytest.raises(RuntimeError, match="checksum changed"):
        b"".join(iterator)
    revoke_transfer_ticket(ticket_info["token"])


def test_stream_download_cleanup_preserves_atomic_replacement(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    original = b"original-cleanup"
    replacement_data = b"replacement-data"
    assert len(original) == len(replacement_data)
    source = tmp_path / "source.bin"
    source.write_bytes(original)
    ticket = remote_transfer.create_stream_download_ticket("source.bin", cleanup_source=True)
    replacement = tmp_path / "replacement.bin"
    replacement.write_bytes(replacement_data)
    try:
        replacement.replace(source)
    except OSError:
        revoke_transfer_ticket(ticket["token"])
        pytest.skip("platform does not permit atomic replacement of an open file")

    revoke_transfer_ticket(ticket["token"])

    assert source.read_bytes() == replacement_data


def test_stream_download_ticket_stays_bound_after_atomic_replace(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    original = b"original-stream" * 131072
    replacement_data = b"replaced-stream" * 131072
    assert len(original) == len(replacement_data)
    source = tmp_path / "source.bin"
    source.write_bytes(original)
    ticket = remote_transfer.create_stream_download_ticket("source.bin")
    replacement = tmp_path / "replacement.bin"
    replacement.write_bytes(replacement_data)
    try:
        replacement.replace(source)
    except OSError:
        revoke_transfer_ticket(ticket["token"])
        pytest.skip("platform does not permit atomic replacement of an open file")

    response = client.get(ticket["url"])

    assert response.status_code == 200
    assert response.content == original
    assert source.read_bytes() == replacement_data


def test_stream_download_rejects_in_place_mutation_before_yield(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    original = b"a" * (remote_transfer._TRANSFER_CHUNK_BYTES + 17)
    mutated = b"b" * len(original)
    source = tmp_path / "source.bin"
    source.write_bytes(original)
    ticket_info = remote_transfer.create_stream_download_ticket("source.bin")
    ticket = remote_transfer._claim_ticket(ticket_info["token"], "download")
    _, handle = remote_transfer._open_download(ticket)
    source.write_bytes(mutated)
    iterator = remote_transfer._download_iterator(ticket_info["token"], ticket, handle)

    with pytest.raises(RuntimeError, match="source changed"):
        next(iterator)

    revoke_transfer_ticket(ticket_info["token"])


def test_stale_orphan_download_snapshot_is_scavenged(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    data = b"orphaned"
    source = tmp_path / "source.bin"
    source.write_bytes(data)
    ticket = create_download_ticket("source.bin", len(data), hashlib.sha256(data).hexdigest())
    snapshot = Path(remote_transfer._TICKETS[ticket["token"]].cleanup_path or "")
    assert snapshot.is_file()

    with remote_transfer._TICKET_LOCK:
        remote_transfer._TICKETS.clear()
        remote_transfer._LAST_ORPHAN_PRUNE_AT = 0.0
        remote_transfer._maybe_prune_orphan_download_snapshots_locked(
            snapshot.stat().st_mtime + remote_transfer._ticket_ttl_s() + 1
        )

    assert not snapshot.exists()


def test_active_download_snapshot_temporary_is_not_scavenged(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    transfer_dir = tmp_path / ".state" / "remote-transfers"
    transfer_dir.mkdir(parents=True, exist_ok=True)
    temporary = transfer_dir / "active.bin.deadbeef.tmp"
    temporary.write_bytes(b"in progress")
    stale_now = temporary.stat().st_mtime + remote_transfer._ticket_ttl_s() + 1

    with remote_transfer._TICKET_LOCK:
        remote_transfer._ACTIVE_SNAPSHOT_PATHS.add(str(temporary))
        try:
            remote_transfer._prune_orphan_download_snapshots_locked(stale_now)
        finally:
            remote_transfer._ACTIVE_SNAPSHOT_PATHS.discard(str(temporary))

    assert temporary.exists()
    with remote_transfer._TICKET_LOCK:
        remote_transfer._prune_orphan_download_snapshots_locked(stale_now)
    assert not temporary.exists()


def test_orphan_snapshot_scan_failure_is_best_effort(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    transfer_dir = tmp_path / ".state" / "remote-transfers"
    transfer_dir.mkdir(parents=True, exist_ok=True)
    original_iterdir = Path.iterdir

    def fail_transfer_scan(path):
        if path == transfer_dir:
            raise OSError("directory disappeared")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", fail_transfer_scan)
    with remote_transfer._TICKET_LOCK:
        remote_transfer._prune_orphan_download_snapshots_locked(100.0)


def test_ticket_claims_do_not_rescan_orphan_directory(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    data = b"payload"
    source = tmp_path / "source.bin"
    source.write_bytes(data)
    ticket_info = create_download_ticket("source.bin", len(data), hashlib.sha256(data).hexdigest())
    scans = 0

    def count_scan(now):
        nonlocal scans
        del now
        scans += 1

    monkeypatch.setattr(remote_transfer, "_prune_orphan_download_snapshots_locked", count_scan)
    for _ in range(3):
        remote_transfer._claim_ticket(ticket_info["token"], "download")
        remote_transfer._release_ticket(ticket_info["token"])

    assert scans == 0
    revoke_transfer_ticket(ticket_info["token"])


def _worker_identity(tmp_path):
    path = tmp_path / "identity.json"
    path.write_text('{"server": "http://testserver"}', encoding="utf-8")
    return path


def test_worker_upload_uses_raw_chunk_endpoint(tmp_path, monkeypatch):
    import subprocess
    from urllib.parse import urlsplit

    import local_shell_mcp.remote as remote

    client = _client(tmp_path, monkeypatch)
    data = b"worker-upload" * 131072
    source = tmp_path / "source.bin"
    source.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    ticket = create_upload_ticket("destination.bin", len(data), digest)
    monkeypatch.setattr(remote, "_worker_identity_path", lambda: _worker_identity(tmp_path))
    monkeypatch.setattr(remote.shutil, "which", lambda name: "/usr/bin/curl")

    def fake_run(command, **kwargs):
        headers = {}
        for index, value in enumerate(command):
            if value == "-H":
                name, header_value = command[index + 1].split(":", 1)
                headers[name] = header_value.strip()
        response = client.put(
            urlsplit(command[-1]).path,
            content=kwargs["input"],
            headers=headers,
        )
        stdout = response.text + f"\n__LSM_HTTP_STATUS__:{response.status_code}"
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=stdout.encode(),
            stderr=b"",
        )

    monkeypatch.setattr(remote.subprocess, "run", fake_run)

    result = remote._worker_upload_url(
        "source.bin",
        ticket["url"],
        len(data),
        digest,
        60,
        chunk_size=len(data),
    )

    assert result["transport"] == "http-chunks"
    assert (tmp_path / "destination.bin").read_bytes() == data





def test_unknown_digest_upload_stages_until_explicit_finalize(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    data = b"single-pass-upload" * 65536
    digest = hashlib.sha256(data).hexdigest()
    (tmp_path / "destination.bin").write_bytes(b"old")
    ticket = create_upload_ticket("destination.bin", len(data), None)

    response = client.put(ticket["url"], content=data)
    status = remote_transfer.get_upload_ticket_status(ticket["token"])

    assert response.status_code == 200
    assert status["staged"] is True
    assert status["completed"] is False
    assert status["sha256"] == digest
    assert (tmp_path / "destination.bin").read_bytes() == b"old"

    finish = remote_transfer.finalize_upload_ticket(ticket["token"], digest)

    assert finish["completed"] is True
    assert finish["sha256"] == digest
    assert (tmp_path / "destination.bin").read_bytes() == data
    revoke_transfer_ticket(ticket["token"])


def test_worker_unknown_digest_put_streams_pinned_source_once(tmp_path, monkeypatch):
    import local_shell_mcp.remote as remote

    _client(tmp_path, monkeypatch)
    data = b"a" * (remote.DEFAULT_TRANSFER_CHUNK_BYTES + 17)
    replacement_data = b"b" * len(data)
    source = tmp_path / "source.bin"
    source.write_bytes(data)
    replacement = tmp_path / "replacement.bin"
    replacement.write_bytes(replacement_data)
    sent = bytearray()

    class FakeStdin:
        def __init__(self):
            self.replaced = False

        def write(self, chunk):
            sent.extend(chunk)
            if not self.replaced:
                self.replaced = True
                replacement.replace(source)
            return len(chunk)

        def flush(self):
            return None

        def close(self):
            return None

    class FakeProcess:
        def __init__(self, command, **kwargs):
            del command, kwargs
            self.stdin = FakeStdin()
            self.returncode = 0

        def communicate(self):
            return b"\n__LSM_HTTP_STATUS__:200", b""

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(remote.shutil, "which", lambda name: "/usr/bin/curl")
    monkeypatch.setattr(remote.subprocess, "Popen", FakeProcess)

    result = remote._worker_put_url(
        "source.bin",
        "http://testserver/upload",
        len(data),
        None,
        60,
    )

    assert bytes(sent) == data
    assert result["sha256"] == hashlib.sha256(data).hexdigest()
    assert source.read_bytes() == replacement_data


def test_worker_unknown_digest_put_rejects_in_place_mutation(tmp_path, monkeypatch):
    import local_shell_mcp.remote as remote

    _client(tmp_path, monkeypatch)
    data = b"a" * (remote.DEFAULT_TRANSFER_CHUNK_BYTES + 17)
    source = tmp_path / "source.bin"
    source.write_bytes(data)
    original_mtime = source.stat().st_mtime_ns
    killed = False

    class FakeStdin:
        def __init__(self):
            self.mutated = False

        def write(self, chunk):
            if not self.mutated:
                self.mutated = True
                source.write_bytes(b"b" * len(data))
                os.utime(
                    source,
                    ns=(source.stat().st_atime_ns, original_mtime + 1_000_000),
                )
            return len(chunk)

        def flush(self):
            return None

        def close(self):
            return None

    class FakeProcess:
        def __init__(self, command, **kwargs):
            del command, kwargs
            self.stdin = FakeStdin()
            self.returncode = None

        def communicate(self):
            return b"", b""

        def kill(self):
            nonlocal killed
            killed = True
            self.returncode = -9

    monkeypatch.setattr(remote.shutil, "which", lambda name: "/usr/bin/curl")
    monkeypatch.setattr(remote.subprocess, "Popen", FakeProcess)

    with pytest.raises(RuntimeError, match="source changed"):
        remote._worker_put_url(
            "source.bin",
            "http://testserver/upload",
            len(data),
            None,
            60,
        )

    assert killed is True


@pytest.mark.asyncio
async def test_worker_stream_put_cancellation_kills_curl(tmp_path, monkeypatch):
    import local_shell_mcp.remote as remote

    _client(tmp_path, monkeypatch)
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    digest = hashlib.sha256(b"payload").hexdigest()
    monkeypatch.setattr(remote, "_worker_identity_path", lambda: _worker_identity(tmp_path))
    monkeypatch.setattr(remote.shutil, "which", lambda name: "/usr/bin/curl")
    started = threading.Event()
    killed = threading.Event()

    class FakeProcess:
        def __init__(self, command, **kwargs):
            del command, kwargs
            self.returncode = None
            started.set()

        def communicate(self):
            assert killed.wait(2)
            self.returncode = -9
            return b"", b"cancelled"

        def kill(self):
            self.returncode = -9
            killed.set()

    monkeypatch.setattr(remote.subprocess, "Popen", FakeProcess)

    task = asyncio.create_task(
        remote._worker_put_url_cancellable(
            "source.bin",
            "http://testserver/upload",
            len(b"payload"),
            digest,
            60,
        )
    )
    assert await asyncio.to_thread(started.wait, 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert killed.is_set()
    assert "transfer_put_url" not in remote.REMOTE_NON_CANCELLABLE_WORKER_TOOLS


def test_stream_upload_rejects_staged_file_changed_after_hash(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    data = b"verified-stream"
    digest = hashlib.sha256(data).hexdigest()
    ticket = create_upload_ticket("artifact.bin", len(data), digest)
    original_finish = remote_transfer.transfer_finish_verified_write

    def mutate_before_commit(path, transfer_id, *args):
        temporary = next(tmp_path.glob(".artifact.bin.local-shell-mcp-transfer-*.tmp"))
        temporary.write_bytes(b"x" * len(data))
        return original_finish(path, transfer_id, *args)

    monkeypatch.setattr(remote_transfer, "transfer_finish_verified_write", mutate_before_commit)

    response = client.put(ticket["url"], content=data)

    assert response.status_code == 400
    assert "file sha256 mismatch" in response.json()["message"]
    assert not (tmp_path / "artifact.bin").exists()


@pytest.mark.asyncio
async def test_stream_write_lease_refresher_renews_until_cancel(monkeypatch):
    calls: list[tuple[str, str]] = []
    refreshed = threading.Event()

    def refresh(path, transfer_id):
        calls.append((path, transfer_id))
        refreshed.set()

    monkeypatch.setattr(remote_transfer, "_STREAM_LEASE_REFRESH_INTERVAL_S", 0)
    monkeypatch.setattr(remote_transfer, "transfer_refresh_stream_write", refresh)

    task = asyncio.create_task(remote_transfer._refresh_stream_write_leases("artifact.bin", "txn"))
    assert await asyncio.to_thread(refreshed.wait, 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert calls
    assert all(call == ("artifact.bin", "txn") for call in calls)


def test_worker_download_deferred_commit_keeps_old_destination_until_verified(
    tmp_path, monkeypatch
):
    from pathlib import Path
    from urllib.parse import urlsplit

    import local_shell_mcp.remote as remote

    client = _client(tmp_path, monkeypatch)
    data = b"deferred-download" * 65536
    digest = hashlib.sha256(data).hexdigest()
    (tmp_path / "source.bin").write_bytes(data)
    (tmp_path / "destination.bin").write_bytes(b"old")
    ticket = remote_transfer.create_stream_download_ticket("source.bin")
    monkeypatch.setattr(remote, "_worker_identity_path", lambda: _worker_identity(tmp_path))
    monkeypatch.setattr(remote.shutil, "which", lambda name: "/usr/bin/curl")

    class FakeProcess:
        def __init__(self, command, **kwargs):
            del kwargs
            self.command = command
            self.returncode = None

        def communicate(self, timeout=None):
            del timeout
            output = Path(self.command[self.command.index("-o") + 1])
            response = client.get(urlsplit(self.command[-1]).path)
            output.write_bytes(response.content)
            self.returncode = 0
            return b"", b""

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(remote.subprocess, "Popen", FakeProcess)

    staged = remote._worker_download_url(
        ticket["url"],
        "destination.bin",
        True,
        len(data),
        None,
        60,
        defer_commit=True,
    )

    assert (tmp_path / "destination.bin").read_bytes() == b"old"
    assert (tmp_path / staged["temp_path"]).is_file()
    status = remote_transfer.get_download_ticket_status(ticket["token"])
    assert status["sha256"] == digest

    finish = transfer_finish_write(
        "destination.bin",
        staged["transfer_id"],
        len(data),
        status["sha256"],
    )

    assert finish["sha256"] == digest
    assert (tmp_path / "destination.bin").read_bytes() == data
    revoke_transfer_ticket(ticket["token"])


def test_worker_download_is_transactional_and_verified(tmp_path, monkeypatch):
    from pathlib import Path
    from urllib.parse import urlsplit

    import local_shell_mcp.remote as remote

    client = _client(tmp_path, monkeypatch)
    data = b"worker-download" * 131072
    source = tmp_path / "source.bin"
    source.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    ticket = create_download_ticket("source.bin", len(data), digest)
    monkeypatch.setattr(remote, "_worker_identity_path", lambda: _worker_identity(tmp_path))
    monkeypatch.setattr(remote.shutil, "which", lambda name: "/usr/bin/curl")

    class FakeProcess:
        def __init__(self, command, **kwargs):
            del kwargs
            self.command = command
            self.returncode = None

        def communicate(self, timeout=None):
            del timeout
            output = Path(self.command[self.command.index("-o") + 1])
            response = client.get(urlsplit(self.command[-1]).path)
            output.write_bytes(response.content)
            self.returncode = 0 if response.status_code < 400 else 22
            return b"", b""

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(remote.subprocess, "Popen", FakeProcess)

    result = remote._worker_download_url(
        ticket["url"], "destination.bin", True, len(data), digest, 60
    )

    assert result["transport"] == "http-stream"
    assert (tmp_path / "destination.bin").read_bytes() == data
    assert not list(tmp_path.glob(".destination.bin.local-shell-mcp-transfer-*.tmp"))


def test_worker_download_refreshes_transaction_lease(tmp_path, monkeypatch):
    import subprocess
    from pathlib import Path
    from urllib.parse import urlsplit

    import local_shell_mcp.remote as remote

    client = _client(tmp_path, monkeypatch)
    data = b"lease-refresh-download"
    digest = hashlib.sha256(data).hexdigest()
    (tmp_path / "source.bin").write_bytes(data)
    ticket = create_download_ticket("source.bin", len(data), digest)
    monkeypatch.setattr(remote, "_worker_identity_path", lambda: _worker_identity(tmp_path))
    monkeypatch.setattr(remote.shutil, "which", lambda name: "/usr/bin/curl")
    refreshed: list[tuple[str, str]] = []

    def record_refresh(path, transfer_id):
        refreshed.append((path, transfer_id))

    monkeypatch.setattr(remote, "transfer_refresh_stream_write", record_refresh)

    class FakeProcess:
        def __init__(self, command, **kwargs):
            del kwargs
            self.command = command
            self.returncode = None
            self.calls = 0

        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired(self.command, timeout)
            output = Path(self.command[self.command.index("-o") + 1])
            response = client.get(urlsplit(self.command[-1]).path)
            output.write_bytes(response.content)
            self.returncode = 0
            return b"", b""

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(remote.subprocess, "Popen", FakeProcess)

    result = remote._worker_download_url(
        ticket["url"], "destination.bin", True, len(data), digest, 60
    )

    assert result["transport"] == "http-stream"
    assert refreshed
    assert refreshed[0][0] == "destination.bin"


@pytest.mark.asyncio
async def test_worker_stream_download_cancellation_kills_curl(tmp_path, monkeypatch):
    import local_shell_mcp.remote as remote

    _client(tmp_path, monkeypatch)
    monkeypatch.setattr(remote, "_worker_identity_path", lambda: _worker_identity(tmp_path))
    monkeypatch.setattr(remote.shutil, "which", lambda name: "/usr/bin/curl")
    started = threading.Event()
    killed = threading.Event()

    class FakeProcess:
        def __init__(self, command, **kwargs):
            del command, kwargs
            self.returncode = None
            started.set()

        def communicate(self, timeout=None):
            del timeout
            assert killed.wait(2)
            self.returncode = -9
            return b"", b"cancelled"

        def kill(self):
            self.returncode = -9
            killed.set()

    monkeypatch.setattr(remote.subprocess, "Popen", FakeProcess)

    task = asyncio.create_task(
        remote._worker_download_url_cancellable(
            "http://testserver/remote/transfer/download/fake",
            "destination.bin",
            True,
            len(b"payload"),
            hashlib.sha256(b"payload").hexdigest(),
            60,
        )
    )
    assert await asyncio.to_thread(started.wait, 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert killed.is_set()
    assert "transfer_download_url" not in remote.REMOTE_NON_CANCELLABLE_WORKER_TOOLS
    assert not (tmp_path / "destination.bin").exists()
    assert not list(tmp_path.glob(".destination.bin.local-shell-mcp-transfer-*.tmp"))


def test_stream_download_interruption_releases_ticket_for_retry(tmp_path, monkeypatch):
    import local_shell_mcp.remote_transfer as remote_transfer

    _client(tmp_path, monkeypatch)
    data = b"interrupted-download" * 131072
    source = tmp_path / "source.bin"
    source.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    ticket_info = create_download_ticket("source.bin", len(data), digest)
    token = ticket_info["token"]
    ticket = remote_transfer._claim_ticket(token, "download")
    _, handle = remote_transfer._open_download(ticket)
    iterator = remote_transfer._download_iterator(token, ticket, handle)

    assert next(iterator)
    iterator.close()

    response = TestClient(Starlette(routes=remote_transfer_routes())).get(ticket_info["url"])
    assert response.status_code == 200
    assert response.content == data
    assert (
        TestClient(Starlette(routes=remote_transfer_routes())).get(ticket_info["url"]).status_code
        == 404
    )


def test_stream_download_encodes_non_ascii_filename(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    data = b"payload"
    filename = "中文.bin"
    (tmp_path / filename).write_bytes(data)
    ticket = create_download_ticket(filename, len(data), hashlib.sha256(data).hexdigest())

    response = client.get(ticket["url"])

    assert response.status_code == 200
    assert response.content == data
    disposition = response.headers["content-disposition"]
    assert "filename*=UTF-8''%E4%B8%AD%E6%96%87.bin" in disposition


def test_stream_download_content_disposition_escapes_quotes():
    disposition = _content_disposition('quote"name.bin')

    assert 'filename="quotename.bin"' in disposition
    assert "filename*=UTF-8''quote%22name.bin" in disposition
