# local-shell-mcp dokümantasyonu

ChatGPT Developer Mode ve diğer MCP istemcileri için yerel bir kontrol düzlemi. Kontrollü workspace, shell, dosyalar, Git, tarayıcı otomasyonu, dosya bağlantıları ve uzak worker’ları MCP araçları olarak sunar.

## Dokümantasyon yolları

- [Hızlı başlangıç](getting-started/quickstart.md)
- [ChatGPT bağlayıcısı](getting-started/chatgpt-connector.md)
- [Uzak worker](guides/remote-workers.md)
- [Güvenlik](security.md)
- [Sorun giderme](troubleshooting.md)

## Temel mimari

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## Temel güvenlik kuralı

Genel dağıtımlarda OAuth’u etkinleştirin ve Docker socket, host kökü veya uzun ömürlü kimlik bilgilerini mount etmeyin.
