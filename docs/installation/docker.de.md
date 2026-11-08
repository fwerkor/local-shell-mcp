<!-- i18n-source-sha256: f769f579039e6eae80c7c955b80248ae0919448b2f5ca18ea4588ee66b0beba1 -->
# Docker-Compose-Runtime

Für die meisten Nutzer ist die [Einzeldatei-Binärversion](binary.md) erste Wahl; Docker Compose eignet sich für isolierte Container.

Dies ist eine Runtime-Auswahl. Sie kann mit ChatGPT oder einem generischen HTTP-MCP-Client verbunden oder nur lokal für Tests genutzt werden.

## Inhalt des Docker-Images

Das Image basiert auf python:3.12-slim und enthält nur grundlegende Laufzeitwerkzeuge. Große Entwicklungs-Toolchains, Playwright/Browser und Office-Suiten sind nicht vorinstalliert.

Enthaltene Kategorien:

| Kategorie | Beispiele |
|---|---|
| Shell und Inspektion | Bash, curl, wget, jq, ripgrep, tree, tmux, patch, file |
| Git und Credentials | Git, GitHub CLI, OpenSSH client, credential persistence volume |
| C/C++ build | Nicht enthalten; bei Bedarf installieren |
| Python | Python 3.12, pip, virtualenv |
| JavaScript/TypeScript | Nicht enthalten; bei Bedarf installieren |
| Weitere Sprachen | Nicht enthalten; bei Bedarf installieren |
| Browser-Automatisierung | Nicht enthalten; bei Bedarf installieren |
| Dokumentwerkzeuge | Nicht enthalten; bei Bedarf installieren |

Der exakte Image-Inhalt ist eine Komfortschicht und keine stabile API. Projektspezifische Abhängigkeiten gehören weiterhin in den Workspace oder die Build-Skripte des Projekts.

## Einfacher lokaler Start

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python scripts/init_compose_env.py
mkdir -p workspaces/default
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Das rohe CLI-Token bleibt ausschließlich in der hosteigenen `.env` (Modus `0600`). Compose übergibt nur den SHA-256-Prüfwert an den Container. So kann sich `lsm call` über die veröffentlichte Docker-Portbrücke authentifizieren, ohne verwalteten Shell-Prozessen im Container ein wiederverwendbares privilegiertes Token zugänglich zu machen.

Die Standard-Compose-Datei bindet den Dienst an localhost:

```text
127.0.0.1:8765 -> container:8765
```

Das eignet sich für lokale Tests und für einen Reverse Proxy auf demselben Host.

## Workspace-Layout

Der Standard-Compose-Runtime mountet:

| Host-Pfad oder Volume | Container-Pfad | Zweck |
|---|---|---|
| `./workspaces/default` | `/workspace` | Kontrollierter Workspace, sichtbar für Tools |
| `local-shell-mcp-credentials` volume | `/persist/credentials` | Persistenter Git/GitHub/SSH/GPG-Credential-State |

Verwenden Sie ein Workspace-Verzeichnis pro Trust Boundary. Mounten Sie nicht aus Bequemlichkeit Ihr gesamtes Home-Verzeichnis.

## Erforderliche öffentliche Einstellungen

