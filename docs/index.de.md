# local-shell-mcp-Dokumentation

Eine lokale Steuerungsebene für ChatGPT Developer Mode und andere MCP-Clients. Sie stellt einen kontrollierten Workspace, shell, Dateien, Git, Browser-Automatisierung, Dateilinks und Remote-Worker als MCP-Tools bereit.

## Dokumentationspfade

- [Schnellstart](getting-started/quickstart.md)
- [ChatGPT-Connector](getting-started/chatgpt-connector.md)
- [Remote-Worker](guides/remote-workers.md)
- [Sicherheit](security.md)
- [Fehlerbehebung](troubleshooting.md)

## Kernarchitektur

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## Wichtige Sicherheitsregel

Aktiviere bei öffentlichen Bereitstellungen OAuth und mounte weder Docker socket noch Host-Wurzel noch langfristige Zugangsdaten.
