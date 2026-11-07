<!-- i18n-source-sha256: b6bf2276867332a25b6e63b3b4cf21045262a9a9535422c02722906d87a2132a -->
# Bắt đầu nhanh

Hướng dẫn này khởi động Bộ điều khiển LSM và mở giao diện trình duyệt của nó. [unified web workspace](web-workspace.md) là trải nghiệm hàng ngày được đề xuất; nó là một ngăn xếp trò chuyện tùy chọn, được triển khai riêng. ChatGPT, Gemini và các máy khách MCP bên ngoài khác có thể kết nối với cùng một Bộ điều khiển. Xem [runtime choices and deployment model](../guides/deployment.md).

Khuyến nghị **tệp thực thi Controller duy nhất** từ [GitHub Releases](https://github.com/fwerkor/local-shell-mcp/releases/latest), không cần Python, Docker hay mã nguồn. Ví dụ cho **Linux x86_64**; nền tảng khác xem [hướng dẫn binary](../installation/binary.md).

## Yêu cầu

- File thực thi phù hợp và `curl` (ví dụ Linux x86_64).
- HTTPS công khai chỉ khi người dùng từ xa hoặc client MCP ngoài cần.
- Workspace riêng có quyền giới hạn.
- PIN quản trị OAuth mạnh và JWT secret ngẫu nhiên.

!!! warning
    Model đã kết nối có thể thao tác workspace đã cấu hình. Chạy dịch vụ trong container hoặc VM dùng một lần và tránh mount tài nguyên điều khiển host.

## 1. Tải file thực thi và cấu hình

Tải tệp đơn và tạo JWT secret:

```bash
mkdir -p ~/lsm && cd ~/lsm
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp
chmod +x local-shell-mcp
./local-shell-mcp --help
openssl rand -hex 32
```

Tạo `.env` và thay PIN, JWT secret mẫu (dùng `openssl rand -hex 32`). Binary **không tự động nạp** `.env`.

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. Khởi động server

Chạy trực tiếp file đã tải:

```bash
chmod 600 .env
set -a
. ./.env
set +a
mkdir -p workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspace"
./local-shell-mcp --mode mcp
```

Kiểm tra ở terminal khác:

```bash
curl -i http://127.0.0.1:8765/healthz
```

Phản hồi đúng là HTTP `200`. Để chạy liên tục hãy dùng trình quản lý dịch vụ và tài khoản giới hạn.

## 3. Công khai HTTPS

Để truy cập từ xa, dùng máy chủ công khai hoặc HTTPS reverse proxy (Caddy, Nginx, Traefik), chuyển tiếp toàn bộ origin gồm upload/download đến:

```text
http://127.0.0.1:8765
```

Kiểm tra HTTPS:

```bash
curl -i https://your-public-host.example.com/healthz
```

**Không khuyến nghị Cloudflare Tunnel** cho truyền tệp: upload từ client có thể chậm. Ưu tiên máy chủ công khai hoặc proxy/chuyển tiếp cổng thông thường và giữ OAuth. Phương án khác: [Docker](../installation/docker.md).

## 4. Mở không gian làm việc của trình duyệt

Mở thông tin đăng nhập Bộ điều khiển:

```text
https://your-public-host.example.com/ui
```

Đối với các trang trò chuyện, dự án và điều khiển tích hợp, hãy làm theo [unified web workspace guide](web-workspace.md). WebUI nhẹ ban đầu có sẵn khi chưa cài đặt trò chuyện.

## 5. Xác nhận an toàn quyền truy cập tools

Yêu cầu model:

```text
Dùng local-shell-mcp. Trước tiên gọi environment_get, sau đó liệt kê root workspace. Chưa sửa file.
```

Các read-only tools dự kiến:

- `environment_get`
- `file_list`
- `file_tree`
- `file_read`

## 6. Bắt đầu bằng coding task có phạm vi giới hạn

Một task đầu tiên phù hợp:

```text
Kiểm tra repository này, tóm tắt layout project, chạy test suite hiện có nếu rõ ràng, và không thay đổi file.
```

Sau khi xác nhận kết nối, đưa chỉ dẫn cụ thể hơn:

```text
Sửa test bị lỗi. Đọc các file liên quan trước, tạo patch nhỏ nhất, chạy test mục tiêu rồi hiển thị git diff. Không commit cho đến khi tôi chấp thuận.
```

## Cập nhật

Thay file thực thi mới rồi khởi động lại Controller:

```bash
# Stop the running Controller before replacing the executable.
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp.new
chmod +x local-shell-mcp.new
./local-shell-mcp.new --version
mv local-shell-mcp.new local-shell-mcp
# Restart the Controller process or service.
curl -i http://127.0.0.1:8765/healthz
```

Nếu dùng Docker Compose hãy cập nhật container. Cài source: [Python](../installation/python.md).

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

## Các trang tiếp theo

| Nhu cầu | Trang |
|---|---|
| Hiểu lựa chọn runtime và client | [Lựa chọn runtime và mô hình deployment](../guides/deployment.md) |
| Chạy với Docker Compose | [Docker Compose runtime](../installation/docker.md) |
| Chạy từ VS Code | [VS Code extension runtime](../installation/vscode-extension.md) |
| Chạy bằng release binary | [Runtime binary độc lập](../installation/binary.md) |
| Chạy bằng Python hoặc source checkout | [Python runtimes](../installation/python.md) |
| Sử dụng giao diện điều khiển và trò chuyện thống nhất | [Unified web workspace](web-workspace.md) |
| Thêm Gemini Spark làm khách hàng | [Gemini Custom Apps](gemini-spark.md) |
| Thêm ChatGPT làm client | [ChatGPT connector](chatgpt-connector.md) |
| Chọn tools và viết prompt tốt hơn | [Mẫu sử dụng](../guides/usage-patterns.md) |
| Gắn máy HPC, NPU/GPU hoặc NAT | [Worker từ xa](../guides/remote-workers.md) |
| Hiểu mọi MCP tool | [Tham chiếu tools](../reference/tools.md) |
