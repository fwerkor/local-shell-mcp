from __future__ import annotations

import contextlib
import gzip
import os
import shutil
import stat
import tempfile
from pathlib import Path

from . import __version__


def embedded_tui_payload() -> Path | None:
    executable_name = "local-shell-mcp-tui.exe" if os.name == "nt" else "local-shell-mcp-tui"
    payload = Path(__file__).resolve().parent / "ui_runtime" / f"{executable_name}.gz"
    return payload if payload.is_file() else None


def materialize_embedded_tui(
    state_dir: Path,
    *,
    payload: Path | None = None,
) -> Path | None:
    payload = embedded_tui_payload() if payload is None else payload
    if payload is None or not payload.is_file():
        return None

    executable_name = payload.name.removesuffix(".gz")
    target_dir = state_dir / "ui-runtime" / __version__
    target = target_dir / executable_name
    if target.is_file():
        return target

    target_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=target_dir,
        prefix=f".{executable_name}.",
        suffix=".tmp",
        delete=False,
    ) as destination:
        temporary = Path(destination.name)
        with gzip.open(payload, "rb") as source:
            shutil.copyfileobj(source, destination)
    try:
        if os.name != "nt":
            temporary.chmod(
                temporary.stat().st_mode
                | stat.S_IXUSR
                | stat.S_IXGRP
                | stat.S_IXOTH
            )
        try:
            os.replace(temporary, target)
        except PermissionError:
            # Windows can reject replacing a target that another concurrent
            # materializer has just completed. Accept that winner only after
            # confirming the fully written target now exists.
            if not target.is_file():
                raise
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink()
    return target
