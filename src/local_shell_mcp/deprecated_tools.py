from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp.server import fastmcp as fastmcp_module
from mcp.server.fastmcp import FastMCP as _FastMCP

DEPRECATED_TOOL_HELP_URL = "https://github.com/fwerkor/local-shell-mcp/issues/70"


@dataclass(frozen=True, slots=True)
class DeprecatedTool:
    replacement: str
    removed_in: str = "3.0.0"


DEPRECATED_TOOLS: dict[str, DeprecatedTool] = {
    "version_info": DeprecatedTool("environment_info"),
    "read_many_files": DeprecatedTool("read_file"),
    "multi_edit_file": DeprecatedTool("edit_file"),
    "git_clone_tool": DeprecatedTool("run_shell_tool"),
    "git_status_tool": DeprecatedTool("run_shell_tool"),
    "git_diff_tool": DeprecatedTool("run_shell_tool"),
    "git_log_tool": DeprecatedTool("run_shell_tool"),
    "git_checkout_tool": DeprecatedTool("run_shell_tool"),
    "git_fetch_tool": DeprecatedTool("run_shell_tool"),
    "git_pull_tool": DeprecatedTool("run_shell_tool"),
    "git_add_tool": DeprecatedTool("run_shell_tool"),
    "git_commit_tool": DeprecatedTool("run_shell_tool"),
    "git_push_tool": DeprecatedTool("run_shell_tool"),
    "git_show_tool": DeprecatedTool("run_shell_tool"),
    "git_reset_tool": DeprecatedTool("run_shell_tool"),
    "playwright_install_tool": DeprecatedTool("run_shell_tool"),
    "browser_screenshot_tool": DeprecatedTool("browser_capture_tool"),
    "browser_eval_tool": DeprecatedTool("playwright_run_script_tool"),
    "browser_pdf_tool": DeprecatedTool("browser_capture_tool"),
    "remote_environment_info": DeprecatedTool("environment_info"),
    "remote_run_shell_tool": DeprecatedTool("run_shell_tool"),
    "remote_run_python_tool": DeprecatedTool("run_python_tool"),
    "remote_shell_start": DeprecatedTool("shell_start"),
    "remote_shell_send": DeprecatedTool("shell_send"),
    "remote_shell_read": DeprecatedTool("shell_read"),
    "remote_shell_kill": DeprecatedTool("shell_kill"),
    "remote_shell_list": DeprecatedTool("shell_list"),
    "remote_job_start": DeprecatedTool("job_start"),
    "remote_job_list": DeprecatedTool("job_list"),
    "remote_job_tail": DeprecatedTool("job_tail"),
    "remote_job_stop": DeprecatedTool("job_stop"),
    "remote_job_retry": DeprecatedTool("job_retry"),
    "remote_list_files": DeprecatedTool("list_files"),
    "remote_tree_view": DeprecatedTool("tree_view"),
    "remote_glob_search": DeprecatedTool("glob_search"),
    "remote_grep_search": DeprecatedTool("grep_search"),
    "remote_read_file": DeprecatedTool("read_file"),
    "remote_read_many_files": DeprecatedTool("read_file"),
    "remote_write_file": DeprecatedTool("write_file"),
    "remote_edit_file": DeprecatedTool("edit_file"),
    "remote_multi_edit_file": DeprecatedTool("edit_file"),
    "remote_delete_file_or_dir": DeprecatedTool("delete_file_or_dir"),
    "remote_apply_patch": DeprecatedTool("apply_patch"),
    "remote_copy_file": DeprecatedTool("transfer_path"),
    "remote_copy_dir": DeprecatedTool("transfer_path"),
    "remote_pull_file": DeprecatedTool("transfer_path"),
    "remote_push_file": DeprecatedTool("transfer_path"),
    "remote_pull_dir": DeprecatedTool("transfer_path"),
    "remote_push_dir": DeprecatedTool("transfer_path"),
    "remote_git_clone_tool": DeprecatedTool("run_shell_tool"),
    "remote_git_status_tool": DeprecatedTool("run_shell_tool"),
    "remote_git_diff_tool": DeprecatedTool("run_shell_tool"),
    "remote_git_log_tool": DeprecatedTool("run_shell_tool"),
    "remote_git_checkout_tool": DeprecatedTool("run_shell_tool"),
    "remote_git_fetch_tool": DeprecatedTool("run_shell_tool"),
    "remote_git_pull_tool": DeprecatedTool("run_shell_tool"),
    "remote_git_add_tool": DeprecatedTool("run_shell_tool"),
    "remote_git_commit_tool": DeprecatedTool("run_shell_tool"),
    "remote_git_push_tool": DeprecatedTool("run_shell_tool"),
    "remote_git_show_tool": DeprecatedTool("run_shell_tool"),
    "remote_git_reset_tool": DeprecatedTool("run_shell_tool"),
    "remote_playwright_install_tool": DeprecatedTool("run_shell_tool"),
    "remote_browser_screenshot_tool": DeprecatedTool("browser_capture_tool"),
    "remote_browser_get_text_tool": DeprecatedTool("browser_get_text_tool"),
    "remote_browser_eval_tool": DeprecatedTool("playwright_run_script_tool"),
    "remote_browser_pdf_tool": DeprecatedTool("browser_capture_tool"),
    "remote_playwright_run_script_tool": DeprecatedTool("playwright_run_script_tool"),
}


def _deprecated_tool_result(name: str, tool: DeprecatedTool) -> dict[str, Any]:
    return {
        "ok": False,
        "message": (
            f"Tool '{name}' was removed in local-shell-mcp {tool.removed_in}. "
            "The client is using an outdated MCP tool snapshot."
        ),
        "data": {
            "status": "stale_tool_snapshot",
            "deprecated_tool": name,
            "replacement": tool.replacement,
            "removed_in": tool.removed_in,
            "help_url": DEPRECATED_TOOL_HELP_URL,
            "assistant_instruction": (
                "Do not retry this deprecated tool. Explain to the user that ChatGPT is using "
                "a stale local-shell-mcp tool snapshot and ask them to refresh the LSM App's "
                "tools, or remove and re-add the App if refresh is unavailable. Refer them to "
                f"{DEPRECATED_TOOL_HELP_URL}. After the cache is updated, use the replacement "
                f"tool '{tool.replacement}'."
            ),
        },
    }


class DeprecatedToolFastMCP(_FastMCP):
    """FastMCP variant that keeps removed tool names as non-enumerated tombstones."""

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        deprecated = DEPRECATED_TOOLS.get(name)
        if deprecated is not None:
            return _deprecated_tool_result(name, deprecated)
        return await super().call_tool(name, arguments)


def install_deprecated_tool_tombstones() -> None:
    """Make subsequent FastMCP imports use the tombstone-aware implementation."""

    if fastmcp_module.FastMCP is DeprecatedToolFastMCP:
        return
    fastmcp_module.FastMCP = DeprecatedToolFastMCP
