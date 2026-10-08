from __future__ import annotations

import sys
from pathlib import Path

from .remote_worker_cli import run_worker_cli


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    # Worker subprocess helpers execute controller-assigned jobs or GUI capture.
    # They do not expose the controller CLI or its tool-call credentials.
    if args and args[0] == "job-runner":
        from .jobs import run_job_runner_cli

        run_job_runner_cli(args[1:])
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
