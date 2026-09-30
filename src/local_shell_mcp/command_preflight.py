from __future__ import annotations

import hashlib
import re
import shlex
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

_WINDOWS_WIDE_ROOT_RE = re.compile(
    r"(?i)^(?:[a-z]:[\\/]?$|[a-z]:[\\/]users(?:[\\/][^\\/]+)?[\\/]?$|%userprofile%[\\/]?$|\$env:userprofile[\\/]?$)"
)
_POSIX_WIDE_ROOTS = {
    "/",
    "/home",
    "/root",
    "/users",
    "/var",
    "/opt",
    "/usr",
    "/tmp",
    "~",
    "$home",
}
_POSIX_HOME_ROOT_RE = re.compile(r"(?i)^/(?:home|users)/[^/]+$")
_SPACE_RE = re.compile(r"\s+")
_SHELL_SEGMENT_RE = re.compile(r"(?:&&|\|\||[;|\r\n])")
_SUDO_OPTIONS_WITH_VALUE = {
    "-u",
    "--user",
    "-g",
    "--group",
    "-h",
    "--host",
    "-p",
    "--prompt",
    "-c",
    "--close-from",
    "-r",
    "--role",
    "-t",
    "--type",
    "-d",
    "--chdir",
}


@dataclass(frozen=True)
class CommandPreflightDecision:
    action: str = "allow"  # allow | limit | block
    reason_code: str | None = None
    message: str | None = None
    cost_score: int = 0
    effective_timeout_s: int | None = None
    recommended_tool: str | None = None
    fingerprint: str = ""
    signals: tuple[str, ...] = ()
    retryable: bool = True
    do_not_repeat_same_command: bool = False

    def error_payload(self) -> dict[str, Any]:
        return {
            "status": "blocked",
            "error_type": "CommandPreflightBlocked",
            "reason_code": self.reason_code,
            "message": self.message or "Command blocked by shell preflight policy",
            "retryable": self.retryable,
            "do_not_repeat_same_command": self.do_not_repeat_same_command,
            "cost_score": self.cost_score,
            "recommended_tool": self.recommended_tool,
            "effective_timeout_s": self.effective_timeout_s,
            "command_fingerprint": self.fingerprint,
            "signals": list(self.signals),
        }


def command_fingerprint(command: str) -> str:
    normalized = _SPACE_RE.sub(" ", str(command or "").strip().casefold())
    normalized = re.sub(r"\bgci\b", "get-childitem", normalized)
    if "get-childitem" in normalized:
        normalized = normalized.replace("/", "\\")
    return hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest()[:20]


def _shell_segments(command: str) -> list[str]:
    return [segment.strip() for segment in _SHELL_SEGMENT_RE.split(command) if segment.strip()]


def _shell_tokens(segment: str) -> list[str]:
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return re.findall(r"(?:'[^']*'|\"[^\"]*\"|\S+)", segment)


def _basename_token(token: str) -> str:
    return token.replace("\\", "/").rsplit("/", 1)[-1].casefold()


def _strip_sudo(tokens: list[str]) -> list[str]:
    index = 1
    while index < len(tokens):
        token = tokens[index]
        folded = token.casefold()
        if token == "--":
            return tokens[index + 1 :]
        if not token.startswith("-"):
            return tokens[index:]
        if "=" not in token and folded in _SUDO_OPTIONS_WITH_VALUE:
            index += 2
        else:
            index += 1
    return []


def _command_tokens(segment: str) -> tuple[str | None, list[str]]:
    tokens = _shell_tokens(segment)
    while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
        tokens = tokens[1:]
    while tokens:
        executable = _basename_token(tokens[0])
        if executable == "sudo":
            tokens = _strip_sudo(tokens)
            continue
        if executable in {"command", "nohup"}:
            tokens = tokens[1:]
            continue
        if executable == "env":
            tokens = tokens[1:]
            while tokens and (tokens[0].startswith("-") or "=" in tokens[0]):
                tokens = tokens[1:]
            continue
        return executable, tokens[1:]
    return None, []


def _normalize_machine(machine: str | None) -> str:
    value = str(machine or "local").strip().casefold()
    return value or "local"


