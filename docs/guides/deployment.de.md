<!-- i18n-source-sha256: 594169d44520f8abd7cebee1bfa42c5ff0ca31f424115d438107ed01b77fa604 -->
# Runtime-Auswahl und Bereitstellungsmodell

`local-shell-mcp` hat zwei komplementäre Entscheidungen:

1. **Runtime**: wie der Serverprozess läuft und welchen Workspace er kontrolliert.
2. **Schnittstelle**: Verwenden Sie den optionalen [unified web workspace](../getting-started/web-workspace.md) oder verbinden Sie einen externen MCP-Client wie Gemini oder ChatGPT.

Die empfohlene tägliche Schnittstelle ist der selbstgehostete Web-Workspace (Chat, Projekte und LSM-Kontrollseiten). Es wird getrennt vom Controller bereitgestellt. Docker, die VS Code-Erweiterung, Release-Binärdateien, Python-Installationen und der stdio-Modus sind Möglichkeiten, den Controller auszuführen; Externe Chat-Apps bleiben optionale Clients.

```text
Runtime layer                      Exposure layer                 Client layer
-------------------------------    ---------------------------    ----------------------
Docker Compose, nur lokaler HTTP-Einheitlicher Web-Arbeitsbereich
VS Code extension                  HTTPS reverse proxy/tunnel     Generic MCP client
Standalone binary                  stdio process pipe             VS Code extension UI
pipx / source checkout             remote-worker outbound join    REST-style diagnostics
```

Ein gängiges selbstgehostetes Setup ist:

```text
Browser -> https://chat.example.com (einheitlicher Webarbeitsbereich)
        -> authentifizierter Local-Shell-MCP-Controller
        -> Kontrollierter Arbeitsbereich und ausgehende Mitarbeiter
Optionaler externer Client -> https://mcp.example.com/mcp
```

Eine lokale MCP-Client-Einrichtung kann einfacher sein:

```text
Local MCP client
  -> starts local-shell-mcp --mode stdio
  -> controlled workspace
```

## Runtime-Auswahlmatrix

