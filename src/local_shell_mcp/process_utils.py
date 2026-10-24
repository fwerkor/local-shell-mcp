from __future__ import annotations

import subprocess
import sys
from typing import Any


def managed_process_creationflags() -> int:
    """Return Windows flags for LSM-managed subprocesses that never need a desktop console."""
    if sys.platform != "win32":
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def managed_process_kwargs() -> dict[str, Any]:
    """Keyword arguments for subprocess APIs, preserving non-Windows call signatures."""
    flags = managed_process_creationflags()
    if not flags:
        return {}
    kwargs: dict[str, Any] = {"creationflags": flags}
    startupinfo_type = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_type is not None:
        startupinfo = startupinfo_type()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        kwargs["startupinfo"] = startupinfo
    return kwargs
