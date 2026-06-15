# local-shell-mcp belgeleri

ChatGPT Developer Mode ve diğer MCP istemcileri için yerel bir kontrol düzlemi. Kontrollü workspace, shell, dosyalar, Git, tarayıcı otomasyonu, dosya bağlantıları ve uzak worker’ları MCP araçları olarak sunar.

## Documentation paths

- [Hızlı başlangıç](getting-started/quickstart.md)
- [ChatGPT bağlayıcı](getting-started/chatgpt-connector.md)
- [Uzak worker’lar](guides/remote-workers.md)
- [Güvenlik](security.md)
- [Sorun giderme](troubleshooting.md)

## Core architecture

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## Key safety rule

Herkese açık dağıtımda OAuth etkin olsun; Docker socket, host root veya uzun ömürlü kimlik bilgilerini bağlamayın.
