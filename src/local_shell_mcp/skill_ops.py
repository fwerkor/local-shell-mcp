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


def _installed_skill(name: str, settings: Settings):
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("Skill name must not be empty")

    result = scan_agent_skills(settings.agent_config_dir, SKILLS_DIRECTORY)
    skill = result.skills.get(normalized_name)
    if skill is None:
        raise ValueError(
            f"Unknown skill: {normalized_name}. Call skills_list to see installed skills."
        )
    return result, skill


def load_installed_skill(name: str, settings: Settings | None = None) -> dict[str, Any]:
    """Load one installed skill by its exact directory name."""
    active_settings = settings or get_settings()
    result, skill = _installed_skill(name, active_settings)
    return {
        "skills_dir": str(skills_directory(active_settings)),
        **activate_skill(active_settings.agent_config_dir, skill),
        "warnings": result.warnings,
    }


def read_installed_skill_file(
    name: str,
    path: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Read one related file from an installed skill by its returned relative path."""
    active_settings = settings or get_settings()
    result, skill = _installed_skill(name, active_settings)
    resource_path = Path(path)
    if resource_path.is_absolute() or ".." in resource_path.parts:
        raise ValueError("Skill file path must be relative to the skill directory")
    normalized_path = resource_path.as_posix()
    if normalized_path not in skill.related_files:
        raise ValueError(
            f"Unknown related file for skill {skill.name}: {normalized_path}. "
            "Use skill_load to see related files."
        )

    skill_root = active_settings.agent_config_dir / SKILLS_DIRECTORY / skill.name
    file_path = skill_root / resource_path
    if file_path.is_symlink() or not file_path.is_file():
        raise ValueError("Skill file path must be a regular file")
    resolved = file_path.resolve()
    if not resolved.is_relative_to(skill_root.resolve()):
        raise ValueError("Skill file path must stay inside the skill directory")
    content = file_path.read_text(encoding="utf-8", errors="replace")
    return {
        "skills_dir": str(skills_directory(active_settings)),
        "name": skill.name,
        "path": normalized_path,
        "content": content,
        "bytes": len(content.encode("utf-8")),
        "warnings": result.warnings,
    }
