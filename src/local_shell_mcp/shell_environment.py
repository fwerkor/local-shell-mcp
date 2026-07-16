from __future__ import annotations

import os
import sys
from pathlib import Path

from .settings import get_settings

FROZEN_LOADER_ENV_VARS = (
    "LD_LIBRARY_PATH",
    "LD_PRELOAD",
    "DYLD_LIBRARY_PATH",
    "DYLD_INSERT_LIBRARIES",
)


def shell_program_name(shell: str) -> str:
    return Path(shell).name.lower()


def shell_command_args(shell: str, command: str) -> list[str]:
    name = shell_program_name(shell)
    powershell = "power" + "shell"
    if name in {powershell + ".exe", powershell, "pwsh.exe", "pwsh"}:
        return [shell, "-NoProfile", "-NonInteractive", "-Command", command]
    if name in {"cmd.exe", "cmd"}:
        return [shell, "/S", "/C", command]
    return [shell, "-lc", command]


def persistent_shell_args(shell: str, command: str | None = None) -> list[str]:
    if command:
        return shell_command_args(shell, command)
    return [shell]


def is_frozen_app() -> bool:
    return bool(getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None))


def _restore_or_remove_loader_var(env: dict[str, str], name: str) -> None:
    original_name = f"{name}_ORIG"
    original_value = env.pop(original_name, None)
    if original_value:
        env[name] = original_value
    else:
        env.pop(name, None)


def filtered_subprocess_env(
    blocked_names: list[str] | tuple[str, ...],
    blocked_prefixes: list[str] | tuple[str, ...],
) -> dict[str, str]:
    blocked = set(blocked_names)
    prefixes = tuple(blocked_prefixes)
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in blocked and not key.startswith(prefixes)
    }
    if is_frozen_app():
        for name in FROZEN_LOADER_ENV_VARS:
            _restore_or_remove_loader_var(env, name)
    return env


def subprocess_env() -> dict[str, str]:
    settings = get_settings()
    return filtered_subprocess_env(
        settings.shell_env_blocklist,
        settings.shell_env_blocked_prefixes,
    )
