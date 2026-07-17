from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import local_shell_mcp.agent_bridge.skills as skills
from local_shell_mcp.agent_bridge.models import SkillRecord


def test_skill_name_and_path_validation_all_rejections(monkeypatch):
    invalid_names = [None, "", " name", "name ", ".", "..", "a/b", r"a\b", "x" * 256, "a\x01"]
    for value in invalid_names:
        with pytest.raises(ValueError):
            skills.validate_skill_name(value)  # type: ignore[arg-type]

    surrogate = "\ud800"
    with pytest.raises(ValueError, match="UTF-8"):
        skills.validate_skill_name(surrogate)
    assert skills.validate_skill_name("合法-name") == "合法-name"

    invalid_paths = [
        None,
        "",
        "x" * (skills.MAX_SKILL_FILE_PATH_CHARS + 1),
        r"a\b",
        "a:b",
        "a\x01",
        "/a",
        "../a",
        ".",
        "a//b",
        "a/./b",
    ]
    for value in invalid_paths:
        with pytest.raises(ValueError):
            skills.validate_skill_file_path(value)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="UTF-8"):
        skills.validate_skill_file_path(surrogate)
    assert skills.validate_skill_file_path("docs/guide.md") == Path("docs/guide.md")


def test_descriptions_front_matter_and_warning_cap():
    assert skills._first_sentence("First. Second") == "First."
    assert skills._first_sentence("No terminator") == "No terminator"
    assert skills._normalize_description(None) is None
    assert skills._normalize_description("   ") is None
    assert skills._normalize_description("x" * 600).endswith("…")

    assert (
        skills._skill_description("\n---\ndescription: Useful skill\n---\n# Heading")
        == "Useful skill"
    )
    assert skills._skill_description("+++\ndescription = 'TOML skill'\n+++\nbody") == "TOML skill"
    assert skills._skill_description("---\n[bad\n---\n# Heading\n```\nignored\n```\n") == "Heading"
    assert skills._skill_description("```\nignored\n```\n") == "Agent skill"
    assert skills._front_matter_description(["---", "description: x"], 0) == (None, 0)

    warnings = []
    for index in range(skills.MAX_SKILL_WARNINGS + 5):
        skills._append_warning(warnings, str(index))
    assert len(warnings) == skills.MAX_SKILL_WARNINGS + 1
    assert warnings[-1] == "Additional Skill warnings were omitted"


def test_resolved_directories_regular_files_and_roots(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    for invalid_directory in ("../outside", "/absolute", r"\absolute", "C:/absolute"):
        with pytest.raises(ValueError, match="inside"):
            skills._resolved_skills_directory(config, invalid_directory)
    root, directory = skills._resolved_skills_directory(config, "skills")
    assert root == config.resolve()
    assert directory == config.resolve() / "skills"

    directory.mkdir()
    with pytest.raises(ValueError, match="Unknown skill"):
        skills._resolve_skill_root(directory, "missing")
    file_skill = directory / "file"
    file_skill.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="resolve to a directory"):
        skills._resolve_skill_root(directory, "file")

    skill = directory / "good"
    skill.mkdir()
    entry = skill / "SKILL.md"
    entry.write_bytes(b"line\r\nnext\r")
    content, size, resolved = skills._open_regular_file(entry, 100)
    assert content == "line\nnext\n"
    assert size > 0 and resolved == entry.resolve()
    with pytest.raises(ValueError, match="maximum"):
        skills._open_regular_file(entry, 1)
    with pytest.raises(ValueError, match="readable regular"):
        skills._open_regular_file(skill / "missing", 100)

    if hasattr(os, "symlink"):
        link = skill / "link.md"
        try:
            link.symlink_to(entry)
        except OSError:
            pass
        else:
            linked_content, linked_size, linked_resolved = skills._open_regular_file(link, 100)
            assert linked_content == content
            assert linked_size == size
            assert linked_resolved == entry.resolve()


