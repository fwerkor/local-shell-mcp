#!/usr/bin/env python3
"""Install compiled React assets in the Python application package."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path,
                        default=ROOT / "integrations" / "librechat" / "app" / "client" / "dist")
    parser.add_argument("--destination", type=Path,
                        default=ROOT / "src" / "local_shell_mcp" / "webui" / "assets")
    args = parser.parse_args()
    if not (args.source / "index.html").is_file():
        raise SystemExit("React build is missing; run 'bun run frontend' in integrations/librechat/app")
    if args.destination.exists():
        shutil.rmtree(args.destination)
    shutil.copytree(args.source, args.destination, ignore=shutil.ignore_patterns("*.map", ".DS_Store"))
    print(f"Embedded React workspace: {args.destination}")


if __name__ == "__main__":
    main()
