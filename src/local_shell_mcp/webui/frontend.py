"""Serve the compiled first-party React workspace from LSM's Python server.

JavaScript tooling is build-only. In onefile releases, the compressed frontend
is lazily unpacked into the Controller's private `.local-shell-mcp/` directory;
no WebUI runtime requires a Node process or writes beside the executable.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tarfile
import tempfile
import threading
from functools import lru_cache
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Match, Route

_STATIC_PREFIXES = ("assets/", "fonts/", "images/", "locales/", "favicon", "robots.txt", "manifest", "sw.js", "sw-heal.js", "registerSW.js", "workbox-")
_SPA_PREFIXES = ("c", "login", "register", "search", "agents", "settings", "control", "projects", "chat", "d", "presets", "prompts", "schedules", "memories")
_CACHE_LOCK = threading.Lock()
_MAX_FILE_BYTES = 60 * 1024 * 1024
_MAX_ASSET_BYTES = 256 * 1024 * 1024


@lru_cache(maxsize=16)
def _extract_frontend(archive: Path, state_dir: Path) -> Path:
    """Verify and atomically extract a versioned archive into private state."""
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()[:20]
    root = state_dir / "runtime" / "webui"
    target = root / digest
    marker = target / "index.html"
    if marker.is_file():
        return target
    root.mkdir(parents=True, exist_ok=True)
    with _CACHE_LOCK:
        if marker.is_file():
            return target
        staging = Path(tempfile.mkdtemp(prefix=".webui-", dir=root))
        try:
            total = 0
            with tarfile.open(archive, "r:gz") as contents:
                for item in contents:
                    parts = PurePosixPath(item.name).parts
                    # Tar paths are POSIX paths even on Windows. pathlib.Path
                    # follows the host platform and misses /absolute entries
                    # on Windows, allowing unexpected extraction locations.
                    if (not item.isfile() or not parts or "\\" in item.name or
                        PurePosixPath(item.name).is_absolute() or
                        (parts[0].endswith(":") or (len(parts[0]) > 1 and parts[0][1] == ":")) or
                        any(part in {"..", "."} or part.startswith(".") for part in parts)):
                        raise ValueError("Unsafe WebUI asset in release payload")
                    total += item.size
                    if item.size > _MAX_FILE_BYTES or total > _MAX_ASSET_BYTES:
                        raise ValueError("Oversized WebUI release payload")
                    destination = staging.joinpath(*parts)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    source = contents.extractfile(item)
                    if source is None:
                        raise ValueError("Missing WebUI asset in release payload")
                    with source, destination.open("wb") as output:
                        shutil.copyfileobj(source, output)
                    if os.name != "nt":
                        destination.chmod(0o600)
            if not (staging / "index.html").is_file():
                raise ValueError("WebUI release payload lacks index.html")
            if target.exists():
                shutil.rmtree(target)
            staging.rename(target)
            return target
        finally:
            if staging.exists():
                shutil.rmtree(staging)


def bundled_frontend() -> Path | None:
    root = Path(__file__).resolve().parent
    candidates = [root / "assets", root.parents[2] / "ui" / "workspace" / "client" / "dist"]
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    source_archive = root.parents[2] / "ui" / "workspace" / "frontend.tar.gz"
    for archive in (root / "frontend.tar.gz", source_archive):
        if archive.is_file():
            from ..settings import get_settings

            return _extract_frontend(archive, get_settings().state_dir)
    return None


def is_spa_path(path: str) -> bool:
    first = path.strip("/").split("/", 1)[0]
    return not first or first in _SPA_PREFIXES


def is_public_frontend(path: str, method: str) -> bool:
    if method not in {"GET", "HEAD"}:
        return False
    relative = path.lstrip("/")
    return is_spa_path(path) or relative.startswith(_STATIC_PREFIXES)


async def frontend(request: Request) -> Response:
    try:
        root = bundled_frontend()
    except (OSError, ValueError, tarfile.TarError):
        return JSONResponse({"error": "Unable to unpack WebUI assets"}, status_code=503)
    if root is None:
        return JSONResponse({"error": "WebUI assets have not been built"}, status_code=503)
    relative = unquote(request.path_params.get("path", ""))
    if "\x00" in relative or any(part in {".", ".."} or part.startswith(".") for part in relative.split("/")):
        return Response(status_code=404)
    try:
        path = (root / relative).resolve(strict=False)
        path.relative_to(root.resolve())
    except (OSError, ValueError):
        return Response(status_code=404)
    if not path.is_file() or path.suffix == ".map":
        if not is_spa_path("/" + relative):
            return Response(status_code=404)
        path = root / "index.html"
    headers = {"Cache-Control": "no-store"} if path.name == "index.html" else {"Cache-Control": "public, max-age=3600"}
    return FileResponse(path, headers=headers)


class FrontendRoute(Route):
    """Leave MCP and unknown server paths to the underlying application."""

    def matches(self, scope):
        path = scope.get("path", "")
        if scope["type"] != "http" or (path != "/" and not is_public_frontend(path, scope.get("method", ""))):
            return Match.NONE, {}
        return super().matches(scope)


def frontend_routes() -> list[Route]:
    return [FrontendRoute("/{path:path}", frontend, methods=["GET", "HEAD"])]
