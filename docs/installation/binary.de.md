<!-- i18n-source-sha256: ed47d5e0691f17af5cd4758981c31957e299202bf72433b34b4656346312091e -->
# Eigenständiger Binary-Runtime

Empfohlen ist die **einzelne ausführbare Controller-Datei** von GitHub Releases, ohne Python, Docker oder Quellcode-Checkout.

Dies ist eine Runtime-Entscheidung. Der ChatGPT-Zugriff wird separat über einen HTTPS-`/mcp`-Endpoint konfiguriert.

## Release-Artefakte

GitHub Releases erstellen selbständige ausführbare Dateien für gängige Plattformen:

| Platform artifact | Archive |
|---|---|
| `local-shell-mcp-linux-x86_64` | `.tar.gz` |
| `local-shell-mcp-linux-aarch64` | `.tar.gz` |
| `local-shell-mcp-macos-x86_64` | `.tar.gz` |
| `local-shell-mcp-macos-aarch64` | `.tar.gz` |
| `local-shell-mcp-windows-x86_64` | `.zip` |

Jedes Archiv enthält die ausführbare Datei, README, Lizenz und eine kurze Quickstart-Datei.

Die Release-Seite bietet auch eine **einzelne ausführbare Datei**. Enthalten sind nur Controller und native WebUI; Chat-Datenbanken, Worker, Entwicklerwerkzeuge und Browser bleiben separat.

## Installation

1. Laden Sie die Einzeldatei oder das passende Archiv von [GitHub Releases](https://github.com/fwerkor/local-shell-mcp/releases/latest) herunter.
2. Falls Sie ein Archiv gewählt haben, entpacken Sie es.
3. Legen Sie die ausführbare Datei in `PATH` oder notieren Sie den absoluten Pfad.
4. Führen Sie `local-shell-mcp --help` aus, um den Start des Binary zu prüfen.

Beispiel: direktes Herunterladen der Linux-x86_64-Datei; für andere Plattformen das passende Release auswählen:

```bash
mkdir -p ~/lsm && cd ~/lsm
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp
chmod +x local-shell-mcp
./local-shell-mcp --help
```

Unter Windows führen Sie `local-shell-mcp.exe` in PowerShell aus oder nehmen das enthaltende Verzeichnis in `PATH` auf.

## Minimale lokale Ausführung

```bash
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
~/lsm/local-shell-mcp --mode mcp
```

In einem anderen Terminal:

```bash
curl -i http://127.0.0.1:8765/healthz
```

## Öffentliche HTTP-MCP-Ausführung

Für ChatGPT oder einen öffentlichen HTTP-MCP-Client konfigurieren Sie folgende Kategorien:

| Setting | Purpose |
|---|---|
| `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | Von Tools kontrolliertes Verzeichnis |
| `LOCAL_SHELL_MCP_HOST` and `LOCAL_SHELL_MCP_PORT` | Lokale Bind-Adresse und Port |
| `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | Öffentlicher HTTPS-Origin ohne `/mcp` |
| `LOCAL_SHELL_MCP_AUTH_MODE` | Für öffentliche Bereitstellungen `oauth` verwenden |
| OAuth PIN and JWT secret settings | Für öffentliche OAuth-Autorisierung erforderlich |

Veröffentlichen Sie den lokalen HTTP-Port über Reverse Proxy oder Tunnel. Der öffentliche Endpoint ist:

```text
https://your-public-host.example.com/mcp
```

## YAML-Konfiguration

Nicht geheime Runtime-Standards können in einer YAML-Konfiguration liegen:

```yaml
host: 127.0.0.1
port: 8765
mode: mcp
workspace_root: /srv/local-shell-mcp/workspace
auth_mode: oauth
public_base_url: https://your-public-host.example.com
```

Ausführen:

```bash
local-shell-mcp --config /path/to/config.yaml
```

Umgebungsvariablen mit Präfix `LOCAL_SHELL_MCP_` überschreiben YAML-Werte.

## Verantwortung für den Host-Toolchain

Das Binary enthält die Python-Anwendung, nicht jedes Entwicklerwerkzeug. MCP-Tools rufen Programme auf, die auf dem Host verfügbar sind.

Installieren Sie, was Ihre Aufgaben benötigen:

| Capability | Host packages to consider |
|---|---|
| Search and shell ergonomics | `ripgrep`, `tree`, `jq`, `curl`, `wget`; Linux-Releases enthalten bereits einen static tmux helper |
| Git workflows | `git`, `gh`, OpenSSH client, credential helpers |
| Python projects | Python, pip, venv, project-specific compilers and headers |
| Node projects | Node.js, npm, pnpm, yarn |
| Rust/Go/Java/C++ | Cargo/rustc, Go, JDK, Maven/Gradle, compilers, CMake, Ninja |
| Browser automation | Playwright browser binaries and OS dependencies |
| Document conversion | LibreOffice, Pandoc, Poppler utilities |

Die Binärdatei enthält den Controller; externe Werkzeuge und Browser sind optional. Chat und Verlauf werden separat im [Web-Arbeitsbereich](../getting-started/web-workspace.md) mit Datenbank bereitgestellt.

## Lang laufender Dienst

Für eine dauerhafte öffentliche Bereitstellung führen Sie das Binary unter dem Process Supervisor Ihres Betriebssystems aus. Beachten Sie:

- Dediziertes OS-Konto mit geringen Rechten.
- Dediziertes Workspace-Verzeichnis.
- Sensible Werte außerhalb world-readable Dateien speichern.
- Bei Fehler automatisch neu starten.
- Nach jedem Neustart `/healthz` prüfen.
- Logs für Fehlerbehebung aufbewahren.

## Updates

1. Die Release-Datei austauschen und Controller neu starten:
2. Optional Prüfsummen verifizieren.
3. Ausführbare Datei ersetzen.
4. Process Manager neu starten.
5. `/healthz` prüfen.
6. Vor weiterer Arbeit den Client `environment_get` ausführen lassen.

## Sicherheitshinweise

Das Binary läuft mit den Rechten seines Betriebssystembenutzers. Verwenden Sie für öffentliche Bereitstellungen einen dedizierten Benutzer mit niedrigen Rechten, einen dedizierten Workspace und wenn möglich eine VM-/Container-Grenze.

Setzen Sie `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true` nicht für ein Binary, das direkt auf Ihrem persönlichen Host läuft. Diese Einstellung ist für wegwerfbare Container oder VMs gedacht.
