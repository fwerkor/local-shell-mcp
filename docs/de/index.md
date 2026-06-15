# local-shell-mcp Dokumentation

Eine lokale Steuerungsebene für ChatGPT Developer Mode und andere MCP-Clients. Sie stellt einen kontrollierten Workspace, Shell, Dateien, Git, Browser-Automation, Dateilinks und Remote-Worker als MCP-Tools bereit.

## Documentation paths

- [Schnellstart](getting-started/quickstart.md)
- [ChatGPT-Connector](getting-started/chatgpt-connector.md)
- [Remote-Worker](guides/remote-workers.md)
- [Sicherheit](security.md)
- [Fehlerbehebung](troubleshooting.md)

## Core architecture

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## Key safety rule

Bei öffentlicher Bereitstellung OAuth aktivieren und weder Docker-Socket, Host-Root noch langlebige Zugangsdaten einbinden.
