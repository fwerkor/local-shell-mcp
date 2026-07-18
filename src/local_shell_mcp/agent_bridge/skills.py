"""Skill discovery and activation helpers for the agent bridge."""

import os
import re
import stat
import tomllib
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import yaml

from .models import SkillRecord, SkillScanResult

DEFAULT_MAX_SKILLS = 256
DEFAULT_MAX_RELATED_FILES = 1_000
DEFAULT_MAX_SCAN_ENTRIES = 5_000
DEFAULT_MAX_PATH_BYTES = 200_000
DEFAULT_MAX_ENTRY_BYTES = 512_000
MAX_SKILL_DESCRIPTION_CHARS = 500
MAX_SKILL_FILE_PATH_CHARS = 4_096
MAX_SKILL_WARNINGS = 100


def _relative_posix(base: Path, path: Path) -> str:
    """Render a validated child path using POSIX separators."""
    return path.relative_to(base).as_posix()


def _is_relative_child_path(value: Path) -> bool:
    """Accept portable relative child paths on every host platform."""
    raw = os.fspath(value)
    posix = PurePosixPath(raw)
    windows = PureWindowsPath(raw)
    return (
        not posix.anchor
        and not windows.anchor
        and ".." not in posix.parts
        and ".." not in windows.parts
    )