def _normalize_cwd(cwd: str | None) -> str:
    value = str(cwd or ".").strip().replace("\\", "/")
    value = re.sub(r"/{2,}", "/", value)
    if re.match(r"(?i)^[a-z]:/", value):
        value = value.casefold()
    if value not in {"/", "."} and not re.match(r"(?i)^[a-z]:/$", value):
        value = value.rstrip("/")
    return value or "."


def _extract_powershell_scans(command: str) -> list[tuple[str, bool]]:
    scans: list[tuple[str, bool]] = []
    pattern = re.compile(r"(?is)\b(?:get-childitem|gci)\b(?P<body>.*?)(?=(?:;|\||\r?\n|$))")
    for match in pattern.finditer(command):
        body = match.group("body")
        folded = body.casefold()
        bounded = re.search(r"(?i)(?:^|\s)-depth\s+\d+", body) is not None
        if "-recurse" not in folded and not bounded:
            continue
        path_match = re.search(
            r"(?i)(?:-path|-literalpath)\s+(?:['\"]([^'\"]+)['\"]|([^\s;|]+))",
            body,
        )
        if path_match:
            scans.append(((path_match.group(1) or path_match.group(2) or ".").strip(), bounded))
            continue
        tokens = re.findall(r"(?:'[^']*'|\"[^\"]*\"|\S+)", body)
        for token in tokens:
            if token.startswith("-"):
                continue
            scans.append((token.strip("'\""), bounded))
            break
        else:
            scans.append((".", bounded))
    return scans


def _extract_find_scans(command: str) -> list[tuple[str, bool]]:
    scans: list[tuple[str, bool]] = []
    for segment in _shell_segments(command):
        executable, args = _command_tokens(segment)
        if executable != "find":
            continue
        index = 0
        while index < len(args):
            folded = args[index].casefold()
            if folded in {"-h", "-l", "-p"} or folded.startswith("-o"):
                index += 1
                continue
            if folded == "-d":
                index += 2
                continue
            if args[index] == "--":
                index += 1
            break
        remaining = args[index:]
        bounded = any(
            token.casefold() == "-maxdepth" or token.casefold().startswith("-maxdepth=")
            for token in remaining
        )
        roots: list[str] = []
        for token in remaining:
            if token in {"(", ")", "!"} or token.startswith("-"):
                break
            roots.append(token)
        if not roots:
            roots = ["."]
        scans.extend((root, bounded) for root in roots)
    return scans


def _option_value_positions(args: list[str], options_with_value: set[str]) -> set[int]:
    positions: set[int] = set()
    index = 0
    while index < len(args):
        token = args[index]
        folded = token.casefold()
        if folded in options_with_value and index + 1 < len(args):
            positions.add(index + 1)
            index += 2
            continue
        index += 1
    return positions


def _extract_recursive_search_scans(command: str) -> list[tuple[str, bool, str]]:
    scans: list[tuple[str, bool, str]] = []
    rg_value_options = {
        "-e",
        "--regexp",
        "-f",
        "--file",
        "-g",
        "--glob",
        "-t",
        "--type",
        "--type-not",
        "--max-depth",
        "--max-filesize",
    }
    grep_value_options = {"-e", "--regexp", "-f", "--file", "--include", "--exclude"}
    for segment in _shell_segments(command):
        executable, args = _command_tokens(segment)
        if executable in {"rg", "ripgrep"}:
            bounded = any(
                token.casefold() == "--max-depth"
                or token.casefold().startswith("--max-depth=")
                for token in args
            )
            value_positions = _option_value_positions(args, rg_value_options)
            positional = [
                token
                for index, token in enumerate(args)
                if index not in value_positions and not token.startswith("-")
            ]
            pattern_from_option = any(
                token.casefold() in {"-e", "--regexp"}
                or token.casefold().startswith("--regexp=")
                for token in args
            )
            files_only = any(token.casefold() == "--files" for token in args)
            if pattern_from_option or files_only:
                roots = positional
            else:
                roots = positional[1:] if positional else []
            if not roots:
                roots = ["."]
            scans.extend((root, bounded, "ripgrep_recursive_scan") for root in roots)
            continue
        if executable != "grep":
            continue
        recursive = any(
            token.casefold() in {"-r", "--recursive", "--dereference-recursive"}
            or (token.startswith("-") and not token.startswith("--") and "r" in token.casefold()[1:])
            for token in args
        )
        if not recursive:
            continue
        value_positions = _option_value_positions(args, grep_value_options)
        positional = [
            token
            for index, token in enumerate(args)
            if index not in value_positions and not token.startswith("-")
        ]
        pattern_from_option = any(
            token.casefold() in {"-e", "--regexp"}
            or token.casefold().startswith("--regexp=")
            for token in args
        )
        roots = positional if pattern_from_option else positional[1:]
        if not roots:
            roots = ["."]
        scans.extend((root, False, "grep_recursive_scan") for root in roots)
    return scans


