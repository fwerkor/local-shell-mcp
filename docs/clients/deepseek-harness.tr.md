<!-- i18n-source-sha256: 6fa729155fcc9e524eb3f8081b80d40ceb72c59f5ece4b311809350005468851 -->
# DeepSeek Harness (DSH)

`local-shell-mcp` doğrudan DeepSeek Harness Web profile içine kurulabilir. Repository’deki DSH-aware bridge tam LSM tool surface’i korur, her DSH Session’ı stable v4 logical-session identity ile eşler ve **Live Workspace**’i native DSH conversation view olarak ekler. Execution state authority LSM’de kalır: local/remote machine’ler, logical Sessions ve Goal Plans, persistent terminals, jobs, browser sessions, Dynamic MCP, file links, audit ve Live Workspace timeline.

## Önerilen topology

DSH ve LSM’yi aynı machine üzerinde doğrudan çalıştırın. Her DSH Session kendi LSM MCP connection’ını kullanır ve default olarak `127.0.0.1:8765/mcp` adresine bağlanır.

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

LSM’yi çalıştıran machine LSM `local` target’tır. LSM container içindeyse `local` o container demektir, otomatik olarak DSH host değildir. LSM default `0.0.0.0:8765` dinler, DSH bundle loopback kullanır; network, firewall, public URL ve authentication doğruysa aynı controller Remote Workers ve external clients için de kullanılabilir.

## Kurulum

Önce LSM’yi başlatın:

```bash
local-shell-mcp --mode mcp
```

Sonra bu repository’yi DSH Web profile’a kurun:

```bash
dsh plugin --profile web add local-shell-mcp-dsh
```

Production için Git spec’i reviewed release tag veya commit’e pin edin. Checkout development için current directory’yi kurun:

```bash
dsh plugin --profile web add .
```

Bundle `cordis.patch.yml` üzerinden `local-shell-mcp-dsh` yükler; DSH normal MCP namespace altında model-facing LSM tools alır, örneğin:

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

Bridge Remote Workers dahil tam LSM catalog’u bilerek korur. Internal app-only `live_workspace_reconnect` yalnız bridge içindir ve modele açılmaz. Daha küçük model tool set istenirse LSM bundle’dan capability silmek yerine sonradan DSH-side `ctx.tools.restrict()` uygulayın.

## DSH Session ve LSM logical Session binding

Integration v4 logical-session runtime tabanlıdır. Her DSH Session kendi upstream Streamable HTTP MCP client’ına sahiptir; bridge DSH Session id’den opaque deterministic session-affinity de göndererek şu stable identity chain’i oluşturur:

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

Farklı DSH conversation’ların tool activity’si aynı Live Workspace timeline’da birleşmez. DSH restart aynı affinity ile MCP transport’u yeniden kurar; LSM controller Session’ı tuttuğu sürece logical Session ve active run attached kalır. Bridge active MCP clients’a periyodik ping göndererek normal idle cleanup’ın uzun conversation’ları koparmasını önler.

## DSH içinde Live Workspace

DSH browser plugin `conversation.view` içine **Live Workspace** ekler ve mevcut v4 implementation’ı reuse eder. View current DSH Session’a scoped olup logical Session, Plan/Goal state, Activity, terminals, files, diff, jobs, remotes ve audit gösterir. **Ask** ve Goal auto-continuation aynı DSH conversation’a döner. Credential DSH host tarafından o Session’ın MCP connection’ı üzerinden server-side alınır; conversation veya model-visible tool result içine girmez.

## Neden stdio yerine HTTP

Remote Workers yalnız MCP tools değil, registration, polling, heartbeats, result delivery ve transfer traffic için controller `/remote/*` HTTP routes ister. stdio-only child process service plane’i kaybeder ve ikinci controller state domain oluşturur. Çalışan LSM HTTP service’i kullanmak Remote Workers, browser state, jobs, Dynamic MCP, audit, file links, logical Sessions ve Live Workspace için tek authority sağlar.

