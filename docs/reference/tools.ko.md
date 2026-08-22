# 도구 참조

이 페이지는 현지화된 도구 참조 개요입니다. 도구 이름과 매개변수 이름은 MCP schema, 감사 로그, Runtime 반환값과 맞추기 위해 코드 식별자로 유지합니다. 전체 필드 세부 사항은 영어 참조와 Runtime이 내보내는 tools JSON을 기준으로 합니다.

## 도구 그룹

### Connector / discovery

`search`, `fetch`

### Environment / audit / task state

`environment_get`, `audit_tail`, `todo_read_tool`, `todo_write_tool`, `secret_scan`

### Skills

`skill_list`, `skill_load`, `skill_read`

### Filesystem

`file_list`, `file_read`, `file_write`, `file_edit`, `file_delete`, `remote_transfer`, `file_tree`, `file_glob`, `file_grep`

### Shell and jobs

`run_shell`, `run_python`, `shell_start`, `shell_read`, `shell_send`, `shell_stop`, `shell_list`, `job_start`, `job_list`, `job_tail`, `job_stop`, `job_retry`

### Browser automation

`browser_get_text_tool`, `browser_capture_tool`, `browser_run_script`

### File links

`link_create`, `link_list`, `link_revoke`

### Remote workers

`remote_manage` (`invite`, `list`, `rename`, `revoke`); normal tools use optional `machine`, and `remote_transfer` handles transfers

## 사용 지침

먼저 읽기 전용 도구로 맥락을 확인한 뒤 쓰기, shell, Git, 원격 도구를 사용합니다. 위험한 호출에는 감사가 쉽도록 purpose 또는 explanation을 채웁니다.
