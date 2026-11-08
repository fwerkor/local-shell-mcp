<!-- i18n-source-sha256: b6bf2276867332a25b6e63b3b4cf21045262a9a9535422c02722906d87a2132a -->
# Schnellstart

Diese Anleitung startet einen LSM Controller und öffnet seine Browseroberfläche. Der [unified web workspace](web-workspace.md) ist das empfohlene tägliche Erlebnis; Es handelt sich um einen separat bereitgestellten, optionalen Chat-Stack. ChatGPT, Gemini und andere externe MCP-Clients können sich mit demselben Controller verbinden. Siehe [runtime choices and deployment model](../guides/deployment.md).

Empfohlen ist die **einzelne ausführbare Controller-Datei** von [GitHub Releases](https://github.com/fwerkor/local-shell-mcp/releases/latest), ohne Python, Docker oder Quellcode-Checkout. Das Beispiel gilt für **Linux x86_64**; für andere Plattformen siehe [Binärinstallation](../installation/binary.md).

## Voraussetzungen

- Passende Release-Datei und `curl` (Beispiel Linux x86_64).
- Öffentliches HTTPS nur für Fernzugriff oder externe MCP-Clients.
- Eigenes, eingeschränktes Arbeitsverzeichnis.
- Starker OAuth-Administrator-PIN und zufälliges JWT-Geheimnis.

!!! warning
    Das verbundene Modell kann den konfigurierten Workspace bedienen. Führen Sie den Dienst in einem wegwerfbaren Container oder einer VM aus und mounten Sie keine Host-Steuerressourcen.

## 1. Executable herunterladen und konfigurieren

Laden Sie die einzelne Datei herunter und erstellen Sie ein JWT-Geheimnis:

```bash
mkdir -p ~/lsm && cd ~/lsm
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp
chmod +x local-shell-mcp
./local-shell-mcp --help
openssl rand -hex 32
```

Erstellen Sie `.env` und ersetzen Sie die Platzhalter für PIN und JWT-Geheimnis (mit `openssl rand -hex 32`). Die Binärdatei liest `.env` **nicht automatisch**.

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. Server starten

Starten Sie die ausführbare Datei direkt:

```bash
chmod 600 .env
set -a
. ./.env
set +a
mkdir -p workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspace"
./local-shell-mcp --mode mcp
```

Status in einem zweiten Terminal prüfen:

```bash
curl -i http://127.0.0.1:8765/healthz
```

Eine erfolgreiche Antwort ist HTTP `200`. Für den Dauerbetrieb einen Dienstmanager und ein eingeschränktes Konto verwenden.

## 3. HTTPS bereitstellen

Für Fernzugriff einen öffentlichen Server oder einen HTTPS-Reverse-Proxy (Caddy/Nginx/Traefik) verwenden. Den gesamten Ursprung inklusive Uploads und Downloads weiterleiten an:

```text
http://127.0.0.1:8765
```

HTTPS-Verbindung prüfen:

```bash
curl -i https://your-public-host.example.com/healthz
```

**Cloudflare Tunnel wird nicht empfohlen**, wenn Dateien übertragen werden: Client-Uploads können sehr langsam sein. Besser sind ein öffentlicher Server oder ein regulärer Reverse-Proxy/Portweiterleitung. Für öffentliche Endpunkte OAuth aktiv lassen. Docker: [Docker-Anleitung](../installation/docker.md).

## 4. Öffnen Sie den Browser-Arbeitsbereich

Öffnen Sie das Controller-Login:

```text
https://your-public-host.example.com/ui
```

Für Chat, Projekte und integrierte Steuerungsseiten folgen Sie dem [unified web workspace guide](web-workspace.md). Die ursprüngliche, leichtgewichtige WebUI ist verfügbar, wenn Chat nicht installiert ist.

## 5. Tool-Zugriff sicher bestätigen

Bitten Sie das Modell:

```text
Verwende local-shell-mcp. Rufe zuerst environment_get auf und liste dann die Workspace-Wurzel auf. Ändere noch keine Dateien.
```

Erwartete Read-only-Tools:

- `environment_get`
- `file_list`
- `file_tree`
- `file_read`

## 6. Mit einer begrenzten Coding-Aufgabe beginnen

Eine gute erste Aufgabe:

```text
Untersuche dieses Repository, fasse das Projektlayout zusammen, führe die vorhandene Testsuite aus, falls sie offensichtlich ist, und ändere keine Dateien.
```

Nach bestätigter Verbindung geben Sie spezifischere Anweisungen:

```text
Behebe den fehlgeschlagenen Test. Lies zuerst die relevanten Dateien, erstelle den kleinsten Patch, führe den Zieltest aus und zeige danach git diff. Committe erst nach meiner Freigabe.
```

## Aktualisieren

Die Release-Datei austauschen und Controller neu starten:

```bash
# Stop the running Controller before replacing the executable.
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp.new
chmod +x local-shell-mcp.new
./local-shell-mcp.new --version
mv local-shell-mcp.new local-shell-mcp
# Restart the Controller process or service.
curl -i http://127.0.0.1:8765/healthz
```

Docker Compose wird durch Container-Aktualisierung gepflegt; Quellcode-Anleitung: [Python/Source](../installation/python.md).

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

## Nächste Seiten

| Ziel | Seite |
|---|---|
| Runtime- und Client-Auswahl verstehen | [Runtime-Auswahl und Bereitstellungsmodell](../guides/deployment.md) |
| Mit Docker Compose ausführen | [Docker Compose runtime](../installation/docker.md) |
| Aus VS Code ausführen | [VS Code extension runtime](../installation/vscode-extension.md) |
| Mit einem Release-Binary ausführen | [Standalone-Binary-Runtime](../installation/binary.md) |
| Mit Python oder Source Checkout ausführen | [Python runtimes](../installation/python.md) |
| Nutzen Sie die einheitliche Chat- und Steuerungsoberfläche | [Unified web workspace](web-workspace.md) |
| Fügen Sie Gemini Spark als Kunden hinzu | [Gemini Custom Apps](gemini-spark.md) |
| ChatGPT als Client hinzufügen | [ChatGPT connector](chatgpt-connector.md) |
| Tools auswählen und bessere Prompts schreiben | [Nutzungsmuster](../guides/usage-patterns.md) |
| Eine HPC-, NPU/GPU- oder NAT-Maschine anbinden | [Remote workers](../guides/remote-workers.md) |
| Alle MCP-Tools verstehen | [Tool-Referenz](../reference/tools.md) |
