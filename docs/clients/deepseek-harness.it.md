<!-- i18n-source-sha256: 9deaf97f0af15e7af335b40fcf9fe8bc468623d1947e6f8c9afaf7dfaebcc036 -->
# DeepSeek Harness (DSH)

`local-shell-mcp` può essere installato direttamente in un profilo Web DeepSeek Harness. Il repository include un bridge DSH-aware che mantiene l’intera superficie degli strumenti LSM, associa ogni DSH Session a una identity logical-session v4 stabile e aggiunge **Live Workspace** come view nativa della conversation DSH. LSM resta l’autorità dello stato di esecuzione: macchine local/remote, logical Sessions e Goal Plan, terminali persistenti, jobs, browser sessions, Dynamic MCP, file link, audit e timeline Live Workspace.

## Topologia consigliata

Esegui DSH e LSM direttamente sulla stessa macchina. Ogni DSH Session usa una propria connessione MCP LSM e di default si collega a `127.0.0.1:8765/mcp`.

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

La macchina che esegue LSM è il target LSM `local`; se LSM gira in un container, `local` indica quel container e non automaticamente l’host DSH. LSM ascolta di default su `0.0.0.0:8765`, mentre il bundle DSH usa loopback. Con rete, firewall, public URL e autenticazione corretti, lo stesso controller serve Remote Workers e altri client esterni.

## Installazione

Avvia prima LSM:

```bash
local-shell-mcp --mode mcp
```

Poi installa il pacchetto npm DSH dedicato nel profilo Web DSH:

```bash
dsh plugin --profile web add local-shell-mcp-dsh
```

Il pacchetto npm DSH usa la stessa versione di release di LSM. Per lo sviluppo da checkout installa la directory corrente:

```bash
dsh plugin --profile web add .
```

Il bundle carica `local-shell-mcp-dsh` da `cordis.patch.yml`; DSH riceve gli strumenti LSM model-facing nel normale namespace MCP, ad esempio:

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

Il bridge mantiene volutamente il catalogo LSM completo, incluse le capacità Remote Worker. Il tool interno app-only `live_workspace_reconnect` serve solo al bridge e non è esposto al modello. Per un model tool set più piccolo usa in seguito `ctx.tools.restrict()` lato DSH, senza rimuovere capacità dal bundle LSM.

## Binding tra DSH Session e LSM logical Session

L’integrazione usa il runtime logical-session v4. Ogni DSH Session ha un proprio client MCP Streamable HTTP upstream e il bridge invia una session-affinity opaca e deterministica derivata dal DSH Session id, creando questa catena stabile:

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

Tool activity di DSH conversations diverse non si mescola nella stessa timeline Live Workspace. Dopo un restart DSH, il transport MCP viene ricreato con la stessa affinity e logical Session/active run restano collegati finché il controller LSM possiede la Session. Ping periodici mantengono inoltre vive le lunghe conversations rispetto al normale idle cleanup MCP.

## Live Workspace dentro DSH

Il browser plugin DSH aggiunge **Live Workspace** a `conversation.view` e riusa l’implementazione v4 esistente. La view è scoped alla DSH Session corrente e mostra logical Session, Plan/Goal state, Activity, terminali, file, diff, jobs, remotes e audit. **Ask** e Goal auto-continuation tornano alla stessa DSH conversation. Le credentials sono ottenute server-side dal DSH host tramite la connessione MCP della Session e non entrano nella conversation o in tool result visibili al modello.

## Perché HTTP invece di stdio

Remote Workers richiede oltre agli MCP tools le route HTTP `/remote/*` per registration, polling, heartbeats, result delivery e transfer traffic. Un child process stdio-only perderebbe questo service plane e creerebbe un secondo controller state domain. Riutilizzare il servizio HTTP LSM esistente mantiene una sola autorità per Remote Workers, browser state, jobs, Dynamic MCP, audit, file links, logical Sessions e Live Workspace.

