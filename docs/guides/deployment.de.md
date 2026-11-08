<!-- i18n-source-sha256: cef0a90f9de3e2806e2a6bd8925217ea44ea6d6e6bce911eea09b1d4192a82d9 -->
# Runtime-Auswahl und Bereitstellungsmodell

`local-shell-mcp` hat zwei komplementäre Entscheidungen:

1. **Runtime**: wie der Serverprozess läuft und welchen Workspace er kontrolliert.
2. **Schnittstelle**: Verwenden Sie den optionalen [unified web workspace](../getting-started/web-workspace.md) oder verbinden Sie einen externen MCP-Client wie Gemini oder ChatGPT.

**Der Controller wird bevorzugt als einzelne ausführbare Datei bereitgestellt**, ohne Python, Docker oder Quellcode. Weitere Runtimes bleiben verfügbar.

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

**Empfohlen:** Für öffentlichen Zugriff einen öffentlichen Server oder eine Weiterleitung über einen öffentlichen Server mit HTTPS-Reverse-Proxy verwenden. **Nicht empfohlen:** Bei Cloudflare Tunnel kann der clientseitige Upload sehr langsam sein, sodass Datei-Uploads und -Übertragungen kaum nutzbar sind. Nur verwenden, wenn direkte Bereitstellung oder Weiterleitung über einen öffentlichen Server nicht möglich ist. ([Public HTTPS exposure](../clients/connectivity.md))

## Runtime-Auswahlmatrix

| Laufzeit | Am besten für | Isolationsgrenze | Toolchain-Quelle | Externer MCP-Zugriff | Seite |
|---|---|---|---|---|---|
| **Einzeldatei (empfohlen)** | Die meisten unterstützten Plattformen | Host or VM | Hosttools plus konfiguriertes Executable | HTTPS-Proxy oder Tunnel hinzufügen | [Standalone binary](../installation/binary.md) |
| Docker Compose | Die meisten Coding-Agent-Workloads und wiederholbaren Arbeitsbereiche | Behälter | Lean Controller-Image; Installieren Sie aufgabenspezifische Toolchains separat | Fügen Sie einen HTTPS-Proxy oder -Tunnel hinzu | [Docker Compose](../installation/docker.md) |
| Docker Compose + Tunnel-Sidecar | Nicht empfohlen: Über öffentlichen Server weiterleiten; Cloudflare Tunnel nur als Notlösung | Behälter | Projektbild | Über öffentlichen Server weiterleiten; Cloudflare Tunnel nur als Notlösung | [Docker Compose](../installation/docker.md#cloudflare-tunnel-sidecar) |
| VS Code extension | Server aus Editor-Workspace starten/stoppen | Meist Hostprozess | Hosttools plus konfiguriertes Executable | Externen HTTPS-Tunnel/Proxy für ChatGPT hinzufügen | [VS Code extension](../installation/vscode-extension.md) |
| Quellcode / pipx | Entwicklung und Anpassung | Host virtualenv or VM | Python-Package plus Hosttools | HTTPS-Proxy oder Tunnel hinzufügen | [Python install](../installation/python.md) |
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

**Die Einzeldatei bevorzugen**: passende Version herunterladen und in einem begrenzten Arbeitsverzeichnis unter einem eingeschränkten Konto starten. [Binäranleitung](../installation/binary.md).

Verwenden Sie die **VS-Code-Erweiterung**, wenn der Workflow von einem Editor aus gestartet wird und Sie einen lokalen Launcher wünschen. Es ist immer noch eine Laufzeit. Remote-Webclients benötigen einen erreichbaren HTTPS-Proxy oder -Tunnel.

**Quellcodeinstallationen** dienen Entwicklung, Debugging und Anpassung mit virtueller Python-Umgebung. [Python-Anleitung](../installation/python.md).

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
