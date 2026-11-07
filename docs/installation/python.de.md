<!-- i18n-source-sha256: c8c0d8ebdbb123b9ac4af1fd288f30e8ca69037ca086486cb8027e2592f4b75a -->
# Python-, pipx- und Source-Runtimes

**Die direkte Installation aus dem Quellcode wird empfohlen.** Verwenden Sie eine virtuelle Python-Umgebung und einen begrenzten Workspace. Docker Compose bleibt eine Alternative.

Diese Seite behandelt drei verwandte Fälle:

- `pipx install local-shell-mcp`: Installation eines ausführbaren Programms auf Benutzerebene.
- `pip install local-shell-mcp`: Installation in einer vorhandenen virtuellen Umgebung.
- Editable source checkout: Entwicklung oder Debugging des Projekts selbst.

## pipx-Installation

`pipx` ist für normale Benutzer die sauberste Python-basierte Installation, da der Befehl seine eigene virtuelle Umgebung erhält und gleichzeitig ein ausführbares Programm in `PATH` bereitgestellt wird.

```bash
pipx install local-shell-mcp
local-shell-mcp --help
```

Starten Sie einen lokalen HTTP-MCP-Server:

```bash
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
local-shell-mcp --mode mcp
```

Prüfen Sie den Zustand:

```bash
curl -i http://127.0.0.1:8765/healthz
```

## Installation in einer virtuellen Umgebung

Verwenden Sie dies, wenn Sie Python-Umgebungen bereits selbst verwalten:

```bash
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install local-shell-mcp
local-shell-mcp --mode mcp
```

Der Prozess verwendet die auf dem Host installierten Werkzeuge. Das Python-Paket installiert keine Compiler, Git, Browser-Systemabhängigkeiten oder Projektabhängigkeiten für Sie.

## Editable source checkout

Für reguläre Bereitstellung und Entwicklung verwenden. Öffentlichen Zugang konfigurieren gemäß [quickstart](../getting-started/quickstart.md).

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e .
cp .env.example .env
# Replace the example OAuth secrets in .env before starting.
set -a
. ./.env
set +a
mkdir -p workspaces/default
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspaces/default"
local-shell-mcp --mode mcp
```

Prüfungen ausführen:

```bash
python -m pip install -e '.[dev,docs]'
ruff check .
pytest -q
mkdocs build --strict
```

## Browser-Einrichtung

Playwright ist optional; installieren Sie die Bibliothek und einen Browser bei Bedarf.

```bash
python -m pip install -e '.[browser]'
python -m playwright install chromium
```

Die Browserinstallation ist optional; das Docker-Basisimage enthält weder Playwright noch Browser.

## Öffentliche HTTP-MCP-Nutzung

Für ChatGPT oder einen anderen öffentlichen HTTP-MCP-Client konfigurieren Sie dieselben Public-Origin- und OAuth-Einstellungen wie bei anderen HTTP-Runtimes und veröffentlichen den lokalen Port über Reverse Proxy oder Tunnel.

Der öffentliche MCP-Endpoint lautet:

```text
https://your-public-host.example.com/mcp
```

## Entwicklungsmodi

| Mode | Command | Verwendung |
|---|---|---|
| MCP HTTP | `local-shell-mcp --mode mcp` | Vollständige MCP-Clients über HTTP, einschließlich ChatGPT hinter HTTPS |
| REST-style HTTP | `local-shell-mcp --mode http` | Diagnose- oder Kompatibilitäts-Endpunkte, nicht der Hauptpfad für ChatGPT |
| stdio | `local-shell-mcp --mode stdio` | Lokale MCP-Clients, die den Prozess starten |

`mode=both` ist reserviert und sollte derzeit nicht als Modus eines einzelnen Prozesses verwendet werden.

## Sicherheit des Host-Runtime

Python-Installationen laufen als Ihr Host-Benutzer, sofern Sie sie nicht in eine VM oder einen Container legen. Halten Sie den Workspace eng, den Full-Container-Modus deaktiviert und richten Sie den Workspace nicht auf ein Home-Verzeichnis.

Verwenden Sie Docker Compose für nicht vertrauenswürdige Repositories, paketmanager-intensive Aufgaben oder Workflows, bei denen Zurücksetzbarkeit wichtiger als Host-Integration ist.
