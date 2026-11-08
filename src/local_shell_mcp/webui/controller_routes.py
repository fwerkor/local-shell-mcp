"""Mount the same authenticated LSM Controller handlers within the React UI.

Both surfaces use the existing Python implementation and permissions. No
reverse proxy, separate Controller API, identity mapping, or Node middleware.
"""

from __future__ import annotations

from starlette.routing import Route

from ..human_ui import UI_API_PREFIX, ui_routes

_PRIVATE_PREFIXES = ("librechat", "hosted-chat")


def controller_routes() -> list[Route]:
    from .attachments import attachment_routes

    target = "/api/lsm/controller"
    output: list[Route] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for item in ui_routes():
        if not isinstance(item, Route) or not item.path.startswith(UI_API_PREFIX + "/"):
            continue
        relative = item.path[len(UI_API_PREFIX) + 1:]
        if relative.split("/", 1)[0] in _PRIVATE_PREFIXES:
            continue
        dest = f"{target}/{relative}"
        methods = tuple(sorted(item.methods)) if item.methods else ("GET",)
        key = (dest, methods)
        if key in seen:
            continue
        seen.add(key)
        output.append(Route(dest, item.endpoint, methods=list(methods), name=item.name))
    return [*attachment_routes(), *output]