def validate_skill_name(name: str) -> str:
    """Validate a portable immediate-child directory name used as a Skill identifier."""
    if not isinstance(name, str):
        raise ValueError("Skill name must be a string")
    if not name:
        raise ValueError("Skill name must not be empty")
    if name != name.strip():
        raise ValueError("Skill name must not have leading or trailing whitespace")
    if name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError("Skill name must be a single directory name")
    if len(name) > 255:
        raise ValueError("Skill name must be at most 255 characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in name):
        raise ValueError("Skill name must not contain control characters")
    try:
        name.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("Skill name must be valid UTF-8") from exc
    return name


def validate_skill_file_path(path: str) -> Path:
    """Validate a canonical portable POSIX path inside one Skill directory."""
    if not isinstance(path, str):
        raise ValueError("Skill file path must be a string")
    if not path:
        raise ValueError("Skill file path must not be empty")
    if len(path) > MAX_SKILL_FILE_PATH_CHARS:
        raise ValueError(f"Skill file path must be at most {MAX_SKILL_FILE_PATH_CHARS} characters")
    if "\\" in path or ":" in path:
        raise ValueError("Skill file path must use portable POSIX separators")
    if any(ord(character) < 32 or ord(character) == 127 for character in path):
        raise ValueError("Skill file path must not contain control characters")
    try:
        path.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("Skill file path must be valid UTF-8") from exc

    relative = PurePosixPath(path)
    if relative.is_absolute() or ".." in relative.parts or relative == PurePosixPath("."):
        raise ValueError("Skill file path must be relative to the skill directory")
    if relative.as_posix() != path:
        raise ValueError("Skill file path must be canonical")
    return Path(*relative.parts)


def _first_sentence(value: str) -> str:
    """Extract the first prose sentence used as a compact skill description."""
    match = re.match(r"(.+?[.!?])(?:\s|$)", value)
    if match:
        return match.group(1)
    return value


def _normalize_description(value: object) -> str | None:
    """Normalize and bound a front-matter or Markdown-derived description."""
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    if not normalized:
        return None
    if len(normalized) > MAX_SKILL_DESCRIPTION_CHARS:
        normalized = normalized[: MAX_SKILL_DESCRIPTION_CHARS - 1].rstrip() + "…"
    return normalized


def _front_matter_description(lines: list[str], start: int) -> tuple[str | None, int]:
    """Parse YAML or TOML front matter and return its description and body start."""
    delimiter = lines[start].strip()
    end = start + 1
    while end < len(lines):
        stripped = lines[end].strip()
        if stripped == delimiter or (delimiter == "---" and stripped == "..."):
            break
        end += 1
    if end >= len(lines):
        return None, start

    raw = "\n".join(lines[start + 1 : end])
    try:
        parsed = yaml.safe_load(raw) if delimiter == "---" else tomllib.loads(raw)
    except (yaml.YAMLError, tomllib.TOMLDecodeError, RecursionError):
        parsed = None
    if isinstance(parsed, dict):
        description = _normalize_description(parsed.get("description"))
        if description is not None:
            return description, end + 1
    return None, end + 1


def _skill_description(markdown: str) -> str:
    """Derive a bounded description from front matter, prose, or the first heading."""
    lines = markdown.splitlines()
    line_index = 0
    while line_index < len(lines) and not lines[line_index].strip():
        line_index += 1

    if line_index < len(lines) and lines[line_index].strip() in {"---", "+++"}:
        description, line_index = _front_matter_description(lines, line_index)
        if description is not None:
            return description

    in_code_fence = False
    first_heading: str | None = None
    for line in lines[line_index:]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        if stripped in {"---", "...", "+++"}:
            continue
        if stripped.startswith("#"):
            heading = _normalize_description(stripped.lstrip("#").strip())
            if first_heading is None and heading is not None:
                first_heading = heading
            continue
        prose = _normalize_description(_first_sentence(stripped))
        if prose is not None:
            return prose
    return first_heading or "Agent skill"


def _bounded(value: int | None, default: int) -> int:
    return max(1, int(default if value is None else value))


def _append_warning(warnings: list[str], message: str) -> None:
    if len(warnings) < MAX_SKILL_WARNINGS:
        warnings.append(message)
    elif len(warnings) == MAX_SKILL_WARNINGS:
        warnings.append("Additional Skill warnings were omitted")


def _resolved_skills_directory(config_dir: Path, directory: str) -> tuple[Path, Path]:
    config_root = config_dir.resolve()
    directory_path = Path(directory)
    if not _is_relative_child_path(directory_path):
        raise ValueError(f"Skills directory must be inside config directory: {directory}")
    skills_dir = config_root / directory_path
    return config_root, skills_dir


def _open_regular_file(path: Path, max_bytes: int) -> tuple[str, int, Path]:
    """Open a bounded regular file, following symlinks when present."""
    limit = _bounded(max_bytes, DEFAULT_MAX_ENTRY_BYTES)
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY

    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"Skill file must be a readable regular file: {exc}") from exc

    try:
        try:
            opened_stat = os.fstat(descriptor)
            if not stat.S_ISREG(opened_stat.st_mode):
                raise ValueError("Skill file path must be a regular file")
            if opened_stat.st_size > limit:
                raise ValueError(f"Skill file is {opened_stat.st_size} bytes; maximum is {limit}")

            resolved = path.resolve(strict=True)
            current_stat = path.stat()
            if (
                opened_stat.st_ino
                and current_stat.st_ino
                and (opened_stat.st_dev, opened_stat.st_ino)
                != (current_stat.st_dev, current_stat.st_ino)
            ):
                raise ValueError("Skill file changed while it was being opened")

            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(descriptor, min(64 * 1024, limit + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > limit:
                    raise ValueError(f"Skill file exceeds maximum size of {limit} bytes")
            data = b"".join(chunks)
        except OSError as exc:
            raise ValueError(
                f"Skill file changed or became unavailable while reading: {exc}"
            ) from exc
    finally:
        os.close(descriptor)

    content = data.decode("utf-8", errors="replace")
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    return content, len(data), resolved


def _resolve_skill_root(skills_dir: Path, name: str) -> Path:
    validated_name = validate_skill_name(name)
    candidate = skills_dir / validated_name
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError(
            f"Unknown skill: {validated_name}. Call skills_list to see installed skills."
        ) from exc
    except OSError as exc:
        raise ValueError(f"Could not inspect skill {validated_name}: {exc}") from exc
    if not resolved.is_dir():
        raise ValueError("Skill path must resolve to a directory")
    return candidate


def _scan_related_files(
    skill_root: Path,
    entry_path: Path,
    *,
    max_related_files: int,
    max_scan_entries: int,
    max_path_bytes: int,
) -> tuple[list[str], list[str], int]:
    related_limit = _bounded(max_related_files, DEFAULT_MAX_RELATED_FILES)
    scan_limit = max(0, int(max_scan_entries))
    path_limit = max(0, int(max_path_bytes))
    related_files: list[str] = []
    warnings: list[str] = []
    scanned_entries = 0
    if scan_limit == 0:
        _append_warning(
            warnings,
            "Related file scan omitted because the scan budget is exhausted",
        )
        return related_files, warnings, scanned_entries
    if path_limit == 0:
        _append_warning(
            warnings,
            "Related file paths omitted because the path budget is exhausted",
        )
        return related_files, warnings, scanned_entries
    path_bytes = 0
    stack: list[tuple[Path, tuple[str, ...]]] = [(skill_root, ())]
    visited_directories: set[Path] = set()
    resolved_entry = entry_path.resolve(strict=True)

    while stack:
        current, relative_parts = stack.pop()
        try:
            resolved_current = current.resolve(strict=True)
        except OSError as exc:
            _append_warning(warnings, f"Could not resolve related directory {current}: {exc}")
            continue
        if resolved_current in visited_directories:
            continue
        visited_directories.add(resolved_current)
        try:
            with os.scandir(current) as iterator:
                entries = []
                for entry in iterator:
                    if scanned_entries >= scan_limit:
                        _append_warning(
                            warnings,
                            f"Related file scan stopped after {scan_limit} entries",
                        )
                        return sorted(related_files), warnings, scanned_entries
                    scanned_entries += 1
                    entries.append(entry)
        except OSError as exc:
            _append_warning(warnings, f"Could not scan related files in {current}: {exc}")
            continue

        for entry in sorted(entries, key=lambda item: item.name, reverse=True):
            path = current / entry.name
            logical_parts = (*relative_parts, entry.name)
            relative = PurePosixPath(*logical_parts).as_posix()
            try:
                entry_stat = entry.stat(follow_symlinks=True)
                if stat.S_ISDIR(entry_stat.st_mode):
                    stack.append((path, logical_parts))
                    continue
                if not stat.S_ISREG(entry_stat.st_mode):
                    continue
                resolved = path.resolve(strict=True)
                if relative == "SKILL.md" or resolved == resolved_entry:
                    continue
                validate_skill_file_path(relative)
                encoded_bytes = len(relative.encode("utf-8"))
                if len(related_files) >= related_limit:
                    _append_warning(
                        warnings,
                        f"Related file list truncated at {related_limit} files",
                    )
                    return sorted(related_files), warnings, scanned_entries
                if path_bytes + encoded_bytes > path_limit:
                    _append_warning(
                        warnings,
                        f"Related file paths truncated at {path_limit} UTF-8 bytes",
                    )
                    return sorted(related_files), warnings, scanned_entries
                related_files.append(relative)
                path_bytes += encoded_bytes
            except (OSError, ValueError) as exc:
                _append_warning(
                    warnings,
                    f"Skipping related path {path.name}: {exc}",
                )

    return sorted(related_files), warnings, scanned_entries


def _load_skill_record(
    config_root: Path,
    skills_dir: Path,
    name: str,
    *,
    max_entry_bytes: int,
    max_related_files: int,
    max_scan_entries: int,
    max_path_bytes: int,
) -> tuple[SkillRecord, str, int, list[str], int]:
    skill_root = _resolve_skill_root(skills_dir, name)
    entry_path = skill_root / "SKILL.md"
    if not entry_path.exists():
        raise ValueError(f"Skill {name} is missing SKILL.md")
    content, content_bytes, resolved_entry = _open_regular_file(entry_path, max_entry_bytes)
    related_files, warnings, scanned_entries = _scan_related_files(
        skill_root,
        resolved_entry,
        max_related_files=max_related_files,
        max_scan_entries=max_scan_entries,
        max_path_bytes=max_path_bytes,
    )
    record = SkillRecord(
        name=name,
        entry_path=_relative_posix(config_root, entry_path),
        description=_skill_description(content),
        related_files=related_files,
    )
    return record, content, content_bytes, warnings, scanned_entries


def scan_agent_skills(
    config_dir: Path,
    directory: str = "skills",
    *,
    max_skills: int = DEFAULT_MAX_SKILLS,
    max_related_files: int = DEFAULT_MAX_RELATED_FILES,
    max_scan_entries: int = DEFAULT_MAX_SCAN_ENTRIES,
    max_path_bytes: int = DEFAULT_MAX_PATH_BYTES,
    max_entry_bytes: int = DEFAULT_MAX_ENTRY_BYTES,
) -> SkillScanResult:
    """Discover bounded valid Markdown Skills and report malformed entries as warnings."""
    try:
        config_root, skills_dir = _resolved_skills_directory(config_dir, directory)
    except (OSError, RuntimeError, ValueError) as exc:
        return SkillScanResult(warnings=[str(exc)])
    if not skills_dir.exists():
        return SkillScanResult()
    if not skills_dir.is_dir():
        return SkillScanResult(warnings=[f"Skills path is not a directory: {directory}"])

    skill_limit = _bounded(max_skills, DEFAULT_MAX_SKILLS)
    scan_limit = _bounded(max_scan_entries, DEFAULT_MAX_SCAN_ENTRIES)
    warnings: list[str] = []
    candidates: list[str] = []
    scanned_entries = 0
    try:
        with os.scandir(skills_dir) as iterator:
            for entry in iterator:
                if scanned_entries >= scan_limit:
                    _append_warning(
                        warnings,
                        f"Skill directory scan stopped after {scan_limit} entries",
                    )
                    break
                scanned_entries += 1
                try:
                    entry_stat = entry.stat(follow_symlinks=True)
                except OSError as exc:
                    _append_warning(warnings, f"Skipping skill {entry.name!r}: {exc}")
                    continue
                if not stat.S_ISDIR(entry_stat.st_mode):
                    continue
                candidates.append(entry.name)
    except OSError as exc:
        return SkillScanResult(
            warnings=[f"Could not scan skills directory {directory}: {exc}"],
            scanned_entries=scanned_entries,
        )

    candidates.sort()
    if len(candidates) > skill_limit:
        _append_warning(
            warnings,
            f"Skill list truncated at {skill_limit} directories",
        )
        candidates = candidates[:skill_limit]

    skills: dict[str, SkillRecord] = {}
    total_scanned_entries = scanned_entries
    remaining_scan_entries = max(0, scan_limit - scanned_entries)
    remaining_path_bytes = max(0, int(max_path_bytes))
    for name in candidates:
        try:
            validate_skill_name(name)
            record, _, _, skill_warnings, related_scanned = _load_skill_record(
                config_root,
                skills_dir,
                name,
                max_entry_bytes=max_entry_bytes,
                max_related_files=max_related_files,
                max_scan_entries=remaining_scan_entries,
                max_path_bytes=remaining_path_bytes,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            _append_warning(warnings, f"Skipping skill {name!r}: {exc}")
            continue
        skills[name] = record
        total_scanned_entries += related_scanned
        remaining_scan_entries = max(0, remaining_scan_entries - related_scanned)
        for warning in skill_warnings:
            _append_warning(warnings, f"Skill {name}: {warning}")
        remaining_path_bytes -= sum(len(path.encode("utf-8")) for path in record.related_files)
        remaining_path_bytes = max(0, remaining_path_bytes)

    return SkillScanResult(
        skills=skills,
        warnings=warnings,
        scanned_entries=total_scanned_entries,
    )


def load_agent_skill(
    config_dir: Path,
    name: str,
    directory: str = "skills",
    *,
    max_related_files: int = DEFAULT_MAX_RELATED_FILES,
    max_scan_entries: int = DEFAULT_MAX_SCAN_ENTRIES,
    max_path_bytes: int = DEFAULT_MAX_PATH_BYTES,
    max_entry_bytes: int = DEFAULT_MAX_ENTRY_BYTES,
) -> dict[str, Any]:
    """Load one Skill directly without scanning or reading every installed Skill."""
    config_root, skills_dir = _resolved_skills_directory(config_dir, directory)
    record, content, content_bytes, warnings, _ = _load_skill_record(
        config_root,
        skills_dir,
        validate_skill_name(name),
        max_entry_bytes=max_entry_bytes,
        max_related_files=max_related_files,
        max_scan_entries=max_scan_entries,
        max_path_bytes=max_path_bytes,
    )
    return {
        "name": record.name,
        "entry_path": record.entry_path,
        "description": record.description,
        "content": content,
        "bytes": content_bytes,
        "related_files": list(record.related_files),
        "warnings": warnings,
    }


def read_agent_skill_file(
    config_dir: Path,
    name: str,
    path: str,
    directory: str = "skills",
    *,
    max_file_bytes: int = DEFAULT_MAX_ENTRY_BYTES,
) -> dict[str, Any]:
    """Read one bounded regular text file directly from inside an installed Skill."""
    _, skills_dir = _resolved_skills_directory(config_dir, directory)
    skill_name = validate_skill_name(name)
    skill_root = _resolve_skill_root(skills_dir, skill_name)
    relative_path = validate_skill_file_path(path)
    if relative_path.as_posix() == "SKILL.md":
        raise ValueError("Use skill_load to read SKILL.md")
    file_path = skill_root / relative_path
    content, content_bytes, _ = _open_regular_file(file_path, max_file_bytes)
    return {
        "name": skill_name,
        "path": relative_path.as_posix(),
        "content": content,
        "bytes": content_bytes,
    }


def activate_skill(
    config_dir: Path,
    skill: SkillRecord,
    *,
    max_entry_bytes: int = DEFAULT_MAX_ENTRY_BYTES,
) -> dict[str, Any]:
    """Load a previously discovered Skill record for legacy agent-bridge callers."""
    config_root = config_dir.resolve()
    entry_relative = Path(skill.entry_path)
    if not _is_relative_child_path(entry_relative):
        raise ValueError("Skill entry path must be inside config directory")
    entry_path = config_root / entry_relative
    content, content_bytes, _ = _open_regular_file(entry_path, max_entry_bytes)
    return {
        "name": skill.name,
        "entry_path": skill.entry_path,
        "description": skill.description,
        "content": content,
        "bytes": content_bytes,
        "related_files": list(skill.related_files),
    }
