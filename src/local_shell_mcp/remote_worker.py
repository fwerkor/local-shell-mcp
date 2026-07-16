from __future__ import annotations

import sys

from .remote_worker_cli import run_worker_cli

if __name__ == "__main__":
    run_worker_cli(sys.argv[1:])
