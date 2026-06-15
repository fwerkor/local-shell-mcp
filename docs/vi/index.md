# Tài liệu local-shell-mcp

Một control plane cục bộ cho ChatGPT Developer Mode và các MCP client khác. Nó cung cấp workspace có kiểm soát, shell, file, Git, tự động hóa trình duyệt, liên kết file và remote worker dưới dạng MCP tools.

## Documentation paths

- [Bắt đầu nhanh](getting-started/quickstart.md)
- [Kết nối ChatGPT](getting-started/chatgpt-connector.md)
- [Remote workers](guides/remote-workers.md)
- [Bảo mật](security.md)
- [Khắc phục sự cố](troubleshooting.md)

## Core architecture

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## Key safety rule

Với deployment công khai, bật OAuth và không mount Docker socket, root của host hoặc credential dài hạn.
