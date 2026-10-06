<!-- i18n-source-sha256: 5f07217e742810704f1919224f6cf68bf7b4f5ecf635fadd5ec4d21b072ce6b2 -->
# Benutzeroberfläche

`local-shell-mcp` bietet zwei kompatible Benutzerschnittstellen über derselben Service-API, demselben Workspace, Persistent-Terminal-Register, Remote-Worker-Register und MCP-Audit-Log:

- **Web UI** ist ein natives Browser-Dashboard für schnelle Betriebsprüfungen.
- **OpenTUI** ist die vollständige terminalorientierte Anwendung und steht sowohl im Browser als auch als nativer Terminalbefehl zur Verfügung.

Keiner der Modi erzeugt eine separate Control Plane. Ein Wechsel der Oberfläche ändert keine verbundenen Maschinen, Sessions, Jobs, Berechtigungen oder Audit-Daten.

## Dienst starten

Starten Sie `local-shell-mcp` wie gewohnt:

```bash
local-shell-mcp --mode mcp
```

## ChatGPT Live Workspace

Wenn ChatGPT MCP Apps rendert, öffnet `workspace_open(session_id=...)` eine schwebende kollaborative Ansicht der **explizit ausgewählten Logical Session**. Die Session besitzt den dauerhaften Task-Zustand – objective, progress, Plan und Activity – während Live Workspace nur diesen Zustand, Live-Aktivität und menschliche Steuerungen darstellt. Die Task-Identität wird niemals aus dem MCP-Transport abgeleitet.

Eine typische explizite Übergabe sieht so aus:

```text
session_manage(action="start", objective=...)
        -> session_id
... Tool-Aufrufe mit logical_session_id=session_id
... session_manage(action="report", session_id=...) ...
neue ChatGPT-Unterhaltung
Benutzer übergibt die bisherige session_id
session_manage(action="resume", session_id=...)
        -> vorhandener progress, Plan und letzte Activity
workspace_open(session_id=...)
        -> Ansicht derselben Session
```

`session_id` ist die einzige dauerhafte Task-Identität. Ein Agent darf Sessions aus anderen Unterhaltungen weder auflisten noch ableiten oder automatisch auswählen. Um die Arbeit in einer neuen Unterhaltung fortzusetzen, übergibt der Benutzer die vorhandene `session_id` ausdrücklich. Der Agent soll die aktive `session_id` nach start/resume, an sinnvollen Fortschritts-Checkpoints und vor dem Ende eines Turns nennen, damit sie manuell weitergegeben werden kann. Sessions sind nicht an machine oder working directory gebunden; normale Tool-Parameter wählen weiterhin lokale/entfernte Ziele und Pfade.

Ein optionaler `plan_manage`-Plan aktiviert den Goal mode der Session. Ist der Plan active und gibt es 15 Minuten lang keine agent activity, kann ein zugeordnetes Live Workspace ChatGPT zur Fortsetzung auffordern. Die Fortsetzung nimmt dieselbe explizite `session_id` wieder auf und ist auf 10 Versuche begrenzt, unabhängig davon, ob sie angenommen oder abgelehnt werden. blocked, completed und cancelled Plans werden nicht automatisch fortgesetzt; ein active Plan, dessen steps alle completed oder skipped sind, bleibt für eine abschließende continuation geeignet, damit der resumed agent den Plan beenden kann. Menschliche pause/resume/cancel-Steuerungen aktualisieren den Session-eigenen Plan statt flüchtigen Live-Workspace-Zustand.

## Browseroberfläche

Öffnen Sie:

```text
http://127.0.0.1:8765/ui
```

Für eine öffentliche Bereitstellung verwenden Sie den konfigurierten HTTPS-Origin:

```text
https://your-public-host.example.com/ui
```

Die Browseroberfläche verwendet denselben OAuth-Server und dieselben Scopes wie MCP. Seitengerüst und statische Assets sind öffentlich, damit der Login-Bildschirm geladen werden kann; `/api/ui/*` und der OpenTUI-Terminal-WebSocket bleiben geschützt. Zugriffstoken werden nur im Session Storage des Browsers gespeichert.

### Oberfläche wählen

Der OAuth-Bildschirm bietet zwei Einstiegspunkte:

