"""Provide command-line entry points for stdio MCP, HTTP server, and remote-worker modes."""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import asynccontextmanager

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .auth import AuthMiddleware
from .http_app import build_http_app
from .oauth import (
    oauth_authorize_get,
    oauth_authorize_post,
    oauth_protected_resource,
    oauth_register,
    oauth_server_metadata,
    oauth_token,
)
from .remote import add_worker_cli_args, remote_routes, run_worker_from_args
from .settings import get_settings, validate_public_oauth_configuration
from .tools import build_mcp


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser shared by server and remote-worker modes."""
    parser = argparse.ArgumentParser(
        prog="local-shell-mcp",
        description="Run a local-shell-mcp server or remote worker.",
    )
    parser.set_defaults(handler=_run_server_from_args)
    parser.add_argument(
        "--mode",
        choices=["mcp", "http", "stdio"],
        default=None,
        help="Server transport mode; overrides LOCAL_SHELL_MCP_MODE",
    )
    parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="Path to config YAML; overrides LOCAL_SHELL_MCP_CONFIG",
    )
    parser.add_argument(
        "--remote",
        dest="remote",
        action="store_true",
        default=None,
        help="Enable remote worker mode (default)",
    )
    parser.add_argument(
        "--no-remote",
        dest="remote",
        action="store_false",
        help="Disable remote worker mode",
    )

    subparsers = parser.add_subparsers(dest="command")
    worker = subparsers.add_parser(
        "worker",
        help="Connect this machine to a local-shell-mcp control server",
    )
    add_worker_cli_args(worker)
    worker.set_defaults(handler=run_worker_from_args)
    return parser


def _apply_server_args(args: argparse.Namespace) -> None:
    """Project CLI server options into environment variables consumed by settings loading."""
    if args.config:
        os.environ["LOCAL_SHELL_MCP_CONFIG"] = args.config
    if args.mode:
        os.environ["LOCAL_SHELL_MCP_MODE"] = args.mode
    if args.remote is not None:
        os.environ["LOCAL_SHELL_MCP_REMOTE_ENABLED"] = "true" if args.remote else "false"


def _run_server_from_args(args: argparse.Namespace) -> None:
    """Select stdio MCP or HTTP server startup based on parsed CLI arguments."""
    _apply_server_args(args)

    settings = get_settings()
    if settings.mode == "http":
        run_http()
    elif settings.mode in {"mcp", "stdio"}:
        run_mcp()
    elif settings.mode == "both":
        raise SystemExit("mode=both is reserved; run separate mcp/http processes for now")
    else:
        raise SystemExit(f"Unsupported mode: {settings.mode}")


def _with_oauth_routes(inner_app) -> Starlette:  # noqa: ANN001
    """Wrap the MCP ASGI app with OAuth and remote routes when serving over HTTP."""

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
    if settings.remote_enabled:
        routes[2:2] = remote_routes()
    return Starlette(
        routes=routes,
        lifespan=lifespan,
    )


def run_mcp() -> None:
    """Run the FastMCP server on stdio using the current environment configuration."""
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
    """Run the HTTP server with FastAPI routes, MCP transport, OAuth metadata, and remote-worker endpoints."""
    settings = get_settings()
    validate_public_oauth_configuration(settings)
    app = build_http_app()
    uvicorn.run(app, host=settings.host, port=settings.port)


def main(argv: list[str] | None = None) -> None:
    """Parse CLI arguments and dispatch to server or worker mode."""
    args = _build_parser().parse_args(argv)
    args.handler(args)


if __name__ == "__main__":
    main(sys.argv[1:])
