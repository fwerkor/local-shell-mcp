"""Coordinate graceful in-process restart without depending on the entrypoint module name."""

from __future__ import annotations

import threading
from typing import Any

_RESTART_REQUESTED = threading.Event()
_ACTIVE_SERVER: Any = None


def set_active_server(server: Any) -> None:
    global _ACTIVE_SERVER
    _ACTIVE_SERVER = server
    _RESTART_REQUESTED.clear()


def clear_active_server() -> None:
    global _ACTIVE_SERVER
    _ACTIVE_SERVER = None


def restart_available() -> bool:
    server = _ACTIVE_SERVER
    return server is not None and server.started and not server.should_exit


def request_controller_restart() -> bool:
    server = _ACTIVE_SERVER
    if server is None or not server.started or server.should_exit:
        return False
    _RESTART_REQUESTED.set()
    server.should_exit = True
    return True


def restart_requested() -> bool:
    return _RESTART_REQUESTED.is_set()
