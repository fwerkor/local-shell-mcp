<!-- i18n-source-sha256: 6fa729155fcc9e524eb3f8081b80d40ceb72c59f5ece4b311809350005468851 -->
# DeepSeek Harness (DSH)

`local-shell-mcp` 可直接安裝到 DeepSeek Harness Web profile。repository 內含 DSH-aware bridge：保留完整 LSM 工具面、把每個 DSH Session 映射到穩定的 v4 logical-session identity，並把 **Live Workspace** 作為原生 DSH conversation view 注入。執行狀態仍由 LSM 統一管理，包括本地/遠端機器、logical Session 與 Goal Plan、持久終端、job、browser session、Dynamic MCP、檔案連結、稽核資料和 Live Workspace timeline。

## 建議拓撲

建議讓 DSH 與 LSM 直接執行在同一台機器上。每個 DSH Session 使用獨立 LSM MCP connection，預設連線 `127.0.0.1:8765/mcp`。

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

在此配置中，執行 LSM 的機器就是 LSM 的 `local` target；若 LSM 本身在 container 中，`local` 指該 container，而不會自動指向 DSH host。LSM 預設監聽 `0.0.0.0:8765`，DSH bundle 預設使用 loopback；正確設定網路、防火牆、public URL 與認證後，同一 controller 也能服務 Remote Workers 和其他外部 client。

## 安裝

先啟動 LSM：

```bash
local-shell-mcp --mode mcp
```

接著把本 repository 安裝到 DSH Web profile：

```bash
dsh plugin --profile web add local-shell-mcp-dsh
```

production 應將 Git spec 固定到已審核 release tag 或 commit；從 checkout 開發時可直接安裝目前目錄：

```bash
dsh plugin --profile web add .
```

bundle 透過 `cordis.patch.yml` 載入 `local-shell-mcp-dsh`。DSH 會在一般 MCP namespace 下取得完整 model-facing LSM 工具，例如：

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

bridge 刻意保留完整 model-facing LSM catalog，包括 Remote Worker 能力。內部 app-only `live_workspace_reconnect` 僅供 bridge 使用，不暴露給模型。若部署希望縮小模型工具集，應在後續 DSH 層使用 `ctx.tools.restrict()`，而非從 LSM bundle 刪除能力。

## DSH Session 與 LSM logical Session 綁定

整合以 v4 logical-session runtime 為基礎。每個 DSH Session 都有自己的 upstream Streamable HTTP MCP client；bridge 也會依 DSH Session id 產生不透明且確定性的 session-affinity 值，形成以下穩定 identity chain：

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

不同 DSH conversation 的 tool activity 因此不會合併到同一條 Live Workspace timeline。DSH restart 會以相同 affinity 重建 MCP transport；只要 LSM controller 仍持有該 Session，原有 v4 logical Session 與 active run 會繼續附著。bridge 也會定期 ping active MCP client，避免 LSM 正常的 idle-session cleanup 中斷長生命週期 DSH conversation。

## DSH 內的 Live Workspace

DSH browser plugin 會在 `conversation.view` 加入 **Live Workspace**，直接重用既有 v4 Live Workspace，不維護第二套 UI/state model。view 依目前 DSH Session 隔離，顯示對應 LSM logical Session、Plan/Goal state、Activity、terminals、files、diff、jobs、remotes 和 audit；**Ask** 與 Goal 自動續跑會回到同一個 DSH conversation。Live Workspace credential 由 DSH host 透過該 Session 自己的 LSM MCP connection 在 server-side 取得，不會放入 DSH conversation 或 model-visible tool result。

## 為什麼使用 HTTP 而不是 stdio

Remote Workers 不只依賴 MCP tools，也需要 controller 的 `/remote/*` HTTP routes 處理註冊、polling、heartbeat、result delivery 與 transfer traffic。stdio-only child process 會破壞這條 service plane，並建立第二個 controller state domain。重用已執行的 LSM HTTP service，可讓 Remote Workers、browser state、jobs、Dynamic MCP、audit、file links、logical Sessions 與 Live Workspace 始終由同一 authority 管理。

## 設定

