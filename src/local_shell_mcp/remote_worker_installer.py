from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .remote_worker_state import (
    read_worker_config,
    update_runtime_metadata,
    worker_runtime_dir,
    worker_state_dir,
)

_WORKER_MANIFEST_PATH = "/remote/worker-bundle.tgz?manifest=1"


def _fetch_bytes(url: str, timeout: float = 60) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
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
