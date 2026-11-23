"""Optional provenance for the LSM About panel.

Only report build fields backed by deployment metadata or the actual source
checkout. A commit timestamp is not a build timestamp.
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from .. import __version__


def _source_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _git_value(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=1,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


@lru_cache(maxsize=1)
def _checkout_info() -> dict[str, str]:
    root = _source_root()
    # Do not accidentally report metadata from a containing, unrelated repo.
    if not (root / ".git").exists():
        return {}
    commit = _git_value(root, "rev-parse", "--verify", "HEAD")
    if not commit or not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
        return {}
    result = {"commit": commit}
    branch = _git_value(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    if branch:
        result["branch"] = branch
    return result


def about_build_info() -> dict[str, object]:
    """Return LSM version plus only verified available build provenance."""
    checkout = _checkout_info()
    commit = os.environ.get("LOCAL_SHELL_MCP_BUILD_COMMIT") or checkout.get("commit")
    branch = os.environ.get("LOCAL_SHELL_MCP_BUILD_BRANCH") or checkout.get("branch")
    build_date = os.environ.get("LOCAL_SHELL_MCP_BUILD_DATE")
    info: dict[str, str] = {}
    if commit and re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
        info.update(commit=commit, commitShort=commit[:8])
    if branch and branch.strip():
        info["branch"] = branch.strip()
    if build_date:
        try:
            parsed_date = datetime.fromisoformat(build_date.replace("Z", "+00:00"))
        except ValueError:
            pass
        else:
            if parsed_date.tzinfo is not None:
                info["buildDate"] = build_date
    return {"lsmVersion": __version__, **({"buildInfo": info} if info else {})}
