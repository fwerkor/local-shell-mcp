# Tài liệu local-shell-mcp

Mặt phẳng điều khiển cục bộ cho ChatGPT Developer Mode và các client MCP khác. Nó cung cấp workspace được kiểm soát, shell, tệp, Git, tự động hóa trình duyệt, liên kết tệp và worker từ xa dưới dạng công cụ MCP.

## Đường dẫn tài liệu

- [Bắt đầu nhanh](getting-started/quickstart.md)
- [Trình kết nối ChatGPT](getting-started/chatgpt-connector.md)
- [Worker từ xa](guides/remote-workers.md)
- [Bảo mật](security.md)
- [Xử lý sự cố](troubleshooting.md)

## Kiến trúc lõi

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## Quy tắc an toàn chính

Khi triển khai công khai, hãy bật OAuth và không mount Docker socket, thư mục gốc của host hoặc thông tin xác thực dài hạn.
