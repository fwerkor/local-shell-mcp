<!-- i18n-source-sha256: 9deaf97f0af15e7af335b40fcf9fe8bc468623d1947e6f8c9afaf7dfaebcc036 -->
# DeepSeek Harness (DSH)

`local-shell-mcp` można zainstalować bezpośrednio w profilu Web DeepSeek Harness. Repository zawiera DSH-aware bridge, który zachowuje pełną powierzchnię narzędzi LSM, mapuje każdą DSH Session na stabilną v4 logical-session identity i dodaje **Live Workspace** jako natywny DSH conversation view. LSM pozostaje authority dla execution state: maszyny local/remote, logical Sessions i Goal Plans, persistent terminals, jobs, browser sessions, Dynamic MCP, file links, audit oraz Live Workspace timeline.

## Zalecana topologia

Uruchamiaj DSH i LSM bezpośrednio na tej samej machine. Każda DSH Session używa własnego LSM MCP connection i domyślnie łączy się z `127.0.0.1:8765/mcp`.

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

Machine uruchamiająca LSM jest targetem LSM `local`. Jeśli LSM działa w containerze, `local` oznacza ten container, a nie automatycznie DSH host. LSM domyślnie słucha na `0.0.0.0:8765`, DSH bundle używa loopback; po poprawnym ustawieniu network, firewall, public URL i authentication ten sam controller może też obsługiwać Remote Workers i external clients.

## Instalacja

Najpierw uruchom LSM:

```bash
local-shell-mcp --mode mcp
```

Następnie zainstaluj dedykowany pakiet npm DSH w profilu Web DSH:

```bash
dsh plugin --profile web add local-shell-mcp-dsh
```

Pakiet npm DSH używa tej samej wersji wydania co LSM. Do pracy deweloperskiej z checkoutu zainstaluj bieżący katalog:

```bash
dsh plugin --profile web add .
```

Bundle ładuje `local-shell-mcp-dsh` z `cordis.patch.yml`; DSH otrzymuje model-facing LSM tools w normalnym MCP namespace, np.:

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

Bridge celowo zachowuje pełny LSM catalog, w tym Remote Workers. Internal app-only `live_workspace_reconnect` służy tylko bridge i nie jest wystawiany modelowi. Jeśli potrzebny jest mniejszy model tool set, zastosuj później DSH-side `ctx.tools.restrict()` zamiast usuwać capability z LSM bundle.

## Binding DSH Session i LSM logical Session

Integracja opiera się na v4 logical-session runtime. Każda DSH Session ma własny upstream Streamable HTTP MCP client, a bridge wysyła opaque deterministic session-affinity pochodzącą z DSH Session id, tworząc następujący stabilny identity chain:

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

Tool activity z różnych DSH conversations nie miesza się w jednej Live Workspace timeline. Po restart DSH MCP transport jest odtwarzany z tą samą affinity, więc logical Session i active run pozostają attached, dopóki LSM controller posiada Session. Bridge okresowo ping active MCP clients, aby normalny idle cleanup nie zrywał długich conversations.

## Live Workspace wewnątrz DSH

DSH browser plugin dodaje **Live Workspace** do `conversation.view` i reuse istniejącą implementację v4. View jest scoped do current DSH Session i pokazuje logical Session, Plan/Goal state, Activity, terminals, files, diff, jobs, remotes i audit. **Ask** oraz Goal auto-continuation wracają do tej samej DSH conversation. Credential jest pobierana server-side przez DSH host poprzez MCP connection tej Session i nie trafia do conversation ani model-visible tool result.

## Dlaczego HTTP zamiast stdio

Remote Workers potrzebuje więcej niż MCP tools: controller `/remote/*` HTTP routes obsługują registration, polling, heartbeats, result delivery i transfer traffic. stdio-only child process utraciłby service plane i stworzył drugi controller state domain. Użycie działającego LSM HTTP service utrzymuje jedną authority dla Remote Workers, browser state, jobs, Dynamic MCP, audit, file links, logical Sessions i Live Workspace.

