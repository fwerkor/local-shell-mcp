<!-- i18n-source-sha256: 521e0f39c8823597b1468b2d63af978794cb28fda8c8e60230da0a96cff2d5c2 -->
# Không gian làm việc web hợp nhất

**Không gian làm việc web LSM hợp nhất** là cách được khuyến nghị để sử dụng local-shell-mcp hàng ngày. Nó kết hợp trò chuyện AI, lịch sử dự án và mặt phẳng điều khiển LSM trong một giao diện đáp ứng, dựa trên giao diện người dùng LibreChat đã được sửa đổi và cung cấp. Bạn vẫn có thể kết nối các máy khách MCP bên ngoài như [ChatGPT](chatgpt-connector.md) hoặc [Gemini](gemini-spark.md).

Không gian làm việc **tự lưu trữ và tùy chọn cài đặt**: đây là một dịch vụ web riêng biệt, không phải là một phần của hình ảnh Bộ điều khiển tối thiểu, gói Thực thi độc lập hoặc gói Công nhân từ xa. Việc triển khai chỉ dành cho bộ điều khiển giữ lại giao diện người dùng trình duyệt gốc và OpenTUI.

## Trong không gian làm việc có gì?

| Khu vực | Bạn có thể làm gì |
|---|---|
| Trò chuyện và dự án | Chọn mô hình đã định cấu hình, tạo cuộc hội thoại, sắp xếp dự án, tìm các cuộc trò chuyện trước đây và lưu trữ các cuộc trò chuyện. Lịch sử vẫn còn trên máy chủ. |
| Tổng quan về bộ điều khiển | Xem tình trạng, hoạt động gần đây và các máy được kết nối. |
| Tập tin | Duyệt và quản lý các tập tin cục bộ hoặc từ xa. |
| Thiết bị đầu cuối | Làm việc với các thiết bị đầu cuối liên tục trên Bộ điều khiển hoặc Công nhân. |
| Máy tính để bàn | Kiểm tra và kiểm soát các phiên GUI từ xa. |
| Phiên | Kiểm tra các nhiệm vụ LSM lâu bền và vòng đời của chúng. |
| Điều khiển từ xa | Kết nối và quản lý Công nhân đi. |
| Kiểm toán | Kiểm tra hoạt động của công cụ có nguồn gốc từ mô hình. |
| MCP lồng nhau | Đăng ký, chỉnh sửa, kích hoạt, vô hiệu hóa, làm mới và xóa các máy chủ MCP bên ngoài đằng sau LSM. |

Các tuyến Bộ điều khiển là `/control/overview`, `/control/files`, `/control/terminals`, `/control/desktop`, `/control/sessions`, `/control/remotes` và `/control/audit`. Trò chuyện mở ra tại `/c/new`. Trình quản lý MCP LSM kiểm soát **Đăng ký MCP lồng nhau của LSM**; nó không tạo sổ đăng ký thứ hai trong LibreChat.

## Triển khai ngăn xếp trò chuyện tùy chọn

1. [Install and start an LSM Controller](quickstart.md) with SQLite (now the default). On startup, durable historical state is imported automatically, retaining the original files for rollback.
2. Configure one HTTP/HTTPS Controller origin, for example `https://lsm.example.org`. Chat, terminals, files and remote controls share the same Python server and authentication.
3. To override the defaults, configure the Controller service environment:

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

4. Start the Controller from its Python package or standalone executable:

```sh
local-shell-mcp --mode mcp
```

5. The original React client is maintained in `ui/workspace/`. Bun is only required for building and releases; consult the [first-party WebUI build and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

Node.js, MongoDB, Meilisearch and the separate LibreChat Compose stack are no longer required at runtime. Workers remain ordinary Python packages.

**Migration status:** The Python Agent generation engine, SSE resume and tool approvals are still being ported. Do not deploy the draft branch as a replacement for a working production Controller.

## Đăng nhập và sử dụng trò chuyện

1. Open the LSM Controller `/ui` entrypoint and authenticate with its existing PIN or OAuth credentials. React and Controller APIs share this identity.
2. Configure an available model endpoint/API credential in LSM. The Python Agent provider engine is being migrated; the draft branch does not yet provide complete generation support.
3. Start a conversation after the Python Agent endpoints and SSE protocol pass the acceptance suite. Nested MCP, LSM tools and file uploads follow existing Controller permissions.
4. Start with a read-only request: “Check Controller status and list the workspace root. Do not modify files.”
5. Navigate to **Files**, **Terminals**, **Desktop**, **Sessions**, **Remotes** or **Audit** for direct inspection and control.

Nội dung tải lên trò chuyện (tối đa 32 MiB) được lưu trữ trong không gian làm việc của Bộ điều khiển và đường dẫn tuyệt đối của chúng được cung cấp cho mô hình. Tải lên trình duyệt không cấp thêm quyền truy cập tệp. Các lệnh gọi công cụ hướng tới mô hình chuyển qua ủy quyền, kiểm tra LSM và bộ định tuyến làm việc từ xa.

## MCP bên ngoài, bảo mật và dữ liệu

Sử dụng thanh bên MCP của không gian làm việc để quản lý các máy chủ MCP bên ngoài lồng nhau. Điều này hỗ trợ các máy chủ stdio cục bộ và máy chủ HTTP, bao gồm các biến môi trường riêng tư và tiêu đề yêu cầu. Bí mật không được trả lại cho trình duyệt. Nút chuyển đổi trò chuyện **MCP bên ngoài** cho phép tìm kiếm, kiểm tra và gọi các công cụ lồng nhau; nó không cấp mô hình `mcp_manage` khi các công cụ LSM gốc bị tắt. Quản lý giao diện người dùng được bảo vệ bằng ủy quyền của Bộ điều khiển thông thường.

Chats, projects, Agents, sessions, audits and Worker metadata share `.local-shell-mcp/lsm.sqlite3`; SQLite FTS5 provides local search. Non-database artifacts remain under `.local-shell-mcp/`.

The workspace is a first-party React application, not an iframe or separately hosted Web service. Python Workers and external MCP clients remain compatible.

## Khắc phục sự cố

- **Unable to start the WebUI:** check the Controller Python logs, SQLite initialization and bundled frontend archive. `LOCAL_SHELL_MCP_STATE_BACKEND=file` is an emergency storage recovery option.
- **Authentication fails:** use the existing Controller PIN/OAuth login. The React UI does not require a separate LibreChat account or bridge secret.
- **Chat loads but cannot answer:** the Python Agent generation and SSE port is still incomplete in this draft branch; do not deploy it to production.
- **Missing MCP tools:** check Controller authorization and the nested MCP registry; never expose `mcp_manage` to external-only model tools.
- **Files or sessions appear empty:** verify the Controller workspace, SQLite migration and authorized principal in its logs.

Để biết chi tiết triển khai và cập nhật, hãy xem [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md) và [human interface guide](../guides/human-interface.md).