def test_related_scan_budgets_symlinks_and_failures(tmp_path, monkeypatch):
    skill = tmp_path / "skill"
    skill.mkdir()
    entry = skill / "SKILL.md"
    entry.write_text("entry", encoding="utf-8")
    (skill / "b.txt").write_text("b", encoding="utf-8")
    (skill / "a.txt").write_text("a", encoding="utf-8")
    nested = skill / "nested"
    nested.mkdir()
    (nested / "c.txt").write_text("c", encoding="utf-8")

    related, warnings, scanned = skills._scan_related_files(
        skill,
        entry.resolve(),
        max_related_files=10,
        max_scan_entries=0,
        max_path_bytes=100,
    )
    assert related == [] and scanned == 0 and "scan budget" in warnings[0]
    related, warnings, _ = skills._scan_related_files(
        skill,
        entry.resolve(),
        max_related_files=10,
        max_scan_entries=100,
        max_path_bytes=0,
    )
    assert related == [] and "path budget" in warnings[0]

    related, warnings, _ = skills._scan_related_files(
        skill,
        entry.resolve(),
        max_related_files=1,
        max_scan_entries=100,
        max_path_bytes=100,
    )
    assert len(related) == 1
    assert any("truncated" in warning for warning in warnings)

    related, warnings, _ = skills._scan_related_files(
        skill,
        entry.resolve(),
        max_related_files=10,
        max_scan_entries=2,
        max_path_bytes=100,
    )
    assert any("stopped" in warning for warning in warnings)

    related, warnings, _ = skills._scan_related_files(
        skill,
        entry.resolve(),
        max_related_files=10,
        max_scan_entries=100,
        max_path_bytes=1,
    )
    assert related == []
    assert any("UTF-8 bytes" in warning for warning in warnings)

    if hasattr(os, "symlink"):
        link = skill / "link"
        try:
            link.symlink_to(entry)
        except OSError:
            pass
        else:
            related, warnings, _ = skills._scan_related_files(
                skill,
                entry.resolve(),
                max_related_files=10,
                max_scan_entries=100,
                max_path_bytes=1000,
            )
            assert "link" not in related
            assert not any("symlink" in warning for warning in warnings)

    real_scandir = skills.os.scandir

    def failing(path):
        if Path(path) == nested:
            raise OSError("scan failed")
        return real_scandir(path)

    monkeypatch.setattr(skills.os, "scandir", failing)
    _, warnings, _ = skills._scan_related_files(
        skill,
        entry.resolve(),
        max_related_files=10,
        max_scan_entries=100,
        max_path_bytes=1000,
    )
    assert any("Could not scan" in warning for warning in warnings)


def test_scan_load_read_and_legacy_activation(tmp_path):
    config = tmp_path / "config"
    skills_dir = config / "skills"
    skills_dir.mkdir(parents=True)
    assert not skills.scan_agent_skills(config / "missing").skills

    bad_path = config / "not-dir"
    bad_path.write_text("x", encoding="utf-8")
    result = skills.scan_agent_skills(config, directory="not-dir")
    assert "not a directory" in result.warnings[0]

    good = skills_dir / "good"
    good.mkdir()
    (good / "SKILL.md").write_text("# Good\nDescription.", encoding="utf-8")
    (good / "guide.md").write_text("guide", encoding="utf-8")
    missing = skills_dir / "missing-entry"
    missing.mkdir()
    (skills_dir / "plain-file").write_text("x", encoding="utf-8")

    result = skills.scan_agent_skills(config, max_skills=1, max_scan_entries=100)
    assert list(result.skills) == ["good"]
    assert any("truncated" in warning for warning in result.warnings)
    loaded = skills.load_agent_skill(config, "good")
    assert loaded["description"] == "Description."
    assert loaded["related_files"] == ["guide.md"]
    read = skills.read_agent_skill_file(config, "good", "guide.md")
    assert read["content"] == "guide"
    with pytest.raises(ValueError, match="skill_load"):
        skills.read_agent_skill_file(config, "good", "SKILL.md")

    record = SkillRecord(
        name="good",
        entry_path="skills/good/SKILL.md",
        description="Good",
        related_files=["guide.md"],
    )
    activated = skills.activate_skill(config, record)
    assert activated["content"].startswith("# Good")
    with pytest.raises(ValueError, match="inside"):
        skills.activate_skill(
            config,
            SimpleNamespace(
                name="bad",
                entry_path="../outside.md",
                description="bad",
                related_files=[],
            ),
        )
