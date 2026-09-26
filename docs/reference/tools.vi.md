<!-- i18n-source-sha256: 13df63c51bc29aa49ae386e7c96e1f729d23914343856b4d20f8776ca0a2acda -->
# Tham chiếu tools

Page này được xây từ MCP tool schemas thực tế. Chạy `python scripts/generate-tools-reference.py` sau khi thay đổi public tool surface để cập nhật English reference.

Phần lớn tool trả về `ToolResult` có cấu trúc gồm `ok`, `message` và `data`. `workspace_open` trả về state mà model nhìn thấy để render MCP App. Hầu hết tool thực thi và file nhận `machine` tùy chọn; bỏ qua để dùng workspace của controller và chỉ định để dùng worker đã kết nối. Các thao tác Git chủ ý dùng `run_shell` hoặc tool shell khác thay vì wrapper Git riêng.

## Hướng dẫn lựa chọn

| Nhu cầu | Tools ưu tiên |
|---|---|
| Theo dõi hoặc cộng tác với execution trong ChatGPT | `workspace_open` |
| Inspect environment | `environment_get`, `file_tree`, `file_read` |
| Chạy command ngắn hoặc Git operation | `run_shell` |
| Chạy task interactive hoặc dài | `shell_start` or `job_start` |
| Thay đổi file chính xác | `file_edit` or `file_patch` |
| Transfer file hoặc directory | `remote_transfer` |
| Discover external MCP capability | `mcp_tool_search`, then `mcp_tool_inspect` |
| Tương tác với page | `browser_session`, `browser_snapshot`, then `browser_act` |
| Chạy custom browser logic | `browser_run_script` |
| Control a native desktop app | `gui_list`, `gui_state`, then `gui_action` |
| Làm việc trên remote machine | dùng cùng tool với `machine`; chỉ dùng `remote_*` cho worker administration |

## Interactive workspace

### `workspace_open`

Mở hoặc tái sử dụng Live Workspace hiển thị Logical Session được chỉ định rõ ràng. Truyền session_id đang hoạt động do session_manage trả về. Workspace không bao giờ suy ra danh tính task từ MCP transport; hãy truyền null rõ ràng khi không có Logical Session hoạt động.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string \| null` | required |  |
| `machine` | `string \| null` | `null` |  |
| `cwd` | `string` | `"."` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

## Environment, Skills và task state

### `environment_get`

Trả về version, workspace, auth, policy và environment information local hoặc trên remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

### `skill_list`

Liệt kê installed Agent Skills mà không load instructions. MCP tool surface giữ cố định; thêm hoặc xóa Skill directories được phản ánh ở call tiếp theo.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_load`

Load installed Skill bằng exact name do `skill_list` trả về. Trả về instructions đầy đủ `SKILL.md` và related file paths.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_read`

Đọc một related text file của installed Skill.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `path` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `secret_scan`

Scan local workspace text files để tìm common secrets trước commit hoặc push.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `max_results` | `integer` | `200` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `session_manage`

Quản lý một Logical Session bền vững. start tạo task mới và trả về session_id của nó. resume chỉ tiếp tục session_id được người dùng cung cấp rõ ràng hoặc đã có trong conversation này. Mọi action ngoài start đều yêu cầu session_id. Action: start, resume, get, report, finish, cancel, delete. report nhận summary/findings/next/blockers/objective/label; delete yêu cầu Session ở trạng thái terminal.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `session_id` | `string \| null` | `null` |  |
| `label` | `string \| null` | `null` |  |
| `objective` | `string \| null` | `null` |  |
| `summary` | `string \| null` | `null` |  |
| `findings` | `array[string] \| null` | `null` |  |
| `next` | `string \| null` | `null` |  |
| `blockers` | `array[string] \| null` | `null` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `plan_manage`

Quản lý Goal mode tùy chọn cho Logical Session được chỉ định rõ ràng. Plan đang active bật automatic continuation sau 15 phút không có agent activity, tối đa 10 lần. session_id phải là cùng durable id do session_manage trả về. Action: start, get, update, block, resume, finish, cancel. start yêu cầu objective và steps; finish yêu cầu mọi steps đều completed hoặc skipped.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `session_id` | `string` | required |  |
| `objective` | `string \| null` | `null` |  |
| `steps` | `array[object] \| null` | `null` |  |
| `step_id` | `string \| null` | `null` |  |
| `status` | `string \| null` | `null` |  |
| `text` | `string \| null` | `null` |  |
| `note` | `string \| null` | `null` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `audit_tail`

Đọc recent local audit log entries.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `lines` | `integer` | `100` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Shells và jobs

### `run_shell`

Chạy một non-interactive shell command local hoặc trên remote machine. Dùng cho build, test, package-manager, Git và inspection commands cần hoàn thành nhanh. Với process long-running, interactive hoặc streaming, dùng `shell_start` hoặc `job_start`. Optional purpose/explanation fields cho phép nêu lý do chạy command.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `max_output_bytes` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

### `run_python`

Viết và chạy short Python script local hoặc trên remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `code` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

### `shell_start`

Khởi động persistent interactive shell local hoặc trên remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `command` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

### `shell_send`

Gửi input tới persistent local/remote shell session.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `input_text` | `string` | required |  |
| `enter` | `boolean` | `true` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

### `shell_read`

Đọc recent output của persistent local/remote shell session.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

### `shell_stop`

Kết thúc persistent local/remote shell session.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

### `shell_list`

Liệt kê persistent shell sessions local hoặc trên remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

### `job_start`

Khởi động tracked long-running job local hoặc trên remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

### `job_list`

Liệt kê tracked jobs local hoặc trên remote machine. Các job đang hoạt động được trả về trước; `limit` được giới hạn trong khoảng 1-1000.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `include_finished` | `boolean` | `true` |  |
| `limit` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

### `job_tail`

Đọc recent output của tracked local/remote job.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

### `job_stop`

Dừng tracked local/remote job.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

### `job_retry`

Khởi động lại stopped/exited tracked local/remote job.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

## Files và transfer

### `file_list`

Liệt kê files và directories local hoặc trên remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | `"."` |  |
| `recursive` | `boolean` | `false` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

### `file_tree`

Trả về compact directory tree local hoặc trên remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `depth` | `integer` | `3` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

### `file_glob`

Tìm paths theo glob local hoặc trên remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `pattern` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `max_results` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

### `file_grep`

Tìm trong file contents local hoặc trên remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `query` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `regex` | `boolean` | `true` |  |
| `case_sensitive` | `boolean` | `true` |  |
| `max_results` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

### `file_read`

Đọc một file hoặc list files local hoặc trên remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string \| array[string]` | required |  |
| `start_line` | `integer \| null` | `null` |  |
| `end_line` | `integer \| null` | `null` |  |
| `binary_preview` | `string \| null` | `null` |  |
| `binary_preview_bytes` | `integer` | `256` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