def _is_wide_root(root: str, cwd: str | None) -> bool:
    value = str(root or ".").strip().rstrip("\\/") or "/"
    folded = value.casefold()
    if _WINDOWS_WIDE_ROOT_RE.match(value):
        return True
    if folded in _POSIX_WIDE_ROOTS or _POSIX_HOME_ROOT_RE.match(value):
        return True
    if value in {".", "./", ".\\"} and cwd:
        cwd_norm = str(cwd).rstrip("\\/") or "/"
        cwd_folded = cwd_norm.casefold()
        return bool(
            _WINDOWS_WIDE_ROOT_RE.match(cwd_norm)
            or cwd_folded in _POSIX_WIDE_ROOTS
            or _POSIX_HOME_ROOT_RE.match(cwd_norm)
        )
    return False


def _looks_like_file_discovery(command: str) -> bool:
    folded = command.casefold()
    return any(
        marker in folded
        for marker in (
            "get-childitem",
            "gci ",
            "find ",
            "dir /s",
            "where /r",
            "-filter ",
            "-include ",
            "-name ",
            "-iname ",
            "rg ",
            "ripgrep ",
            "grep ",
        )
    )


def _scan_signals(command: str, cwd: str | None) -> tuple[list[str], int, bool, bool, bool]:
    signals: list[str] = []
    score = 0
    recursive_count = 0
    wide_unbounded = False
    unbounded = False

    ps_scans = _extract_powershell_scans(command)
    if ps_scans:
        recursive_count += len(ps_scans)
        signals.append("powershell_recursive_scan")
        score += 3
        if any(not bounded for _, bounded in ps_scans):
            signals.append("unbounded_depth")
            score += 2
            unbounded = True
        if any(not bounded and _is_wide_root(root, cwd) for root, bounded in ps_scans):
            signals.append("wide_root")
            score += 4
            wide_unbounded = True

    find_scans = _extract_find_scans(command)
    if find_scans:
        recursive_count += len(find_scans)
        signals.append("posix_find_scan")
        score += 2
        if any(not bounded for _, bounded in find_scans):
            signals.append("unbounded_depth")
            score += 2
            unbounded = True
        if any(not bounded and _is_wide_root(root, cwd) for root, bounded in find_scans):
            signals.append("wide_root")
            score += 4
            wide_unbounded = True

    recursive_search_scans = _extract_recursive_search_scans(command)
    if recursive_search_scans:
        recursive_count += len(recursive_search_scans)
        signals.extend(dict.fromkeys(signal for _, _, signal in recursive_search_scans))
        score += 2
        if any(not bounded for _, bounded, _ in recursive_search_scans):
            signals.append("unbounded_depth")
            score += 2
            unbounded = True
        if any(
            not bounded and _is_wide_root(root, cwd)
            for root, bounded, _ in recursive_search_scans
        ):
            signals.append("wide_root")
            score += 4
            wide_unbounded = True

    windows_recursive = re.search(r"(?i)\bdir\b[^\r\n;&|]*\s/s(?:\s|$)", command) or re.search(
        r"(?i)\bwhere\s+/r\b", command
    )
    if windows_recursive:
        recursive_count += 1
        signals.extend(["windows_recursive_scan", "unbounded_depth"])
        score += 6
        unbounded = True
        if re.search(
            r"(?i)(?:\b[a-z]:[\\/](?:\s|$)|\b[a-z]:[\\/]users(?:[\\/][^\\/\s]+)?(?:\s|$)|%userprofile%|\$env:userprofile)",
            command,
        ):
            signals.append("wide_root")
            score += 4
            wide_unbounded = True

    if recursive_count > 1:
        signals.append("multiple_recursive_scans")
        score += min(4, recursive_count)
    file_discovery = _looks_like_file_discovery(command)
    if file_discovery:
        signals.append("file_discovery")
        score += 1
    return list(dict.fromkeys(signals)), score, recursive_count > 0, unbounded, wide_unbounded


