from pathlib import Path

import pytest

from local_shell_mcp.agent_bridge import (
    SkillRecord,
    activate_skill,
    make_unique_tool_name,
    scan_agent_skills,
)


def test_scan_agent_skills_reads_skill_md(tmp_path):
    skill_dir = tmp_path / "skills" / "paper-writer"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "# Paper Writer\n\nHelps draft ML papers.\n",
        encoding="utf-8",
    )
    (skill_dir / "template.md").write_text("template", encoding="utf-8")

    result = scan_agent_skills(tmp_path, "skills")

    assert result.warnings == []
    assert result.skills == {
        "paper-writer": SkillRecord(
            name="paper-writer",
            entry_path="skills/paper-writer/SKILL.md",
            description="Helps draft ML papers.",
            related_files=[
                "skills/paper-writer/SKILL.md",
                "skills/paper-writer/template.md",
            ],
        )
    }


def test_scan_agent_skills_skips_missing_entry(tmp_path):
    (tmp_path / "skills" / "broken").mkdir(parents=True)

    result = scan_agent_skills(tmp_path, "skills")

    assert result.skills == {}
    assert result.warnings == ["Skipping skill broken: missing SKILL.md"]


def test_scan_agent_skills_skips_symlinked_entry_outside_skill_dir(tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n\nDo not load.\n", encoding="utf-8")
    skill_dir = tmp_path / "skills" / "escape"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").symlink_to(outside)

    result = scan_agent_skills(tmp_path, "skills")

    assert result.skills == {}
    assert result.warnings == [
        "Skipping skill escape: SKILL.md must be a regular file inside the skill directory"
    ]
    with pytest.raises(ValueError, match="regular file"):
        activate_skill(
            tmp_path,
            SkillRecord(
                name="escape",
                entry_path="skills/escape/SKILL.md",
                description="Do not load.",
                related_files=["skills/escape/SKILL.md"],
            ),
        )


def test_scan_agent_skills_rejects_directories_outside_config_root(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    outside = tmp_path / "outside"
    skill_dir = outside / "sneaky"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "# Sneaky\n\nDo not scan.\n", encoding="utf-8"
    )

    relative_result = scan_agent_skills(config_dir, "../outside")
    absolute_result = scan_agent_skills(config_dir, str(outside))

    assert relative_result.skills == {}
    assert absolute_result.skills == {}
    assert relative_result.warnings == [
        "Skills directory must be inside config directory: ../outside"
    ]
    assert absolute_result.warnings == [
        f"Skills directory must be inside config directory: {outside}"
    ]


def test_activate_skill_returns_content_and_related_files(tmp_path):
    skill_dir = tmp_path / "skills" / "debugging"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "# Debugging\n\nFind root causes.\n", encoding="utf-8"
    )

    records = scan_agent_skills(tmp_path, "skills").skills
    payload = activate_skill(tmp_path, records["debugging"])

    assert payload["name"] == "debugging"
    assert payload["entry_path"] == "skills/debugging/SKILL.md"
    assert payload["content"] == "# Debugging\n\nFind root causes.\n"
    assert payload["related_files"] == ["skills/debugging/SKILL.md"]


def test_make_unique_tool_name_sanitizes_and_hashes_collisions():
    seen: set[str] = set()
    first = make_unique_tool_name("activate_skill", "paper-writer", seen)
    second = make_unique_tool_name("activate_skill", "paper writer", seen)

    assert first == "activate_skill__paper_writer"
    assert second.startswith("activate_skill__paper_writer__")
    assert first != second


def test_make_unique_tool_name_preserves_empty_raw_name_segment():
    seen: set[str] = set()

    result = make_unique_tool_name("activate_skill", "!!!", seen)

    assert result == "activate_skill__unnamed"


def test_scan_agent_skills_description_uses_early_paragraph_over_later_example(
    tmp_path,
):
    skill_dir = tmp_path / "skills" / "examples"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "# Examples\n\nUse the early paragraph.\n\n```yaml\ndescription: wrong\n```\n",
        encoding="utf-8",
    )

    result = scan_agent_skills(tmp_path, "skills")

    assert result.skills["examples"].description == "Use the early paragraph."


def test_scan_agent_skills_warns_when_directory_iteration_fails(
    tmp_path, monkeypatch
):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    original_iterdir = Path.iterdir

    def fail_iterdir(path):  # noqa: ANN001
        if path == skills_dir:
            raise OSError("racing directory")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", fail_iterdir)

    result = scan_agent_skills(tmp_path, "skills")

    assert result.skills == {}
    assert result.warnings == [
        "Could not scan skills directory skills: racing directory"
    ]


def test_scan_agent_skills_warns_when_skills_dir_resolution_fails(
    tmp_path, monkeypatch
):
    original_resolve = Path.resolve

    def fail_resolve(path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if path == tmp_path / "skills":
            raise RuntimeError("symlink loop")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", fail_resolve)

    result = scan_agent_skills(tmp_path, "skills")

    assert result.skills == {}
    assert result.warnings == [
        "Could not scan skills directory skills: symlink loop"
    ]


def test_scan_agent_skills_skips_unreadable_skill_and_continues(
    tmp_path, monkeypatch
):
    broken_dir = tmp_path / "skills" / "broken"
    good_dir = tmp_path / "skills" / "good"
    broken_dir.mkdir(parents=True)
    good_dir.mkdir()
    (broken_dir / "SKILL.md").write_text(
        "# Broken\n\nDo not load.\n", encoding="utf-8"
    )
    (good_dir / "SKILL.md").write_text(
        "# Good\n\nLoad this.\n", encoding="utf-8"
    )
    original_read_text = Path.read_text

    def fail_read_text(path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if path == broken_dir / "SKILL.md":
            raise OSError("unreadable skill")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    result = scan_agent_skills(tmp_path, "skills")

    assert set(result.skills) == {"good"}
    assert result.warnings == ["Skipping skill broken: unreadable skill"]


def test_scan_agent_skills_warns_when_related_file_scan_fails(
    tmp_path, monkeypatch
):
    skill_dir = tmp_path / "skills" / "racing"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "# Racing\n\nStill load.\n", encoding="utf-8"
    )
    original_rglob = Path.rglob

    def fail_rglob(path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if path == skill_dir:
            raise OSError("rglob failed")
        return original_rglob(path, *args, **kwargs)

    monkeypatch.setattr(Path, "rglob", fail_rglob)

    result = scan_agent_skills(tmp_path, "skills")

    assert set(result.skills) == {"racing"}
    assert result.warnings == [
        "Skipping related files for skill racing: rglob failed"
    ]
