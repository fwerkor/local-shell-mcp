"""First-party Controller routing replaces the old Node reverse proxy."""

from __future__ import annotations

from types import SimpleNamespace

from local_shell_mcp.webui.controller_routes import controller_routes


def test_react_controller_routes_reuse_python_handlers(monkeypatch):
    from local_shell_mcp import human_ui
    from local_shell_mcp.webui import controller_routes as routes_module

    settings = SimpleNamespace(ui_enabled=True, ui_path="ui")
    monkeypatch.setattr(human_ui, "get_settings", lambda: settings)
    original = human_ui.ui_routes()
    mirrored = routes_module.controller_routes()
    first_party = {route.path: route.endpoint for route in mirrored}
    old_routes = {route.path: route.endpoint for route in original}
    assert len(first_party) >= 24
    for relative in ("bootstrap", "dashboard", "machines", "files", "files/content", "files/upload",
                     "gui/frame", "gui/action", "terminals", "logical-sessions", "audit", "remotes",
                     "nested-mcp", "settings/{action}"):
        old = "/api/ui/" + relative
        new = "/api/lsm/controller/" + relative
        assert new in first_party
        if old in old_routes:
            assert first_party[new] is old_routes[old]
    assert not any("librechat" in path or "hosted-chat" in path for path in first_party)


def test_controller_routes_do_not_duplicate_registered_paths(monkeypatch):
    from local_shell_mcp import human_ui

    monkeypatch.setattr(human_ui, "get_settings", lambda: SimpleNamespace(ui_enabled=True, ui_path="ui"))
    rows = controller_routes()
    assert len({(row.path, tuple(sorted(row.methods))) for row in rows}) == len(rows)


def test_controller_routes_keep_login_private_and_coalesce_aliases(monkeypatch):
    from starlette.routing import Route

    from local_shell_mcp.webui import controller_routes as module

    async def handler(request):
        pass

    row = Route("/api/ui/files", handler)
    monkeypatch.setattr(module, "ui_routes", lambda: [
        row, row, Route("/api/ui/webui/ticket", handler), Route("/unrelated", handler),
    ])
    paths = [row.path for row in module.controller_routes()]
    assert paths.count("/api/lsm/controller/files") == 1
    assert not any("ticket" in path for path in paths)
