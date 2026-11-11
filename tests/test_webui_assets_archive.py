"""Cross-platform packaging and safe lazy extraction of the React WebUI."""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import tarfile
from pathlib import Path

import pytest

from local_shell_mcp.webui import frontend


def _builder():
    source = Path(__file__).resolve().parents[1] / "scripts" / "embed-react-webui.py"
    spec = importlib.util.spec_from_file_location("embed_webui", source)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.bundle_react_assets


def test_archive_reproducible_and_extracts_only_in_private_state(tmp_path):
    source = tmp_path / "dist"
    (source / "assets").mkdir(parents=True)
    (source / "index.html").write_text("<title>local-shell-mcp</title>")
    (source / "assets" / "index.abc.js").write_text("console.log('works')")
    (source / "assets" / "index.abc.js.gz").write_bytes(b"ignored-precompressed")
    (source / "assets" / "index.abc.js.map").write_text("ignored-map")
    archive = tmp_path / "webui.tar.gz"
    builder = _builder()
    assert builder(source, archive) == 2
    first_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert builder(source, archive) == 2
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == first_digest
    state_dir = tmp_path / ".local-shell-mcp"
    assets = frontend._extract_frontend(archive, state_dir)
    assert assets.is_relative_to(state_dir)
    assert (assets / "assets/index.abc.js").read_text() == "console.log('works')"
    assert not (assets / "assets/index.abc.js.gz").exists()
    assert not (assets / "assets/index.abc.js.map").exists()
    assert frontend._extract_frontend(archive, state_dir) == assets
    assert not (tmp_path / "assets").exists()


def test_webui_archive_rejects_malicious_paths_without_writing_outside_state(tmp_path):
    archive = tmp_path / "unsafe.tar.gz"
    with (
        archive.open("wb") as destination,
        gzip.GzipFile(filename="", mode="wb", fileobj=destination) as writer,
        tarfile.open(mode="w|", fileobj=writer) as tar,
    ):
        for name in ("index.html", "../escaped.txt"):
            payload = b"bad"
            entry = tarfile.TarInfo(name)
            entry.size = len(payload)
            tar.addfile(entry, io.BytesIO(payload))
    state = tmp_path / ".local-shell-mcp"
    with pytest.raises(ValueError, match="Unsafe WebUI asset"):
        frontend._extract_frontend(archive, state)
    assert not (tmp_path / "escaped.txt").exists()
    assert not list((state / "runtime/webui").glob(".webui-*/index.html"))


def test_build_requires_valid_react_index(tmp_path):
    with pytest.raises(ValueError, match="React build missing"):
        _builder()(tmp_path, tmp_path / "dist.tar.gz")


def test_source_frontend_resolves_first_party_workspace() -> None:
    """No access to the deleted integrations tree is required at runtime."""
    source_root = Path(__file__).resolve().parents[1]
    root = source_root / "ui" / "workspace"
    if not (root / "client" / "dist" / "index.html").is_file():
        pytest.skip("React UI not built in this source checkout")
    assert frontend.bundled_frontend() == root / "client" / "dist"
