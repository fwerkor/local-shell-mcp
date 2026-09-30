from dataclasses import dataclass

import pytest
from mcp.types import CallToolResult

import local_shell_mcp.tools as tools_module
from local_shell_mcp.command_preflight import command_fingerprint, preflight_command
from local_shell_mcp.models import CommandResult
from local_shell_mcp.settings import get_settings
from local_shell_mcp.tools import _command_preflight_for_call


@dataclass
class SettingsStub:
    shell_preflight_enabled: bool = True
    shell_preflight_expensive_timeout_s: int = 15
    shell_preflight_repeat_failure_window_s: int = 900
    shell_preflight_repeat_failure_limit: int = 1


def test_blocks_wide_powershell_recursive_scan():
    command = (
        "$ErrorActionPreference='SilentlyContinue'; "
        "Get-ChildItem -Path C:\\Users\\alice -File -Recurse -Filter '*.db'"
    )
    decision = preflight_command(
        command,
        cwd=r"C:\Users\alice",
        machine="windows-worker",
        requested_timeout_s=60,
        settings=SettingsStub(),
    )
    assert decision.action == "block"
    assert decision.reason_code == "wide_recursive_scan"
    assert decision.recommended_tool == "file_glob"
    assert decision.do_not_repeat_same_command is True


def test_bounded_project_scan_is_allowed():
    command = (
        r"Get-ChildItem -Path C:\src\project -File -Recurse -Depth 3 -Filter '*.py'"
    )
    decision = preflight_command(
        command,
        cwd=r"C:\src\project",
        machine="windows-worker",
        requested_timeout_s=60,
        settings=SettingsStub(),
    )
    assert decision.action == "allow"
    assert "unbounded_depth" not in decision.signals


def test_bounded_scan_does_not_mask_separate_wide_unbounded_powershell_scan():
    decision = preflight_command(
        (
            r"Get-ChildItem -Path C:\src\project -Recurse -Depth 2 -Filter '*.py'; "
            r"Get-ChildItem -Path C:\ -File -Recurse -Filter '*.db'"
        ),
        cwd=r"C:\src\project",
        requested_timeout_s=60,
        settings=SettingsStub(),
    )
    assert decision.action == "block"
    assert decision.reason_code == "wide_recursive_scan"


def test_posix_home_find_is_blocked():
    decision = preflight_command(
        "find /home/alice -type f -name '*.db'",
        cwd="/home/alice",
        machine="linux-worker",
        requested_timeout_s=60,
        settings=SettingsStub(),
    )
    assert decision.action == "block"
    assert "wide_root" in decision.signals


@pytest.mark.parametrize(
    "command",
    [
        "sudo find / -type f -name '*.db'",
        "sudo -u root find -L / -type f -name '*.db'",
        "find -L / -type f -name '*.db'",
        "find /root -type f -name '*.db'",
        "rg needle /",
        "sudo rg needle /",
        "grep -R needle /",
        "grep -R needle /root",
    ],
)
def test_common_wide_recursive_scan_forms_are_blocked(command):
    decision = preflight_command(
        command,
        cwd="/workspace/project",
        machine="linux-worker",
        requested_timeout_s=60,
        settings=SettingsStub(),
    )
    assert decision.action == "block"
    assert decision.reason_code == "wide_recursive_scan"
    assert "wide_root" in decision.signals


def test_ripgrep_wide_scan_with_explicit_depth_bound_is_allowed():
    decision = preflight_command(
        "rg --max-depth 2 needle /",
        cwd="/workspace/project",
        machine="linux-worker",
        requested_timeout_s=60,
        settings=SettingsStub(),
    )
    assert decision.action == "allow"
    assert "unbounded_depth" not in decision.signals


def test_bounded_posix_find_is_allowed_without_unbounded_signal():
    decision = preflight_command(
        "find /workspace/project -maxdepth 2 -type f",
        cwd="/workspace/project",
        requested_timeout_s=60,
        settings=SettingsStub(),
    )
    assert decision.action == "allow"
    assert "unbounded_depth" not in decision.signals


