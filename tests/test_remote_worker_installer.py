from __future__ import annotations

import hashlib
import io
import json
import tarfile

import pytest

from local_shell_mcp import remote_worker_installer as installer
from local_shell_mcp import remote_worker_state as state


def _bundle() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        content = b"value = 1\n"
        info = tarfile.TarInfo("local_shell_mcp/example.py")
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def _configure(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path / "state"))
    state.write_worker_config(server="https://example.test", name="worker", workdir=str(tmp_path))


def test_install_update_and_cache_runtime(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    payload = _bundle()
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(
        installer,
        "fetch_manifest",
        lambda server: {
            "schema_version": 1,
            "sha256": digest,
            "bundle_version": "3.0.1",
            "url": "https://example.test/bundle.tgz",
        },
    )
    monkeypatch.setattr(installer, "_fetch_bytes", lambda url, timeout=60: payload)

    result = installer.install_or_update_runtime("https://example.test")
    assert result["updated"] is True
    assert (state.worker_runtime_dir() / "local_shell_mcp" / "example.py").exists()
    assert state.read_worker_config()["runtime_digest"] == digest

    monkeypatch.setattr(installer, "_fetch_bytes", lambda *args, **kwargs: pytest.fail("downloaded"))
    cached = installer.install_or_update_runtime("https://example.test")
    assert cached["updated"] is False


def test_runtime_checksum_and_archive_validation(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    payload = _bundle()
    monkeypatch.setattr(
        installer,
        "fetch_manifest",
        lambda server: {
            "schema_version": 1,
            "sha256": "0" * 64,
            "bundle_version": "3.0.1",
            "url": "https://example.test/bundle.tgz",
        },
    )
    monkeypatch.setattr(installer, "_fetch_bytes", lambda url, timeout=60: payload)
    with pytest.raises(ValueError, match="checksum mismatch"):
        installer.install_or_update_runtime("https://example.test")

    archive = tmp_path / "unsafe.tgz"
    with tarfile.open(archive, mode="w:gz") as tar:
        info = tarfile.TarInfo("../escape")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(ValueError, match="unsafe worker bundle path"):
        installer._safe_extract(archive, tmp_path / "extract")  # noqa: SLF001

    link_archive = tmp_path / "link.tgz"
    with tarfile.open(link_archive, mode="w:gz") as tar:
        info = tarfile.TarInfo("local_shell_mcp/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "target"
        tar.addfile(info)
    with pytest.raises(ValueError, match="links are not supported"):
        installer._safe_extract(link_archive, tmp_path / "extract-links")  # noqa: SLF001


def test_fetch_manifest_validation(monkeypatch):
    valid = {
        "schema_version": 1,
        "sha256": "a" * 64,
        "bundle_version": "3.0.0",
        "url": "/remote/worker-bundle.tgz",
    }
    requested = []

    def fetch(url):
        requested.append(url)
        return json.dumps(valid).encode()

    monkeypatch.setattr(installer, "_fetch_bytes", fetch)
    result = installer.fetch_manifest("https://example.test/base")
    assert requested == ["https://example.test/base/remote/worker-bundle.tgz?manifest=1"]
    assert result["url"] == "https://example.test/remote/worker-bundle.tgz"

    monkeypatch.setattr(installer, "_fetch_bytes", lambda url: b"{}")
    with pytest.raises(ValueError, match="invalid remote worker manifest"):
        installer.fetch_manifest("https://example.test")

    incomplete = {"schema_version": 1, "sha256": "short", "url": ""}
    monkeypatch.setattr(installer, "_fetch_bytes", lambda url: json.dumps(incomplete).encode())
    with pytest.raises(ValueError, match="manifest is incomplete"):
        installer.fetch_manifest("https://example.test")


def test_fetch_bytes_uses_urlopen(monkeypatch):
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return b"payload"
    captured = []
    monkeypatch.setattr(
        installer.urllib.request,
        "urlopen",
        lambda request, timeout=60: captured.append((request, timeout)) or Response(),
    )
    assert installer._fetch_bytes("https://example.test/file", timeout=7) == b"payload"  # noqa: SLF001
    request, timeout = captured[0]
    assert request.full_url == "https://example.test/file"
    assert request.headers["Cache-control"] == "no-cache"
    assert request.headers["Pragma"] == "no-cache"
    assert timeout == 7


def test_install_without_existing_config_rejects_incomplete_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKER_STATE_DIR", str(tmp_path / "state"))
    payload_buffer = io.BytesIO()
    with tarfile.open(fileobj=payload_buffer, mode="w:gz") as tar:
        content = b"not a package"
        info = tarfile.TarInfo("other.txt")
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    payload = payload_buffer.getvalue()
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(
        installer,
        "fetch_manifest",
        lambda server: {"sha256": digest, "bundle_version": "v", "url": "https://s/b.tgz"},
    )
    monkeypatch.setattr(installer, "_fetch_bytes", lambda *args, **kwargs: payload)
    with pytest.raises(ValueError, match="does not contain local_shell_mcp"):
        installer.install_or_update_runtime("https://s")
