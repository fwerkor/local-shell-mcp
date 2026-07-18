"""Fixed operations for discovering and loading installed agent skills."""

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .agent_bridge.skills import (
    load_agent_skill,
    read_agent_skill_file,
    scan_agent_skills,
    validate_skill_name,
)
from .settings import Settings, get_settings

SKILLS_DIRECTORY = "skills"
UNIVERSAL_SKILLS_DIRECTORY = ".agents/skills"
GLOBAL_SKILLS_DIRECTORY = "agents/skills"


@dataclass(frozen=True)
class SkillSource:
    """One ordered Agent Skill registry root."""

    name: str
    config_dir: Path
    directory: str

    @property
    def path(self) -> Path:
        return self.config_dir.expanduser().resolve() / self.directory


def skills_directory(settings: Settings | None = None) -> Path:
    """Return the LSM-managed skills directory kept for API compatibility."""
    active_settings = settings or get_settings()
    return active_settings.agent_config_dir / SKILLS_DIRECTORY


def skill_sources(settings: Settings | None = None) -> tuple[SkillSource, ...]:
    """Return Skill roots in lookup priority order."""
    active_settings = settings or get_settings()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))).expanduser()
    candidates = (
        SkillSource("project", active_settings.workspace_root, UNIVERSAL_SKILLS_DIRECTORY),
        SkillSource("managed", active_settings.agent_config_dir, SKILLS_DIRECTORY),
        SkillSource("global", config_home, GLOBAL_SKILLS_DIRECTORY),
    )

    unique: list[SkillSource] = []
    seen_paths: set[Path] = set()
    for source in candidates:
        resolved_path = source.path.resolve()
        if resolved_path in seen_paths:
            continue
        seen_paths.add(resolved_path)
        unique.append(source)
    return tuple(unique)


def _source_list(settings: Settings) -> list[dict[str, str]]:
    return [{"source": source.name, "path": str(source.path)} for source in skill_sources(settings)]


def _common_registry_metadata(settings: Settings) -> dict[str, Any]:
    return {
        "skills_dir": str(skills_directory(settings)),
        "skills_dirs": _source_list(settings),
    }


def list_installed_skills(settings: Settings | None = None) -> dict[str, Any]:
    """Scan all Skill roots and return compact metadata without loading instructions."""
    active_settings = settings or get_settings()
    skills: list[dict[str, Any]] = []
    warnings: list[str] = []
    accepted_names: set[str] = set()
    remaining_skills = max(0, active_settings.max_skills)
    remaining_scan_entries = max(0, active_settings.max_skill_scan_entries)
    remaining_path_bytes = max(0, active_settings.max_skill_path_bytes)

    for source in skill_sources(active_settings):
        if remaining_skills == 0:
            warnings.append(f"Skill list truncated at {active_settings.max_skills} directories")
            break
        if remaining_scan_entries == 0:
            warnings.append(
                f"Skill directory scan stopped after "
                f"{active_settings.max_skill_scan_entries} entries"
            )
            break
        result = scan_agent_skills(
            source.config_dir,
            source.directory,
            max_skills=active_settings.max_skills,
            max_related_files=active_settings.max_skill_related_files,
            max_scan_entries=remaining_scan_entries,
            max_path_bytes=remaining_path_bytes,
            max_entry_bytes=active_settings.max_file_read_bytes,
        )
        warnings.extend(f"{source.name}: {warning}" for warning in result.warnings)
        remaining_scan_entries = max(
            0,
            remaining_scan_entries - result.scanned_entries,
        )

        for record in result.skills.values():
            if record.name in accepted_names:
                warnings.append(
                    f"{source.name}: skipped duplicate Skill {record.name!r}; "
                    "a higher-priority source already provides it"
                )
                continue
            payload = asdict(record)
            payload["source"] = source.name
            payload["source_path"] = str(source.path)
            skills.append(payload)
            accepted_names.add(record.name)
            remaining_skills -= 1
            remaining_path_bytes = max(
                0,
                remaining_path_bytes
                - sum(len(path.encode("utf-8")) for path in record.related_files),
            )
            if remaining_skills == 0:
                break

    return {
        **_common_registry_metadata(active_settings),
        "skills": skills,
        "warnings": warnings,
    }


def _load_skill_from_sources(
    name: str,
    settings: Settings,
) -> tuple[SkillSource, dict[str, Any]]:
    validated_name = validate_skill_name(name)
    errors: list[str] = []

    for source in skill_sources(settings):
        candidate = source.path / validated_name
        try:
            if not candidate.exists() or not candidate.is_dir():
                continue
            payload = load_agent_skill(
                source.config_dir,
                validated_name,
                source.directory,
                max_related_files=settings.max_skill_related_files,
                max_scan_entries=settings.max_skill_scan_entries,
                max_path_bytes=settings.max_skill_path_bytes,
                max_entry_bytes=settings.max_file_read_bytes,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            errors.append(f"{source.name}: {exc}")
            continue
        return source, payload

    if errors:
        raise ValueError(f"Could not load skill {validated_name}: " + "; ".join(errors))
    raise ValueError(f"Unknown skill: {validated_name}. Call skills_list to see installed skills.")


def load_installed_skill(name: str, settings: Settings | None = None) -> dict[str, Any]:
    """Load one installed Skill from the highest-priority valid source."""
    active_settings = settings or get_settings()
    source, payload = _load_skill_from_sources(name, active_settings)
    return {
        **_common_registry_metadata(active_settings),
        "source": source.name,
        "source_path": str(source.path),
        **payload,
    }


def read_installed_skill_file(
    name: str,
    path: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Read one bounded related file from the selected installed Skill."""
    active_settings = settings or get_settings()
    source, _ = _load_skill_from_sources(name, active_settings)
    payload = read_agent_skill_file(
        source.config_dir,
        name,
        path,
        source.directory,
        max_file_bytes=active_settings.max_file_read_bytes,
    )
    return {
        **_common_registry_metadata(active_settings),
        "source": source.name,
        "source_path": str(source.path),
        **payload,
    }
