<!-- i18n-source-sha256: d3c380d9a5d9a43019b0be2b5e9accc0d6e0c785d77226005db60c5721672ba6 -->
# Remote workers

Remote worker cho phép `local-shell-mcp` điều khiển các máy có thể gửi yêu cầu HTTP(S) đi ra nhưng không thể nhận kết nối SSH đi vào.

```text
MCP client -> control server -> outbound polling worker -> remote machine
```

## Workflow cơ bản

1. Tạo lời mời bằng `remote_manage(action="invite", ...)`.
2. Chạy lệnh được tạo trên máy từ xa.
3. Xác nhận đăng ký bằng `remote_manage(action="list")`.
4. Gọi tool thông thường với `machine="<worker-name>"`, ví dụ `environment_get`, `run_shell`, `file_read` hoặc `browser_run_script`.
5. Dùng `remote_transfer` để bắt đầu transfer tệp/thư mục được theo dõi controller-to-worker, worker-to-controller hoặc worker-to-worker. Theo dõi bằng `job_list` hoặc `job_tail`; dừng hoặc thử lại bằng `job_stop` hoặc `job_retry`.
6. Đổi tên hoặc thu hồi worker bằng `remote_manage(action="rename", ...)` hoặc `remote_manage(action="revoke", ...)`.

Theo mặc định, mỗi lời mời đăng ký một worker (`max_uses=1`). Tăng `max_uses` để đăng ký nhiều worker bằng cùng một lời mời. Để trống `name` khi dùng lời mời nhiều lần. Tham số tùy chọn `ttl_s` mặc định là hai giờ (7200 giây) và tối đa là bảy ngày (604800 giây).

Chỉ phần quản trị worker dùng tên `remote_*`. Các thao tác execution, shell, job, filesystem, patch và browser dùng cùng schema ở local và remote. Khi truyền machine còn cần OAuth scope `remote:use`.

## Worker bền vững

Kết quả lời mời chứa các lệnh theo nền tảng:

- `persistent_command` cài và khởi động user service trên Linux hoặc macOS.
- `powershell_persistent_command` cài và khởi động Windows user task từ PowerShell.

Trên Windows, `local-shell-mcp worker install-service` đăng ký task `local-shell-mcp-worker` cho người dùng hiện tại. Nó khởi động ngay, khởi động lại khi người dùng đó đăng nhập sau reboot, cho phép chạy bằng pin, bỏ qua start trùng và thử lại các lần chạy thất bại. Không cần quyền administrator và không chạy trước khi người dùng đăng nhập.

Dùng cùng lifecycle commands trên mọi nền tảng:

```text
local-shell-mcp worker status
local-shell-mcp worker start
local-shell-mcp worker stop
local-shell-mcp worker restart
local-shell-mcp worker uninstall-service
```

Worker log được lưu trong worker state directory với tên `worker.log`.

## Khả năng

Worker hỗ trợ shell/persistent shell sessions, tracked jobs, thao tác filesystem, transfer internals, thực thi Python, patches và Playwright khi đã cài dependencies. Git dùng lệnh chuẩn qua `run_shell(machine=...)`.

## Bảo mật và phiên bản

Worker đã tham gia cho MCP client quyền điều khiển môi trường được cấu hình. Hãy dùng invite TTL ngắn, work directory hoặc account riêng, xem audit log và thu hồi worker sau tác vụ. Lời mời được tạo sẽ cài worker code khớp phiên bản control server.

## Xử lý sự cố

Nếu worker không xuất hiện, hãy kiểm tra outbound HTTPS access, khả năng truy cập public base URL, invite expiry, system time và log của control server.