- **Open Web UI** autorisiert und öffnet das native Dashboard.
- **Continue to OpenTUI** autorisiert und öffnet die Terminaloberfläche unter Beibehaltung des bisherigen Browserverhaltens.

Nach der Autorisierung kann der Umschalter in der Seitenleiste ohne erneute Anmeldung zwischen Web UI und OpenTUI wechseln. Die aktuelle native Seite wird beim vorübergehenden Wechsel zu OpenTUI gespeichert.

Die Routen können als Lesezeichen gespeichert werden:

```text
/ui/#/overview
/ui/#/machines
/ui/#/workloads
/ui/#/activity
/ui/#/console
```

`#/web` und `#/dashboard` sind Aliase für Overview. `#/tui` und `#/opentui` sind Aliase für Console.

## Native Web UI

Die native Web UI fragt die vorhandene Human-Interface-API alle fünf Sekunden ab und rendert browsernative Steuerelemente statt Terminalzellen. Ein PTY wird erst gestartet, wenn OpenTUI ausgewählt wurde.

### Overview

Overview zeigt die wichtigsten Betriebsinformationen zuerst:

- Zustand des Controllers und aktuelle LSM-Version.
- Anzahl der Online- und Offline-Maschinen.
- Aktive tracked Jobs und persistente Terminal-Sessions.
- CPU, Arbeitsspeicher, Workspace-Datenträger, Load, Netzwerkdurchsatz und Uptime.
- Warnungen aus worker-Status, Ressourcenschwellen, fehlgeschlagenen Jobs und fehlgeschlagenen MCP-Aufrufen.
- Letzte vom Modell ausgelöste MCP-Aktivität.

### Machines

Machines listet den lokalen Controller und verbundene Remote-worker mit Status, Plattform, Version, Arbeitsverzeichnis, Fähigkeiten und Last-seen-Informationen auf.

### Workloads

Workloads kombiniert aktive tracked Jobs und eigenständige persistente Shell-Sessions. In der Web UI sind diese Datensätze nur lesbar; für interaktive Sitzungsverwaltung verwenden Sie OpenTUI.

### Activity

Activity kombiniert aktuelle Warnungen mit jüngster MCP-Audit-Aktivität. Von Menschen eingegebene Befehle und Dateioperationen bleiben aus dem MCP-Audit-Log ausgeschlossen.

## OpenTUI im Browser

Durch Auswahl von **OpenTUI** wird dieselbe OpenTUI-Anwendung wie beim nativen Terminal-Launcher verzögert gestartet. Die Browserkonsole behält:

- Authentifizierten binären PTY-Transport über WebSocket.
- Automatische Terminalgrößenanpassung und Reconnect-Backoff.
- Mausinteraktion mit OpenTUI-Steuerelementen.
- Vollbildmodus und browsersichere Tastenkürzel.
- Mobile Schnellwahltasten und explizite Bildschirmtastatursteuerung.
- SIXEL- und Inline-image-Unterstützung über xterm.js.

Der Browser erstellt kein OpenTUI-PTY, solange der Benutzer im nativen Web-UI-Modus bleibt.

## Native OpenTUI

Eigenständige Release-Executables enthalten die plattformspezifische OpenTUI-Runtime. Behalten Sie nur die Hauptdatei, starten Sie den Dienst und führen Sie aus:

```bash
local-shell-mcp tui
```

Die native TUI verlangt vom menschlichen Bediener keine Anmeldung. Im dokumentierten Docker-Compose-Setup verwendet der Launcher für die Human-UI-API über Loopback dieselbe hostseitige dedizierte CLI-Berechtigung; für andere Split-Runtime-Layouts steht `--token-file` zur Verfügung. Vom Browser gestartete OpenTUI-Instanzen verwenden eine nur im Controller-Prozess gehaltene Berechtigung, die erst bei Bedarf erzeugt und weder im State Directory noch im State Backend gespeichert wird. Ein Reverse Proxy erhält keinen dieser lokalen Bypässe allein dadurch, dass er über Loopback verbindet.

Ein Source-Checkout kann die TUI nach Installation der Bun-Abhängigkeiten ebenfalls ausführen:

```bash
cd ui
bun install --frozen-lockfile
bun run build
cd ..
local-shell-mcp tui
```

