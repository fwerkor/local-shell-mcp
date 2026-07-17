"""Data models used by installed agent skills."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SkillRecord:
    """Resolved skill metadata."""

    name: str
    """Stable skill name derived from its directory."""
    entry_path: str
    """Path to the Markdown skill entry file."""
    description: str
    """Human-readable skill summary."""
    related_files: list[str]
    """Additional files related to the skill entry."""


@dataclass(frozen=True)
class SkillScanResult:
    """Skill discovery result."""

    skills: dict[str, SkillRecord] = field(default_factory=dict)
    """Accepted skills keyed by skill name."""
    warnings: list[str] = field(default_factory=list)
    """Non-fatal discovery warnings for ignored or invalid entries."""
    scanned_entries: int = 0
    """Filesystem entries consumed from the registry scan budget."""