DSH Host bridge 支援以下環境變數：

| 變數 | 預設值 | 用途 |
|---|---|---|
| `DSH_LSM_MCP_URL` | `http://127.0.0.1:8765/mcp` | DSH 使用的 LSM Streamable HTTP MCP endpoint。 |
| `DSH_LSM_AUTHORIZATION` | unset | 可選的完整 `Authorization` header，例如 `Bearer ...`。 |
| `DSH_LSM_TOOL_CALL_TIMEOUT_MS` | `120000` | 每次 tool call timeout，單位毫秒。 |
| `DSH_LSM_KEEPALIVE_INTERVAL_MS` | `30000` | 維持長生命週期 per-Session MCP identity 的 ping interval；最小 5000 ms。 |
| `DSH_LSM_BROWSER_URL` | unset | browser-reachable LSM origin 與 Host-side MCP origin 不同時使用。 |

同機部署通常不需要 authorization header，因為 LSM 預設啟用 localhost auth bypass；但不要把未認證 LSM service 暴露到 public network。連線受保護的 remote LSM controller 時可設定 endpoint 與 bearer token：

```bash
export DSH_LSM_MCP_URL='https://lsm.example.com/mcp'
export DSH_LSM_AUTHORIZATION='Bearer <token>'
dsh --profile web
```

bridge 只傳送固定 upstream headers，不會代表 DSH 執行互動式 OAuth authorization/refresh flow。

### 遠端 DSH Web 瀏覽器

`DSH_LSM_MCP_URL` 由 DSH **Host** process 解析，但 Live Workspace API request 在使用者瀏覽器中執行。若 DSH 遠端託管，而 LSM 回傳的 loopback URL 對瀏覽器不可達，請設定 browser-reachable LSM origin：

```bash
export DSH_LSM_BROWSER_URL='https://lsm.example.com'
```

Live Workspace token 仍會授權這些 browser API request。

## Remote Workers

透過 DSH 仍可完整使用 Remote Worker mode。`mcp__lsm__remote_manage`、`mcp__lsm__remote_transfer` 與帶 `machine` 參數的一般 LSM tool，都使用和其他 LSM client 相同的 controller 與 remote-worker state。若 worker 從 controller host 外部連線，照一般方式設定 LSM public URL 與 network exposure 即可；DSH 本身仍可使用 `127.0.0.1:8765/mcp`。

## 生命週期與故障行為

bundle 不會另外啟動 LSM process。即使啟動時 LSM 不可用，catalog connection 也會按 backoff 重連，並在 LSM 出現後同步 tool catalog。model tool call 在不明確 transport failure 後不會自動 replay，因為重放 mutating shell/file/remote call 可能執行兩次。穩定 affinity key 與 keepalive 處理正常 MCP transport 重建和 idle period；真正替換 LSM controller 時仍依 deployment 的 durable Session recovery 規則。移除 plugin 只會移除 DSH-side integration：

```bash
dsh plugin --profile web remove local-shell-mcp-dsh
```

它不會停止 LSM。

## 驗證安裝

檢查組合後的 DSH profile：

```bash
dsh --profile web --dump-config
```

輸出應包含類似 `id: local-shell-mcp`、`name: local-shell-mcp-dsh`、`url: http://127.0.0.1:8765/mcp` 的項目。LSM 上線後，DSH 應暴露以下 `mcp__lsm__*` tools：

```text
id: local-shell-mcp
name: local-shell-mcp-dsh
url: http://127.0.0.1:8765/mcp
```

LSM 上線後，DSH 應暴露包括以下內容在內的 `mcp__lsm__*` tools：

```text
mcp__lsm__run_shell
mcp__lsm__remote_manage
mcp__lsm__remote_transfer
mcp__lsm__browser_session
mcp__lsm__session_manage
```

在 DSH Web 中，非空 conversation 也應出現 **Live Workspace** conversation view。若 integration 缺失，檢查 `DSH_LSM_MCP_URL`、LSM `/healthz`、`/mcp` reachability、DSH Host log；若只有 embedded UI 失敗，再檢查 `DSH_LSM_BROWSER_URL`。
