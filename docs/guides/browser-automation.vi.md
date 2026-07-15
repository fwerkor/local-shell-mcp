# Tự động hóa trình duyệt

Trang này mô tả kịch bản “Tự động hóa trình duyệt” và giữ cấu trúc Runtime/Client chung của trang tài liệu.

## Tổng quan

Runtime xác định tiến trình server chạy như thế nào và điều khiển workspace nào. Client xác định ChatGPT hoặc client MCP khác kết nối như thế nào. Docker, tiện ích VS Code, tệp nhị phân độc lập, cài đặt Python/pipx/mã nguồn và stdio là lựa chọn Runtime; trình kết nối ChatGPT, client MCP HTTP chung và client MCP stdio là kết nối Client.

## Khi nào dùng

- Dùng trang này khi đường dẫn Runtime hoặc Client đã chọn khớp với tiêu đề.
- Giữ nhất quán workspace root, public base URL, MCP endpoint, chế độ xác thực và các công cụ host khả dụng.
- Với ChatGPT web/app, hãy công bố MCP endpoint HTTPS kết thúc bằng `/mcp`.
- Với client MCP cục bộ, dùng HTTP localhost hoặc `local-shell-mcp --mode stdio` tùy khả năng hỗ trợ của client.

## Các bước

1. Trước tiên chọn trang cài đặt Runtime.
2. Khởi động Runtime và kiểm tra `/healthz` khi dùng chế độ HTTP.
3. Sau đó chọn trang kết nối Client.
4. Đăng ký MCP endpoint hoặc lệnh stdio trong Client.
5. Gọi `environment_info` để kiểm tra workspace và cấu hình thực tế.

```text
Runtime: Docker / VS Code extension / binary / Python / stdio
Client:  ChatGPT connector / generic HTTP MCP / generic stdio MCP
Endpoint: https://your-host.example.com/mcp
```

## Xác minh

- `environment_info` xác nhận cấu hình Runtime và workspace.
- `tree_view` xác nhận các tệp nhìn thấy được.
- `run_shell_tool` xác nhận môi trường lệnh.

## Ghi chú

Ưu tiên các bước nhỏ và có thể xác minh: kiểm tra, chỉnh sửa, diff, test, scan và commit. Tác vụ lớn cũng nên được chia thành các lời gọi công cụ có thể audit.
