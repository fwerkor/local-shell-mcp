# Dateilinks

Diese Seite beschreibt das Szenario „Dateilinks“ und verwendet die gemeinsame Runtime/Client-Struktur der Dokumentation.

## Überblick

Runtime legt fest, wie der Serverprozess läuft und welchen Workspace er kontrolliert. Client legt fest, wie ChatGPT oder ein anderer MCP-Client eine Verbindung herstellt. Docker, die VS Code-Erweiterung, eigenständige Binärdateien, Python/pipx/Quellcode-Installationen und stdio sind Runtime-Optionen; der ChatGPT-Connector, generische HTTP-MCP-Clients und stdio-MCP-Clients sind Client-Verbindungen.

## Wann verwenden

- Verwende diese Seite, wenn der gewählte Runtime- oder Client-Pfad zum Titel passt.
- Halte Workspace-Wurzel, öffentliche base URL, MCP endpoint, Authentifizierungsmodus und verfügbare Host-Tools konsistent.
- Für ChatGPT Web/App muss ein HTTPS-MCP-endpoint bereitgestellt werden, der auf `/mcp` endet.
- Für lokale MCP-Clients verwende je nach Client-Unterstützung HTTP localhost oder `local-shell-mcp --mode stdio`.

## Schritte

1. Wähle zuerst die Runtime-Installationsseite.
2. Starte die Runtime und prüfe im HTTP-Modus `/healthz`.
3. Wähle danach die Client-Verbindungsseite.
4. Registriere den MCP endpoint oder den stdio-Befehl im Client.
5. Rufe `environment_info` auf, um den effektiven Workspace und die Einstellungen zu prüfen.

```text
Runtime: Docker / VS Code extension / binary / Python / stdio
Client:  ChatGPT connector / generic HTTP MCP / generic stdio MCP
Endpoint: https://your-host.example.com/mcp
```

## Überprüfung

- `environment_info` bestätigt Runtime-Einstellungen und Workspace.
- `tree_view` bestätigt sichtbare Dateien.
- `git_status_tool` bestätigt den Repository-Kontext.
- `run_shell_tool` bestätigt die Befehlsumgebung.

## Hinweise

Arbeite bevorzugt in kleinen, überprüfbaren Schritten: prüfen, bearbeiten, diff ansehen, testen, scannen und committen. Große Aufgaben sollten ebenfalls in auditierbare Tool-Aufrufe zerlegt werden.
