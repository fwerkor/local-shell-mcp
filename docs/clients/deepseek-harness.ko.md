<!-- i18n-source-sha256: 6fa729155fcc9e524eb3f8081b80d40ceb72c59f5ece4b311809350005468851 -->
# DeepSeek Harness (DSH)

`local-shell-mcp`는 DeepSeek Harness Web profile에 직접 설치할 수 있습니다. repository의 DSH-aware bridge는 전체 LSM tool surface를 유지하고 각 DSH Session을 안정적인 v4 logical-session identity에 매핑하며 **Live Workspace**를 native DSH conversation view로 추가합니다. local/remote machine, logical Session/Goal Plan, persistent terminal, job, browser session, Dynamic MCP, file link, audit, Live Workspace timeline을 포함한 execution state의 authority는 계속 LSM controller입니다.

## 권장 topology

DSH와 LSM을 같은 machine에서 직접 실행하는 구성을 권장합니다. 각 DSH Session은 독립된 LSM MCP connection을 사용하며 기본적으로 `127.0.0.1:8765/mcp`에 연결합니다.

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

이 구성에서 LSM을 실행하는 machine이 LSM의 `local` target입니다. LSM 자체가 container에서 실행되면 `local`은 그 container이며 자동으로 DSH host가 아닙니다. LSM은 기본 `0.0.0.0:8765`에서 listen하고 DSH bundle은 loopback을 사용합니다. network/firewall/public URL/authentication을 올바르게 설정하면 같은 controller를 Remote Workers와 외부 client도 사용할 수 있습니다.

## 설치

먼저 LSM을 시작합니다.

```bash
local-shell-mcp --mode mcp
```

그 다음 이 repository를 DSH Web profile에 설치합니다.

```bash
dsh plugin --profile web add local-shell-mcp-dsh
```

production에서는 Git spec을 검토된 release tag/commit으로 pin하세요. checkout 개발에서는 현재 directory를 설치할 수 있습니다.

```bash
dsh plugin --profile web add .
```

bundle은 `cordis.patch.yml`에서 `local-shell-mcp-dsh`를 load하며 DSH에 일반 MCP namespace의 전체 model-facing LSM tool을 제공합니다.

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

bridge는 Remote Worker capability를 포함한 전체 LSM catalog를 유지합니다. internal app-only `live_workspace_reconnect`는 bridge 전용이며 model에 노출되지 않습니다. model tool set을 줄이려면 LSM bundle에서 제거하지 말고 이후 DSH `ctx.tools.restrict()` policy를 적용하세요.

## DSH Session과 LSM logical Session binding

integration은 v4 logical-session runtime을 기반으로 합니다. 각 DSH Session은 자체 upstream Streamable HTTP MCP client를 가지며 bridge가 DSH Session id에서 opaque deterministic session-affinity를 보내므로 다음 stable identity chain이 만들어집니다.

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

서로 다른 DSH conversation의 tool activity는 같은 Live Workspace timeline에 합쳐지지 않습니다. DSH restart 후에도 같은 affinity로 MCP transport를 재생성하므로 LSM controller가 Session을 보유하는 한 기존 logical Session과 active run이 유지됩니다. bridge는 active MCP client를 주기적으로 ping하여 일반 MCP idle cleanup이 long-lived conversation을 끊지 않게 합니다.

## DSH 내부 Live Workspace

DSH browser plugin은 `conversation.view`에 **Live Workspace**를 추가하고 기존 v4 UI/state model을 그대로 재사용합니다. current DSH Session의 logical Session, Plan/Goal state, Activity, terminals, files, diff, jobs, remotes, audit를 보여주며 **Ask**와 Goal auto-continuation은 같은 DSH conversation으로 돌아갑니다. credential은 DSH host가 해당 Session의 LSM MCP connection을 통해 server-side로 얻으며 conversation이나 model-visible tool result에 들어가지 않습니다.

## stdio 대신 HTTP를 쓰는 이유

Remote Workers는 MCP tools뿐 아니라 registration, polling, heartbeat, result delivery, transfer traffic을 위한 controller의 `/remote/*` HTTP routes가 필요합니다. stdio-only child process는 service plane을 보존하지 못하고 별도 controller state domain을 만듭니다. 이미 실행 중인 LSM HTTP service를 사용하면 Remote Workers, browser state, jobs, Dynamic MCP, audit, file links, logical Sessions, Live Workspace를 하나의 authority로 유지할 수 있습니다.

