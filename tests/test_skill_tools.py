import os
import sys

import pytest
from fastapi.testclient import TestClient

import local_shell_mcp.agent_bridge.skills as skills_module
import local_shell_mcp.skill_ops as skill_ops_module
from local_shell_mcp.http_app import build_http_app
from local_shell_mcp.settings import get_settings
from local_shell_mcp.skill_ops import (
    list_installed_skills,
    load_installed_skill,
    read_installed_skill_file,
)
from local_shell_mcp.tools import build_mcp


def _skills_root(tmp_path):
    return tmp_path / ".local-shell-mcp" / "agent_config" / "skills"


def _project_skills_root(tmp_path):
    return tmp_path / ".agents" / "skills"


def _global_skills_root(tmp_path):
    return tmp_path / "home" / ".config" / "agents" / "skills"


def _configure(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "home" / ".config"))
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()


def _install_skill(tmp_path, name="debugging", source="managed"):
    roots = {
        "project": _project_skills_root(tmp_path),
        "managed": _skills_root(tmp_path),
        "global": _global_skills_root(tmp_path),
    }
    skill_dir = roots[source] / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\ndescription: Diagnose failing tests safely.\n---\n\n# Debugging\n",
        encoding="utf-8",
    )
    (skill_dir / "checklist.md").write_text("Reproduce first.\n", encoding="utf-8")
    return skill_dir


