<!-- i18n-source-sha256: 6fa729155fcc9e524eb3f8081b80d40ceb72c59f5ece4b311809350005468851 -->
# DeepSeek Harness (DSH)

`local-shell-mcp` は DeepSeek Harness Web profile に直接 install できます。repository には DSH-aware bridge が含まれ、完全な LSM tool surface を維持し、各 DSH Session を安定した v4 logical-session identity に mapping し、**Live Workspace** を native DSH conversation view として追加します。local/remote machine、logical Session/Goal Plan、persistent terminal、job、browser session、Dynamic MCP、file link、audit、Live Workspace timeline を含む execution state の authority は引き続き LSM controller です。

## 推奨 topology

DSH と LSM は同じ machine 上で直接実行する構成を推奨します。各 DSH Session は独立した LSM MCP connection を持ち、既定では `127.0.0.1:8765/mcp` に接続します。

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

この構成では LSM を実行する machine が LSM の `local` target です。LSM 自身が container 内なら `local` はその container であり、DSH host ではありません。LSM は既定で `0.0.0.0:8765` を listen し、DSH bundle は loopback を使います。network/firewall/public URL/authentication を適切に設定すれば、同じ controller を Remote Workers や他の external client も利用できます。

## インストール

まず LSM を起動します。

```bash
local-shell-mcp --mode mcp
```

次にこの repository を DSH Web profile に install します。

```bash
dsh plugin --profile web add local-shell-mcp-dsh
```

production では Git spec を review 済み release tag/commit に pin してください。checkout から開発する場合は current directory を install できます。

```bash
dsh plugin --profile web add .
```

bundle は `cordis.patch.yml` から `local-shell-mcp-dsh` を load し、通常の MCP namespace で完全な model-facing LSM tool を DSH に提供します。

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

bridge は Remote Worker capabilities を含む完全な LSM catalog を保持します。internal app-only `live_workspace_reconnect` は bridge 専用で model には公開されません。model tool set を縮小する場合は LSM bundle から削除せず、後段の DSH `ctx.tools.restrict()` policy を使います。

## DSH Session と LSM logical Session の binding

integration は v4 logical-session runtime に基づきます。各 DSH Session は独自の upstream Streamable HTTP MCP client を持ち、bridge は DSH Session id から opaque deterministic session-affinity を送るため、次の stable identity chain が成立します。

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

別の DSH conversation の tool activity は同じ Live Workspace timeline に混ざりません。DSH restart でも同じ affinity で MCP transport を再作成するため、LSM controller が Session を保持している限り既存 logical Session/active run が再接続されます。bridge は active MCP client を定期 ping し、通常の MCP idle cleanup が長期 conversation を切らないようにします。

## DSH 内の Live Workspace

DSH browser plugin は `conversation.view` に **Live Workspace** を追加し、既存 v4 UI/state model をそのまま再利用します。current DSH Session に対応する logical Session、Plan/Goal、Activity、terminal、file、diff、job、remote、audit を表示し、**Ask** や Goal auto-continuation は同じ DSH conversation に返ります。credential は DSH host がその Session の LSM MCP connection 経由で server-side に取得し、conversation や model-visible tool result には入りません。

## stdio ではなく HTTP を使う理由

Remote Workers には MCP tools だけでなく、registration、polling、heartbeat、result delivery、transfer traffic 用の `/remote/*` HTTP routes が必要です。stdio-only child process は service plane と controller state domain を分断します。既存 LSM HTTP service を共有することで Remote Workers、browser state、jobs、Dynamic MCP、audit、file links、logical Sessions、Live Workspace の authority を一つに保てます。

## 設定

DSH Host bridge は次の environment variables を受け付けます。

| 変数 | 既定値 | 用途 |
|---|---|---|
| `DSH_LSM_MCP_URL` | `http://127.0.0.1:8765/mcp` | DSH が使う LSM Streamable HTTP MCP endpoint。 |
| `DSH_LSM_AUTHORIZATION` | unset | `Bearer ...` など完全な `Authorization` header（optional）。 |
| `DSH_LSM_TOOL_CALL_TIMEOUT_MS` | `120000` | tool call ごとの timeout（ms）。 |
| `DSH_LSM_KEEPALIVE_INTERVAL_MS` | `30000` | long-lived per-Session MCP identity を保つ ping interval。最小 5000 ms。 |
| `DSH_LSM_BROWSER_URL` | unset | browser-reachable LSM origin が Host-side MCP origin と異なる場合に指定。 |

same-host deployment は LSM の localhost auth bypass が既定で有効なため通常 authorization header 不要です。ただし unauthenticated LSM service を public network に公開しないでください。protected remote controller では endpoint と bearer token を設定します。

```bash
export DSH_LSM_MCP_URL='https://lsm.example.com/mcp'
export DSH_LSM_AUTHORIZATION='Bearer <token>'
dsh --profile web
```

bridge は fixed upstream headers を送るだけで、DSH の代わりに interactive OAuth authorization/refresh flow は実行しません。

### Remote DSH Web browser

`DSH_LSM_MCP_URL` は DSH **Host** process が解決しますが、Live Workspace API request は user browser で実行されます。remote-hosted DSH で LSM の loopback URL が browser から届かない場合、browser-reachable LSM origin を設定します。

```bash
export DSH_LSM_BROWSER_URL='https://lsm.example.com'
```

Live Workspace token が browser API request の authorization を引き続き担当します。

## Remote Workers

DSH からも Remote Worker mode は完全に利用できます。`mcp__lsm__remote_manage`、`mcp__lsm__remote_transfer`、`machine` parameter を持つ通常 LSM tools は他 client と同じ controller/remote-worker state を使います。worker が controller host 外から接続する場合は通常どおり public URL/network exposure を設定し、DSH 自身は loopback MCP URL のままでも構いません。

## Lifecycle と failure behavior

bundle は別の LSM process を起動しません。LSM がまだ unavailable でも開始でき、catalog connection が backoff reconnect して LSM 出現後に tool catalog を sync します。ambiguous transport failure 後に model tool call を自動 replay しないため、mutating call の二重実行を避けます。stable affinity/keepalive は通常 transport recreation/idle を処理し、controller replacement は deployment の durable Session recovery rules に従います。plugin removal は DSH-side integration だけを削除します。

```bash
dsh plugin --profile web remove local-shell-mcp-dsh
```

LSM 自体は停止しません。

## インストール確認

composed DSH profile を確認します。

```bash
dsh --profile web --dump-config
```

output には `id: local-shell-mcp`、`name: local-shell-mcp-dsh`、`url: http://127.0.0.1:8765/mcp` に相当する row が必要です。LSM online 後は以下の `mcp__lsm__*` tools が見えるはずです。

```text
id: local-shell-mcp
name: local-shell-mcp-dsh
url: http://127.0.0.1:8765/mcp
```

LSM が online になると、DSH は少なくとも次の `mcp__lsm__*` tools を公開します。

```text
mcp__lsm__run_shell
mcp__lsm__remote_manage
mcp__lsm__remote_transfer
mcp__lsm__browser_session
mcp__lsm__session_manage
```

DSH Web の non-empty conversation には **Live Workspace** view も表示されます。integration がなければ `DSH_LSM_MCP_URL`、LSM `/healthz`、`/mcp` reachability、DSH Host log を確認し、embedded UI だけ失敗する場合は `DSH_LSM_BROWSER_URL` も確認します。