## Konfiguracja

DSH Host bridge przyjmuje następujące environment variables:

| Variable | Default | Cel |
|---|---|---|
| `DSH_LSM_MCP_URL` | `http://127.0.0.1:8765/mcp` | LSM Streamable HTTP MCP endpoint używany przez DSH. |
| `DSH_LSM_AUTHORIZATION` | unset | Optional pełna wartość header `Authorization`, np. `Bearer ...`. |
| `DSH_LSM_TOOL_CALL_TIMEOUT_MS` | `120000` | Timeout per tool call w milliseconds. |
| `DSH_LSM_KEEPALIVE_INTERVAL_MS` | `30000` | Ping interval utrzymujący long-lived per-Session MCP identity; minimum 5000 ms. |
| `DSH_LSM_BROWSER_URL` | unset | Browser-reachable LSM origin, gdy różni się od Host-side MCP origin. |

Same-host deployments zwykle nie wymagają authorization header, ponieważ LSM localhost auth bypass jest default włączony. Nie expose unauthenticated LSM do public network. Dla protected remote controller ustaw endpoint i bearer token:

```bash
export DSH_LSM_MCP_URL='https://lsm.example.com/mcp'
export DSH_LSM_AUTHORIZATION='Bearer <token>'
dsh --profile web
```

Bridge wysyła fixed upstream headers i nie uruchamia interactive OAuth authorization/refresh flow w imieniu DSH.

### Remote DSH Web browsers

`DSH_LSM_MCP_URL` jest resolve przez DSH **Host** process, lecz Live Workspace API requests działają w browser użytkownika. Jeśli remote-hosted DSH zwraca LSM loopback URL niedostępną z browsera, ustaw browser-reachable LSM origin:

```bash
export DSH_LSM_BROWSER_URL='https://lsm.example.com'
```

Live Workspace token nadal authorize te browser API requests.

## Remote Workers

Remote Worker mode pozostaje w pełni dostępny przez DSH. `mcp__lsm__remote_manage`, `mcp__lsm__remote_transfer` i normal LSM tools z `machine` używają tego samego controller i remote-worker state. External workers wymagają zwykłej konfiguracji public URL/network exposure LSM; DSH może nadal używać MCP loopback.

## Lifecycle i failure behavior

Bundle nie uruchamia innego LSM process. Może startować przy unavailable LSM; catalog connection reconnect z backoff i później sync tool catalog. Model tool calls nie są auto-replay po ambiguous transport failure, aby mutating call nie wykonał się dwa razy. Stable affinity/keepalive obsługują normal transport recreation/idle; real controller replacement korzysta z durable Session recovery deployment. Usunięcie plugin usuwa tylko DSH-side integration:

```bash
dsh plugin --profile web remove local-shell-mcp-dsh
```

Nie zatrzymuje LSM.

## Weryfikacja instalacji

Inspect composed DSH profile:

```bash
dsh --profile web --dump-config
```

Output powinien zawierać row z `id: local-shell-mcp`, `name: local-shell-mcp-dsh`, `url: http://127.0.0.1:8765/mcp`.

```text
id: local-shell-mcp
name: local-shell-mcp-dsh
url: http://127.0.0.1:8765/mcp
```

Gdy LSM jest online, DSH powinien expose m.in. następujące `mcp__lsm__*` tools:

```text
mcp__lsm__run_shell
mcp__lsm__remote_manage
mcp__lsm__remote_transfer
mcp__lsm__browser_session
mcp__lsm__session_manage
```

W DSH Web non-empty conversation pokazuje też **Live Workspace**. Jeśli integration brakuje, sprawdź `DSH_LSM_MCP_URL`, LSM `/healthz`, `/mcp` reachability, DSH Host log oraz `DSH_LSM_BROWSER_URL`, jeśli problem dotyczy tylko embedded UI.
