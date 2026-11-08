#!/usr/bin/env python3
"""Embed the first-party React WebUI into the Controller release archive.

Source builds keep compiled files in ui/workspace/client/dist; Controller
onefile releases carry this compressed payload, while ordinary Worker wheels
omit it and retain the Python-only footprint.
"""

from __future__ import annotations

import argparse
import gzip
import io
import os
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def bundle_react_assets(source: Path, destination: Path) -> int:
    source = Path(source).resolve()
    destination = Path(destination)
    if not (source / "index.html").is_file():
        raise ValueError("React build missing; run 'bun run frontend' in ui/workspace")
    files = sorted(p for p in source.rglob("*") if p.is_file() and not p.is_symlink()
                   and p.suffix not in {".map", ".gz", ".br"} and not p.name.startswith("."))
    if not files:
        raise ValueError("React build contains no files")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + f".{os.getpid()}.tmp")
    try:
        with (
            temporary.open("wb") as output,
            gzip.GzipFile(filename="", mode="wb", mtime=0, fileobj=output) as compressor,
            tarfile.open(mode="w|", fileobj=compressor) as archive,
        ):
            for path in files:
                name = path.relative_to(source).as_posix()
                content = path.read_bytes()
                info = tarfile.TarInfo(name=name)
                info.size = len(content)
                info.mode = 0o644
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                archive.addfile(info, io.BytesIO(content))
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return len(files)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "ui/workspace/client/dist")
    parser.add_argument("--destination", type=Path,
                        default=ROOT / "ui/workspace/frontend.tar.gz")
    args = parser.parse_args()
    count = bundle_react_assets(args.source, args.destination)
    print(f"Embedded {count} frontend files: {args.destination} ({args.destination.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
