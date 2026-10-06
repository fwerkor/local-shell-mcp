<!-- i18n-source-sha256: 5f07217e742810704f1919224f6cf68bf7b4f5ecf635fadd5ec4d21b072ce6b2 -->
# Giao diện người dùng

`local-shell-mcp` cung cấp hai human interface tương thích trên cùng service API, workspace, persistent terminal registry, remote-worker registry và MCP audit log:

- **Web UI** là bảng điều khiển trình duyệt native được tối ưu cho việc kiểm tra vận hành nhanh.
- **OpenTUI** là ứng dụng hướng terminal đầy đủ và vẫn dùng được cả trong trình duyệt lẫn dưới dạng lệnh terminal native.

Không mode nào tạo control plane riêng. Chuyển interface không thay đổi machine đã kết nối, Sessions, jobs, permission hay audit data.

## Khởi động dịch vụ

Khởi động `local-shell-mcp` như bình thường:

```bash
local-shell-mcp --mode mcp
```

## ChatGPT Live Workspace

Khi ChatGPT hiển thị MCP Apps, `workspace_open(session_id=...)` mở một khung cộng tác nổi cho **Logical Session được chọn rõ ràng**. Session giữ state task bền vững—objective, progress, Plan và Activity—còn Live Workspace chỉ hiển thị state đó, hoạt động trực tiếp và các điều khiển của con người. Nó không bao giờ suy ra danh tính task từ MCP transport.

Một handoff rõ ràng điển hình:

```text
session_manage(action="start", objective=...)
        -> session_id
... gọi tool với logical_session_id=session_id
... session_manage(action="report", session_id=...) ...
cuộc trò chuyện ChatGPT mới
người dùng truyền session_id trước đó
session_manage(action="resume", session_id=...)
        -> progress, Plan và Activity gần đây đã có
workspace_open(session_id=...)
        -> xem cùng Session đó
```

`session_id` là danh tính task bền vững duy nhất. Agent không được liệt kê, suy đoán hoặc tự động chọn Session từ cuộc trò chuyện khác. Để tiếp tục công việc trong cuộc trò chuyện mới, người dùng truyền `session_id` hiện có một cách rõ ràng. Agent nên báo `session_id` đang dùng sau start/resume, tại các checkpoint tiến độ quan trọng và trước khi kết thúc turn để có thể handoff thủ công. Session không gắn với machine hay working directory; parameter tool thông thường vẫn chọn target local/remote và path.

Plan `plan_manage` tùy chọn bật Goal mode cho Session. Nếu Plan active và không có agent activity trong 15 phút, Live Workspace liên kết có thể yêu cầu ChatGPT tiếp tục. Continuation resume cùng `session_id` rõ ràng đó và giới hạn ở 10 lần thử, dù được chấp nhận hay từ chối. Plan blocked, completed và cancelled không được tự động tiếp tục; Plan active có mọi steps completed hoặc skipped vẫn đủ điều kiện cho continuation kết thúc để agent được resume có thể hoàn tất Plan. Điều khiển pause/resume/cancel của con người cập nhật Plan thuộc Session thay vì state tạm thời của Live Workspace.

## Giao diện trình duyệt

Mở:

```text
http://127.0.0.1:8765/ui
```

Với deployment công khai, dùng HTTPS origin đã cấu hình:

```text
https://your-public-host.example.com/ui
```

Giao diện trình duyệt dùng cùng OAuth server và scope với MCP. Page shell và tài nguyên tĩnh là công khai để màn hình đăng nhập tải được, còn `/api/ui/*` và WebSocket terminal OpenTUI vẫn được bảo vệ. Access token chỉ được lưu trong session storage của trình duyệt.

### Chọn giao diện

Màn hình OAuth có hai điểm vào:

- **Open Web UI** cấp quyền rồi mở dashboard native.
- **Continue to OpenTUI** cấp quyền rồi mở giao diện terminal, giữ hành vi trình duyệt trước đó.

Sau khi cấp quyền, bộ chọn ở sidebar có thể chuyển giữa Web UI và OpenTUI mà không cần đăng nhập lại. Trang native hiện tại được ghi nhớ khi tạm thời chuyển sang OpenTUI.

Có thể bookmark các route:

```text
/ui/#/overview
/ui/#/machines
/ui/#/workloads
/ui/#/activity
/ui/#/console
```

`#/web` và `#/dashboard` là alias của Overview. `#/tui` và `#/opentui` là alias của Console.

## Web UI native

Web UI native poll API giao diện người dùng hiện có mỗi năm giây và render control native của trình duyệt thay vì cell terminal. PTY không được khởi động cho đến khi chọn OpenTUI.

### Overview

Overview hiển thị thông tin vận hành ưu tiên cao nhất trước:

- Tình trạng controller và phiên bản LSM hiện tại.
- Số máy online và offline.
- Tracked job đang hoạt động và session terminal bền vững.
- CPU, bộ nhớ, đĩa workspace, load, throughput mạng và uptime.
- Cảnh báo sinh từ trạng thái worker, ngưỡng tài nguyên, job lỗi và lệnh gọi MCP lỗi.
- Hoạt động MCP gần đây do model khởi tạo.

### Machines

Machines liệt kê controller cục bộ và worker từ xa đã kết nối cùng trạng thái, nền tảng, phiên bản, thư mục làm việc, capability và thông tin last-seen.

### Workloads