@pytest.mark.parametrize(
    "command",
    [
        "HOME=/tmp command find / -type f -name '*.db'",
        "nohup find / -type f -name '*.db'",
        "env -i FOO=1 find / -type f -name '*.db'",
        "sudo -- find / -type f -name '*.db'",
        "sudo -n find / -type f -name '*.db'",
    ],
)
def test_command_wrappers_do_not_hide_wide_find(command):
    decision = preflight_command(
        command,
        cwd="/workspace/project",
        machine="linux-worker",
        requested_timeout_s=60,
        settings=SettingsStub(),
    )
    assert decision.action == "block"
    assert decision.reason_code == "wide_recursive_scan"


def test_incomplete_sudo_option_is_allowed_without_crashing():
    decision = preflight_command(
        "sudo -u",
        cwd="/workspace/project",
        requested_timeout_s=60,
        settings=SettingsStub(),
    )
    assert decision.action == "allow"


def test_non_recursive_powershell_listing_is_not_a_recursive_scan():
    decision = preflight_command(
        r"Get-ChildItem C:\ -File",
        cwd=r"C:\Users\alice",
        requested_timeout_s=60,
        settings=SettingsStub(),
    )
    assert decision.action == "allow"
    assert "powershell_recursive_scan" not in decision.signals


@pytest.mark.parametrize(
    "command,cwd",
    [
        (r"Get-ChildItem C:\Users\alice -Recurse", r"C:\src\project"),
        ("Get-ChildItem -Recurse", r"C:\Users\alice"),
    ],
)
def test_powershell_positional_and_default_roots_are_detected(command, cwd):
    decision = preflight_command(
        command,
        cwd=cwd,
        requested_timeout_s=60,
        settings=SettingsStub(),
    )
    assert decision.action == "block"
    assert decision.reason_code == "wide_recursive_scan"


def test_find_parser_handles_d_option_separator_and_implicit_root():
    explicit = preflight_command(
        "find -d ignored -- / -type f",
        cwd="/workspace/project",
        requested_timeout_s=60,
        settings=SettingsStub(),
    )
    implicit = preflight_command(
        "find -type f -name '*.db'",
        cwd="/home/alice",
        requested_timeout_s=60,
        settings=SettingsStub(),
    )
    assert explicit.action == "block"
    assert explicit.reason_code == "wide_recursive_scan"
    assert implicit.action == "block"
    assert implicit.reason_code == "wide_recursive_scan"


def test_recursive_search_parsing_handles_option_patterns_and_default_roots():
    rg_option = preflight_command(
        "rg -e needle /",
        cwd="/workspace/project",
        requested_timeout_s=60,
        settings=SettingsStub(),
    )
    rg_default = preflight_command(
        "rg needle",
        cwd="/home/alice",
        requested_timeout_s=60,
        settings=SettingsStub(),
    )
    grep_default = preflight_command(
        "grep -R needle",
        cwd="/home/alice",
        requested_timeout_s=60,
        settings=SettingsStub(),
    )
    grep_non_recursive = preflight_command(
        "grep needle /workspace/project/file.txt",
        cwd="/workspace/project",
        requested_timeout_s=60,
        settings=SettingsStub(),
    )
    assert rg_option.reason_code == "wide_recursive_scan"
    assert rg_default.reason_code == "wide_recursive_scan"
    assert grep_default.reason_code == "wide_recursive_scan"
    assert grep_non_recursive.action == "allow"
    assert "grep_recursive_scan" not in grep_non_recursive.signals


@pytest.mark.parametrize(
    "command",
    [
        r"dir C:\ /s",
        r"where /r C:\Users\alice *.db",
    ],
)
def test_windows_recursive_commands_from_wide_roots_are_blocked(command):
    decision = preflight_command(
        command,
        cwd=r"C:\src\project",
        requested_timeout_s=60,
        settings=SettingsStub(),
    )
    assert decision.action == "block"
    assert decision.reason_code == "wide_recursive_scan"
    assert "windows_recursive_scan" in decision.signals
    assert "wide_root" in decision.signals


