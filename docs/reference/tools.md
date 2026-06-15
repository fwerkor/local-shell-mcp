# Tools reference

Tool availability depends on MCP client mode and server configuration. Normal tools operate under `LOCAL_SHELL_MCP_WORKSPACE_ROOT` unless full-container mode is enabled. Remote tools perform the same class of operation on a connected remote worker and add a `machine` argument.

## Core categories

- Connector read tools: `search`, `fetch`.
- Environment and safety: `environment_info`, `secret_scan`, `audit_tail`.
- Shell and Python: `run_shell_tool`, `run_python_tool`, `shell_start`, `shell_send`, `shell_read`, `shell_kill`, `shell_list`.
- Filesystem and search: `list_files`, `tree_view`, `glob_search`, `grep_search`, `read_file`, `read_many_files`, `write_file`, `edit_file`, `multi_edit_file`, `delete_file_or_dir`, `apply_patch`.
- Download links: `create_file_link`, `list_file_links`, `revoke_file_link`.
- Git: `git_status_tool`, `git_diff_tool`, `git_log_tool`, `git_add_tool`, `git_commit_tool`, `git_push_tool`, and related checkout/fetch/pull/show/reset/clone tools.
- Browser: Playwright install, screenshot, text extraction, JS evaluation, PDF, and full script tools.
- Remote workers: `remote_invite`, `remote_list_machines`, remote shell/filesystem/search/git/browser tools, and remote file/directory transfer tools.