## 설정

DSH Host bridge는 다음 environment variables를 지원합니다.

| 변수 | 기본값 | 용도 |
|---|---|---|
| `DSH_LSM_MCP_URL` | `http://127.0.0.1:8765/mcp` | DSH가 사용하는 LSM Streamable HTTP MCP endpoint. |
| `DSH_LSM_AUTHORIZATION` | unset | `Bearer ...` 같은 optional 전체 `Authorization` header. |
| `DSH_LSM_TOOL_CALL_TIMEOUT_MS` | `120000` | tool call별 timeout(ms). |
| `DSH_LSM_KEEPALIVE_INTERVAL_MS` | `30000` | long-lived per-Session MCP identity를 유지하는 ping interval; 최소 5000 ms. |
| `DSH_LSM_BROWSER_URL` | unset | browser-reachable LSM origin이 Host-side MCP origin과 다를 때 사용. |

same-host deployment는 LSM의 localhost auth bypass가 기본 활성화되어 보통 authorization header가 필요 없습니다. 그러나 unauthenticated LSM service를 public network에 노출하지 마세요. protected remote controller에서는 endpoint와 bearer token을 설정합니다.

```bash
export DSH_LSM_MCP_URL='https://lsm.example.com/mcp'
export DSH_LSM_AUTHORIZATION='Bearer <token>'
dsh --profile web
```

bridge는 fixed upstream headers만 보내며 DSH를 대신해 interactive OAuth authorization/refresh flow를 실행하지 않습니다.

### Remote DSH Web browser

`DSH_LSM_MCP_URL`은 DSH **Host** process가 해석하지만 Live Workspace API request는 사용자 browser에서 실행됩니다. remote-hosted DSH에서 LSM loopback URL이 browser에서 도달하지 않으면 browser-reachable LSM origin을 설정합니다.

```bash
export DSH_LSM_BROWSER_URL='https://lsm.example.com'
```

Live Workspace token은 계속 browser API request를 authorize합니다.

## Remote Workers

DSH에서도 Remote Worker mode를 그대로 사용할 수 있습니다. `mcp__lsm__remote_manage`, `mcp__lsm__remote_transfer`, `machine` argument를 가진 일반 LSM tools는 다른 LSM client와 동일한 controller/remote-worker state를 사용합니다. worker가 controller host 밖에서 연결하면 보통처럼 public URL/network exposure를 구성하고 DSH 자체는 loopback MCP URL을 계속 써도 됩니다.

## Lifecycle 및 failure behavior

bundle은 별도 LSM process를 시작하지 않습니다. LSM이 unavailable한 상태에서도 시작할 수 있고 catalog connection이 backoff reconnect 후 LSM이 나타나면 tool catalog를 sync합니다. ambiguous transport failure 뒤 model tool call을 자동 replay하지 않아 mutating call 이중 실행을 피합니다. stable affinity/keepalive는 일반 transport recreation/idle을 처리하고 controller replacement는 deployment의 durable Session recovery rules를 따릅니다. plugin remove는 DSH-side integration만 제거합니다.

```bash
dsh plugin --profile web remove local-shell-mcp-dsh
```

LSM은 멈추지 않습니다.

## 설치 확인

composed DSH profile을 확인합니다.

```bash
dsh --profile web --dump-config
```

output에는 `id: local-shell-mcp`, `name: local-shell-mcp-dsh`, `url: http://127.0.0.1:8765/mcp`와 유사한 row가 있어야 합니다. LSM online 후에는 아래 `mcp__lsm__*` tools가 노출되어야 합니다.

```text
id: local-shell-mcp
name: local-shell-mcp-dsh
url: http://127.0.0.1:8765/mcp
```

LSM이 online이면 DSH는 최소한 다음 `mcp__lsm__*` tools를 노출해야 합니다.

```text
mcp__lsm__run_shell
mcp__lsm__remote_manage
mcp__lsm__remote_transfer
mcp__lsm__browser_session
mcp__lsm__session_manage
```

DSH Web의 non-empty conversation에는 **Live Workspace** view도 나타납니다. integration이 없으면 `DSH_LSM_MCP_URL`, LSM `/healthz`, `/mcp` reachability, DSH Host log를 확인하고 embedded UI만 실패하면 `DSH_LSM_BROWSER_URL`도 확인하세요.
