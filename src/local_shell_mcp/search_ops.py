"""Search workspace text files and produce compact directory trees for code-navigation tools."""

from __future__ import annotations

import asyncio
import json
import shlex

from .fs_ops import missing_path_context, resolve_path
from .settings import get_settings
from .shell_ops import run_shell


async def grep(
    query: str,
    cwd: str = ".",
    glob: str | None = None,
    regex: bool = True,
    case_sensitive: bool = True,
    max_results: int | None = None,
) -> dict:
    """Run ripgrep with workspace path resolution and return structured match records."""
    settings = get_settings()
    max_results = max_results or settings.max_grep_results
    args = [settings.rg_bin, "--json", "--line-number", "--column"]
    if not regex:
        args.append("--fixed-strings")
    if not case_sensitive:
        args.append("--ignore-case")
    if glob:
        args.extend(["--glob", glob])
    args.append(query)
    cmd = " ".join(shlex.quote(x) for x in args)
    result = await run_shell(cmd, cwd=cwd, timeout_s=60, max_output_bytes=1_000_000)
    matches = []
    for line in result.stdout.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "match":
            continue
        data = obj.get("data", {})
        submatches = data.get("submatches") or [{}]
        first = submatches[0]
        matches.append(
            {
                "path": data.get("path", {}).get("text"),
                "line": data.get("line_number"),
                "column": first.get("start") + 1 if first.get("start") is not None else None,
                "text": data.get("lines", {}).get("text", "").rstrip("\n"),
            }
        )
        if len(matches) >= max_results:
            break
    return {
        "ok": result.exit_code in {0, 1},
        "matches": matches,
        "count": len(matches),
        "truncated": len(matches) >= max_results or result.truncated,
        "stderr": result.stderr,
    }


def tree_sync(cwd: str = ".", depth: int = 3, max_entries: int = 500) -> dict:
    """Build a compact, depth-limited directory tree while skipping common generated directories."""
    settings = get_settings()
    base = resolve_path(cwd)
    if not base.exists():
        context = missing_path_context(base, max_entries=min(max_entries, 100))
        return {
            "root": context["path"],
            "exists": False,
            "is_directory": False,
            "entries": [],
            "count": 0,
            "truncated": False,
            "message": f"Path does not exist: {context['path']}",
            "nearest_existing_parent": context["nearest_existing_parent"],
            "nearest_parent_entries": context["nearest_parent_entries"],
            "nearest_parent_entries_truncated": context["truncated"],
        }
    if not base.is_dir():
        return {
            "root": str(base),
            "exists": True,
            "is_directory": False,
            "entries": [],
            "count": 0,
            "truncated": False,
            "message": f"Path exists but is not a directory: {base}",
        }

    depth = max(0, min(depth, 10))
    limit = max(1, min(max_entries, settings.max_tree_entries))
    rows: list[str] = []
    count = 0
    truncated = False

    def walk(directory, current_depth: int) -> None:  # noqa: ANN001
        nonlocal count, truncated
        if current_depth >= depth or count >= limit:
            return
        try:
            iterator = directory.iterdir()
        except OSError:
            return
        for path in iterator:
            if path.name == ".git":
                continue
            if count >= limit:
                truncated = True
                return
            rel = path.relative_to(base)
            indent = "  " * (len(rel.parts) - 1)
            suffix = "/" if path.is_dir() else ""
            rows.append(f"{indent}{path.name}{suffix}")
            count += 1
            if path.is_dir():
                walk(path, current_depth + 1)
            if count >= limit:
                truncated = True
                return

    walk(base, 0)
    return {
        "root": str(base),
        "exists": True,
        "is_directory": True,
        "entries": rows,
        "count": count,
        "truncated": truncated,
    }


async def tree(cwd: str = ".", depth: int = 3, max_entries: int = 500) -> dict:
    """Expose tree generation through an async API used by MCP and HTTP handlers."""
    return await asyncio.to_thread(tree_sync, cwd, depth, max_entries)