### `image_view`

Hiển thị PNG, JPEG, GIF hoặc WebP dưới dạng native MCP image content local hoặc trên remote machine. Dùng thay `file_read` khi cần visual inspection. Remote images reuse file-transfer protocol hiện có nên worker không cần image-specific RPC.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

### `file_write`

Ghi UTF-8 text file local hoặc trên remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `content` | `string` | required |  |
| `overwrite` | `boolean` | `true` |  |
| `encoding` | `string` | `"utf-8"` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

### `file_edit`

Áp dụng một hoặc nhiều exact-text edits cho local/remote file. Mỗi edit có old, new và optional `replace_all`; old phải exact match kể cả whitespace và indentation.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `edits` | `array[TextEdit]` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

### `file_delete`

Xóa local/remote file hoặc directory. `recursive=false` xóa files hoặc empty directories; non-empty directories cần `recursive=true` và phải dùng cẩn thận.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `recursive` | `boolean` | `false` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

### `file_patch`

Kiểm tra và áp dụng unified diff hoặc file_patch envelope local hoặc remote.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `patch` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

### `remote_transfer`

Khởi chạy tracked job để copy file hoặc directory giữa controller và remote machine. Remote upload dùng chunk raw-binary có thể resume; quản lý transfer bằng `job_list`, `job_tail`, `job_stop` và `job_retry`.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `source_path` | `string` | required |  |
| `destination_path` | `string` | required |  |
| `source_machine` | `string \| null` | `null` |  |
| `destination_machine` | `string \| null` | `null` |  |
| `overwrite` | `boolean` | `false` |  |
| `chunk_size` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Phải cung cấp ít nhất một trong `source_machine` và `destination_machine`. Endpoint bị bỏ qua nghĩa là workspace của controller; source có thể là file hoặc directory.

### `link_create`

Tạo temporary browser-accessible URL cho local file. Default response là attachment download; set `inline=true` để render trực tiếp trong browser hoặc Markdown image. Links là public bearer URLs được bảo vệ bởi high-entropy token, TTL, optional download-count limit và explicit revocation.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `filename` | `string \| null` | `null` |  |
| `max_downloads` | `integer \| null` | `null` |  |
| `inline` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_list`

Liệt kê generated local file download URLs.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `include_expired` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_revoke`

Revoke generated local file download URL.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `token` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Dynamic MCP gateway

### `mcp_manage`