## Configurazione

Il bridge DSH Host accetta queste environment variables:

| Variabile | Default | Scopo |
|---|---|---|
| `DSH_LSM_MCP_URL` | `http://127.0.0.1:8765/mcp` | Endpoint LSM Streamable HTTP MCP usato da DSH. |
| `DSH_LSM_AUTHORIZATION` | unset | Valore completo opzionale dell’header `Authorization`, per esempio `Bearer ...`. |
| `DSH_LSM_TOOL_CALL_TIMEOUT_MS` | `120000` | Timeout per tool call in millisecondi. |
| `DSH_LSM_KEEPALIVE_INTERVAL_MS` | `30000` | Ping interval per preservare identity MCP per-Session di lunga durata; minimo 5000 ms. |
| `DSH_LSM_BROWSER_URL` | unset | Origin LSM raggiungibile dal browser se diverso dall’origin MCP lato Host. |

I deployment same-host normalmente non richiedono authorization header perché il localhost auth bypass LSM è attivo di default. Non esporre un servizio LSM non autenticato su rete pubblica. Per un controller remoto protetto imposta endpoint e bearer token:

```bash
export DSH_LSM_MCP_URL='https://lsm.example.com/mcp'
export DSH_LSM_AUTHORIZATION='Bearer <token>'
dsh --profile web
```

Il bridge invia fixed upstream headers e non esegue un interactive OAuth authorization/refresh flow per DSH.

### Browser DSH Web remoti

`DSH_LSM_MCP_URL` è risolta dal process **Host** DSH, mentre le richieste API Live Workspace girano nel browser utente. Se DSH è remote-hosted e la loopback URL LSM non è raggiungibile, imposta un origin LSM raggiungibile dal browser:

```bash
export DSH_LSM_BROWSER_URL='https://lsm.example.com'
```

Il Live Workspace token continua ad autorizzare queste browser API requests.

## Remote Workers

Remote Worker mode resta completamente disponibile via DSH. `mcp__lsm__remote_manage`, `mcp__lsm__remote_transfer` e normali tools LSM con `machine` usano lo stesso controller e remote-worker state degli altri client. Per worker esterni configura normalmente public URL e network exposure LSM; DSH può continuare a usare l’endpoint MCP loopback.

## Lifecycle e comportamento ai guasti

Il bundle non avvia un altro process LSM. Può partire con LSM non disponibile: la catalog connection riconnette con backoff e sincronizza i tools in seguito. Le model tool calls non vengono replay automaticamente dopo transport failure ambigui, evitando doppie esecuzioni di calls mutanti. Stable affinity e keepalive gestiscono normale ricreazione transport/idle; la sostituzione reale del controller segue durable Session recovery del deployment. Rimuovere il plugin elimina solo l’integrazione DSH-side:

```bash
dsh plugin --profile web remove local-shell-mcp-dsh
```

Non arresta LSM.

## Verificare l’installazione

Ispeziona il profilo DSH composto:

```bash
dsh --profile web --dump-config
```

L’output deve contenere una row simile con `id: local-shell-mcp`, `name: local-shell-mcp-dsh`, `url: http://127.0.0.1:8765/mcp`.

```text
id: local-shell-mcp
name: local-shell-mcp-dsh
url: http://127.0.0.1:8765/mcp
```

Quando LSM è online, DSH deve esporre tra gli altri questi tools `mcp__lsm__*`:

```text
mcp__lsm__run_shell
mcp__lsm__remote_manage
mcp__lsm__remote_transfer
mcp__lsm__browser_session
mcp__lsm__session_manage
```

In DSH Web, una conversation non vuota espone anche **Live Workspace**. Se manca l’integrazione, controlla `DSH_LSM_MCP_URL`, `/healthz`, reachability `/mcp`, DSH Host log e `DSH_LSM_BROWSER_URL` se fallisce solo la UI incorporata.