| Laufzeit | Am besten für | Isolationsgrenze | Toolchain-Quelle | Externer MCP-Zugriff | Seite |
|---|---|---|---|---|---|
| Docker Compose | Die meisten Coding-Agent-Workloads und wiederholbaren Arbeitsbereiche | Behälter | Lean Controller-Image; Installieren Sie aufgabenspezifische Toolchains separat | Fügen Sie einen HTTPS-Proxy oder -Tunnel hinzu | [Docker Compose](../installation/docker.md) |
| Docker Compose + Tunnel-Sidecar | Public Controller-Bereitstellung mit Cloudflare Tunnel | Behälter | Projektbild | Integriert in das Compose `tunnel`-Profil | [Docker Compose](../installation/docker.md#cloudflare-tunnel-sidecar) |
| VS Code extension | Server aus Editor-Workspace starten/stoppen | Meist Hostprozess | Hosttools plus konfiguriertes Executable | Externen HTTPS-Tunnel/Proxy für ChatGPT hinzufügen | [VS Code extension](../installation/vscode-extension.md) |
| Standalone binary | Hosts oder VMs ohne Docker | Host or VM | Hosttools plus konfiguriertes Executable | HTTPS-Proxy oder Tunnel hinzufügen | [Standalone binary](../installation/binary.md) |
| `pipx` / source install | Python-native Nutzung, Debugging, Entwicklung | Host virtualenv or VM | Python-Package plus Hosttools | HTTPS-Proxy oder Tunnel hinzufügen | [Python install](../installation/python.md) |
| Stdio mode | Lokale MCP-Clients, die Prozesse direkt starten | Client process boundary | Hosttools plus konfiguriertes Executable | Nicht mit ChatGPT web/app nutzbar | [Stdio mode](../installation/stdio.md) |

## Client-Verbindungsmatrix

| Schnittstelle | Erfordert öffentliches HTTPS | Verwendet `/mcp` | Erfordert OAuth | Typische Laufzeit |
|---|---:|---:|---:|---|
| Einheitlicher LSM-Webarbeitsbereich | Ja für Fernzugriff; Auch lokaler Proxy möglich | Intern | LSM-Login | Controller plus separater Web-Stack |
| Gemini Spark / Benutzerdefinierte Apps | Ja | Ja | Ja, für die öffentliche Nutzung | Jeder HTTP-Controller |
| ChatGPT custom MCP connector | Ja | Ja | Ja für öffentliche Nutzung | Docker, VS Code extension, binary, or Python |
| Generic local MCP client over stdio | Nein | Nein | Nein | `local-shell-mcp --mode stdio` |
| Generic HTTP MCP client | Für localhost meist nein; über Netzwerke ja | Ja | Außerhalb localhost empfohlen | Any HTTP runtime |
| VS Code extension helper flow | Nur wenn ChatGPT verbinden muss | Ja beim Kopieren der ChatGPT-URL | Für ChatGPT empfohlen | VS Code-launched runtime |

Siehe [unified web workspace](../getting-started/web-workspace.md), [Gemini Spark](../getting-started/gemini-spark.md), [ChatGPT connector](../getting-started/chatgpt-connector.md), [generic MCP clients](../clients/generic-mcp.md) und [network connectivity](../clients/connectivity.md).

## Was jeder Runtime kontrolliert

Jeder Runtime startet denselben Servercode und stellt bei Aktivierung dieselben MCP-Toolfamilien bereit:

- Shell und persistente Shell-Sessions.
- Filesystem-, Search- und Patch-Tools.
- Git-Operationen.
- Browser-Automatisierung über Playwright.
- Audit-Log und Task-State-Tools.
- Tokenisierte File Links.
- Optionale Remote-worker-Lifecycle- und Machine-routed-Tools.

Der Unterschied ist nicht die abstrakte API, sondern die **Betriebsumgebung** dahinter.

| Frage | Docker Compose | VS Code extension | Binary / Python |
|---|---|---|---|
| Wo laufen Befehle? | Im Container | Meist im Host-Workspace | In Host- oder VM-Prozessumgebung |
| Standard-Workspace? | Mounted `/workspace` | Aktueller VS-Code-Ordner oder konfigurierter Pfad | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` |
| Sind Compiler und Browser vorinstalliert? | NEIN; Installieren Sie, was die Aufgabe benötigt | Nur wenn auf dem Host installiert | Nur wenn auf dem Host installiert |
| Leicht zurücksetzbar? | Container und Workspace-Volume neu erstellen | Hängt vom Workspace ab | Hängt von Host/VM ab |
| Für beliebige Paketinstallationen geeignet? | Ja, wenn disposable | Riskanter auf Host | Riskanter außerhalb VM |

## Empfohlene Auswahl

Verwenden Sie zuerst **Docker Compose**, es sei denn, Sie haben einen Grund, dies nicht zu tun. Es bietet eine klare Sicherheitsgrenze, ohne dass eine große vorinstallierte Entwicklungs-Toolchain erforderlich ist.

Verwenden Sie die **VS-Code-Erweiterung**, wenn der Workflow von einem Editor aus gestartet wird und Sie einen lokalen Launcher wünschen. Es ist immer noch eine Laufzeit. Remote-Webclients benötigen einen erreichbaren HTTPS-Proxy oder -Tunnel.

Verwenden Sie **standalone binary**, wenn Docker nicht verfügbar ist, aber VM, Container-Host oder dediziertes Benutzerkonto bereits eine Grenze bieten.

Verwenden Sie **`pipx` oder source install** für Entwicklung/Debugging von `local-shell-mcp` oder wenn eine Python-Umgebung leichter zu pflegen ist.

Verwenden Sie **stdio mode** nur für lokale MCP-Clients, die den Serverprozess starten können. Es ist kein öffentliches Deployment und nicht direkt mit ChatGPT web/app nutzbar.

## Regel für öffentlichen Endpoint

Für externe HTTP-MCP-Clients wie Gemini und ChatGPT lautet der MCP-Endpunkt:

```text
https://your-public-host.example.com/mcp
```

`LOCAL_SHELL_MCP_PUBLIC_BASE_URL` ist nur der Origin:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

Hängen Sie `/mcp` nicht an `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` an.

## Runtime-Seiten

- [Docker Compose](../installation/docker.md)
- [VS Code extension](../installation/vscode-extension.md)
- [Standalone binary](../installation/binary.md)
- [Python, `pipx`, and source install](../installation/python.md)
- [Stdio mode](../installation/stdio.md)

## Client-Seiten

- [Unified web workspace](../getting-started/web-workspace.md)
- [Gemini Spark / Custom Apps](../getting-started/gemini-spark.md)
- [ChatGPT connector](../getting-started/chatgpt-connector.md)
- [Generic MCP clients](../clients/generic-mcp.md)
- [Public HTTPS exposure](../clients/connectivity.md)
