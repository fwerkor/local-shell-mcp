from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

from .remote_worker_cli import run_worker_cli


def _save_runner_failure(args: list[str], exc: Exception) -> None:
    """Preserve bounded, private startup diagnostics if no receipt was written.

    Keep exception text and command-line arguments out of the evidence file: a
    failing import or runtime can include credentials in exception messages.
    """
    try:
        index = args.index("--status-file")
        status = Path(args[index + 1])
        if status.suffix != ".json" or status.exists():
            return
        trace = traceback.extract_tb(exc.__traceback__, limit=20)
        payload = {
            "exception_type": type(exc).__name__,
            "frames": [
                {"module": Path(frame.filename).name, "function": frame.name, "line": frame.lineno}
                for frame in trace
            ],
        }
        path = status.with_name(status.name + ".runner-error.json")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output)
    except (OSError, ValueError, IndexError, TypeError):
        # Preserve the original exception even if diagnostic storage is broken.
        return


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    # Worker subprocess helpers execute controller-assigned jobs or GUI capture.
    # They do not expose the controller CLI or its tool-call credentials.
    if args and args[0] == "job-runner":
        try:
            from .jobs import run_job_runner_cli

            run_job_runner_cli(args[1:])
        except Exception as exc:
            _save_runner_failure(args[1:], exc)
            raise
        return
    if args and args[0] == "_gui-capture-window":
        if len(args) != 3:
            raise SystemExit("_gui-capture-window requires HWND and destination")
        from .gui.windows import _capture_window_image_native

        _capture_window_image_native(int(args[1]), Path(args[2]))
        return
    # Retain the public `worker <command>` management spelling.
    if args and args[0] == "worker":
        args.pop(0)
    run_worker_cli(args)


if __name__ == "__main__":
    main()
