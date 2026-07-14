from __future__ import annotations

import hashlib
import os
import platform
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

from .settings import get_settings

TMUX_HELPER_VERSION = "3.5a"


@dataclass(frozen=True)
class TmuxSelection:
    path: str | None
    source: str


def _platform_tag() -> str | None:
    system = platform.system().lower()
    machine = platform.machine().lower()
    machine_aliases = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "x86_64": "x86_64",
        "aarch64": "aarch64",
        "arm64": "aarch64",
    }
    normalized_machine = machine_aliases.get(machine)
    if normalized_machine is None or system not in {"linux", "darwin"}:
        return None
    return f"{system}-{normalized_machine}"


def bundled_tmux_path() -> Path | None:
    tag = _platform_tag()
    if tag is None:
        return None
    candidate = Path(__file__).resolve().parent / "helpers" / tag / "tmux"
    if not candidate.is_file():
        return None
    if os.access(candidate, os.X_OK):
        return candidate
    try:
        candidate.chmod(candidate.stat().st_mode | stat.S_IXUSR)
    except OSError:
        return None
    return candidate if os.access(candidate, os.X_OK) else None


def resolve_tmux() -> TmuxSelection:
    configured = str(get_settings().tmux_bin or "tmux").strip() or "tmux"
    resolved = shutil.which(configured)
    if resolved:
        return TmuxSelection(resolved, "system")

    configured_path = Path(configured).expanduser()
    if configured != "tmux" and configured_path.is_file() and os.access(configured_path, os.X_OK):
        return TmuxSelection(str(configured_path.resolve()), "configured")

    bundled = bundled_tmux_path()
    if bundled is not None:
        return TmuxSelection(str(bundled), "bundled")
    return TmuxSelection(None, "native")


def tmux_socket_name() -> str:
    state_dir = str(get_settings().state_dir.expanduser().resolve())
    digest = hashlib.sha256(state_dir.encode("utf-8")).hexdigest()[:12]
    return f"local-shell-mcp-{digest}"


def persistent_shell_backend_info() -> dict[str, object]:
    if os.name == "nt":
        try:
            from . import conpty_ops

            if conpty_ops.is_available():
                return {
                    "backend": "conpty",
                    "durable_across_server_restart": False,
                }
        except Exception:
            pass
        return {
            "backend": "native",
            "durable_across_server_restart": False,
        }

    selection = resolve_tmux()
    if selection.path:
        return {
            "backend": f"tmux-{selection.source}",
            "tmux_path": selection.path,
            "tmux_helper_version": TMUX_HELPER_VERSION if selection.source == "bundled" else None,
            "socket_name": tmux_socket_name(),
            "durable_across_server_restart": True,
        }
    return {
        "backend": "native",
        "durable_across_server_restart": False,
        "warning": "tmux is unavailable; sessions remain usable only while this process is running",
    }
