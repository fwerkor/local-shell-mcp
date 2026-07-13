"""Skill discovery and activation helpers for the agent bridge."""

import re
from pathlib import Path
from typing import Any

from .models import SkillRecord, SkillScanResult


def _relative_posix(base: Path, path: Path) -> str:
    """Render a path relative to a base directory using POSIX separators for stable manifest output."""
    return path.resolve().relative_to(base.resolve()).as_posix()


def _is_relative_child_path(value: Path) -> bool:
    """Accept only relative child paths so skill manifests cannot reference arbitrary filesystem locations."""
    return not value.is_absolute() and ".." not in value.parts


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


def _first_sentence(value: str) -> str:
    """Extract the first prose sentence used as a compact skill or tool description."""
    match = re.match(r"(.+?[.!?])(?:\s|$)", value)
    if match:
        return match.group(1)
    return value


def _description_value(line: str) -> str | None:
    """Parse a front-matter description field from a Markdown skill file."""
    key, separator, value = line.strip().partition(":")
    if separator and key.strip().lower() == "description":
        return value.strip().strip("'\"") or "Agent skill"
    return None


def _skill_description(markdown: str) -> str:
    """Derive a human-readable skill description from front matter, heading text, or body prose."""
    lines = markdown.splitlines()
    line_index = 0
    while line_index < len(lines) and not lines[line_index].strip():
        line_index += 1

    if line_index < len(lines) and lines[line_index].strip() in {"---", "+++"}:
        delimiter = lines[line_index].strip()
        line_index += 1
        while line_index < len(lines):
            stripped = lines[line_index].strip()
            if stripped in {delimiter, "..."}:
                line_index += 1
                break
            description = _description_value(lines[line_index])
            if description is not None:
                return description
            line_index += 1

    in_code_fence = False
    for line in lines[line_index:]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        if stripped in {"---", "...", "+++"} or stripped.startswith("#"):
            continue
        return _first_sentence(stripped)
    return "Agent skill"


def scan_agent_skills(
    config_dir: Path, directory: str = "skills"
) -> SkillScanResult:
    """Discover valid Markdown skill files, resolve related files, and report unsafe or malformed entries as warnings."""
    try:
        config_root = config_dir.resolve()
    except (OSError, RuntimeError) as exc:
        return SkillScanResult(
            warnings=[f"Could not scan skills directory {directory}: {exc}"]
        )
    directory_path = Path(directory)
    if not _is_relative_child_path(directory_path):
        return SkillScanResult(
            warnings=[
                f"Skills directory must be inside config directory: {directory}"
            ]
        )

    try:
        skills_dir = (config_root / directory_path).resolve()
    except (OSError, RuntimeError) as exc:
        return SkillScanResult(
            warnings=[f"Could not scan skills directory {directory}: {exc}"]
        )
    if not skills_dir.is_relative_to(config_root):
        return SkillScanResult(
            warnings=[
                f"Skills directory must be inside config directory: {directory}"
            ]
        )
    try:
        skills_dir_exists = skills_dir.exists()
    except OSError as exc:
        return SkillScanResult(
            warnings=[f"Could not scan skills directory {directory}: {exc}"]
        )
    if not skills_dir_exists:
        return SkillScanResult()

    skills: dict[str, SkillRecord] = {}
    warnings: list[str] = []
    try:
        children = sorted(
            skills_dir.iterdir(), key=lambda candidate: candidate.name
        )
    except OSError as exc:
        return SkillScanResult(
            warnings=[f"Could not scan skills directory {directory}: {exc}"]
        )

    for child in children:
        try:
            validate_skill_name(child.name)
        except ValueError as exc:
            warnings.append(f"Skipping skill {child.name!r}: {exc}")
            continue
        try:
            if not child.is_dir():
                continue
            if child.is_symlink():
                warnings.append(
                    f"Skipping skill {child.name}: skill directory is a symlink"
                )
                continue
            skill_root = child.resolve()
            if not skill_root.is_relative_to(config_root):
                warnings.append(
                    f"Skipping skill {child.name}: skill directory must be inside config directory"
                )
                continue
            entry_path = child / "SKILL.md"
            if entry_path.is_symlink():
                warnings.append(
                    f"Skipping skill {child.name}: "
                    "SKILL.md must be a regular file inside the skill directory"
                )
                continue
            if not entry_path.is_file():
                warnings.append(
                    f"Skipping skill {child.name}: missing SKILL.md"
                )
                continue
            if not entry_path.resolve().is_relative_to(skill_root):
                warnings.append(
                    f"Skipping skill {child.name}: SKILL.md must be inside the skill directory"
                )
                continue
            markdown = entry_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            warnings.append(f"Skipping skill {child.name}: {exc}")
            continue

        related_files: list[str] = []
        try:
            for related_path in child.rglob("*"):
                try:
                    if not related_path.is_file():
                        continue
                    if related_path == entry_path:
                        continue
                    if (
                        related_path.is_symlink()
                        or not related_path.resolve().is_relative_to(skill_root)
                    ):
                        warnings.append(
                            f"Skipping related file "
                            f"{related_path.relative_to(config_root).as_posix()}: "
                            "file must be inside the skill directory"
                        )
                        continue
                    related_files.append(
                        _relative_posix(skill_root, related_path)
                    )
                except OSError as exc:
                    try:
                        related_display = related_path.relative_to(
                            config_root
                        ).as_posix()
                    except ValueError:
                        related_display = str(related_path)
                    warnings.append(
                        f"Skipping related file {related_display}: {exc}"
                    )
        except OSError as exc:
            warnings.append(
                f"Skipping related files for skill {child.name}: {exc}"
            )

        skills[child.name] = SkillRecord(
            name=child.name,
            entry_path=_relative_posix(config_root, entry_path),
            description=_skill_description(markdown),
            related_files=sorted(related_files),
        )
    return SkillScanResult(skills=skills, warnings=warnings)


def activate_skill(config_dir: Path, skill: SkillRecord) -> dict[str, Any]:
    """Load a skill entry point and related files into a payload that an agent can use to execute the skill."""
    config_root = config_dir.resolve()
    entry_relative = Path(skill.entry_path)
    if not _is_relative_child_path(entry_relative):
        raise ValueError("Skill entry path must be inside config directory")
    entry_path = config_root / entry_relative
    skill_root = entry_path.parent.resolve()
    if entry_path.is_symlink() or not entry_path.is_file():
        raise ValueError("Skill entry path must be a regular file")
    entry_resolved = entry_path.resolve()
    if not entry_resolved.is_relative_to(config_root):
        raise ValueError("Skill entry path must be inside config directory")
    if not entry_resolved.is_relative_to(skill_root):
        raise ValueError("Skill entry path must be inside the skill directory")
    content = entry_path.read_text(encoding="utf-8", errors="replace")
    return {
        "name": skill.name,
        "entry_path": skill.entry_path,
        "description": skill.description,
        "content": content,
        "related_files": list(skill.related_files),
    }
