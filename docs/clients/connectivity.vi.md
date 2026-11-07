<!-- i18n-source-sha256: 4eb43e1a065d72171aad5493848eb2f8c57361b110237c8816928e28f227a3d8 -->
# Kết nối mạng

MCP client HTTP ở ngoài máy cần một HTTPS origin có thể truy cập. Trang này nói về định tuyến mạng, không phải việc chọn runtime.

client endpoint thường kết thúc bằng `/mcp`:

```text
https://your-public-host.example.com/mcp
```

Thiết lập public base URL của máy chủ chỉ là origin:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

Không đưa `/mcp` vào base URL này.

## Các lựa chọn kết nối

**Khuyến nghị:** Để truy cập công khai, hãy triển khai trên máy chủ công khai hoặc chuyển tiếp lưu lượng qua máy chủ công khai bằng reverse proxy HTTPS.

**Không khuyến nghị:** Tốc độ tải lên phía máy khách qua Cloudflare Tunnel có thể rất chậm, khiến việc tải lên và truyền tệp khó sử dụng. Chỉ dùng khi không thể triển khai hoặc chuyển tiếp qua máy chủ công khai.


| Lựa chọn | Khi nào dùng |
|---|---|
| Caddy | TLS tự động đơn giản |
| Nginx hoặc Nginx Proxy Manager | Hạ tầng Nginx hiện có |
| Traefik | Định tuyến container-native hiện có |
| Chuyển tiếp qua máy chủ công khai | Để truy cập công khai, hãy triển khai trên máy chủ công khai hoặc chuyển tiếp lưu lượng qua máy chủ công khai bằng reverse proxy HTTPS. |
| Cloudflare Tunnel (không khuyến nghị) | Chuyển tiếp qua máy chủ công khai; Cloudflare Tunnel chỉ là phương án cuối |

## Đường dẫn

Chuyển tiếp toàn bộ origin tới máy chủ đang chạy. Các đường dẫn quan trọng gồm:

| Đường dẫn | Mục đích |
|---|---|
| `/mcp` | MCP Streamable HTTP endpoint |
| `/healthz`, `/readyz` | Kiểm tra sức khỏe |
| `/.well-known/...` | Metadata khám phá client |
| `/oauth/...` | Luồng ủy quyền client |
| `/downloads/...` | Liên kết tệp được tạo tùy chọn |
| `/join/...`, `/remote/...` | Luồng remote-worker tùy chọn |

## Hành vi proxy

Proxy cần giữ nguyên đường dẫn, chuyển tiếp request body, hỗ trợ response dài và tránh timeout quá ngắn.

## Kiểm tra

```bash
curl -i http://127.0.0.1:8765/healthz
curl -i https://your-public-host.example.com/healthz
```

## Lỗi thường gặp

| Lỗi | Cách sửa |
|---|---|
| Dùng `https://host` thay vì `https://host/mcp` trong ChatGPT | Chỉ thêm `/mcp` vào client endpoint |
| Đặt `LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://host/mcp` | Chỉ đặt origin |
| Chỉ route `/mcp` | Route toàn bộ origin để discovery và ủy quyền cũng hoạt động |
| Chạy host runtime với workspace quá rộng | Dùng workspace hẹp hoặc Docker |

## Kết hợp gợi ý

| Runtime | Kiểu mạng |
|---|---|
| Docker Compose trên server | Reverse proxy HTTPS |
| Docker Compose trên máy gia đình | Chuyển tiếp qua máy chủ công khai; Cloudflare Tunnel chỉ là phương án cuối |
| VS Code extension trên laptop | Chuyển tiếp qua máy chủ công khai |
| Binary trên VM | Reverse proxy trên VM hoặc biên mạng |
| Server dev Python/source | Thường chỉ localhost |
| Stdio mode | Không có đường HTTP; dùng MCP client cục bộ |
