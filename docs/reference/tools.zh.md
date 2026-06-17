# 工具参考

本页是本地化的工具参考总览。工具名和参数名保持代码标识符，便于与 MCP schema、审计日志和运行时返回值对应。完整字段细节以英文参考页和运行时导出的 tools JSON 为准。

## 工具分组

### Connector / discovery

`search`, `fetch`

### Environment / audit / task state

`environment_info`, `version_info`, `audit_tail`, `todo_read_tool`, `todo_write_tool`, `secret_scan`

### Filesystem

`list_files`, `read_file`, `read_many_files`, `write_file`, `edit_file`, `multi_edit_file`, `delete_file_or_dir`, `tree_view`, `glob_search`, `grep_search`

### Shell and jobs

`run_shell_tool`, `run_python_tool`, `shell_start`, `shell_read`, `shell_send`, `shell_kill`, `shell_list`, `job_start`, `job_list`, `job_tail`, `job_stop`, `job_retry`

### Git

`git_status_tool`, `git_diff_tool`, `git_add_tool`, `git_commit_tool`, `git_push_tool`, `git_pull_tool`, `git_fetch_tool`, `git_checkout_tool`, `git_log_tool`, `git_show_tool`, `git_reset_tool`

### Browser automation

`browser_get_text_tool`, `browser_eval_tool`, `browser_screenshot_tool`, `browser_pdf_tool`, `playwright_run_script_tool`, `playwright_install_tool`

### File links

`create_file_link`, `list_file_links`, `revoke_file_link`

### Remote workers

`remote_list_machines`, `remote_invite`, `remote_environment_info`, `remote_run_shell_tool`, `remote_run_python_tool`, `remote_shell_start`, `remote_shell_read`, `remote_shell_send`, `remote_shell_kill`, `remote_shell_list`, `remote_job_start`, `remote_job_list`, `remote_job_tail`, `remote_job_stop`, `remote_job_retry`, `remote_read_file`, `remote_write_file`, `remote_push_file`, `remote_pull_file`, `remote_copy_file`

## 使用建议

先用只读工具确认上下文，再使用写入、shell、Git 或远程工具；对有风险的调用填写 purpose 或 explanation，便于审计。
