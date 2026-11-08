"""WebUI asset extraction fails closed for malicious, oversized and broken bundles."""

from __future__ import annotations

import gzip
import io
import tarfile
from pathlib import Path

import httpx
import pytest
from starlette.applications import Starlette

from local_shell_mcp.webui import frontend


def _archive(tmp_path: Path, entries: list[tuple[str, bytes, str]]):
    path = tmp_path / "assets.tar.gz"
    with path.open("wb") as output, gzip.GzipFile(fileobj=output, mode="wb", filename="") as zipped, \
            tarfile.open(fileobj=zipped, mode="w|") as archive:
        for name, payload, kind in entries:
            info = tarfile.TarInfo(name)
            if kind == "file":
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            elif kind == "dir":
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            elif kind == "link":
                info.type = tarfile.SYMTYPE
                info.linkname = "../../secrets"
                archive.addfile(info)
    return path


@pytest.mark.parametrize("item", [
    ("/absolute", b"bad", "file"),
    (".hidden", b"bad", "file"),
    ("asset/../secret", b"bad", "file"),
    ("an-ignored-dir", b"", "dir"),
    ("path/link", b"", "link"),
])
def test_untrusted_archive_members_are_rejected(tmp_path, item):
    archive = _archive(tmp_path, [("index.html", b"ok", "file"), item])
    with pytest.raises(ValueError, match="Unsafe"):
        frontend._extract_frontend(archive, tmp_path / ".local-shell-mcp")
    assert not (tmp_path / "secret").exists()


def test_archive_without_index_fails_and_temporary_directory_cleans_up(tmp_path):
    archive = _archive(tmp_path, [("assets/main.js", b"safe", "file")])
    with pytest.raises(ValueError, match="index.html"):
        frontend._extract_frontend(archive, tmp_path / ".local-shell-mcp")
    assert not list((tmp_path / ".local-shell-mcp/runtime/webui").glob(".webui-*"))


def test_archive_size_guard_and_repeated_valid_extraction(tmp_path, monkeypatch):
    archive = _archive(tmp_path, [("index.html", b"html", "file"), ("assets/a.js", b"manybytes", "file")])
    monkeypatch.setattr(frontend, "_MAX_FILE_BYTES", 5)
    with pytest.raises(ValueError, match="Oversized"):
        frontend._extract_frontend(archive, tmp_path / ".local-shell-mcp")
    monkeypatch.setattr(frontend, "_MAX_FILE_BYTES", 60 * 1024 * 1024)
    where = frontend._extract_frontend(archive, tmp_path / ".local-shell-mcp")
    assert (where / "index.html").read_bytes() == b"html"
    assert frontend._extract_frontend(archive, tmp_path / ".local-shell-mcp") == where


@pytest.mark.asyncio
async def test_static_app_does_not_serve_dotfiles_maps_or_unknown_paths(tmp_path, monkeypatch):
    bundle = tmp_path / "dist"
    (bundle / "assets").mkdir(parents=True)
    (bundle / "index.html").write_text("<title>LSM</title>")
    (bundle / "assets/a.js").write_bytes(b"console.log('ready')")
    (bundle / "assets/secrets.map").write_bytes(b"private")
    (bundle / ".env").write_bytes(b"private")
    monkeypatch.setattr(frontend, "bundled_frontend", lambda: bundle)
    app = Starlette(routes=frontend.frontend_routes())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        assert (await client.get("/assets/a.js")).status_code == 200
        assert (await client.get("/assets/secrets.map")).status_code == 404
        assert (await client.get("/.env")).status_code == 404
        assert (await client.get("/not-a-spa-page")).status_code == 404
        assert (await client.get("/c/new")).status_code == 200
        assert (await client.get("/assets/nonexistent.js")).status_code == 404
    monkeypatch.setattr(frontend, "bundled_frontend", lambda: None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        assert (await client.get("/c/new")).status_code == 503
    monkeypatch.setattr(frontend, "bundled_frontend", lambda: (_ for _ in ()).throw(ValueError("broken archive")))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        assert (await client.get("/c/new")).status_code == 503


def test_bundled_frontend_uses_compressed_release_when_source_dist_is_missing(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from local_shell_mcp import settings as settings_module

    root = tmp_path / "src" / "local_shell_mcp" / "webui"
    root.mkdir(parents=True)
    archive = _archive(tmp_path, [("index.html", b"<html>test</html>", "file")])
    (root / "frontend.tar.gz").write_bytes(archive.read_bytes())
    monkeypatch.setattr(frontend, "__file__", str(root / "frontend.py"))
    monkeypatch.setattr(settings_module, "get_settings",
                        lambda: SimpleNamespace(state_dir=tmp_path / ".local-shell-mcp"))
    found = frontend.bundled_frontend()
    assert found is not None
    assert found.is_relative_to(tmp_path / ".local-shell-mcp")
    assert (found / "index.html").read_bytes() == b"<html>test</html>"


def test_reused_frontend_release_cache_is_not_unpacked_again(tmp_path):
    import hashlib

    archive = _archive(tmp_path, [("index.html", b"ok", "file")])
    state = tmp_path / ".local-shell-mcp"
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()[:20]
    cached = state / "runtime" / "webui" / digest
    cached.mkdir(parents=True)
    (cached / "index.html").write_bytes(b"preexisting-index")
    frontend._extract_frontend.cache_clear()
    assert frontend._extract_frontend(archive, state) == cached
    assert (cached / "index.html").read_bytes() == b"preexisting-index"