def test_windows_recursive_command_without_explicit_wide_root_is_limited():
    decision = preflight_command(
        "dir /s",
        cwd=r"C:\src\project",
        requested_timeout_s=60,
        settings=SettingsStub(),
    )
    assert decision.action == "limit"
    assert decision.reason_code == "expensive_filesystem_discovery"
    assert "wide_root" not in decision.signals


def test_bounded_find_does_not_mask_separate_wide_unbounded_find():
    decision = preflight_command(
        "find /workspace/project -maxdepth 2 -type f; find / -type f -name '*.db'",
        cwd="/workspace/project",
        requested_timeout_s=60,
        settings=SettingsStub(),
    )
    assert decision.action == "block"
    assert decision.reason_code == "wide_recursive_scan"


def test_narrow_unbounded_find_is_timeout_limited():
    decision = preflight_command(
        "find /workspace/project -type f -name '*.db'",
        cwd="/workspace/project",
        requested_timeout_s=60,
        settings=SettingsStub(),
    )
    assert decision.action == "limit"
    assert decision.reason_code == "expensive_filesystem_discovery"
    assert decision.effective_timeout_s == 15


def test_existing_shorter_timeout_is_preserved():
    decision = preflight_command(
        "find /workspace/project -type f -name '*.db'",
        cwd="/workspace/project",
        requested_timeout_s=5,
        settings=SettingsStub(),
    )
    assert decision.action == "limit"
    assert decision.effective_timeout_s == 5


def test_long_running_shell_cannot_bypass_expensive_scan_limit():
    decision = _command_preflight_for_call(
        "job_start",
        {
            "command": "find /workspace/project -type f -name '*.db'",
            "cwd": "/workspace/project",
        },
        settings=SettingsStub(),
        recent_activity=None,
    )
    assert decision is not None
    assert decision.action == "block"
    assert decision.reason_code == "expensive_discovery_requires_bounded_tool"


def test_repeat_expensive_failed_scan_is_blocked():
    command = "find /workspace/project -type f -name '*.db'"
    activity = [
        {
            "type": "tool.failed",
            "ts": 990.0,
            "data": {
                "tool": "run_shell",
                "command": command,
                "cwd": "/workspace/project",
            },
        }
    ]
    decision = preflight_command(
        command,
        cwd="/workspace/project",
        requested_timeout_s=60,
        settings=SettingsStub(),
        recent_activity=activity,
        now=1000.0,
    )
    assert decision.action == "block"
    assert decision.reason_code == "repeated_failed_command"


def test_repeat_failed_scan_in_different_cwd_is_not_suppressed():
    command = "find . -type f -name '*.db'"
    activity = [
        {
            "type": "tool.failed",
            "ts": 990.0,
            "data": {
                "tool": "run_shell",
                "command": command,
                "cwd": "/workspace/first",
            },
        }
    ]
    decision = preflight_command(
        command,
        cwd="/workspace/second",
        requested_timeout_s=60,
        settings=SettingsStub(),
        recent_activity=activity,
        now=1000.0,
    )
    assert decision.action == "limit"
    assert decision.reason_code == "expensive_filesystem_discovery"


def test_local_failure_without_machine_does_not_suppress_remote_scan():
    command = "find . -type f -name '*.db'"
    activity = [
        {
            "type": "tool.failed",
            "ts": 990.0,
            "data": {
                "tool": "run_shell",
                "command": command,
                "cwd": "/workspace/project",
            },
        }
    ]
    decision = preflight_command(
        command,
        cwd="/workspace/project",
        machine="linux-worker",
        requested_timeout_s=60,
        settings=SettingsStub(),
        recent_activity=activity,
        now=1000.0,
    )
    assert decision.action == "limit"
    assert decision.reason_code == "expensive_filesystem_discovery"


def test_same_remote_machine_and_cwd_repeat_is_suppressed():
    command = "find . -type f -name '*.db'"
    activity = [
        {
            "type": "tool.failed",
            "ts": 990.0,
            "data": {
                "tool": "run_shell",
                "command": command,
                "cwd": "/workspace/project",
                "machine": "linux-worker",
            },
        }
    ]
    decision = preflight_command(
        command,
        cwd="/workspace/project",
        machine="linux-worker",
        requested_timeout_s=60,
        settings=SettingsStub(),
        recent_activity=activity,
        now=1000.0,
    )
    assert decision.action == "block"
    assert decision.reason_code == "repeated_failed_command"