Register, list, get, enable, disable, refresh, remove hoặc update isolated environment/headers của dynamic MCP servers. Dùng transport `stdio` với command/args/cwd hoặc `streamable_http` với url. Secret env/header values được persist riêng tư và không bao giờ trả về.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `name` | `string \| null` | `null` |  |
| `transport` | `string \| null` | `null` |  |
| `command` | `string \| null` | `null` |  |
| `args` | `array[string] \| null` | `null` |  |
| `cwd` | `string \| null` | `null` |  |
| `url` | `string \| null` | `null` |  |
| `env` | `object \| null` | `null` |  |
| `headers` | `object \| null` | `null` |  |
| `enabled` | `boolean` | `true` |  |
| `overwrite` | `boolean` | `false` |  |
| `refresh` | `boolean` | `true` |  |
| `key` | `string \| null` | `null` |  |
| `value` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_search`

Tìm cached lightweight tool summaries từ enabled dynamic MCP servers. Dynamic tools không vào `tools/list` của server này; dùng returned `<server>:<tool>` name với `mcp_tool_inspect` trước khi call.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `query` | `string` | `""` |  |
| `server` | `string \| null` | `null` |  |
| `limit` | `integer` | `20` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_inspect`

Trả về full cached schema của dynamic MCP tool tên `<server>:<tool>`. Refresh server bằng `mcp_manage` nếu cache stale.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_call`

Call cached dynamic MCP tool tên `<server>:<tool>`. Discover bằng `mcp_tool_search` và inspect schema bằng `mcp_tool_inspect` trước. External MCP connections chỉ mở trong thời gian call.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `arguments` | `object \| null` | `null` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Browser automation

### `browser_session`

Start, list, close hoặc cleanup persistent high-level browser sessions local hoặc remote. `start` có thể open URL, reuse persistent `profile_id` hoặc load `storage_state_path`; `close` có thể save storage state.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `session_id` | `string \| null` | `null` |  |
| `browser` | `string` | `"chromium"` |  |
| `headless` | `boolean` | `true` |  |
| `width` | `integer` | `1440` |  |
| `height` | `integer` | `1000` |  |
| `url` | `string \| null` | `null` |  |
| `wait_until` | `string` | `"domcontentloaded"` |  |
| `profile_id` | `string \| null` | `null` |  |
| `storage_state_path` | `string \| null` | `null` |  |
| `save_storage_state_path` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

### `browser_snapshot`

Capture persistent browser page: title, URL, bounded visible text, interactive elements có stable short refs như `e1`, recent page/network errors và optional screenshot path. Dùng refs trực tiếp làm `browser_act` targets cho tới khi page navigate hoặc có snapshot mới.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `include_text` | `boolean` | `true` |  |
| `screenshot` | `boolean` | `true` |  |
| `full_page` | `boolean` | `false` |  |
| `max_text_chars` | `integer` | `100000` |  |
| `max_elements` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

### `browser_act`

Chạy structured actions trong persistent browser session. Hỗ trợ navigate, new_page, close_page, click, fill, type, select, press, check, uncheck, hover, wait, wait_for_text và wait_for_url. `target` có thể là `browser_snapshot` ref như `e1` hoặc CSS selector. Chỉ dùng `browser_run_script` khi high-level actions không đủ.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `actions` | `array[object]` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `timeout_ms` | `integer` | `30000` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

### `browser_run_script`

Chạy full Python Playwright script local hoặc trên remote machine.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `script` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.

## Tự động hóa GUI máy tính

### `gui_list`

List visible desktop application windows and GUI backend capabilities locally or remotely.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session for this tool call. Pass the session_id returned by session_manage while working in that task. Use null only when no Logical Session is active. This is the same durable session_id used by session_manage. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `gui_state`

Observe one desktop window before acting. Returns its accessibility elements plus an optional native MCP screenshot and a short-lived state_id. Prefer element_id actions; coordinate actions are relative to the observed window and are rejected if the window moved or resized.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `window_id` | `string` | required |  |
| `screenshot` | `boolean` | `true` |  |
| `include_elements` | `boolean` | `true` |  |
| `max_elements` | `integer` | `300` |  |
| `max_depth` | `integer` | `12` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session for this tool call. Pass the session_id returned by session_manage while working in that task. Use null only when no Logical Session is active. This is the same durable session_id used by session_manage. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `gui_action`

Execute GUI actions against a fresh gui_state observation locally or remotely. The state_id is single-use. Prefer semantic element_id targeting; raw x/y coordinates are window-relative. Supported actions are click, double_click, right_click, move, scroll, drag, type, key, set_value, focus, and wait.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `window_id` | `string` | required |  |
| `state_id` | `string` | required |  |
| `actions` | `array[GuiAction]` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session for this tool call. Pass the session_id returned by session_manage while working in that task. Use null only when no Logical Session is active. This is the same durable session_id used by session_manage. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

## Remote worker administration

### `remote_manage`

Quản lý remote workers bằng action=invite, list, revoke hoặc rename. invite nhận name/workdir/ttl_s; revoke cần machine; rename cần machine và new_name.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `name` | `string \| null` | `null` |  |
| `workdir` | `string \| null` | `null` |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `new_name` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session cho lần gọi tool này. Khi làm việc trên task, truyền session_id do session_manage trả về. Chỉ dùng null khi không có Logical Session hoạt động. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

Khi cung cấp `machine`, call cũng cần `remote:use` và chạy qua giao thức remote worker.