Workloads kết hợp tracked job đang hoạt động và session shell bền vững độc lập. Web UI chỉ đọc các record này; dùng OpenTUI để quản lý session tương tác.

### Activity

Activity kết hợp cảnh báo hiện tại với hoạt động audit MCP gần đây. Lệnh và thao tác file do người dùng nhập không được ghi vào nhật ký audit MCP.

## OpenTUI trong trình duyệt

Chọn **OpenTUI** sẽ lazy-start cùng ứng dụng OpenTUI mà launcher terminal native sử dụng. Browser console giữ:

- Truyền PTY nhị phân đã xác thực qua WebSocket.
- Tự động resize terminal và reconnect backoff.
- Tương tác chuột với control OpenTUI.
- Chế độ fullscreen và phím tắt an toàn cho trình duyệt.
- Phím tắt mobile và điều khiển bàn phím mềm rõ ràng.
- Hỗ trợ SIXEL và inline image qua xterm.js.

Trình duyệt không tạo OpenTUI PTY khi người dùng vẫn ở chế độ Web UI native.

## OpenTUI native

Executable release độc lập nhúng runtime OpenTUI theo nền tảng. Chỉ cần giữ executable chính, khởi động dịch vụ rồi chạy:

```bash
local-shell-mcp tui
```

TUI native không yêu cầu người vận hành đăng nhập. Trong cấu hình Docker Compose được tài liệu hóa, launcher tái sử dụng dedicated CLI credential chỉ nằm trên host cho Human UI API qua loopback; các bố cục split-runtime khác có thể dùng `--token-file`. Các instance OpenTUI do trình duyệt khởi chạy dùng credential trong process của controller, chỉ được tạo khi cần và không bao giờ được lưu vào state directory hoặc state backend. Reverse proxy không nhận được các bypass cục bộ này chỉ vì kết nối qua loopback.

Checkout source cũng có thể chạy TUI sau khi cài dependency Bun:

```bash
cd ui
bun install --frozen-lockfile
bun run build
cd ..
local-shell-mcp tui
```

Chỉ dùng `--api-base` khi dịch vụ cục bộ sử dụng cổng không mặc định:

```bash
local-shell-mcp tui --api-base http://127.0.0.1:9876/api/ui
```

## Màn hình OpenTUI

### Dashboard

Dashboard là tổng quan vận hành của OpenTUI. Terminal rộng hiển thị riêng các vùng node, workload, alert, activity, thông tin hệ thống và trend; terminal hẹp hơn thu gọn thành tóm tắt compact mà không scroll ngang.

### Files

Files là trình quản lý file ba pane native của LSM cho máy cục bộ và từ xa. Nó hỗ trợ tạo, sửa, đổi tên, copy, move, paste, xóa, bật/tắt file ẩn, refresh, preview text, preview binary và thumbnail ảnh có giới hạn.

### Terminals

Terminals quản lý session shell bền vững trên máy cục bộ và từ xa. Nó hỗ trợ nhập lệnh đầy đủ, nhập tương tác raw, chuyển session, tạo và kết thúc session, output gần đây và rail audit MCP có thể thu gọn.

### Audit

Audit đọc nhật ký audit JSONL có giới hạn và hỗ trợ filter node, operation, event, session, search, time-range, sort cùng xem chi tiết record.

### Remotes

Remotes hiển thị worker từ xa online và offline, capability, thư mục làm việc và metadata hệ thống. Có thể tạo join invite dùng một lần, đổi tên node hoặc revoke identity bền vững.

## Điều hướng OpenTUI

Thanh category phía trên và action footer theo ngữ cảnh có thể được click bằng chuột cả trong terminal native lẫn browser console.

| Phím | Hành động |
|---|---|
| `Alt+1` … `Alt+5` | Mở Dashboard, Files, Terminals, Remotes hoặc Audit. |
| `F2` … `F6` | Shortcut category thay thế. |
| `F1` | Mở hướng dẫn bàn phím. |
| `F9` | Refresh danh sách máy. |
| `Alt+Q` | Thoát tiến trình OpenTUI native mà không kích hoạt shortcut Ctrl dành riêng cho trình duyệt. |

Terminals dùng `Alt+N` để tạo session mới, `Alt+W` để dừng session đã chọn, `Alt+A` để bật/tắt rail audit, `Alt+R` để refresh và `Alt+Left/Right` để chuyển session. Browser console chặn các chord này trước điều hướng hay xử lý menu của trình duyệt.

## Cấu hình

| Khóa YAML | Biến môi trường | Mặc định | Mục đích |
|---|---|---|---|
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `true` | Mount hoặc tắt giao diện người dùng. |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `/ui` | Đường dẫn mount giao diện trình duyệt trên dịch vụ MCP. |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | auto | Override việc tìm executable OpenTUI native. |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `bing` | Cấu hình wallpaper giữ lại cho deployment browser console OpenTUI. |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | Đóng PTY OpenTUI trình duyệt không hoạt động sau số giây này; `0` tắt timeout. |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | Số session PTY OpenTUI trình duyệt đồng thời tối đa. |

## Ghi chú đóng gói

- Image Docker chứa asset Web UI và runtime OpenTUI native.
- Executable độc lập nhúng asset Web UI và runtime OpenTUI nền tảng đã nén.
- Wheel Python chứa asset trình duyệt; OpenTUI native cần executable release hoặc checkout source đã cài dependency Bun.
- Cả hai giao diện đều được phục vụ từ cùng tiến trình và cổng với MCP; không cần dịch vụ web bổ sung.
