from __future__ import annotations

import argparse
import os
import sys


def _with_oauth_routes(inner_app):  # noqa: ANN001
    from contextlib import asynccontextmanager

    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Mount, Route

    from .downloads import download_routes
    from .human_ui import ui_routes
    from .oauth import (
        oauth_authorize_get,
        oauth_authorize_post,
        oauth_protected_resource,
        oauth_register,
        oauth_server_metadata,
        oauth_token,
    )
    from .remote import remote_routes
    from .settings import get_settings

    @asynccontextmanager
    async def lifespan(app):  # noqa: ANN001
        async with inner_app.router.lifespan_context(inner_app):
            yield

    routes = [
        Route("/healthz", lambda request: JSONResponse({"ok": True}), methods=["GET"]),
        Route("/readyz", lambda request: JSONResponse({"ok": True}), methods=["GET"]),
        Route("/.well-known/oauth-protected-resource", oauth_protected_resource, methods=["GET"]),
        Route("/.well-known/oauth-authorization-server", oauth_server_metadata, methods=["GET"]),
        Route("/.well-known/openid-configuration", oauth_server_metadata, methods=["GET"]),
        Route("/oauth/register", oauth_register, methods=["POST"]),
        Route("/oauth/authorize", oauth_authorize_get, methods=["GET"]),
        Route("/oauth/authorize", oauth_authorize_post, methods=["POST"]),
        Route("/oauth/token", oauth_token, methods=["POST"]),
        Mount("/", app=inner_app),
    ]
    settings = get_settings()
    routes[2:2] = download_routes()
    routes[2:2] = ui_routes()
    if settings.remote_enabled:
        routes[2:2] = remote_routes()
    return Starlette(
        routes=routes,
        lifespan=lifespan,
    )


def run_mcp() -> None:
    import uvicorn

    from .auth import AuthMiddleware
    from .settings import get_settings, validate_public_oauth_configuration
    from .tools import build_mcp

    settings = get_settings()
    validate_public_oauth_configuration(settings)
    mcp = build_mcp()

    if settings.mode == "stdio":
        mcp.run(transport="stdio")
        return

    for attr in ("streamable_http_app", "sse_app"):
        if hasattr(mcp, attr):
            inner = getattr(mcp, attr)()
            app = _with_oauth_routes(inner)
            if settings.auth_mode != "none":
                app.add_middleware(AuthMiddleware)
            uvicorn.run(app, host=settings.host, port=settings.port)
            return

    # Fallback for older MCP SDKs. OAuth metadata cannot be attached in this mode, so this is
    # suitable only for localhost/stdio-style testing.
    try:
        mcp.run(transport="streamable-http")
    except TypeError:
        mcp.run(transport="sse")


def run_http() -> None:
    import uvicorn

    from .http_app import build_http_app
    from .settings import get_settings, validate_public_oauth_configuration

    settings = get_settings()
    validate_public_oauth_configuration(settings)
    app = build_http_app()
    uvicorn.run(app, host=settings.host, port=settings.port)


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] == "worker":
        from .remote import run_worker_cli

        run_worker_cli(argv[1:])
        return
    if argv and argv[0] == "version":
        from .version import format_version_info

        print(format_version_info())
        return
    if argv and argv[0] in {"--version", "-V"}:
        from . import __version__

        print(__version__)
        return

    parser = argparse.ArgumentParser(description="local-shell-mcp")
    parser.add_argument("--mode", choices=["mcp", "http", "stdio"], default=None)
    parser.add_argument("--config", default=None, help="Path to config YAML")
    parser.add_argument("--remote", dest="remote", action="store_true", default=None, help="Enable remote worker mode (default)")
    parser.add_argument("--no-remote", dest="remote", action="store_false", help="Disable remote worker mode")
    args = parser.parse_args(argv)
    if args.config:
        os.environ["LOCAL_SHELL_MCP_CONFIG"] = args.config
    if args.mode:
        os.environ["LOCAL_SHELL_MCP_MODE"] = args.mode
    if args.remote is not None:
        os.environ["LOCAL_SHELL_MCP_REMOTE_ENABLED"] = "true" if args.remote else "false"

    from .settings import get_settings

    settings = get_settings()
    if settings.mode == "http":
        run_http()
    elif settings.mode in {"mcp", "stdio"}:
        run_mcp()
    elif settings.mode == "both":
        raise SystemExit("mode=both is reserved; run separate mcp/http processes for now")
    else:
        raise SystemExit(f"Unsupported mode: {settings.mode}")


if __name__ == "__main__":
    main(sys.argv[1:])
