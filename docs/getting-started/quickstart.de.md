<!-- i18n-source-sha256: a3fdf9088031e6903b15497a3df881a8e6ed2f6f2b34dd4d0b68b0414a2ca81e -->
# Schnellstart

Diese Anleitung verwendet Docker Compose als ersten Runtime und ChatGPT als ersten Client. Das sind unabhängige Entscheidungen: Docker, VS Code extension, binary, Python und stdio sind Runtime-Optionen; ChatGPT und generische MCP-Clients sind Client-Optionen. Die vollständige Übersicht finden Sie unter [Runtime-Auswahl und Bereitstellungsmodell](../guides/deployment.md).

## Voraussetzungen

- Docker Engine mit Compose v2.
- Ein öffentlicher HTTPS-Endpoint, wenn ChatGPT aus dem Web verbinden muss.
- Ein eigenes Workspace-Verzeichnis.
- Eine lange zufällige OAuth admin PIN und ein JWT secret.

!!! warning
    Das verbundene Modell kann den konfigurierten Workspace bedienen. Führen Sie den Dienst in einem wegwerfbaren Container oder einer VM aus und mounten Sie keine Host-Steuerressourcen.

## 1. Klonen und konfigurieren

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python scripts/init_compose_env.py
```

Bearbeiten Sie `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
CLOUDFLARE_TUNNEL_TOKEN=
```

## 2. Server starten

```bash
mkdir -p workspaces/default
docker compose up -d
```

Status prüfen:

```bash
docker compose ps
docker compose logs --tail=100 local-shell-mcp
curl -i http://127.0.0.1:8765/healthz
```

Eine gesunde Antwort liefert HTTP `200`.

## 3. HTTPS bereitstellen

Für den Cloudflare-Tunnel-Sidecar:

```bash
docker compose --profile tunnel up -d
```

In Cloudflare Zero Trust setzen Sie den Public Hostname auf:

```text
http://local-shell-mcp:8765
```

Bei Caddy, Nginx, Traefik, Nginx Proxy Manager oder einem anderen Reverse Proxy leiten Sie HTTPS-Verkehr an `127.0.0.1:8765` oder die Container-Netzwerkadresse weiter.

## 4. ChatGPT verbinden

Verwenden Sie den MCP-Endpoint:

```text
https://your-public-host.example.com/mcp
```

Folgen Sie der [ChatGPT-Connector-Anleitung](chatgpt-connector.md), um OAuth und Tool-Freigabe abzuschließen.

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

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Wenn Sie das Tunnel-Profil verwenden:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
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
| ChatGPT als Client hinzufügen | [ChatGPT connector](chatgpt-connector.md) |
| Tools auswählen und bessere Prompts schreiben | [Nutzungsmuster](../guides/usage-patterns.md) |
| Eine HPC-, NPU/GPU- oder NAT-Maschine anbinden | [Remote workers](../guides/remote-workers.md) |
| Alle MCP-Tools verstehen | [Tool-Referenz](../reference/tools.md) |
