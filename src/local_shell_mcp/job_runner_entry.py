"""Minimal Job runner entry shared by installed and frozen executables."""

from __future__ import annotations

import json
import os
import traceback
from pathlib import Path


def runner_error_path(status: Path) -> Path:
    return status.with_name(status.name + ".runner-error.json")


def _save_runner_failure(args: list[str], exc: Exception) -> None:
    """Record bounded startup evidence without commands, arguments, or exception text."""
    try:
        index = args.index("--status-file")
        status = Path(args[index + 1])
        if status.suffix != ".json" or status.exists():
            return
        frames = traceback.extract_tb(exc.__traceback__, limit=20)
        payload = {
            "exception_type": type(exc).__name__,
            "frames": [
                {"module": Path(frame.filename).name, "function": frame.name, "line": frame.lineno}
                for frame in frames
            ],
        }
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(runner_error_path(status), flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output)
    except (OSError, ValueError, IndexError, TypeError):
        # An unavailable evidence file must never hide the original failure.
        return


def run_job_runner(args: list[str]) -> None:
    try:
        from .jobs import run_job_runner_cli

        run_job_runner_cli(args)
    except Exception as exc:
        _save_runner_failure(args, exc)
        raise
