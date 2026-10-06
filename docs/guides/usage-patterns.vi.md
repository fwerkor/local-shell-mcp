<!-- i18n-source-sha256: 382c9edbbba8fa4fb3aab11dcc4127ba80bff8c7104bdedffdf66b9bbcdb744a -->
# Mẫu sử dụng và hướng dẫn prompting

`local-shell-mcp` cung cấp tools mạnh. Kết quả tốt phụ thuộc vào việc yêu cầu model kiểm tra trước, hành động theo bước nhỏ, chạy xác minh và báo cáo thay đổi.

## Vòng vận hành chung

Dùng vòng này cho phần lớn coding task:

1. Inspect: `environment_get`, `file_tree`, `file_grep`, `file_read` và `run_shell` cho command như `git status`.
2. Plan: yêu cầu model xác định tối thiểu files và tests liên quan.
3. Edit: dùng `file_edit`, `file_patch` hoặc shell commands.
4. Verify: chạy targeted tests/builds bằng `run_shell` hoặc persistent shells.
5. Review: chạy `git diff` qua `run_shell`, sau đó dùng `secret_scan` và `audit_tail` khi cần.
6. Commit/export: dùng explicit Git CLI commands qua `run_shell` hoặc `link_create`.

## Chọn tool

| Task | Ưu tiên | Tránh |
|---|---|---|
| One-shot command ngắn | `run_shell` | Khởi động persistent shell cho mọi command |
| Dev server, REPL hoặc watch task dài | `shell_start` + `shell_read` + `shell_send` | Block `run_shell` đến timeout |
| Structured analysis hoặc file generation | `run_python` | Shell pipeline mong manh cho JSON/text phức tạp |
| Edit exact nhỏ | `file_edit` | Viết lại cả file không cần thiết |
| Một hoặc nhiều replacement trong một file | `file_edit` with an `edits` array | Lặp stale edit mà không đọc lại |
| Multi-file patch | `file_patch` | Ad hoc shell edit |
| Tìm file | `file_tree`, `file_glob` | Recursive listing toàn bộ repository lớn |
| Tìm code | `file_grep` | Đọc nhiều file không định hướng |
| Browser evidence | `browser_snapshot`, `browser_run_script` | Đoán từ tên page/route |
| Downloadable artifacts | `link_create` | Dán binary content lớn vào chat |
| Remote machine work | normal tools with `machine`, plus `remote_transfer` | Mở inbound SSH khi outbound worker đã đủ |

## Gọi công cụ từ CLI

Đối với shell script và CI, `lsm call <tool>` gọi cùng bề mặt công cụ đã đăng ký thông qua loopback controller đang chạy, vì vậy remote worker và trạng thái controller được giữ nguyên.

```bash
lsm call run_shell --json '{"command":"uname -a"}'
printf '%s\n' '{"path":"README.md"}' | lsm call file_read
```

Dùng `--session s_...` để gắn lời gọi với Logical Session. Trong cấu hình Docker Compose được tài liệu hóa, `LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN` gốc chỉ nằm trong `.env` thuộc sở hữu host với quyền truy cập hạn chế, còn Compose chỉ truyền bộ xác minh SHA-256 vào controller; các bố cục runtime tách biệt khác có thể dùng `--token-file <path>`. `--direct` bỏ qua controller, áp dụng các thiết lập runtime của `.env` hiện tại ngay trong tiến trình, không đưa host CLI token vào môi trường của công cụ và chỉ hỗ trợ lời gọi cục bộ. Human UI token không bao giờ được `/mcp` chấp nhận; controller trong cấu hình runtime tách biệt phải đặt `LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN_SHA256` tương ứng.

## Template prompt

### Read-only repository orientation

```text
Dùng local-shell-mcp. Kiểm tra layout repository và git status. Không sửa file. Tóm tắt các component chính, test command có thể suy ra và risk rõ ràng trước khi thay đổi.
```

### Focused bug fix

```text
Dùng local-shell-mcp để sửa bug. Trước hết reproduce hoặc locate bằng relevant command nhỏ nhất. Đọc file trước khi edit. Tạo minimal patch, chạy targeted verification, sau đó hiển thị git diff và chính xác các tests đã chạy. Không commit cho tới khi tôi chấp thuận.
```

### Workflow commit và push

```text
Dùng local-shell-mcp. Kiểm tra git status và diff, chạy relevant tests và secret_scan, tạo một focused commit với message ngắn, rồi push current branch. Không bao gồm cache, build artifacts hoặc unrelated formatting.
```

### Long-running process

```text
Khởi động dev server trong persistent shell session, đọc output đến khi ready, rồi dùng browser tools để xác minh page. Giữ session id và kill session sau khi xác minh.
```

### Remote worker task

```text
Dùng remote worker đã kết nối tên <machine>. Trước tiên gọi environment_get với machine=<machine>, sau đó file_list với cùng machine. Chỉ làm việc trong configured remote workdir. Dùng run_shell cho command ngắn và shell_start hoặc job_start cho công việc dài.
```

## Làm việc với repositories

Sequence khuyến nghị cho thay đổi open-source:

1. Chạy `git status --short --branch` qua `run_shell`.
2. Fetch và inspect branches bằng explicit Git CLI khi upstream state quan trọng.
3. Dùng `file_grep` và `file_read` trước edit.
4. Tạo minimal patch.
5. Chạy targeted tests trước, rồi broader tests khi phù hợp.
6. Chạy `secret_scan` trước commit hoặc push.
7. Stage và commit rõ ràng với message ngắn.

Yêu cầu một commit cho mỗi logical change khi maintainer cần history dễ review.

## Làm việc với generated artifacts

Với PDF, report, screenshot, archive hoặc log:

1. Generate file trong workspace.
2. Xác minh file tồn tại và có size đúng.
3. Dùng `link_create` với TTL ngắn và optional `max_downloads`.
4. Revoke link khi không còn cần.

Không tạo public link cho private key, credential directory hoặc unrelated personal data.

## Làm việc với remote machines

Remote worker mode hữu ích khi machine có thể gửi outbound HTTPS nhưng không nhận inbound SSH.

Thực hành tốt:

- Tạo hoặc rename machine bằng `remote_manage(action="invite", ...)` hoặc `remote_manage(action="rename", ...)`.
- Gọi `environment_get(machine=...)` trước khi hành động.
- Dùng `remote_transfer` để khởi động controller/worker hoặc worker/worker transfer jobs rồi quản lý bằng normal `job_*` tools.
- Revoke worker sau task bằng `remote_manage(action="revoke", ...)`.

## Anti-patterns

Tránh các chỉ dẫn sau trừ khi environment disposable và đã hiểu hậu quả:

- “Install global bất cứ thứ gì cần” trên host-launched server.
- “Chạy cho đến khi hoạt động” mà không có time bound hoặc verification criteria.
- “Commit tất cả” trong repository có generated artifacts.
- “Expose toàn bộ home directory” cho tiện.
- “Tạo file link cho toàn workspace”.
- Chạy public deployment với `LOCAL_SHELL_MCP_AUTH_MODE=none`.
