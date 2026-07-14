from __future__ import annotations

import hashlib

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from local_shell_mcp.auth import RequestBodyLimitMiddleware
from local_shell_mcp.remote_transfer import (
    create_download_ticket,
    create_upload_ticket,
    remote_transfer_routes,
    revoke_transfer_ticket,
)
from local_shell_mcp.settings import get_settings


def _client(tmp_path, monkeypatch, *, request_limit: int = 1024) -> TestClient:
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_STATE_DIR", str(tmp_path / ".state"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_PUBLIC_BASE_URL", "http://testserver")
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_HTTP_REQUEST_BYTES", str(request_limit))
    get_settings.cache_clear()
    app = Starlette(routes=remote_transfer_routes())
    app.add_middleware(RequestBodyLimitMiddleware)
    return TestClient(app)


def test_stream_upload_bypasses_json_body_limit_and_is_one_time(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, request_limit=1024)
    data = (b"streamed-binary-data" * 131072)[:2_000_000]
    digest = hashlib.sha256(data).hexdigest()
    ticket = create_upload_ticket("artifact.bin", len(data), digest)

    response = client.put(ticket["url"], content=data)

    assert response.status_code == 200
    assert response.json()["data"]["transport"] == "http-stream"
    assert (tmp_path / "artifact.bin").read_bytes() == data
    assert client.put(ticket["url"], content=data).status_code == 404


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


def _worker_identity(tmp_path):
    path = tmp_path / "identity.json"
    path.write_text('{"server": "http://testserver"}', encoding="utf-8")
    return path


def test_worker_upload_uses_raw_stream_endpoint(tmp_path, monkeypatch):
    import subprocess
    from pathlib import Path
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
        del kwargs
        upload_path = Path(command[command.index("--upload-file") + 1])
        response = client.put(urlsplit(command[-1]).path, content=upload_path.read_bytes())
        return subprocess.CompletedProcess(
            command,
            0 if response.status_code < 400 else 22,
            stdout=response.text,
            stderr="",
        )

    monkeypatch.setattr(remote.subprocess, "run", fake_run)

    result = remote._worker_upload_url("source.bin", ticket["url"], len(data), digest, 60)

    assert result["transport"] == "http-stream"
    assert (tmp_path / "destination.bin").read_bytes() == data


def test_worker_download_is_transactional_and_verified(tmp_path, monkeypatch):
    import subprocess
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

    def fake_run(command, **kwargs):
        del kwargs
        output = Path(command[command.index("-o") + 1])
        response = client.get(urlsplit(command[-1]).path)
        output.write_bytes(response.content)
        return subprocess.CompletedProcess(
            command,
            0 if response.status_code < 400 else 22,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(remote.subprocess, "run", fake_run)

    result = remote._worker_download_url(
        ticket["url"], "destination.bin", True, len(data), digest, 60
    )

    assert result["transport"] == "http-stream"
    assert (tmp_path / "destination.bin").read_bytes() == data
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


@pytest.mark.parametrize(
    ("filename", "encoded"),
    [
        ("中文.bin", "%E4%B8%AD%E6%96%87.bin"),
        ('quote"name.bin', "quote%22name.bin"),
    ],
)
def test_stream_download_encodes_non_ascii_and_quoted_filenames(
    tmp_path, monkeypatch, filename, encoded
):
    client = _client(tmp_path, monkeypatch)
    data = b"payload"
    (tmp_path / filename).write_bytes(data)
    ticket = create_download_ticket(filename, len(data), hashlib.sha256(data).hexdigest())

    response = client.get(ticket["url"])

    assert response.status_code == 200
    assert response.content == data
    disposition = response.headers["content-disposition"]
    assert f"filename*=UTF-8''{encoded}" in disposition
    assert '\\"name.bin' not in disposition
