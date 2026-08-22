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
    "version_info": DeprecatedTool("environment_get"),
    "read_many_files": DeprecatedTool("file_read"),
    "multi_edit_file": DeprecatedTool("file_edit"),
    "git_clone_tool": DeprecatedTool("run_shell"),
    "git_status_tool": DeprecatedTool("run_shell"),
    "git_diff_tool": DeprecatedTool("run_shell"),
    "git_log_tool": DeprecatedTool("run_shell"),
    "git_checkout_tool": DeprecatedTool("run_shell"),
    "git_fetch_tool": DeprecatedTool("run_shell"),
    "git_pull_tool": DeprecatedTool("run_shell"),
    "git_add_tool": DeprecatedTool("run_shell"),
    "git_commit_tool": DeprecatedTool("run_shell"),
    "git_push_tool": DeprecatedTool("run_shell"),
    "git_show_tool": DeprecatedTool("run_shell"),
    "git_reset_tool": DeprecatedTool("run_shell"),
    "playwright_install_tool": DeprecatedTool("run_shell"),
    "browser_screenshot_tool": DeprecatedTool("browser_capture_tool"),
    "browser_eval_tool": DeprecatedTool("browser_run_script"),
    "browser_pdf_tool": DeprecatedTool("browser_capture_tool"),
    "remote_environment_info": DeprecatedTool("environment_get"),
    "remote_run_shell_tool": DeprecatedTool("run_shell"),
    "remote_run_python_tool": DeprecatedTool("run_python"),
    "remote_shell_start": DeprecatedTool("shell_start"),
    "remote_shell_send": DeprecatedTool("shell_send"),
    "remote_shell_read": DeprecatedTool("shell_read"),
    "remote_shell_kill": DeprecatedTool("shell_stop"),
    "remote_shell_list": DeprecatedTool("shell_list"),
    "remote_job_start": DeprecatedTool("job_start"),
    "remote_job_list": DeprecatedTool("job_list"),
    "remote_job_tail": DeprecatedTool("job_tail"),
    "remote_job_stop": DeprecatedTool("job_stop"),
    "remote_job_retry": DeprecatedTool("job_retry"),
    "remote_list_files": DeprecatedTool("file_list"),
    "remote_tree_view": DeprecatedTool("file_tree"),
    "remote_glob_search": DeprecatedTool("file_glob"),
    "remote_grep_search": DeprecatedTool("file_grep"),
    "remote_read_file": DeprecatedTool("file_read"),
    "remote_read_many_files": DeprecatedTool("file_read"),
    "remote_write_file": DeprecatedTool("file_write"),
    "remote_edit_file": DeprecatedTool("file_edit"),
    "remote_multi_edit_file": DeprecatedTool("file_edit"),
    "remote_delete_file_or_dir": DeprecatedTool("file_delete"),
    "remote_apply_patch": DeprecatedTool("file_patch"),
    "remote_copy_file": DeprecatedTool("remote_transfer"),
    "remote_copy_dir": DeprecatedTool("remote_transfer"),
    "remote_pull_file": DeprecatedTool("remote_transfer"),
    "remote_push_file": DeprecatedTool("remote_transfer"),
    "remote_pull_dir": DeprecatedTool("remote_transfer"),
    "remote_push_dir": DeprecatedTool("remote_transfer"),
    "remote_git_clone_tool": DeprecatedTool("run_shell"),
    "remote_git_status_tool": DeprecatedTool("run_shell"),
    "remote_git_diff_tool": DeprecatedTool("run_shell"),
    "remote_git_log_tool": DeprecatedTool("run_shell"),
    "remote_git_checkout_tool": DeprecatedTool("run_shell"),
    "remote_git_fetch_tool": DeprecatedTool("run_shell"),
    "remote_git_pull_tool": DeprecatedTool("run_shell"),
    "remote_git_add_tool": DeprecatedTool("run_shell"),
    "remote_git_commit_tool": DeprecatedTool("run_shell"),
    "remote_git_push_tool": DeprecatedTool("run_shell"),
    "remote_git_show_tool": DeprecatedTool("run_shell"),
    "remote_git_reset_tool": DeprecatedTool("run_shell"),
    "remote_playwright_install_tool": DeprecatedTool("run_shell"),
    "remote_browser_screenshot_tool": DeprecatedTool("browser_capture_tool"),
    "remote_browser_get_text_tool": DeprecatedTool("browser_get_text_tool"),
    "remote_browser_eval_tool": DeprecatedTool("browser_run_script"),
    "remote_browser_pdf_tool": DeprecatedTool("browser_capture_tool"),
    "remote_playwright_run_script_tool": DeprecatedTool("browser_run_script"),
    "search": DeprecatedTool("file_grep", removed_in="3.2.1"),
    "fetch": DeprecatedTool("file_read", removed_in="3.2.1"),
    "environment_info": DeprecatedTool("environment_get", removed_in="3.2.1"),
    "skills_list": DeprecatedTool("skill_list", removed_in="3.2.1"),
    "skill_read_file": DeprecatedTool("skill_read", removed_in="3.2.1"),
    "run_shell_tool": DeprecatedTool("run_shell", removed_in="3.2.1"),
    "run_python_tool": DeprecatedTool("run_python", removed_in="3.2.1"),
    "shell_kill": DeprecatedTool("shell_stop", removed_in="3.2.1"),
    "list_files": DeprecatedTool("file_list", removed_in="3.2.1"),
    "tree_view": DeprecatedTool("file_tree", removed_in="3.2.1"),
    "glob_search": DeprecatedTool("file_glob", removed_in="3.2.1"),
    "grep_search": DeprecatedTool("file_grep", removed_in="3.2.1"),
    "read_file": DeprecatedTool("file_read", removed_in="3.2.1"),
    "view_image": DeprecatedTool("image_view", removed_in="3.2.1"),
    "create_file_link": DeprecatedTool("link_create", removed_in="3.2.1"),
    "list_file_links": DeprecatedTool("link_list", removed_in="3.2.1"),
    "revoke_file_link": DeprecatedTool("link_revoke", removed_in="3.2.1"),
    "write_file": DeprecatedTool("file_write", removed_in="3.2.1"),
    "edit_file": DeprecatedTool("file_edit", removed_in="3.2.1"),
    "delete_file_or_dir": DeprecatedTool("file_delete", removed_in="3.2.1"),
    "apply_patch": DeprecatedTool("file_patch", removed_in="3.2.1"),
    "transfer_path": DeprecatedTool("remote_transfer", removed_in="3.2.1"),
    "playwright_run_script_tool": DeprecatedTool("browser_run_script", removed_in="3.2.1"),
    "remote_invite": DeprecatedTool("remote_manage", removed_in="3.2.1"),
    "remote_list_machines": DeprecatedTool("remote_manage", removed_in="3.2.1"),
    "remote_revoke_machine": DeprecatedTool("remote_manage", removed_in="3.2.1"),
    "remote_rename_machine": DeprecatedTool("remote_manage", removed_in="3.2.1"),
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
