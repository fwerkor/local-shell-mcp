<!-- i18n-source-sha256: 6fa729155fcc9e524eb3f8081b80d40ceb72c59f5ece4b311809350005468851 -->
# DeepSeek Harness (DSH)

`local-shell-mcp` kann direkt in ein DeepSeek-Harness-Web-Profil installiert werden. Das Repository enthält eine DSH-aware Bridge, die die vollständige LSM-Tool-Oberfläche erhält, jede DSH Session einer stabilen v4-logical-session identity zuordnet und **Live Workspace** als native DSH conversation view beiträgt. LSM bleibt die Autorität für Ausführungszustand: lokale/remote Maschinen, logical Sessions und Goal Plans, persistente Terminals, Jobs, Browser Sessions, Dynamic MCP, File Links, Audit-Daten und Live-Workspace-Timeline.

## Empfohlene Topologie

DSH und LSM sollten direkt auf derselben Maschine laufen. Jede DSH Session verwendet eine eigene LSM-MCP-Verbindung und verbindet sich standardmäßig mit `127.0.0.1:8765/mcp`.

```text
DSH Web
  |
  | one LSM MCP connection per DSH Session
  | 127.0.0.1:8765/mcp
  v
local-shell-mcp :8765
  |-- local execution = this LSM host
  |-- /mcp
  |-- /remote/*
  |-- /ui
  |-- Live Workspace / audit / browser / jobs / links
  |
  +--> Remote Workers
```

Die LSM-Maschine ist dabei das LSM-Target `local`. Läuft LSM in einem Container, bezeichnet `local` diesen Container und nicht automatisch den DSH-Host. LSM lauscht standardmäßig auf `0.0.0.0:8765`, das DSH-Bundle nutzt loopback. Mit korrekt konfiguriertem Netzwerk, Firewall, Public URL und Authentifizierung kann derselbe Controller auch Remote Workers und externe Clients bedienen.

## Installation

Zuerst LSM starten:

```bash
local-shell-mcp --mode mcp
```

Dann dieses Repository in das DSH-Web-Profil installieren:

```bash
dsh plugin --profile web add local-shell-mcp-dsh
```

Für Production den Git-Spec auf ein geprüftes Release-Tag oder Commit pinnen. Für Entwicklung aus einem Checkout das aktuelle Verzeichnis installieren:

```bash
dsh plugin --profile web add .
```

Das Bundle lädt `local-shell-mcp-dsh` aus `cordis.patch.yml`; DSH erhält die model-facing LSM-Tools im normalen MCP-Namespace, zum Beispiel:

```text
mcp__lsm__run_shell
mcp__lsm__file_read
mcp__lsm__remote_manage
mcp__lsm__remote_transfer
mcp__lsm__browser_session
mcp__lsm__mcp_tool_search
mcp__lsm__session_manage
mcp__lsm__plan_manage
...
```

Die Bridge behält absichtlich den vollständigen LSM-Katalog einschließlich Remote-Worker-Fähigkeiten. Das interne app-only Tool `live_workspace_reconnect` dient nur der Bridge und wird dem Modell nicht gezeigt. Ein kleineres Tool-Set sollte später per DSH `ctx.tools.restrict()` erzwungen werden, statt Fähigkeiten aus dem LSM-Bundle zu entfernen.

## Bindung von DSH Session und LSM logical Session

Die Integration basiert auf der v4 logical-session runtime. Jede DSH Session erhält einen eigenen upstream Streamable-HTTP-MCP-Client; die Bridge sendet zusätzlich eine opaque deterministic session-affinity aus der DSH-Session-ID. Daraus entsteht folgende stabile Identitätskette:

```text
DSH Session A
  -> stable LSM session affinity A
  -> v4 MCP session key A
  -> LSM logical Session / active run A
  -> Live Workspace A

DSH Session B
  -> stable LSM session affinity B
  -> v4 MCP session key B
  -> LSM logical Session / active run B
  -> Live Workspace B
```

Tool-Aktivität verschiedener DSH conversations landet deshalb nicht in derselben Live-Workspace-Timeline. Nach einem DSH-Neustart wird der MCP-Transport mit derselben affinity neu erstellt; logical Session und active run bleiben angeheftet, solange der LSM controller diese Session besitzt. Periodische Pings verhindern außerdem, dass normales MCP idle cleanup lange DSH conversations trennt.

## Live Workspace in DSH

Das DSH-Browser-Plugin fügt **Live Workspace** zu `conversation.view` hinzu und verwendet die vorhandene v4-Implementierung statt eines zweiten UI/State-Modells. Die View ist auf die aktuelle DSH Session beschränkt und zeigt logical Session, Plan/Goal state, Activity, Terminals, Files, Diff, Jobs, Remotes und Audit. **Ask** und Goal Auto-Continuation gehen in dieselbe DSH conversation zurück. Credentials holt der DSH host server-side über die MCP-Verbindung dieser Session; sie erscheinen weder in der conversation noch in model-visible tool results.