Verwenden Sie `--api-base` nur, wenn der lokale Dienst einen nicht standardmäßigen Port nutzt:

```bash
local-shell-mcp tui --api-base http://127.0.0.1:9876/api/ui
```

## OpenTUI-Bildschirme

### Dashboard

Dashboard ist die Betriebsübersicht von OpenTUI. Breite Terminals zeigen getrennte Bereiche für Node, Workload, Alert, Activity, Systeminformationen und Trends; schmalere Terminals fassen sie ohne horizontales Scrollen kompakt zusammen.

### Files

Files ist ein LSM-nativer Dateimanager mit drei Bereichen für lokale und entfernte Maschinen. Er unterstützt Erstellen, Bearbeiten, Umbenennen, Kopieren, Verschieben, Einfügen, Löschen, Umschalten versteckter Dateien, Aktualisieren, Textvorschau, Binärvorschau und begrenzte Bildminiaturen.

### Terminals

Terminals verwaltet persistente Shell-Sessions auf lokalen und entfernten Maschinen. Unterstützt werden vollständige Befehlseingabe, rohe interaktive Eingabe, Sitzungswechsel, Erstellung und Beendigung von Sessions, letzte Ausgabe sowie eine einklappbare MCP-Audit-Leiste.

### Audit

Audit liest das begrenzte JSONL-Audit-Log und unterstützt Filter nach Node, Operation, Event, Session, Search, Time-range und Sort sowie die Detailansicht einzelner Datensätze.

### Remotes

Remotes zeigt Online- und Offline-Remote-worker, Fähigkeiten, Arbeitsverzeichnisse und Systemmetadaten. Es kann eine einmalige Join-Einladung erzeugen, einen Node umbenennen oder seine persistente Identität widerrufen.

## OpenTUI-Navigation

Die obere Kategorienleiste und kontextbezogene Footer-Aktionen können sowohl in nativen Terminals als auch in der Browserkonsole mit der Maus angeklickt werden.

| Tasten | Aktion |
|---|---|
| `Alt+1` … `Alt+5` | Öffnet Dashboard, Files, Terminals, Remotes oder Audit. |
| `F2` … `F6` | Alternative Kategorie-Shortcuts. |
| `F1` | Tastaturhilfe öffnen. |
| `F9` | Maschinenliste aktualisieren. |
| `Alt+Q` | Nativen OpenTUI-Prozess beenden, ohne ein vom Browser reserviertes Ctrl-Kürzel auszulösen. |

Terminals verwendet `Alt+N` für eine neue Session, `Alt+W` zum Beenden der ausgewählten Session, `Alt+A` zum Umschalten der Audit-Leiste, `Alt+R` zum Aktualisieren und `Alt+Left/Right` zum Wechseln zwischen Sessions. Die Browserkonsole fängt diese Tastenkombinationen vor Browsernavigation oder Menüverarbeitung ab.

## Konfiguration

| YAML-Schlüssel | Umgebungsvariable | Standard | Zweck |
|---|---|---|---|
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `true` | Benutzeroberflächen einbinden oder deaktivieren. |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `/ui` | Mount-Pfad der Browseroberfläche im MCP-Dienst. |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | auto | Auflösung des nativen OpenTUI-Executables überschreiben. |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `bing` | Hintergrund-Einstellung für OpenTUI-Browserkonsolen-Bereitstellungen. |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | Inaktives Browser-OpenTUI-PTY nach dieser Sekundenzahl schließen; `0` deaktiviert das Timeout. |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | Maximale Zahl gleichzeitiger Browser-OpenTUI-PTY-Sessions. |

## Hinweise zur Paketierung

- Docker-Images enthalten die Web-UI-Assets und die native OpenTUI-Runtime.
- Eigenständige Executables enthalten die Web-UI-Assets und eine komprimierte plattformspezifische OpenTUI-Runtime.
- Python-Wheels enthalten Browser-Assets; native OpenTUI benötigt ein Release-Executable oder einen Source-Checkout mit installierten Bun-Abhängigkeiten.
- Beide Oberflächen werden vom selben Prozess und Port wie MCP bereitgestellt; ein zusätzlicher Webdienst ist nicht erforderlich.