def test_repeat_normal_command_is_not_blocked():
    command = "pytest -q tests/test_one.py"
    activity = [
        {
            "type": "tool.failed",
            "ts": 990.0,
            "data": {"tool": "run_shell", "command": command},
        }
    ]
    decision = preflight_command(
        command,
        cwd="/workspace/project",
        requested_timeout_s=60,
        settings=SettingsStub(),
        recent_activity=activity,
        now=1000.0,
    )
    assert decision.action == "allow"


def test_malformed_and_irrelevant_failure_events_are_ignored():
    command = "find /workspace/project -type f -name '*.db'"
    activity = [
        None,
        {"type": "tool.started", "ts": 990.0},
        {"type": "tool.failed", "ts": "not-a-number", "data": {}},
        {"type": "tool.failed", "ts": 0.0, "data": {}},
        {"type": "tool.failed", "ts": 1010.0, "data": {}},
        {"type": "tool.failed", "ts": 990.0, "data": "invalid"},
        {
            "type": "tool.failed",
            "ts": 990.0,
            "data": {
                "machine": "linux-worker",
                "cwd": "/workspace/project",
                "command": "find /workspace/other -type f",
            },
        },
    ]
    decision = preflight_command(
        command,
        cwd="/workspace/project",
        machine="linux-worker",
        requested_timeout_s=60,
        settings=SettingsStub(),
        recent_activity=activity,
        now=1000.0,
    )
    assert decision.action == "limit"
    assert decision.reason_code == "expensive_filesystem_discovery"


def test_aliases_share_fingerprint():
    assert command_fingerprint(r"gci C:\Users\alice -Recurse") == command_fingerprint(
        r"Get-ChildItem C:\Users\alice -Recurse"
    )


def test_preflight_can_be_disabled():
    settings = SettingsStub(shell_preflight_enabled=False)
    decision = preflight_command(
        "find / -type f -name '*.db'",
        cwd="/",
        requested_timeout_s=60,
        settings=settings,
    )
    assert decision.action == "allow"


@pytest.mark.asyncio
async def test_mcp_wrapper_blocks_wide_scan_before_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    executed = False

    async def fake_public_run_shell(command, cwd, timeout_s, max_output_bytes):  # noqa: ANN001, ARG001
        nonlocal executed
        executed = True
        raise AssertionError("blocked scan reached shell execution")

    monkeypatch.setattr(tools_module, "public_run_shell", fake_public_run_shell)

    result = await tools_module.build_mcp().call_tool(
        "run_shell",
        {
            "command": "find / -type f -name '*.db'",
            "cwd": "/",
            "timeout_s": 60,
        },
    )

    assert isinstance(result, CallToolResult)
    assert result.isError is True
    assert executed is False
    payload = result.structuredContent
    assert payload["data"]["error_type"] == "CommandPreflightBlocked"
    assert payload["data"]["reason_code"] == "wide_recursive_scan"


@pytest.mark.asyncio
async def test_mcp_wrapper_limits_narrow_scan_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SHELL_MCP_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    observed = {}

    async def fake_public_run_shell(command, cwd, timeout_s, max_output_bytes):  # noqa: ANN001
        observed.update(
            command=command,
            cwd=cwd,
            timeout_s=timeout_s,
            max_output_bytes=max_output_bytes,
        )
        return CommandResult(
            ok=True,
            exit_code=0,
            timed_out=False,
            duration_ms=1,
            cwd=cwd,
            command=command,
            stdout="",
            stderr="",
            truncated=False,
        )

    monkeypatch.setattr(tools_module, "public_run_shell", fake_public_run_shell)

    result = await tools_module.build_mcp().call_tool(
        "run_shell",
        {
            "command": "find project -type f -name '*.db'",
            "cwd": str(tmp_path),
            "timeout_s": 60,
        },
    )

    assert observed["timeout_s"] == 15
    _, structured = result
    assert structured["ok"] is True
    assert structured["data"]["preflight"]["reason_code"] == "expensive_filesystem_discovery"
