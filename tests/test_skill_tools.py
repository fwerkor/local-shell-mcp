import pytest
from fastapi.testclient import TestClient

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


def _configure(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_AUTH_MODE", "none")
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")
    get_settings.cache_clear()


def _install_skill(tmp_path, name="debugging"):
    skill_dir = _skills_root(tmp_path) / name
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
        }
    ]
    assert loaded["name"] == "debugging"
    assert loaded["content"].startswith("---\ndescription:")
    assert loaded["related_files"] == ["checklist.md"]


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


def test_skill_read_file_works_when_agent_config_is_outside_workspace(
    tmp_path, monkeypatch
):
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
