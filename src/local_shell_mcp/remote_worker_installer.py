from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from . import __version__
from .remote_worker_state import (
    read_worker_config,
    update_runtime_metadata,
    worker_runtime_dir,
    worker_state_dir,
)

_WORKER_MANIFEST_PATH = "/remote/worker-bundle.tgz?manifest=1"
_WINDOWS_PTY_REQUIREMENT = "pywinpty>=2.0.13"
_GUI_REQUIREMENTS: dict[str, tuple[tuple[str, str], ...]] = {
    "win32": (
        ("PIL", "pillow>=10.3.0"),
        ("uiautomation", "uiautomation>=2.0.29,<3"),
    ),
    "linux": (
        ("PIL", "pillow>=10.3.0"),
        ("dbus_next", "dbus-next>=0.2.3,<1"),
        ("Xlib", "python-xlib>=0.33,<1"),
    ),
    "darwin": (
        ("PIL", "pillow>=10.3.0"),
        ("ApplicationServices", "pyobjc-framework-ApplicationServices>=11.1,<13"),
        ("Quartz", "pyobjc-framework-Quartz>=11.1,<13"),
    ),
}


def worker_dependency_dir() -> Path:
    python_tag = f"py{sys.version_info.major}{sys.version_info.minor}"
    return worker_state_dir() / "dependencies" / python_tag


def _activate_worker_dependency_dir(path: Path) -> None:
    value = str(path.resolve())
    if value not in sys.path:
        sys.path.insert(0, value)
    current = [entry for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep) if entry]
    if value not in current:
        os.environ["PYTHONPATH"] = os.pathsep.join([value, *current])


def ensure_platform_dependencies() -> dict[str, Any]:
    path = worker_dependency_dir()
    _activate_worker_dependency_dir(path)
    if sys.platform != "win32":
        return {"available": True, "installed": False, "path": str(path)}
    try:
        module = importlib.import_module("winpty")
    except (ImportError, OSError):
        module = None
    if module is not None and hasattr(module, "PtyProcess"):
        return {"available": True, "installed": False, "path": str(path)}

    path.mkdir(parents=True, exist_ok=True)
    argv = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--retries",
        "1",
        "--timeout",
        "5",
        "--target",
        str(path),
        _WINDOWS_PTY_REQUIREMENT,
    ]
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "available": False,
            "installed": False,
            "path": str(path),
            "error": str(exc),
        }
    importlib.invalidate_caches()
    try:
        module = importlib.import_module("winpty")
    except (ImportError, OSError):
        module = None
    available = module is not None and hasattr(module, "PtyProcess")
    result: dict[str, Any] = {
        "available": available,
        "installed": available and completed.returncode == 0,
        "path": str(path),
    }
    if not available:
        result["error"] = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or f"pip exited with code {completed.returncode}"
        )
    return result


def ensure_gui_dependencies() -> dict[str, Any]:
    path = worker_dependency_dir()
    _activate_worker_dependency_dir(path)
    required = _GUI_REQUIREMENTS.get(sys.platform, ())
    if not required:
        return {
            "available": True,
            "installed": False,
            "path": str(path),
            "missing": [],
        }

    missing: list[tuple[str, str]] = []
    for module_name, requirement in required:
        try:
            importlib.import_module(module_name)
        except (ImportError, OSError):
            missing.append((module_name, requirement))
    if not missing:
        return {
            "available": True,
            "installed": False,
            "path": str(path),
            "missing": [],
        }

    path.mkdir(parents=True, exist_ok=True)
    argv = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--retries",
        "1",
        "--timeout",
        "10",
        "--target",
        str(path),
        *[requirement for _module_name, requirement in missing],
    ]
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "available": False,
            "installed": False,
            "path": str(path),
            "missing": [module for module, _requirement in missing],
            "error": str(exc),
        }

    importlib.invalidate_caches()
    still_missing: list[str] = []
    for module_name, _requirement in missing:
        try:
            importlib.import_module(module_name)
        except (ImportError, OSError):
            still_missing.append(module_name)
    available = not still_missing
    result: dict[str, Any] = {
        "available": available,
        "installed": available and completed.returncode == 0,
        "path": str(path),
        "missing": still_missing,
    }
    if not available:
        result["error"] = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or f"pip exited with code {completed.returncode}"
        )
    return result


def _fetch_bytes(url: str, timeout: float = 60) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": f"local-shell-mcp-worker/{__version__}",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read()


def fetch_manifest(server: str) -> dict[str, Any]:
    url = server.rstrip("/") + _WORKER_MANIFEST_PATH
    data = json.loads(_fetch_bytes(url).decode("utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("invalid remote worker manifest")
    digest = str(data.get("sha256") or "")
    bundle_url = str(data.get("url") or "")
    if len(digest) != 64 or not bundle_url:
        raise ValueError("remote worker manifest is incomplete")
    data["url"] = urllib.parse.urljoin(server.rstrip("/") + "/", bundle_url)
    return data


def _safe_extract(archive: Path, destination: Path) -> None:
    destination_resolved = destination.resolve()
    with tarfile.open(archive, mode="r:gz") as tar:
        for member in tar.getmembers():
            target = (destination / member.name).resolve()
            if target != destination_resolved and destination_resolved not in target.parents:
                raise ValueError(f"unsafe worker bundle path: {member.name}")
            if member.issym() or member.islnk():
                raise ValueError(f"worker bundle links are not supported: {member.name}")
        tar.extractall(destination)  # noqa: S202


def install_or_update_runtime(server: str, *, force: bool = False) -> dict[str, Any]:
    manifest = fetch_manifest(server)
    digest = str(manifest["sha256"])
    version = str(manifest.get("bundle_version") or "")
    runtime = worker_runtime_dir()
    try:
        current = read_worker_config()
    except (FileNotFoundError, ValueError):
        current = {}
    if not force and runtime.is_dir() and current.get("runtime_digest") == digest:
        return {"updated": False, "sha256": digest, "version": version, "runtime": str(runtime)}

    state_dir = worker_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = _fetch_bytes(str(manifest["url"]), timeout=120)
    actual = hashlib.sha256(payload).hexdigest()
    if actual != digest:
        raise ValueError(f"worker bundle checksum mismatch: expected {digest}, got {actual}")

    with tempfile.TemporaryDirectory(prefix="runtime-install-", dir=state_dir) as temporary:
        temporary_path = Path(temporary)
        archive = temporary_path / "worker.tgz"
        extracted = temporary_path / "runtime"
        archive.write_bytes(payload)
        extracted.mkdir()
        _safe_extract(archive, extracted)
        if not (extracted / "local_shell_mcp").is_dir():
            raise ValueError("worker bundle does not contain local_shell_mcp")

        staged = state_dir / f"runtime.next.{os.getpid()}"
        backup = state_dir / f"runtime.previous.{os.getpid()}"
        shutil.rmtree(staged, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)
        shutil.copytree(extracted, staged)
        try:
            if runtime.exists():
                runtime.replace(backup)
            staged.replace(runtime)
        except Exception:
            if not runtime.exists() and backup.exists():
                backup.replace(runtime)
            raise
        finally:
            shutil.rmtree(staged, ignore_errors=True)
            shutil.rmtree(backup, ignore_errors=True)

    if current:
        update_runtime_metadata(digest, version)
    return {"updated": True, "sha256": digest, "version": version, "runtime": str(runtime)}
