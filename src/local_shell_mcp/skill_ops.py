"""Fixed operations for discovering and loading installed agent skills."""

from dataclasses import asdict
from pathlib import Path
from typing import Any

from .agent_bridge.skills import activate_skill, scan_agent_skills
from .settings import Settings, get_settings

SKILLS_DIRECTORY = "skills"


def skills_directory(settings: Settings | None = None) -> Path:
    """Return the externally managed skills directory."""
    active_settings = settings or get_settings()
    return active_settings.agent_config_dir / SKILLS_DIRECTORY


def list_installed_skills(settings: Settings | None = None) -> dict[str, Any]:
    """Scan installed skills and return compact metadata without loading instructions."""
    active_settings = settings or get_settings()
    result = scan_agent_skills(active_settings.agent_config_dir, SKILLS_DIRECTORY)
    return {
        "skills_dir": str(skills_directory(active_settings)),
        "skills": [asdict(skill) for skill in result.skills.values()],
        "warnings": result.warnings,
    }


def load_installed_skill(name: str, settings: Settings | None = None) -> dict[str, Any]:
    """Load one installed skill by its exact directory name."""
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("Skill name must not be empty")

    active_settings = settings or get_settings()
    result = scan_agent_skills(active_settings.agent_config_dir, SKILLS_DIRECTORY)
    skill = result.skills.get(normalized_name)
    if skill is None:
        raise ValueError(
            f"Unknown skill: {normalized_name}. Call skills_list to see installed skills."
        )

    return {
        "skills_dir": str(skills_directory(active_settings)),
        **activate_skill(active_settings.agent_config_dir, skill),
        "warnings": result.warnings,
    }
