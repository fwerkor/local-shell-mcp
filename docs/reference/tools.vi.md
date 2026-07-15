# Tham chiếu công cụ

Trang này là phần tổng quan công cụ đã bản địa hóa. Tên công cụ và tham số vẫn là định danh mã để khớp với MCP schema, nhật ký audit và giá trị trả về của Runtime. Chi tiết đầy đủ của các field nằm trong trang tham chiếu tiếng Anh và tools JSON do Runtime xuất ra.

## Nhóm công cụ

### Connector / discovery

`search`, `fetch`

### Environment / audit / task state

`environment_info`, `audit_tail`, `todo_read_tool`, `todo_write_tool`, `secret_scan`

### Skills

`skills_list`, `skill_load`, `skill_read_file`

### Filesystem

`list_files`, `read_file`, `write_file`, `edit_file`, `delete_file_or_dir`, `transfer_path`, `tree_view`, `glob_search`, `grep_search`

### Shell and jobs

`run_shell_tool`, `run_python_tool`, `shell_start`, `shell_read`, `shell_send`, `shell_kill`, `shell_list`, `job_start`, `job_list`, `job_tail`, `job_stop`, `job_retry`

### Browser automation

`browser_get_text_tool`, `browser_capture_tool`, `playwright_run_script_tool`

### File links

`create_file_link`, `list_file_links`, `revoke_file_link`

### Remote workers

`remote_invite`, `remote_list_machines`, `remote_rename_machine`, `remote_revoke_machine`; normal tools use optional `machine`, and `transfer_path` handles transfers

## Gợi ý sử dụng

Trước hết xác nhận ngữ cảnh bằng công cụ chỉ đọc, sau đó mới dùng công cụ ghi, shell, Git hoặc công cụ từ xa. Với lời gọi rủi ro hơn, hãy điền purpose hoặc explanation để dễ audit.