def _recent_failed_fingerprint_count(
    recent_activity: Iterable[dict[str, Any]] | None,
    fingerprint: str,
    *,
    now: float,
    window_s: int,
    machine: str | None,
    cwd: str,
) -> int:
    count = 0
    normalized_machine = _normalize_machine(machine)
    normalized_cwd = _normalize_cwd(cwd)
    for event in recent_activity or ():
        if not isinstance(event, dict) or event.get("type") != "tool.failed":
            continue
        try:
            age = now - float(event.get("ts") or 0)
        except (TypeError, ValueError):
            continue
        if age < 0 or age > window_s:
            continue
        data = event.get("data") or {}
        if not isinstance(data, dict):
            continue
        if _normalize_machine(data.get("machine")) != normalized_machine:
            continue
        if _normalize_cwd(data.get("cwd")) != normalized_cwd:
            continue
        prior = data.get("command")
        if isinstance(prior, str) and command_fingerprint(prior) == fingerprint:
            count += 1
    return count


def preflight_command(
    command: str,
    *,
    cwd: str = ".",
    machine: str | None = None,
    requested_timeout_s: int | None = None,
    settings: Any,
    recent_activity: Iterable[dict[str, Any]] | None = None,
    now: float | None = None,
) -> CommandPreflightDecision:
    fingerprint = command_fingerprint(command)
    if not bool(getattr(settings, "shell_preflight_enabled", True)):
        return CommandPreflightDecision(fingerprint=fingerprint)

    now = time.time() if now is None else float(now)
    signals, score, recursive, unbounded, wide = _scan_signals(command, cwd)
    expensive = recursive and unbounded and _looks_like_file_discovery(command)

    repeat_window = int(getattr(settings, "shell_preflight_repeat_failure_window_s", 900))
    repeat_limit = int(getattr(settings, "shell_preflight_repeat_failure_limit", 1))
    failures = _recent_failed_fingerprint_count(
        recent_activity,
        fingerprint,
        now=now,
        window_s=max(1, repeat_window),
        machine=machine,
        cwd=cwd,
    )
    if expensive and repeat_limit > 0 and failures >= repeat_limit:
        return CommandPreflightDecision(
            action="block",
            reason_code="repeated_failed_command",
            message=(
                "This expensive filesystem discovery command already failed in the current Logical Session; "
                "refusing an unchanged retry. Narrow the root/depth or use file_glob/file_grep/file_tree."
            ),
            cost_score=max(score, 1),
            recommended_tool="file_glob",
            fingerprint=fingerprint,
            signals=tuple([*signals, "repeated_failure"]),
            do_not_repeat_same_command=True,
        )

    if recursive and unbounded and wide:
        return CommandPreflightDecision(
            action="block",
            reason_code="wide_recursive_scan",
            message=(
                "Refusing an unbounded recursive filesystem scan from a wide root. "
                "Use file_glob/file_grep/file_tree from a project root, or add an explicit depth bound."
            ),
            cost_score=score,
            recommended_tool="file_glob",
            fingerprint=fingerprint,
            signals=tuple(signals),
            do_not_repeat_same_command=True,
        )

    if expensive:
        expensive_timeout = int(getattr(settings, "shell_preflight_expensive_timeout_s", 15))
        requested = int(requested_timeout_s) if requested_timeout_s is not None else expensive_timeout
        effective = max(1, min(requested, expensive_timeout))
        return CommandPreflightDecision(
            action="limit",
            reason_code="expensive_filesystem_discovery",
            message="Unbounded recursive filesystem discovery is limited to a shorter execution timeout.",
            cost_score=score,
            effective_timeout_s=effective,
            recommended_tool="file_glob",
            fingerprint=fingerprint,
            signals=tuple(signals),
        )

    return CommandPreflightDecision(
        action="allow",
        cost_score=score,
        recommended_tool="file_glob" if recursive and _looks_like_file_discovery(command) else None,
        fingerprint=fingerprint,
        signals=tuple(signals),
    )
