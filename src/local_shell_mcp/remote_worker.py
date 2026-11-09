from __future__ import annotations

import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    # Workers do not initialize the Controller's database.  Restore the
    # caller's environment when invoking this entrypoint in-process (tests).
    old_backend = os.environ.get("LOCAL_SHELL_MCP_STATE_BACKEND")
    os.environ["LOCAL_SHELL_MCP_STATE_BACKEND"] = "file"
    try:
        _run_worker_main(args)
    finally:
        if old_backend is None:
            os.environ.pop("LOCAL_SHELL_MCP_STATE_BACKEND", None)
        else:
            os.environ["LOCAL_SHELL_MCP_STATE_BACKEND"] = old_backend
        from .settings import get_settings

        get_settings.cache_clear()


def _run_worker_main(args: list[str]) -> None:
    # Worker subprocess helpers execute controller-assigned jobs or GUI capture.
    # They do not expose the controller CLI or its tool-call credentials.
    if args and args[0] == "job-runner":
        from .job_runner_entry import run_job_runner

        run_job_runner(args[1:])
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
    from .remote_worker_cli import run_worker_cli

    run_worker_cli(args)


if __name__ == "__main__":
    main()
