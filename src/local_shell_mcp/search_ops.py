from __future__ import annotations

import asyncio
import json
from contextlib import suppress

from .fs_ops import missing_path_context, resolve_path
from .settings import get_settings
from .shell_ops import _close_process_transport


async def grep(query: str, cwd: str = ".", glob: str | None = None, regex: bool = True, case_sensitive: bool = True, max_results: int | None = None) -> dict:
    settings = get_settings()
    max_results = max(1, min(max_results or settings.max_grep_results, settings.max_grep_results))
    base = resolve_path(cwd, must_exist=True)
    args = [settings.rg_bin, "--json", "--line-number", "--column"]
    if not regex:
        args.append("--fixed-strings")
    if not case_sensitive:
        args.append("--ignore-case")
    if glob:
        args.extend(["--glob", glob])
    args.extend(["--", query])

    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(base),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    matches = []
    stderr_parts: list[bytes] = []
    stopped_early = False
    timed_out = False

    async def read_stderr() -> None:
        if proc.stderr is None:
            return
        stderr_parts.append(await proc.stderr.read(settings.max_output_bytes + 1))

    stderr_task = asyncio.create_task(read_stderr())
    try:
        if proc.stdout is not None:
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=60)
                if not line:
                    break
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
                    stopped_early = True
                    proc.terminate()
                    break
        with suppress(TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=2 if stopped_early else 60)
    except TimeoutError:
        timed_out = True
        proc.terminate()
        with suppress(Exception):
            await proc.wait()
    finally:
        if not stderr_task.done():
            stderr_task.cancel()
        await asyncio.gather(stderr_task, return_exceptions=True)
        await _close_process_transport(proc)

    stderr_bytes = b"".join(stderr_parts)
    stderr_truncated = len(stderr_bytes) > settings.max_output_bytes
    if stderr_truncated:
        stderr_bytes = stderr_bytes[: settings.max_output_bytes]
    return {
        "ok": (not timed_out) and (stopped_early or proc.returncode in {0, 1}),
        "matches": matches,
        "count": len(matches),
        "truncated": stopped_early or stderr_truncated,
        "stderr": stderr_bytes.decode(errors="replace"),
    }


def tree_sync(cwd: str = ".", depth: int = 3, max_entries: int = 500) -> dict:
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
            is_directory = path.is_dir() and not path.is_symlink()
            suffix = "/" if is_directory else ""
            rows.append(f"{indent}{path.name}{suffix}")
            count += 1
            if is_directory:
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
    return await asyncio.to_thread(tree_sync, cwd, depth, max_entries)
