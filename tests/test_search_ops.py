import pytest

from local_shell_mcp.search_ops import tree
from local_shell_mcp.settings import get_settings
from local_shell_mcp.tools import _handled_error


@pytest.mark.asyncio
async def test_tree_reports_existing_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    (tmp_path / "project" / "src").mkdir(parents=True)
    (tmp_path / "project" / "README.md").write_text("hello", encoding="utf-8")

    result = await tree("project")

    assert result["exists"] is True
    assert result["is_directory"] is True
    assert "src/" in result["entries"]
    assert "README.md" in result["entries"]


@pytest.mark.asyncio
async def test_tree_returns_context_for_missing_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    (tmp_path / "actual").mkdir()

    result = await tree("missing/project")

    assert result["exists"] is False
    assert result["is_directory"] is False
    assert result["nearest_existing_parent"] == str(tmp_path)
    assert "actual/" in result["nearest_parent_entries"]
    assert "Path does not exist" in result["message"]


def test_tool_error_returns_successful_not_found_result(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    (tmp_path / "actual").mkdir()

    result = _handled_error(FileNotFoundError(str(tmp_path / "missing" / "project")))

    assert result["ok"] is True
    assert result["data"]["status"] == "not_found"
    assert result["data"]["error_type"] == "FileNotFoundError"
    assert result["data"]["exists"] is False
    assert result["data"]["nearest_existing_parent"] == str(tmp_path)
    assert "actual/" in result["data"]["nearest_parent_entries"]


def test_tool_error_returns_successful_error_result():
    result = _handled_error(ValueError("bad input"))

    assert result["ok"] is True
    assert "error" not in result
    assert result["data"] == {
        "status": "error",
        "error_type": "ValueError",
        "message": "bad input",
    }
