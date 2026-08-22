# Tham chiếu công cụ

Trang này là phần tổng quan công cụ đã bản địa hóa. Tên công cụ và tham số vẫn là định danh mã để khớp với MCP schema, nhật ký audit và giá trị trả về của Runtime. Chi tiết đầy đủ của các field nằm trong trang tham chiếu tiếng Anh và tools JSON do Runtime xuất ra.

## Nhóm công cụ

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

## Gợi ý sử dụng

Trước hết xác nhận ngữ cảnh bằng công cụ chỉ đọc, sau đó mới dùng công cụ ghi, shell, Git hoặc công cụ từ xa. Với lời gọi rủi ro hơn, hãy điền purpose hoặc explanation để dễ audit.
