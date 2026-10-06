<!-- i18n-source-sha256: 51bfe29de540492ab1da2df9479464641bb335796b0538357235fac5b4a2e446 -->
# Bắt đầu nhanh

Hướng dẫn này dùng Docker Compose làm runtime đầu tiên và ChatGPT làm client đầu tiên. Đây là hai lựa chọn độc lập: Docker, VS Code extension, binary, Python và stdio là các lựa chọn runtime; ChatGPT và client MCP chung là các lựa chọn client. Xem [lựa chọn runtime và mô hình deployment](../guides/deployment.md) để có sơ đồ đầy đủ.

## Yêu cầu

- Docker Engine với Compose v2.
- Endpoint HTTPS công khai nếu ChatGPT cần kết nối từ Web.
- Một thư mục workspace riêng.
- OAuth admin PIN và JWT secret dài, ngẫu nhiên.

!!! warning
    Model đã kết nối có thể thao tác workspace đã cấu hình. Chạy dịch vụ trong container hoặc VM dùng một lần và tránh mount tài nguyên điều khiển host.

## 1. Clone và cấu hình

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python -c 'from pathlib import Path; import secrets; p=Path(".env"); s=p.read_text(); p.write_text(s.replace("LOCAL_SHELL_MCP_UI_LOCAL_TOKEN=", "LOCAL_SHELL_MCP_UI_LOCAL_TOKEN=" + secrets.token_urlsafe(48), 1))'
chmod 600 .env
```

Sửa `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
CLOUDFLARE_TUNNEL_TOKEN=
```

## 2. Khởi động server

```bash
mkdir -p workspaces/default
docker compose up -d
```

Kiểm tra trạng thái:

```bash
docker compose ps
docker compose logs --tail=100 local-shell-mcp
curl -i http://127.0.0.1:8765/healthz
```

Phản hồi khỏe mạnh trả về HTTP `200`.

## 3. Công khai HTTPS

Với Cloudflare Tunnel sidecar:

```bash
docker compose --profile tunnel up -d
```

Trong Cloudflare Zero Trust, trỏ public hostname tới:

```text
http://local-shell-mcp:8765
```

Với Caddy, Nginx, Traefik, Nginx Proxy Manager hoặc reverse proxy khác, chuyển tiếp HTTPS traffic tới `127.0.0.1:8765` hoặc địa chỉ mạng của container.

## 4. Kết nối ChatGPT

Dùng MCP endpoint:

```text
https://your-public-host.example.com/mcp
```

Làm theo [hướng dẫn connector ChatGPT](chatgpt-connector.md) để hoàn tất OAuth và phê duyệt tools.

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

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Nếu dùng profile tunnel:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
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
| Thêm ChatGPT làm client | [ChatGPT connector](chatgpt-connector.md) |
| Chọn tools và viết prompt tốt hơn | [Mẫu sử dụng](../guides/usage-patterns.md) |
| Gắn máy HPC, NPU/GPU hoặc NAT | [Worker từ xa](../guides/remote-workers.md) |
| Hiểu mọi MCP tool | [Tham chiếu tools](../reference/tools.md) |
