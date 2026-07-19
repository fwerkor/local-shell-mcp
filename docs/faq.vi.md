# Câu hỏi thường gặp

Trang này tổng hợp các vấn đề Client và reverse proxy thường gặp có thể trông giống lỗi LSM dù máy chủ vẫn hoạt động bình thường.

## Vì sao một số công cụ không khả dụng trong ChatGPT sau khi nâng cấp LSM?

### Triệu chứng

- Công cụ mới không xuất hiện trong ChatGPT.
- ChatGPT vẫn cố gọi công cụ cũ đã bị xóa, đổi tên hoặc hợp nhất.
- Công cụ tồn tại nhưng lời gọi thất bại vì ChatGPT gửi schema đầu vào cũ.
- Khởi động lại LSM hoặc mở cuộc trò chuyện mới không khắc phục được.

### Nguyên nhân

ChatGPT có thể giữ snapshot cố định của các công cụ và schema đầu vào có tại thời điểm MCP App được quét, phê duyệt hoặc xuất bản. Khi bản phát hành LSM thay đổi `tools/list`, snapshot đó không được bảo đảm tự động làm mới. Đây không phải cache ngắn hạn có thời gian hết hạn được công bố.

### Cách khắc phục

=== "Developer mode hoặc kết nối cá nhân"

    1. Mở **ChatGPT Settings → Apps**.
    2. Mở LSM App và dùng **Refresh** để quét lại công cụ.
    3. Nếu không có Refresh, hãy xóa App cũ và thêm lại cùng MCP endpoint.
    4. Bắt đầu cuộc trò chuyện mới sau khi danh sách công cụ mới được chấp nhận.

=== "App đã xuất bản trong ChatGPT Business"

    Hiện tại App tùy chỉnh đã xuất bản không thể cập nhật công cụ hoặc metadata tại chỗ. Quản trị viên phải tạo App mới, quét endpoint LSM hiện tại, xuất bản bản thay thế và ngừng App cũ.

=== "ChatGPT Enterprise hoặc Edu"

    Quản trị viên có thể mở **Workspace Settings → Apps → LSM App → … → Action control → Refresh**, xem khác biệt và bật các action mới khi cần.

Xem [issue #70](https://github.com/fwerkor/local-shell-mcp/issues/70) và [tài liệu MCP App của OpenAI](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt).

## Vì sao WebUI liên tục kết nối lại khi đặt sau Nginx?

### Triệu chứng

- Trang WebUI và đăng nhập OAuth tải bình thường.
- TUI không xuất hiện.
- Trạng thái lặp giữa `Connecting`, `Connection error` và `Reconnecting`.
- Kết nối trực tiếp đến cổng `8765` hoạt động.

### Nguyên nhân

Giao diện trình duyệt hiển thị TUI gốc qua PTY WebSocket. Endpoint mặc định là `/ui/ws`; với `ui_path` tùy chỉnh, endpoint là `${ui_path}/ws`. `proxy_pass` Nginx thông thường không tự chuyển tiếp các header hop-by-hop cần cho việc nâng cấp WebSocket.

### Cách khắc phục

Bật HTTP/1.1 và chuyển tiếp header `Upgrade` cùng `Connection`:

```nginx
# Đặt map trong khối http.
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 443 ssl;
    server_name lsm.example.com;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;
    }
}
```

Kiểm tra rồi tải lại Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Trong Nginx Proxy Manager, bật **Websockets Support** cho Proxy Host. Nếu vẫn kết nối lại, thêm các header nâng cấp tương đương trong Advanced.

### Xác minh

Mở công cụ nhà phát triển, tải lại WebUI và kiểm tra yêu cầu `/ui/ws`. Kết nối đúng trả về:

```text
101 Switching Protocols
```

Xem [issue #71](https://github.com/fwerkor/local-shell-mcp/issues/71).
