<!-- i18n-source-sha256: 6fa729155fcc9e524eb3f8081b80d40ceb72c59f5ece4b311809350005468851 -->
# DeepSeek Harness (DSH)

`local-shell-mcp` pode ser instalado diretamente em um perfil Web do DeepSeek Harness. O repository inclui um bridge ciente de DSH que mantém toda a superfície de ferramentas LSM, mapeia cada DSH Session para uma identidade logical-session v4 estável e adiciona **Live Workspace** como view nativa de conversation do DSH. LSM continua sendo a autoridade do estado de execução: máquinas local/remotas, logical Sessions e Goal Plans, terminais persistentes, jobs, browser sessions, Dynamic MCP, file links, audit e timeline Live Workspace.

## Topologia recomendada

Execute DSH e LSM diretamente na mesma máquina. Cada DSH Session usa sua própria conexão MCP ao LSM e, por default, conecta a `127.0.0.1:8765/mcp`.

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

A máquina que executa LSM é o target `local` do LSM. Se o próprio LSM roda em container, `local` significa esse container, não automaticamente o host DSH. LSM escuta `0.0.0.0:8765` por default e o bundle DSH usa loopback; com rede, firewall, public URL e autenticação configurados, o mesmo controller atende Remote Workers e outros clientes externos.

## Instalação

Inicie LSM primeiro:

```bash
local-shell-mcp --mode mcp
```

Depois instale o pacote npm dedicado do DSH no perfil Web DSH:

```bash
dsh plugin --profile web add local-shell-mcp-dsh
```

O pacote npm do DSH usa a mesma versão de release do LSM. Para desenvolvimento a partir de um checkout, instale o diretório atual:

```bash
dsh plugin --profile web add .
```

O bundle carrega `local-shell-mcp-dsh` de `cordis.patch.yml`; DSH recebe as ferramentas LSM model-facing no namespace MCP normal, por exemplo:

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

O bridge mantém deliberadamente o catálogo LSM completo, incluindo Remote Workers. O tool interno app-only `live_workspace_reconnect` é usado apenas pelo bridge e não aparece ao modelo. Para reduzir o model tool set, aplique depois `ctx.tools.restrict()` no lado DSH em vez de remover capacidades do bundle LSM.

## Binding entre DSH Session e LSM logical Session

A integração usa o runtime logical-session v4. Cada DSH Session tem seu próprio client MCP Streamable HTTP upstream; o bridge envia também session-affinity opaca e determinística derivada do DSH Session id, criando esta cadeia de identidade estável:

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

Tool activity de conversations DSH diferentes não se mistura no mesmo Live Workspace timeline. Um restart do DSH recria o MCP transport com a mesma affinity, preservando logical Session e active run enquanto o LSM controller possuir a Session. O bridge faz ping periódico nos MCP clients ativos para o idle cleanup normal do LSM não quebrar conversations longas.

## Live Workspace dentro do DSH

O browser plugin do DSH adiciona **Live Workspace** a `conversation.view` e reutiliza a implementação v4 existente. A view é scoped à DSH Session atual e mostra logical Session, Plan/Goal state, Activity, terminals, files, diff, jobs, remotes e audit. **Ask** e Goal auto-continuation voltam à mesma DSH conversation. Credentials são obtidas server-side pelo DSH host via a conexão MCP dessa Session e não entram na conversation nem em tool result visível ao modelo.

## Por que HTTP em vez de stdio

Remote Workers precisa de mais que MCP tools: routes HTTP `/remote/*` tratam registration, polling, heartbeats, result delivery e transfer traffic. Um child process stdio-only perderia esse service plane e criaria outro controller state domain. Usar o serviço HTTP LSM existente mantém uma única autoridade para Remote Workers, browser state, jobs, Dynamic MCP, audit, file links, logical Sessions e Live Workspace.

## Configuração

O DSH Host bridge aceita estas environment variables:

| Variável | Default | Finalidade |
|---|---|---|
| `DSH_LSM_MCP_URL` | `http://127.0.0.1:8765/mcp` | Endpoint LSM Streamable HTTP MCP usado pelo DSH. |
| `DSH_LSM_AUTHORIZATION` | unset | Valor completo opcional do header `Authorization`, como `Bearer ...`. |
| `DSH_LSM_TOOL_CALL_TIMEOUT_MS` | `120000` | Timeout por tool call em milissegundos. |
| `DSH_LSM_KEEPALIVE_INTERVAL_MS` | `30000` | Ping interval para preservar identidade MCP per-Session longa; mínimo 5000 ms. |
| `DSH_LSM_BROWSER_URL` | unset | Origin LSM alcançável pelo browser quando diferente do origin MCP visto pelo Host. |

Deployments same-host normalmente não precisam de authorization header porque o localhost auth bypass do LSM é default. Não exponha LSM sem autenticação em rede pública. Para controller remoto protegido, configure endpoint e bearer token:

```bash
export DSH_LSM_MCP_URL='https://lsm.example.com/mcp'
export DSH_LSM_AUTHORIZATION='Bearer <token>'
dsh --profile web
```

O bridge envia fixed upstream headers; não executa interactive OAuth authorization/refresh flow pelo DSH.

### Browsers DSH Web remotos

`DSH_LSM_MCP_URL` é resolvida pelo process **Host** DSH, mas requests da API Live Workspace rodam no browser do usuário. Se DSH é hospedado remotamente e a loopback URL LSM não é alcançável, configure um origin LSM alcançável pelo browser:

```bash
export DSH_LSM_BROWSER_URL='https://lsm.example.com'
```

O Live Workspace token continua autorizando esses browser API requests.

## Remote Workers

Remote Worker mode permanece totalmente disponível via DSH. `mcp__lsm__remote_manage`, `mcp__lsm__remote_transfer` e tools LSM comuns com `machine` usam o mesmo controller e remote-worker state de outros clients. Workers externos exigem a configuração normal de public URL/network exposure; o DSH pode continuar usando o endpoint MCP loopback.

## Lifecycle e comportamento de falhas

O bundle não inicia outro process LSM. Pode iniciar com LSM indisponível: a catalog connection reconecta com backoff e sincroniza tools depois. Model tool calls não são replay automaticamente após transport failure ambíguo, evitando execução dupla de calls mutantes. Stable affinity e keepalive cuidam da recreação normal de transport/idle; substituição real do controller segue durable Session recovery do deployment. Remover o plugin remove apenas a integração DSH-side:

```bash
dsh plugin --profile web remove local-shell-mcp-dsh
```

Isso não para LSM.

## Verificar a instalação

Inspecione o perfil DSH composto:

```bash
dsh --profile web --dump-config
```

A saída deve conter uma row com `id: local-shell-mcp`, `name: local-shell-mcp-dsh`, `url: http://127.0.0.1:8765/mcp`.

```text
id: local-shell-mcp
name: local-shell-mcp-dsh
url: http://127.0.0.1:8765/mcp
```

Quando LSM estiver online, DSH deve expor, entre outros, estes tools `mcp__lsm__*`:

```text
mcp__lsm__run_shell
mcp__lsm__remote_manage
mcp__lsm__remote_transfer
mcp__lsm__browser_session
mcp__lsm__session_manage
```

No DSH Web, uma conversation não vazia também mostra **Live Workspace**. Se a integração faltar, verifique `DSH_LSM_MCP_URL`, `/healthz`, reachability de `/mcp`, DSH Host log e `DSH_LSM_BROWSER_URL` quando apenas a UI embutida falhar.