## Warum HTTP statt stdio

Remote Workers brauchen neben MCP tools die `/remote/*`-HTTP-Routen für Registrierung, Polling, Heartbeats, Result Delivery und Transfer Traffic. Ein stdio-only Child Process würde diese Service Plane verlieren und eine zweite Controller-State-Domain schaffen. Der laufende LSM-HTTP-Service hält eine Authority für Remote Workers, Browser State, Jobs, Dynamic MCP, Audit, File Links, logical Sessions und Live Workspace.

## Konfiguration

Die DSH-Host-Bridge akzeptiert folgende Umgebungsvariablen:

| Variable | Standard | Zweck |
|---|---|---|
| `DSH_LSM_MCP_URL` | `http://127.0.0.1:8765/mcp` | LSM Streamable HTTP MCP Endpoint für DSH. |
| `DSH_LSM_AUTHORIZATION` | unset | Optionaler vollständiger `Authorization`-Header, z. B. `Bearer ...`. |
| `DSH_LSM_TOOL_CALL_TIMEOUT_MS` | `120000` | Timeout pro Tool Call in Millisekunden. |
| `DSH_LSM_KEEPALIVE_INTERVAL_MS` | `30000` | Ping-Intervall zum Erhalt langlebiger per-Session MCP identity; mindestens 5000 ms. |
| `DSH_LSM_BROWSER_URL` | unset | Browser-erreichbare LSM-Origin, wenn sie von der Host-seitigen MCP-Origin abweicht. |

Same-host Deployments benötigen normalerweise keinen Authorization-Header, weil LSMs localhost auth bypass standardmäßig aktiv ist. Stellen Sie keinen unauthentifizierten LSM-Service öffentlich bereit. Für einen geschützten Remote-Controller Endpoint und Bearer Token setzen:

```bash
export DSH_LSM_MCP_URL='https://lsm.example.com/mcp'
export DSH_LSM_AUTHORIZATION='Bearer <token>'
dsh --profile web
```

Die Bridge sendet feste Upstream-Header und führt keinen interaktiven OAuth authorization/refresh flow für DSH aus.

### Remote DSH-Webbrowser

`DSH_LSM_MCP_URL` wird vom DSH-**Host**-Prozess aufgelöst, Live-Workspace-API-Requests laufen jedoch im Browser des Benutzers. Ist DSH remote gehostet und die LSM-Loopback-URL dort nicht erreichbar, eine browser-erreichbare LSM-Origin setzen:

```bash
export DSH_LSM_BROWSER_URL='https://lsm.example.com'
```

Das Live-Workspace-Token autorisiert diese Browser-API-Requests weiterhin.

## Remote Workers

Remote Worker Mode bleibt über DSH vollständig verfügbar. `mcp__lsm__remote_manage`, `mcp__lsm__remote_transfer` und normale LSM-Tools mit `machine` verwenden denselben Controller und Remote-Worker-State wie andere LSM-Clients. Externe Worker benötigen die übliche Public-URL-/Netzwerk-Konfiguration; DSH kann weiterhin den Loopback-MCP-Endpoint verwenden.

## Lifecycle und Fehlerverhalten

Das Bundle startet keinen weiteren LSM-Prozess. Es kann auch ohne verfügbares LSM starten; die Catalog Connection reconnectet mit Backoff und synchronisiert Tools später. Model Tool Calls werden nach mehrdeutigen Transportfehlern nicht automatisch replayed, damit mutierende Calls nicht doppelt laufen. Stable affinity und Keepalive behandeln normale Transport-Recreation/Idle; ein echter Controller-Austausch folgt der Durable-Session-Recovery des Deployments. Plugin Removal entfernt nur die DSH-Integration:

```bash
dsh plugin --profile web remove local-shell-mcp-dsh
```

LSM wird dadurch nicht gestoppt.

## Installation prüfen

Das zusammengesetzte DSH-Profil prüfen:

```bash
dsh --profile web --dump-config
```

Die Ausgabe sollte eine Zeile mit `id: local-shell-mcp`, `name: local-shell-mcp-dsh` und `url: http://127.0.0.1:8765/mcp` enthalten.

```text
id: local-shell-mcp
name: local-shell-mcp-dsh
url: http://127.0.0.1:8765/mcp
```

Sobald LSM online ist, sollte DSH unter anderem folgende `mcp__lsm__*` Tools zeigen:

```text
mcp__lsm__run_shell
mcp__lsm__remote_manage
mcp__lsm__remote_transfer
mcp__lsm__browser_session
mcp__lsm__session_manage
```

In DSH Web bietet eine nichtleere conversation außerdem **Live Workspace**. Fehlt die Integration, prüfen Sie `DSH_LSM_MCP_URL`, LSM `/healthz`, `/mcp` reachability, DSH Host Log und bei ausschließlich eingebetteter UI-Störung `DSH_LSM_BROWSER_URL`.
