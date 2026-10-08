from __future__ import annotations

import sys

from .remote_worker_cli import run_worker_cli


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    # The installed worker launcher retains the public `worker <command>`
    # spelling, but must not dispatch through the controller's full CLI.
    if args and args[0] == "worker":
        args.pop(0)
    run_worker_cli(args)


if __name__ == "__main__":
    main()
