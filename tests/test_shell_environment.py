import pytest
from conftest import python_shell_command

from local_shell_mcp.settings import get_settings
from local_shell_mcp.shell_ops import run_shell


@pytest.mark.asyncio
async def test_run_shell_filters_server_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_EXAMPLE_SECRET", "should-not-leak")
    monkeypatch.setenv("DOCKER_INTERNAL_FLAG", "should-not-leak")
    monkeypatch.setenv("CLOUDFLARE_TUNNEL_TOKEN", "should-not-leak")
    monkeypatch.setenv("VISIBLE_TO_SHELL", "ok")
    get_settings.cache_clear()

    result = await run_shell(
        python_shell_command(
            "import os; "
            "print(os.getenv('LOCAL_SHELL_MCP_EXAMPLE_SECRET')); "
            "print(os.getenv('DOCKER_INTERNAL_FLAG')); "
            "print(os.getenv('CLOUDFLARE_TUNNEL_TOKEN')); "
            "print(os.getenv('VISIBLE_TO_SHELL'))"
        ),
        timeout_s=5,
    )

    assert result.ok is True
    assert result.stdout.splitlines() == ["None", "None", "None", "ok"]


@pytest.mark.asyncio
async def test_shell_environment_filter_is_configurable(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_SHELL_ENV_BLOCKED_PREFIXES", "")
    monkeypatch.setenv("LOCAL_SHELL_MCP_SHELL_ENV_BLOCKLIST", "ONLY_THIS")
    monkeypatch.setenv("LOCAL_SHELL_MCP_VISIBLE", "visible")
    monkeypatch.setenv("ONLY_THIS", "hidden")
    get_settings.cache_clear()

    result = await run_shell(
        python_shell_command(
            "import os; "
            "print(os.getenv('LOCAL_SHELL_MCP_VISIBLE')); "
            "print(os.getenv('ONLY_THIS'))"
        ),
        timeout_s=5,
    )

    assert result.ok is True
    assert result.stdout.splitlines() == ["visible", "None"]
