# 도구 참조

이 페이지는 현지화된 도구 참조 개요입니다. 도구 이름과 매개변수 이름은 MCP schema, 감사 로그, Runtime 반환값과 맞추기 위해 코드 식별자로 유지합니다. 전체 필드 세부 사항은 영어 참조와 Runtime이 내보내는 tools JSON을 기준으로 합니다.

## 도구 그룹

### Connector / discovery

`search`, `fetch`

### Environment / audit / task state

`environment_info`, `version_info`, `audit_tail`, `todo_read_tool`, `todo_write_tool`, `secret_scan`

### Skills

`skills_list`, `skill_load`, `skill_read_file`

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

## 사용 지침

먼저 읽기 전용 도구로 맥락을 확인한 뒤 쓰기, shell, Git, 원격 도구를 사용합니다. 위험한 호출에는 감사가 쉽도록 purpose 또는 explanation을 채웁니다.
