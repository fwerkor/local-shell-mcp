"""Serve the compiled LibreChat React workspace from LSM's Python HTTP server.

Node and package managers are build-only dependencies; the Controller runtime
never launches a separate frontend or LibreChat backend process.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

_STATIC_PREFIXES = ("assets/", "fonts/", "images/", "locales/", "favicon", "robots.txt", "manifest")
_SPA_PREFIXES = ("c", "login", "register", "search", "agents", "settings", "control", "projects", "chat", "d", "presets", "prompts", "schedules", "memories")


def bundled_frontend() -> Path | None:
    root = Path(__file__).resolve().parent
    candidates = [root / "assets", root.parents[2] / "integrations" / "librechat" / "app" / "client" / "dist"]
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return None


def is_spa_path(path: str) -> bool:
    first = path.strip("/").split("/", 1)[0]
    return first in _SPA_PREFIXES


def is_public_frontend(path: str, method: str) -> bool:
    if method not in {"GET", "HEAD"}:
        return False
    relative = path.lstrip("/")
    return is_spa_path(path) or relative.startswith(_STATIC_PREFIXES)


async def frontend(request: Request) -> Response:
    root = bundled_frontend()
    if root is None:
        return JSONResponse({"error": "WebUI React assets have not been built"}, status_code=503)
    relative = unquote(request.path_params.get("path", ""))
    # Never serve source, generated sourcemaps, dotfiles or untrusted filesystem paths.
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


def frontend_routes() -> list[Route]:
    return [Route("/{path:path}", frontend, methods=["GET", "HEAD"])]
