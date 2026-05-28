from __future__ import annotations

import shlex

from .settings import get_settings
from .shell_ops import run_shell


def _git(*args: str) -> str:
    return " ".join(shlex.quote(x) for x in [get_settings().git_bin, *args])


async def git_status(cwd: str = ".") -> dict:
    result = await run_shell(f"{_git('status', '--short', '--branch')} && echo '---' && {_git('remote', '-v')}", cwd=cwd)
    return result.model_dump()


async def git_diff(cwd: str = ".", staged: bool = False, path: str | None = None, stat: bool = False) -> dict:
    args = ["diff"]
    if staged:
        args.append("--cached")
    if stat:
        args.append("--stat")
    if path:
        args.extend(["--", path])
    result = await run_shell(_git(*args), cwd=cwd, timeout_s=60, max_output_bytes=500_000)
    return result.model_dump()


async def git_log(cwd: str = ".", max_count: int = 20) -> dict:
    max_count = max(1, min(max_count, 200))
    result = await run_shell(_git("log", f"--max-count={max_count}", "--oneline", "--decorate"), cwd=cwd)
    return result.model_dump()


async def git_clone(repo_url: str, dest: str | None = None, branch: str | None = None, cwd: str = ".") -> dict:
    args = ["clone"]
    if branch:
        args.extend(["--branch", branch])
    args.append(repo_url)
    if dest:
        args.append(dest)
    result = await run_shell(_git(*args), cwd=cwd, timeout_s=60, max_output_bytes=500_000)
    return result.model_dump()


async def git_checkout(cwd: str, ref: str, create: bool = False) -> dict:
    args = ["checkout"]
    if create:
        args.append("-b")
    args.append(ref)
    result = await run_shell(_git(*args), cwd=cwd)
    return result.model_dump()


async def git_fetch(cwd: str = ".", remote: str = "origin", prune: bool = True) -> dict:
    args = ["fetch"]
    if prune:
        args.append("--prune")
    args.append(remote)
    result = await run_shell(_git(*args), cwd=cwd, timeout_s=60)
    return result.model_dump()


async def git_pull(cwd: str = ".", ff_only: bool = True) -> dict:
    args = ["pull"]
    if ff_only:
        args.append("--ff-only")
    result = await run_shell(_git(*args), cwd=cwd, timeout_s=60, max_output_bytes=500_000)
    return result.model_dump()


async def git_add(cwd: str = ".", paths: list[str] | None = None) -> dict:
    paths = paths or ["."]
    result = await run_shell(_git("add", *paths), cwd=cwd)
    return result.model_dump()


async def git_commit(cwd: str, message: str, all_changes: bool = False) -> dict:
    cmd = ""
    if all_changes:
        cmd += f"{_git('add', '.')} && "
    cmd += _git("commit", "-m", message)
    result = await run_shell(cmd, cwd=cwd, timeout_s=60, max_output_bytes=500_000)
    return result.model_dump()


async def git_push(cwd: str, remote: str = "origin", branch: str | None = None, set_upstream: bool = True) -> dict:
    args = ["push"]
    if set_upstream and branch:
        args.extend(["-u", remote, f"HEAD:{branch}"])
    elif branch:
        args.extend([remote, f"HEAD:{branch}"])
    else:
        args.append(remote)
    result = await run_shell(_git(*args), cwd=cwd, timeout_s=60, max_output_bytes=500_000)
    return result.model_dump()


async def git_show(cwd: str = ".", ref: str = "HEAD", path: str | None = None) -> dict:
    spec = ref if path is None else f"{ref}:{path}"
    result = await run_shell(_git("show", spec), cwd=cwd, timeout_s=60, max_output_bytes=500_000)
    return result.model_dump()


async def git_reset(cwd: str = ".", mode: str = "soft", ref: str = "HEAD") -> dict:
    if mode not in {"soft", "mixed", "hard"}:
        raise ValueError("mode must be soft, mixed, or hard")
    result = await run_shell(_git("reset", f"--{mode}", ref), cwd=cwd, timeout_s=60)
    return result.model_dump()