def test_skills_list_is_empty_when_no_skills_are_installed(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    payload = list_installed_skills()

    assert payload["skills"] == []
    assert payload["warnings"] == []
    assert payload["skills_dir"] == str(_skills_root(tmp_path))
    assert payload["skills_dirs"] == [
        {"source": "project", "path": str(_project_skills_root(tmp_path))},
        {"source": "managed", "path": str(_skills_root(tmp_path))},
        {"source": "global", "path": str(_global_skills_root(tmp_path))},
    ]


def test_skill_load_returns_instructions_and_related_paths(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    _install_skill(tmp_path)

    listed = list_installed_skills()
    loaded = load_installed_skill("debugging")

    assert listed["skills"] == [
        {
            "name": "debugging",
            "entry_path": "skills/debugging/SKILL.md",
            "description": "Diagnose failing tests safely.",
            "related_files": ["checklist.md"],
            "source": "managed",
            "source_path": str(_skills_root(tmp_path)),
        }
    ]
    assert loaded["name"] == "debugging"
    assert loaded["content"].startswith("---\ndescription:")
    assert loaded["related_files"] == ["checklist.md"]
    assert loaded["source"] == "managed"
    assert loaded["source_path"] == str(_skills_root(tmp_path))


def test_skill_sources_merge_with_project_then_managed_then_global_priority(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    project = _install_skill(tmp_path, "shared", "project")
    managed = _install_skill(tmp_path, "shared", "managed")
    _install_skill(tmp_path, "managed-only", "managed")
    _install_skill(tmp_path, "global-only", "global")
    (project / "SKILL.md").write_text("# Project copy\n", encoding="utf-8")
    (managed / "SKILL.md").write_text("# Managed copy\n", encoding="utf-8")

    listed = list_installed_skills()
    loaded = load_installed_skill("shared")
    related = read_installed_skill_file("shared", "checklist.md")

    assert [(skill["name"], skill["source"]) for skill in listed["skills"]] == [
        ("shared", "project"),
        ("managed-only", "managed"),
        ("global-only", "global"),
    ]
    assert loaded["content"] == "# Project copy\n"
    assert loaded["source"] == "project"
    assert related["source"] == "project"
    assert any("skipped duplicate Skill 'shared'" in warning for warning in listed["warnings"])


def test_skill_sources_share_one_registry_scan_budget(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_SKILL_SCAN_ENTRIES", "3")
    get_settings.cache_clear()
    _install_skill(tmp_path, "project-only", "project")
    _install_skill(tmp_path, "managed-only", "managed")

    listed = list_installed_skills()

    assert [(skill["name"], skill["source"]) for skill in listed["skills"]] == [
        ("project-only", "project")
    ]
    assert any("stopped after 3 entries" in warning for warning in listed["warnings"])


@pytest.mark.skipif(os.name == "nt", reason="symlink creation requires privileges on Windows")
def test_symlinked_skill_directory_and_entry_file_are_supported(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    real_skill = tmp_path / "real-skill"
    real_skill.mkdir()
    real_entry = tmp_path / "real-entry.md"
    real_entry.write_text("# Linked Skill\n", encoding="utf-8")
    (real_skill / "SKILL.md").symlink_to(real_entry)
    (real_skill / "guide.md").write_text("linked guide", encoding="utf-8")
    project_root = _project_skills_root(tmp_path)
    project_root.mkdir(parents=True)
    (project_root / "linked-skill").symlink_to(real_skill, target_is_directory=True)

    listed = list_installed_skills()
    loaded = load_installed_skill("linked-skill")
    related = read_installed_skill_file("linked-skill", "guide.md")

    assert [(skill["name"], skill["source"]) for skill in listed["skills"]] == [
        ("linked-skill", "project")
    ]
    assert loaded["content"] == "# Linked Skill\n"
    assert related["content"] == "linked guide"


def test_mcp_instructions_describe_the_fixed_skill_flow(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    instructions = build_mcp().instructions

    assert "skills_list first" in instructions
    assert "skill_load with that exact name" in instructions
    assert "skill_read_file only when" in instructions
    assert "do not expect per-Skill MCP tools" in instructions
    assert "activate_skill__" not in instructions


@pytest.mark.asyncio
async def test_skill_changes_are_visible_without_mcp_tool_list_changes(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    mcp = build_mcp()
    initial_tool_names = {tool.name for tool in await mcp.list_tools()}

    _, initial = await mcp.call_tool("skills_list", {})
    assert initial["data"]["skills"] == []

    _install_skill(tmp_path, "paper-writer")
    _, updated = await mcp.call_tool("skills_list", {})
    updated_tool_names = {tool.name for tool in await mcp.list_tools()}

    assert [skill["name"] for skill in updated["data"]["skills"]] == ["paper-writer"]
    assert updated_tool_names == initial_tool_names
    assert not any(name.startswith("activate_skill__") for name in updated_tool_names)


@pytest.mark.asyncio
async def test_skill_tools_are_read_only_and_callable(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    _install_skill(tmp_path)
    mcp = build_mcp()
    tools = {tool.name: tool for tool in await mcp.list_tools()}

    assert tools["skills_list"].annotations.readOnlyHint is True
    assert tools["skill_load"].annotations.readOnlyHint is True
    assert tools["skill_read_file"].annotations.readOnlyHint is True

    _, loaded = await mcp.call_tool("skill_load", {"name": "debugging"})
    _, related = await mcp.call_tool(
        "skill_read_file", {"name": "debugging", "path": "checklist.md"}
    )
    assert loaded["ok"] is True
    assert loaded["data"]["name"] == "debugging"
    assert related["ok"] is True
    assert related["data"]["content"] == "Reproduce first.\n"


def test_skill_rest_endpoints_use_the_same_fixed_registry(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    _install_skill(tmp_path)
    client = TestClient(build_http_app())

    listed = client.get("/tools/skills_list").json()
    loaded = client.post("/tools/skill_load", json={"name": "debugging"}).json()
    related = client.post(
        "/tools/skill_read_file",
        json={"name": "debugging", "path": "checklist.md"},
    ).json()

    assert listed == list_installed_skills()
    assert loaded == load_installed_skill("debugging")
    assert related == read_installed_skill_file("debugging", "checklist.md")


def test_skill_load_rejects_unknown_names(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="Call skills_list"):
        load_installed_skill("missing")


def test_skill_read_file_works_when_agent_config_is_outside_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    agent_config = tmp_path / "external-agent-config"
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AGENT_CONFIG_DIR", str(agent_config))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()

    skill_dir = agent_config / "skills" / "external"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# External\n", encoding="utf-8")
    (skill_dir / "reference.md").write_text("External reference.\n", encoding="utf-8")

    loaded = load_installed_skill("external")
    related = read_installed_skill_file("external", loaded["related_files"][0])

    assert loaded["related_files"] == ["reference.md"]
    assert related["content"] == "External reference.\n"


@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows normalizes trailing spaces in directory names",
)
def test_invalid_skill_directory_names_are_skipped(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    _install_skill(tmp_path, "space ")

    payload = list_installed_skills()

    assert payload["skills"] == []
    assert "leading or trailing whitespace" in payload["warnings"][0]


def test_skill_text_normalizes_newlines_across_platforms(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    skill_dir = _skills_root(tmp_path) / "crlf"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_bytes(b"---\r\ndescription: CRLF skill.\r\n---\r\n# CRLF\r\n")
    (skill_dir / "reference.md").write_bytes(b"Line one.\r\nLine two.\r")

    loaded = load_installed_skill("crlf")
    related = read_installed_skill_file("crlf", "reference.md")

    assert "\r" not in loaded["content"]
    assert related["content"] == "Line one.\nLine two.\n"


def test_skill_load_does_not_normalize_names(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    _install_skill(tmp_path)

    with pytest.raises(ValueError, match="leading or trailing whitespace"):
        load_installed_skill(" debugging ")


def test_skill_rest_rejects_non_string_arguments(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    client = TestClient(build_http_app(), raise_server_exceptions=False)

    load_response = client.post("/tools/skill_load", json={"name": 123})
    read_response = client.post("/tools/skill_read_file", json={"name": "debugging", "path": 123})

    assert load_response.status_code == 400
    assert read_response.status_code == 400
    assert load_response.json()["error"] == "validation_error"
    assert read_response.json()["error"] == "validation_error"


@pytest.mark.skipif(
    sys.platform != "linux",
    reason="invalid-byte filenames rely on Linux surrogateescape behavior",
)
def test_non_utf8_skill_directory_names_are_skipped(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    skills_root = _skills_root(tmp_path)
    skills_root.mkdir(parents=True)
    raw_name = os.fsencode(skills_root) + b"/bad-\xff"
    os.mkdir(raw_name)
    with open(raw_name + b"/SKILL.md", "wb") as handle:
        handle.write(b"# Bad\n")

    payload = list_installed_skills()
    client = TestClient(build_http_app(), raise_server_exceptions=False)
    response = client.get("/tools/skills_list")

    assert payload["skills"] == []
    assert "valid UTF-8" in payload["warnings"][0]
    assert response.status_code == 200


def test_skill_load_does_not_scan_unrelated_skills(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    _install_skill(tmp_path, "target")

    def fail_scan(*args, **kwargs):
        raise AssertionError("skill_load must not scan the full registry")

    monkeypatch.setattr(skill_ops_module, "scan_agent_skills", fail_scan)

    loaded = load_installed_skill("target")

    assert loaded["name"] == "target"


def test_skill_entry_and_related_file_reads_obey_size_limit(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_FILE_READ_BYTES", "32")
    get_settings.cache_clear()
    skill_dir = _install_skill(tmp_path, "large")
    (skill_dir / "SKILL.md").write_text("# Large\n\n" + "x" * 100, encoding="utf-8")
    (skill_dir / "checklist.md").write_text("y" * 100, encoding="utf-8")

    with pytest.raises(ValueError, match="maximum is 32"):
        load_installed_skill("large")
    with pytest.raises(ValueError, match="maximum is 32"):
        read_installed_skill_file("large", "checklist.md")


def test_skill_related_file_list_is_bounded(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_SKILL_RELATED_FILES", "2")
    get_settings.cache_clear()
    skill_dir = _install_skill(tmp_path, "bounded")
    for index in range(5):
        (skill_dir / f"reference-{index}.md").write_text("x", encoding="utf-8")

    loaded = load_installed_skill("bounded")

    assert len(loaded["related_files"]) == 2
    assert any("truncated at 2 files" in warning for warning in loaded["warnings"])


def test_skill_registry_count_is_bounded(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_SKILLS", "1")
    get_settings.cache_clear()
    _install_skill(tmp_path, "first")
    _install_skill(tmp_path, "second")

    listed = list_installed_skills()

    assert len(listed["skills"]) == 1
    assert any("truncated at 1 directories" in warning for warning in listed["warnings"])


def test_loading_small_skill_ignores_oversized_unrelated_skill(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_FILE_READ_BYTES", "128")
    get_settings.cache_clear()
    _install_skill(tmp_path, "small")
    large_dir = _install_skill(tmp_path, "oversized")
    (large_dir / "SKILL.md").write_text("# Large\n" + "x" * 1000, encoding="utf-8")

    loaded = load_installed_skill("small")
    listed = list_installed_skills()

    assert loaded["name"] == "small"
    assert [skill["name"] for skill in listed["skills"]] == ["small"]
    assert any("maximum is 128" in warning for warning in listed["warnings"])


def test_skill_read_file_rejects_path_traversal(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    _install_skill(tmp_path)

    with pytest.raises(ValueError, match="relative to the skill directory"):
        read_installed_skill_file("debugging", "../outside.md")


@pytest.mark.skipif(os.name == "nt", reason="symlink creation requires privileges on Windows")
def test_skill_read_file_follows_symlinks(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    skill_dir = _install_skill(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    (skill_dir / "linked.md").symlink_to(outside)

    loaded = load_installed_skill("debugging")
    related = read_installed_skill_file("debugging", "linked.md")

    assert "linked.md" in loaded["related_files"]
    assert related["content"] == "outside"


def test_skill_path_budget_is_strict_across_registry(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_SKILL_PATH_BYTES", "1")
    get_settings.cache_clear()
    for name in ("alpha", "beta"):
        skill_dir = _skills_root(tmp_path) / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
        (skill_dir / "x").write_text("x", encoding="utf-8")

    listed = list_installed_skills()
    returned_paths = [path for skill in listed["skills"] for path in skill["related_files"]]

    assert sum(len(path.encode("utf-8")) for path in returned_paths) <= 1
    assert any("path budget is exhausted" in warning for warning in listed["warnings"])


def test_bounded_skill_registry_keeps_sorted_names(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_SKILLS", "1")
    get_settings.cache_clear()
    _install_skill(tmp_path, "z-last")
    _install_skill(tmp_path, "a-first")

    listed = list_installed_skills()

    assert [skill["name"] for skill in listed["skills"]] == ["a-first"]


def test_skill_file_paths_reject_windows_and_noncanonical_forms(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    _install_skill(tmp_path)

    for path in (r"sub\\file.md", "C:checklist.md", "./checklist.md"):
        with pytest.raises(ValueError, match="portable POSIX|canonical"):
            read_installed_skill_file("debugging", path)


def test_skill_file_race_errors_are_normalized(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    _install_skill(tmp_path)

    def fail_read(descriptor, size):  # noqa: ARG001
        raise FileNotFoundError("replaced during read")

    monkeypatch.setattr(skills_module.os, "read", fail_read)

    with pytest.raises(ValueError, match="changed or became unavailable"):
        read_installed_skill_file("debugging", "checklist.md")


def test_skill_registry_uses_one_global_scan_budget(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("LOCAL_SHELL_MCP_MAX_SKILL_SCAN_ENTRIES", "4")
    get_settings.cache_clear()
    for name in ("alpha", "beta"):
        skill_dir = _skills_root(tmp_path) / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
        (skill_dir / "reference.md").write_text("x", encoding="utf-8")

    listed = list_installed_skills()
    by_name = {skill["name"]: skill for skill in listed["skills"]}

    assert by_name["alpha"]["related_files"] == ["reference.md"]
    assert by_name["beta"]["related_files"] == []
    assert any("scan budget is exhausted" in warning for warning in listed["warnings"])
