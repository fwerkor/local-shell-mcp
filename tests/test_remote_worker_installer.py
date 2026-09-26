from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
from types import SimpleNamespace

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
    assert request.headers["User-agent"] == f"local-shell-mcp-worker/{installer.__version__}"
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



def test_worker_dependency_bootstrap_is_noop_off_windows(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(installer.sys, "platform", "linux")
    monkeypatch.setattr(installer.sys, "path", list(installer.sys.path))
    monkeypatch.setenv("PYTHONPATH", "")

    result = installer.ensure_platform_dependencies()

    assert result["available"] is True
    assert result["installed"] is False


def test_windows_worker_reuses_existing_pywinpty(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(installer.sys, "platform", "win32")
    monkeypatch.setattr(installer.sys, "path", list(installer.sys.path))
    monkeypatch.setenv("PYTHONPATH", "")
    monkeypatch.setattr(
        installer.importlib,
        "import_module",
        lambda name: SimpleNamespace(PtyProcess=object()),
    )
    monkeypatch.setattr(
        installer.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("pip should not run when pywinpty is available"),
    )

    result = installer.ensure_platform_dependencies()

    assert result["available"] is True
    assert result["installed"] is False


def test_windows_worker_reports_failed_import_after_successful_pip(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(installer.sys, "platform", "win32")
    monkeypatch.setattr(installer.sys, "path", list(installer.sys.path))
    monkeypatch.setenv("PYTHONPATH", "")
    def missing(name):
        raise ImportError(name)

    monkeypatch.setattr(installer.importlib, "import_module", missing)
    monkeypatch.setattr(installer.importlib, "invalidate_caches", lambda: None)
    monkeypatch.setattr(
        installer.subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 0, stdout="installed but unavailable", stderr=""
        ),
    )

    result = installer.ensure_platform_dependencies()

    assert result["available"] is False
    assert result["installed"] is False
    assert result["error"] == "installed but unavailable"

def test_windows_worker_installs_pywinpty_into_state_dir(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(installer.sys, "platform", "win32")
    monkeypatch.setattr(installer.sys, "path", list(installer.sys.path))
    monkeypatch.setenv("PYTHONPATH", "")
    imports = []

    def import_module(name):
        imports.append(name)
        if len(imports) == 1:
            raise ImportError(name)
        return SimpleNamespace(PtyProcess=object())

    captured = {}

    def run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 0, stdout="installed", stderr="")

    monkeypatch.setattr(installer.importlib, "import_module", import_module)
    monkeypatch.setattr(installer.importlib, "invalidate_caches", lambda: None)
    monkeypatch.setattr(installer.subprocess, "run", run)

    result = installer.ensure_platform_dependencies()

    target = installer.worker_dependency_dir()
    assert result["available"] is True
    assert result["installed"] is True
    assert captured["argv"][-1] == "pywinpty>=2.0.13"
    assert captured["argv"][captured["argv"].index("--target") + 1] == str(target)
    assert str(target.resolve()) in installer.sys.path
    assert captured["kwargs"]["timeout"] == 60


def test_windows_worker_falls_back_when_pywinpty_install_fails(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(installer.sys, "platform", "win32")
    monkeypatch.setattr(installer.sys, "path", list(installer.sys.path))
    monkeypatch.setenv("PYTHONPATH", "")

    def missing(name):
        raise ImportError(name)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 60)

    monkeypatch.setattr(installer.importlib, "import_module", missing)
    monkeypatch.setattr(installer.subprocess, "run", timeout)

    result = installer.ensure_platform_dependencies()

    assert result["available"] is False
    assert result["installed"] is False
    assert "timed out" in result["error"]


def test_gui_dependency_bootstrap_reuses_available_modules(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(installer.sys, "platform", "linux")
    monkeypatch.setattr(installer.sys, "path", list(installer.sys.path))
    monkeypatch.setenv("PYTHONPATH", "")
    imported = []

    def import_module(name):
        imported.append(name)
        return SimpleNamespace()

    monkeypatch.setattr(installer.importlib, "import_module", import_module)
    monkeypatch.setattr(
        installer.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("pip should not run when GUI deps are available"),
    )

    result = installer.ensure_gui_dependencies()

    assert result["available"] is True
    assert result["installed"] is False
    assert result["missing"] == []
    assert imported == ["PIL", "dbus_next", "Xlib"]


def test_gui_dependency_bootstrap_installs_missing_modules(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(installer.sys, "platform", "win32")
    monkeypatch.setattr(installer.sys, "path", list(installer.sys.path))
    monkeypatch.setenv("PYTHONPATH", "")
    installed = False
    captured = {}

    def import_module(name):
        if not installed:
            raise ImportError(name)
        return SimpleNamespace()

    def run(argv, **kwargs):
        nonlocal installed
        installed = True
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 0, stdout="installed", stderr="")

    monkeypatch.setattr(installer.importlib, "import_module", import_module)
    monkeypatch.setattr(installer.importlib, "invalidate_caches", lambda: None)
    monkeypatch.setattr(installer.subprocess, "run", run)

    result = installer.ensure_gui_dependencies()

    assert result["available"] is True
    assert result["installed"] is True
    assert result["missing"] == []
    assert "uiautomation>=2.0.29,<3" in captured["argv"]
    assert captured["kwargs"]["timeout"] == 180


def test_gui_dependency_bootstrap_failure_is_nonfatal_status(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(installer.sys, "platform", "darwin")
    monkeypatch.setattr(installer.sys, "path", list(installer.sys.path))
    monkeypatch.setenv("PYTHONPATH", "")

    def missing(name):
        raise ImportError(name)

    monkeypatch.setattr(installer.importlib, "import_module", missing)
    monkeypatch.setattr(
        installer.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(args[0], 180)
        ),
    )

    result = installer.ensure_gui_dependencies()

    assert result["available"] is False
    assert result["installed"] is False
    assert result["missing"] == ["PIL", "ApplicationServices", "Quartz"]
    assert "timed out" in result["error"]


def test_gui_dependency_bootstrap_serializes_inflight_install(tmp_path, monkeypatch):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(installer.sys, "platform", "win32")
    monkeypatch.setattr(installer.sys, "path", list(installer.sys.path))
    monkeypatch.setenv("PYTHONPATH", "")

    installed = False
    started = threading.Event()
    release = threading.Event()
    run_calls = []

    def import_module(name):
        if not installed:
            raise ImportError(name)
        return SimpleNamespace()

    def run(argv, **kwargs):
        nonlocal installed
        run_calls.append(argv)
        started.set()
        assert release.wait(timeout=2)
        installed = True
        return subprocess.CompletedProcess(argv, 0, stdout="installed", stderr="")

    monkeypatch.setattr(installer.importlib, "import_module", import_module)
    monkeypatch.setattr(installer.importlib, "invalidate_caches", lambda: None)
    monkeypatch.setattr(installer.subprocess, "run", run)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(installer.ensure_gui_dependencies)
        assert started.wait(timeout=1)
        second = pool.submit(installer.ensure_gui_dependencies)
        time.sleep(0.05)
        assert len(run_calls) == 1
        release.set()
        first_result = first.result(timeout=2)
        second_result = second.result(timeout=2)

    assert first_result["available"] is True
    assert second_result["available"] is True
    assert len(run_calls) == 1


def test_gui_dependency_bootstrap_unknown_platform_is_noop(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(installer.sys, "platform", "plan9")
    monkeypatch.setattr(installer.sys, "path", list(installer.sys.path))
    monkeypatch.setenv("PYTHONPATH", "")

    result = installer.ensure_gui_dependencies()

    assert result["available"] is True
    assert result["installed"] is False
    assert result["missing"] == []
