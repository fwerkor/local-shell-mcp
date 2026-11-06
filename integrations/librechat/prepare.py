#!/usr/bin/env python3
"""Clone the pinned LibreChat upstream release and apply the LSM integration."""
import secrets
import subprocess
from pathlib import Path

from apply_upstream import apply

UPSTREAM_TAG = "v0.8.8"
UPSTREAM_COMMIT = "e8f3be08623663d4ad7f7241e693c94469b63bb0"
SOURCE = Path(__file__).resolve().parent / "upstream-src"


def main() -> None:
    if not SOURCE.exists():
        subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", UPSTREAM_TAG,
             "https://github.com/LibreChat-AI/LibreChat.git", str(SOURCE)],
            check=True,
        )
    commit = subprocess.check_output(
        ["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True,
    ).strip()
    if commit != UPSTREAM_COMMIT:
        raise RuntimeError(f"Unsupported LibreChat revision: {commit}")
    apply(SOURCE)
    settings = Path(__file__).resolve().parent / "searxng-settings.yml"
    if not settings.exists():
        example = (settings.parent / "searxng-settings.example.yml").read_text()
        settings.write_text(
            example.replace("REPLACE_WITH_RANDOM_KEY_GENERATED_BY_PREPARE", secrets.token_urlsafe(48))
        )
        settings.chmod(0o600)
    print(f"Prepared LibreChat {UPSTREAM_TAG} with LSM patch at {SOURCE}")


if __name__ == "__main__":
    main()
