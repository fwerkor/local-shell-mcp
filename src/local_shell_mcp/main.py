from __future__ import annotations

import argparse
import logging
import os
import sys

# Long-lived MCP connections must not prevent process supervisors from observing exit.
_GRACEFUL_SHUTDOWN_TIMEOUT_S = 10
_LOG_LEVEL_ENV = "LOCAL_SHELL_MCP_LOG_LEVEL"
_DEFAULT_LOG_LEVEL = "WARNING"
_LOG_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}


def _log_level_name(value: str | None = None) -> str:
    raw = os.getenv(_LOG_LEVEL_ENV, _DEFAULT_LOG_LEVEL) if value is None else value
    name = str(raw).strip().upper()
    if name not in _LOG_LEVELS:
        choices = ", ".join(_LOG_LEVELS)
        raise ValueError(f"{_LOG_LEVEL_ENV} must be one of: {choices}")
    return name


def _configure_logging() -> str:
    name = _log_level_name()
    level = _LOG_LEVELS[name]
    logging.basicConfig(level=level)
    logging.getLogger().setLevel(level)
    return name


def _run_uvicorn(app, settings) -> None:  # noqa: ANN001
    from contextlib import suppress

    import uvicorn
    from uvicorn.main import STARTUP_FAILURE

    from .remote import (
        _interrupt_remote_polls_for_shutdown,
        _prepare_remote_polls_for_server_start,
    )

    class ShutdownAwareServer(uvicorn.Server):
        async def shutdown(self, sockets=None) -> None:  # noqa: ANN001
            _interrupt_remote_polls_for_shutdown()
            await super().shutdown(sockets=sockets)

    config = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        forwarded_allow_ips=settings.forwarded_allow_ips,
        timeout_graceful_shutdown=_GRACEFUL_SHUTDOWN_TIMEOUT_S,
        log_level=_log_level_name().lower(),
    )
    server = ShutdownAwareServer(config=config)
    _prepare_remote_polls_for_server_start()
    with suppress(KeyboardInterrupt):  # pragma: full coverage
        server.run()
    if not server.started:
        raise SystemExit(STARTUP_FAILURE)


def _with_oauth_routes(inner_app):  # noqa: ANN001
    from contextlib import asynccontextmanager

    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Mount, Route

    from .downloads import download_routes
    from .human_ui import ui_routes
    from .live_channel_routes import live_channel_routes
    from .oauth import (
        oauth_authorize_get,
        oauth_authorize_post,
        oauth_protected_resource,
        oauth_register,
        oauth_server_metadata,
        oauth_token,
    )
    from .remote_worker_routes import remote_routes
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
    if settings.ui_enabled and settings.live_workspace_enabled:
        routes[2:2] = live_channel_routes()
    if settings.ui_enabled:
        routes[2:2] = ui_routes()
    if settings.remote_enabled:
        routes[2:2] = remote_routes()
    return Starlette(
        routes=routes,
        lifespan=lifespan,
    )


def _build_mcp_http_app(mcp):  # noqa: ANN001
    from .auth import (
        AuthMiddleware,
        EmbeddedUiCorsMiddleware,
        McpSessionLimitMiddleware,
        RequestBodyLimitMiddleware,
    )
    from .settings import get_settings

    settings = get_settings()
    inner = mcp.streamable_http_app()
    session_manager = getattr(mcp, "_session_manager", None)
    if session_manager is not None and hasattr(session_manager, "session_idle_timeout"):
        session_manager.session_idle_timeout = max(1, settings.mcp_session_idle_timeout_s)

    app = _with_oauth_routes(inner)
    if session_manager is not None:
        app.add_middleware(
            McpSessionLimitMiddleware,
            session_manager=session_manager,
        )
    if settings.auth_mode != "none":
        app.add_middleware(AuthMiddleware)
    app.add_middleware(RequestBodyLimitMiddleware)
    # Must be outermost so browser preflights from the MCP App sandbox do not
    # reach OAuth middleware. Actual API requests still require bearer auth.
    app.add_middleware(EmbeddedUiCorsMiddleware)
    return app


def run_mcp() -> None:
    from .deprecated_tools import install_deprecated_tool_tombstones

    install_deprecated_tool_tombstones()

    from .settings import get_settings, validate_public_oauth_configuration
    from .tools import build_mcp

    settings = get_settings()
    validate_public_oauth_configuration(settings)
    mcp = build_mcp()

    if settings.mode == "stdio":
        mcp.run(transport="stdio")
        return

    if hasattr(mcp, "streamable_http_app"):
        _run_uvicorn(_build_mcp_http_app(mcp), settings)
        return
    if hasattr(mcp, "sse_app"):
        from .auth import AuthMiddleware, RequestBodyLimitMiddleware

        app = _with_oauth_routes(mcp.sse_app())
        if settings.auth_mode != "none":
            app.add_middleware(AuthMiddleware)
        app.add_middleware(RequestBodyLimitMiddleware)
        _run_uvicorn(app, settings)
        return

    try:
        mcp.run(transport="streamable-http")
    except TypeError:
        mcp.run(transport="sse")


def run_http() -> None:
    from .http_app import build_http_app
    from .settings import get_settings, validate_public_oauth_configuration

    settings = get_settings()
    validate_public_oauth_configuration(settings)
    app = build_http_app()
    _run_uvicorn(app, settings)


def main(argv: list[str] | None = None) -> None:
    _configure_logging()
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] == "job-runner":
        from .jobs import run_job_runner_cli

        run_job_runner_cli(argv[1:])
        return
    if argv and argv[0] == "worker":
        from .remote_worker_cli import run_worker_cli

        run_worker_cli(argv[1:])
        return
    if argv and argv[0] == "version":
        from .version import format_version_info

        print(format_version_info())
        return
    if argv and argv[0] == "tui":
        from .human_ui import run_tui_cli

        run_tui_cli(argv[1:])
        return
    if argv and argv[0] in {"--version", "-V"}:
        from . import __version__

        print(__version__)
        return

    parser = argparse.ArgumentParser(description="local-shell-mcp")
    parser.add_argument("--mode", choices=["mcp", "http", "stdio"], default=None)
    parser.add_argument("--config", default=None, help="Path to config YAML")
    parser.add_argument(
        "--remote",
        dest="remote",
        action="store_true",
        default=None,
        help="Enable remote worker mode (default)",
    )
    parser.add_argument(
        "--no-remote", dest="remote", action="store_false", help="Disable remote worker mode"
    )
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
