import sys

import pytest
from conftest import python_shell_command

from local_shell_mcp.settings import get_settings
from local_shell_mcp.shell_environment import persistent_pipe_shell_args, subprocess_env
from local_shell_mcp.shell_ops import run_shell

pytestmark = pytest.mark.usefixtures("legacy_file_state_backend")

def test_persistent_pipe_powershell_reads_commands_from_stdin():
    assert persistent_pipe_shell_args("powershell.exe") == [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "-",
    ]

def test_persistent_pipe_shell_keeps_regular_interactive_invocation():
    assert persistent_pipe_shell_args("/bin/bash") == ["/bin/bash"]

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

def test_frozen_subprocess_env_restores_pyinstaller_loader_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_SHELL_ENV_BLOCKED_PREFIXES", "")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI-bundled")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/lib")
    monkeypatch.setenv("LD_PRELOAD", "/tmp/_MEI-bundled/libpreload.so")
    monkeypatch.setenv("DYLD_LIBRARY_PATH", "/tmp/_MEI-bundled")
    monkeypatch.setenv("DYLD_LIBRARY_PATH_ORIG", "/opt/homebrew/lib")
    monkeypatch.setenv("DYLD_INSERT_LIBRARIES", "/tmp/_MEI-bundled/libinject.dylib")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "/tmp/_MEI-bundled", raising=False)
    get_settings.cache_clear()

    env = subprocess_env()

    assert env["LD_LIBRARY_PATH"] == "/usr/lib"
    assert "LD_LIBRARY_PATH_ORIG" not in env
    assert "LD_PRELOAD" not in env
    assert env["DYLD_LIBRARY_PATH"] == "/opt/homebrew/lib"
    assert "DYLD_LIBRARY_PATH_ORIG" not in env
    assert "DYLD_INSERT_LIBRARIES" not in env

def test_non_frozen_subprocess_env_preserves_loader_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_SHELL_ENV_BLOCKED_PREFIXES", "")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/custom/lib")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/original/lib")
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    get_settings.cache_clear()

    env = subprocess_env()

    assert env["LD_LIBRARY_PATH"] == "/custom/lib"
    assert env["LD_LIBRARY_PATH_ORIG"] == "/original/lib"

@pytest.mark.asyncio
async def test_frozen_run_shell_restores_loader_env_for_child_process(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_SHELL_MCP_SHELL_ENV_BLOCKED_PREFIXES", "")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI-bundled")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/lib")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "/tmp/_MEI-bundled", raising=False)
    get_settings.cache_clear()

    result = await run_shell(
        python_shell_command(
            "import os; "
            "print(os.getenv('LD_LIBRARY_PATH')); "
            "print(os.getenv('LD_LIBRARY_PATH_ORIG'))"
        ),
        timeout_s=5,
    )

    assert result.ok is True
    child_ld_path, child_orig = result.stdout.splitlines()
    # Shell init may prepend machine-local libraries (for example CUDA).
    # It must still restore the original loader path and never leak the
    # temporary PyInstaller extraction directory into child processes.
    assert "/usr/lib" in child_ld_path.split(":")
    assert "/tmp/_MEI-bundled" not in child_ld_path
    assert child_orig == "None"