Für ChatGPT oder einen anderen öffentlichen HTTP-MCP-Client konfigurieren Sie `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

Erzeugen Sie ein JWT Secret z. B. mit:

```bash
openssl rand -hex 32
```

Die öffentliche MCP-URL ist:

```text
https://your-public-host.example.com/mcp
```

## Cloudflare Tunnel sidecar

**Nicht empfohlen:** Bei Cloudflare Tunnel kann der clientseitige Upload sehr langsam sein, sodass Datei-Uploads und -Übertragungen kaum nutzbar sind. Nur verwenden, wenn direkte Bereitstellung oder Weiterleitung über einen öffentlichen Server nicht möglich ist. Für öffentlichen Zugriff einen öffentlichen Server oder eine Weiterleitung über einen öffentlichen Server mit HTTPS-Reverse-Proxy verwenden. ([network connectivity](../clients/connectivity.md))

Die Compose-Datei enthält einen optionalen `cloudflared`-Service hinter dem Profil `tunnel`. Dadurch läuft der Tunnel neben dem MCP-Server.

Konfigurieren Sie `.env`:

```env
CLOUDFLARE_TUNNEL_TOKEN=<token from Cloudflare Tunnel>
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=<strong pin>
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=<strong random secret>
```

Starten Sie beide Services:

```bash
docker compose --profile tunnel up -d
```

Routen Sie in Cloudflare Zero Trust den Public Hostname zu:

```text
http://local-shell-mcp:8765
```

Dies ist Cloudflare Tunnel, nicht Cloudflare Access. `local-shell-mcp` verwaltet weiterhin sein eigenes OAuth für ChatGPT.
Der Compose-Service vertraut Forwarded Headers, weil sein veröffentlichter Port auf localhost beschränkt ist; dadurch bleibt die öffentliche Caller-Adresse für OAuth-PIN-Rate-Limiting erhalten. Wenn Sie den Container-Port direkt freigeben, ersetzen Sie `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS=*` durch die expliziten Adressen Ihrer vertrauenswürdigen Reverse Proxies.

## Reverse Proxy ohne Tunnel-Sidecar

**Empfohlen:** Für öffentlichen Zugriff einen öffentlichen Server oder eine Weiterleitung über einen öffentlichen Server mit HTTPS-Reverse-Proxy verwenden.
Wenn Sie bereits Caddy, Nginx, Traefik oder Nginx Proxy Manager verwenden, behalten Sie den normalen Compose-Service und leiten HTTPS weiter an:

```text
http://127.0.0.1:8765
```

Der Proxy muss diese Routen ohne Path-Stripping weiterleiten:

| Route | Zweck |
|---|---|
| `/mcp` | MCP streamable HTTP endpoint |
| `/healthz`, `/readyz` | Health Checks |
| `/.well-known/oauth-protected-resource` | OAuth-Resource-Metadata |
| `/.well-known/oauth-authorization-server` | OAuth-Authorization-Server-Metadata |
| `/oauth/register` | Dynamische Client-Registrierung |
| `/oauth/authorize` | Browser-Autorisierungsseite |
| `/oauth/token` | Token-Austausch |
| `/downloads/<token>` | Optionale Downloads erzeugter Dateien |
| `/join/<token>`, `/remote/*` | Optionaler Remote-worker-Bootstrap/Polling |

Siehe [network connectivity](../clients/connectivity.md) für Anforderungen an das Proxy-Verhalten.

## Full-Container-Modus

`LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=false` hält Filesystem-Operationen auf den Workspace beschränkt. Das ist der sicherere Default.

Setzen Sie nur dann `true`, wenn der Container absichtlich disposable ist und das Modell das gesamte Container-Filesystem bedienen soll. Dadurch werden eingebaute Command-/Path-Denylist-Beschränkungen entfernt.

```env
LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true
```

Aktivieren Sie Full-Container-Modus nicht für hostgestartete Runtimes wie VS Code extension oder ein Binary direkt auf Ihrem Laptop.

## Credentials

Der Docker-Runtime kann gängige Entwickler-Credentials in einem eigenen Volume persistieren. Das ist nützlich für GitHub-CLI-Login, Git-HTTPS-Credential-Helper, `.netrc`, SSH config und GPG-State.

Behandeln Sie das Credential-Volume als sensibel. Bevorzugen Sie repository-spezifische Deploy Keys, Fine-grained Tokens oder kurzlebige Credentials. Legen Sie keine breiten persönlichen Credentials in einen Workspace, den das Modell frei lesen kann.

SSH-Agent-Forwarding ist durch Mounten des Agent-Sockets möglich, erweitert aber das Vertrauen vom Container auf Ihren aktiven Agent. Nutzen Sie es nur, wenn Sie die Exposition verstehen.

## Updates

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Mit Tunnel-Sidecar:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
curl -i http://127.0.0.1:8765/healthz
```

Lassen Sie nach dem Upgrade zunächst einen Read-only-Check durchführen:

```text
Verwende local-shell-mcp. Rufe environment_get auf und führe file_list auf der Workspace-Wurzel aus. Ändere keine Dateien.
```

## Fehlerbehebung

| Symptom | Prüfen |
|---|---|
| `/healthz` schlägt lokal fehl | `docker compose ps`, `docker compose logs --tail=200 local-shell-mcp` |
| ChatGPT entdeckt keine Tools | Öffentliche URL muss mit `/mcp` enden; `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` darf `/mcp` nicht enthalten |
| OAuth-Seite schlägt fehl | Admin-PIN und JWT Secret müssen bei öffentlichen OAuth-Deployments gesetzt sein |
| Tools sehen Dateien nicht | Prüfen, dass das gewünschte Host-Verzeichnis auf `/workspace` gemountet ist |
| Browser-Tools schlagen fehl | Playwright-Image aktualisieren; `run_shell` für den Zielbrowser versuchen |
| Git-Auth ist verschwunden | Credential-Volume und Wiederverwendung desselben Volumes beim Container-Neustart prüfen |
