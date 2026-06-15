import json
import subprocess
import sys


def test_export_tools_json_script_outputs_current_tool_surface(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_REMOTE_ENABLED", "false")

    result = subprocess.run(
        [sys.executable, "scripts/export-tools-json.py"],
        check=True,
        text=True,
        capture_output=True,
    )

    tools = json.loads(result.stdout)
    names = {tool["name"] for tool in tools}
    shell_tool = next(tool for tool in tools if tool["name"] == "run_shell_tool")

    assert "run_shell_tool" in names
    assert "remote_run_shell_tool" not in names
    assert "For long-running" in shell_tool["description"]
    assert shell_tool["outputSchema"]["title"] == "ToolResult"