## Yapılandırma

DSH Host bridge şu environment variables değerlerini kabul eder:

| Variable | Default | Amaç |
|---|---|---|
| `DSH_LSM_MCP_URL` | `http://127.0.0.1:8765/mcp` | DSH’nin kullandığı LSM Streamable HTTP MCP endpoint. |
| `DSH_LSM_AUTHORIZATION` | unset | `Bearer ...` gibi optional tam `Authorization` header değeri. |
| `DSH_LSM_TOOL_CALL_TIMEOUT_MS` | `120000` | Tool call başına timeout, milliseconds. |
| `DSH_LSM_KEEPALIVE_INTERVAL_MS` | `30000` | Long-lived per-Session MCP identity için ping interval; minimum 5000 ms. |
| `DSH_LSM_BROWSER_URL` | unset | Host-side MCP origin’den farklıysa browser-reachable LSM origin. |

Same-host deployment genelde authorization header istemez çünkü LSM localhost auth bypass default açıktır. Unauthenticated LSM’yi public network’e expose etmeyin. Protected remote controller için endpoint ve bearer token ayarlayın:

```bash
export DSH_LSM_MCP_URL='https://lsm.example.com/mcp'
export DSH_LSM_AUTHORIZATION='Bearer <token>'
dsh --profile web
```

Bridge fixed upstream headers gönderir; DSH adına interactive OAuth authorization/refresh flow çalıştırmaz.

### Remote DSH Web browsers

`DSH_LSM_MCP_URL` DSH **Host** process tarafından resolve edilir, fakat Live Workspace API requests user browser’da çalışır. Remote-hosted DSH’de LSM loopback URL browser’dan reachable değilse browser-reachable LSM origin ayarlayın:

```bash
export DSH_LSM_BROWSER_URL='https://lsm.example.com'
```

Live Workspace token browser API requests’i authorize etmeye devam eder.

## Remote Workers

Remote Worker mode DSH üzerinden tamamen kullanılabilir. `mcp__lsm__remote_manage`, `mcp__lsm__remote_transfer` ve `machine` alan normal LSM tools aynı controller ve remote-worker state’i kullanır. External worker’lar için LSM public URL/network exposure normal şekilde ayarlanır; DSH MCP loopback kullanmaya devam edebilir.

## Lifecycle ve failure behavior

Bundle başka LSM process başlatmaz. LSM unavailable iken başlayabilir; catalog connection backoff ile reconnect eder ve tool catalog’u sonra sync eder. Ambiguous transport failure sonrası model tool calls auto-replay edilmez, böylece mutating call iki kez çalışmaz. Stable affinity/keepalive normal transport recreation/idle durumlarını yönetir; gerçek controller replacement deployment’ın durable Session recovery kurallarını izler. Plugin remove yalnız DSH-side integration’ı kaldırır:

```bash
dsh plugin --profile web remove local-shell-mcp-dsh
```

LSM’yi durdurmaz.

## Kurulumu doğrulama

Composed DSH profile’ı inspect edin:

```bash
dsh --profile web --dump-config
```

Output içinde `id: local-shell-mcp`, `name: local-shell-mcp-dsh`, `url: http://127.0.0.1:8765/mcp` benzeri row olmalıdır.

```text
id: local-shell-mcp
name: local-shell-mcp-dsh
url: http://127.0.0.1:8765/mcp
```

LSM online olduğunda DSH örneğin şu `mcp__lsm__*` tools’u expose etmelidir:

```text
mcp__lsm__run_shell
mcp__lsm__remote_manage
mcp__lsm__remote_transfer
mcp__lsm__browser_session
mcp__lsm__session_manage
```

DSH Web’de non-empty conversation ayrıca **Live Workspace** view gösterir. Integration yoksa `DSH_LSM_MCP_URL`, LSM `/healthz`, `/mcp` reachability, DSH Host log ve yalnız embedded UI bozuksa `DSH_LSM_BROWSER_URL` kontrol edin.
