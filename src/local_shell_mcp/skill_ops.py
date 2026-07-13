"""Fixed operations for discovering and loading installed agent skills."""

from dataclasses import asdict
from pathlib import Path
from typing import Any

from .agent_bridge.skills import (
    load_agent_skill,
    read_agent_skill_file,
    scan_agent_skills,
)
from .settings import Settings, get_settings

SKILLS_DIRECTORY = "skills"


def skills_directory(settings: Settings | None = None) -> Path:
    """Return the externally managed skills directory."""
    active_settings = settings or get_settings()
    return active_settings.agent_config_dir / SKILLS_DIRECTORY


def _scan_limits(settings: Settings) -> dict[str, int]:
    return {
        "max_skills": settings.max_skills,
        "max_related_files": settings.max_skill_related_files,
        "max_scan_entries": settings.max_skill_scan_entries,
        "max_path_bytes": settings.max_skill_path_bytes,
        "max_entry_bytes": settings.max_file_read_bytes,
    }


def list_installed_skills(settings: Settings | None = None) -> dict[str, Any]:
    """Scan installed skills and return compact metadata without loading instructions."""
    active_settings = settings or get_settings()
    result = scan_agent_skills(
        active_settings.agent_config_dir,
        SKILLS_DIRECTORY,
        **_scan_limits(active_settings),
    )
    return {
        "skills_dir": str(skills_directory(active_settings)),
        "skills": [asdict(skill) for skill in result.skills.values()],
        "warnings": result.warnings,
    }


def load_installed_skill(name: str, settings: Settings | None = None) -> dict[str, Any]:
    """Load one installed skill directly by its exact directory name."""
    active_settings = settings or get_settings()
    payload = load_agent_skill(
        active_settings.agent_config_dir,
        name,
        SKILLS_DIRECTORY,
        max_related_files=active_settings.max_skill_related_files,
        max_scan_entries=active_settings.max_skill_scan_entries,
        max_path_bytes=active_settings.max_skill_path_bytes,
        max_entry_bytes=active_settings.max_file_read_bytes,
    )
    return {
        "skills_dir": str(skills_directory(active_settings)),
        **payload,
    }


def read_installed_skill_file(
    name: str,
    path: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Read one bounded related file from an installed Skill."""
    active_settings = settings or get_settings()
    payload = read_agent_skill_file(
        active_settings.agent_config_dir,
        name,
        path,
        SKILLS_DIRECTORY,
        max_file_bytes=active_settings.max_file_read_bytes,
    )
    return {
        "skills_dir": str(skills_directory(active_settings)),
        **payload,
    }
