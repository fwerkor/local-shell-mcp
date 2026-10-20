<!-- i18n-source-sha256: d3c380d9a5d9a43019b0be2b5e9accc0d6e0c785d77226005db60c5721672ba6 -->
# 遠端 workers

Remote worker 讓 `local-shell-mcp` 可以控制只能發出對外 HTTP(S) 請求、但無法接受入站 SSH 連線的機器。

```text
MCP client -> control server -> outbound polling worker -> remote machine
```

## 基本工作流程

1. 使用 `remote_manage(action="invite", ...)` 建立邀請。
2. 在遠端機器上執行產生的命令。
3. 使用 `remote_manage(action="list")` 確認註冊。
4. 呼叫一般工具並指定 `machine="<worker-name>"`，例如 `environment_get`、`run_shell`、`file_read` 或 `browser_run_script`。
5. 使用 `remote_transfer` 啟動受追蹤的 controller-to-worker、worker-to-controller 或 worker-to-worker 檔案/目錄傳輸。接著用 `job_list` 或 `job_tail` 查看進度，並用 `job_stop` 或 `job_retry` 停止或重試。
6. 使用 `remote_manage(action="rename", ...)` 或 `remote_manage(action="revoke", ...)` 重新命名或撤銷 worker。

邀請碼預設只能註冊一台 Worker（`max_uses=1`），提高 `max_uses` 可供批次註冊。多次使用時須留空 `name`。選用參數 `ttl_s` 預設兩小時（7200 秒），最長七天（604800 秒）。

只有 worker 管理使用 `remote_*` 名稱。執行、shell、job、filesystem、patch 與 browser 操作在本地和遠端共用相同 schema。指定 machine 時還需要 `remote:use` OAuth scope。

## 持久化 worker

邀請結果包含平台特定命令：

- `persistent_command` 在 Linux 或 macOS 上安裝並啟動使用者層級服務。
- `powershell_persistent_command` 從 PowerShell 在 Windows 上安裝並啟動使用者層級工作。

在 Windows 上，`local-shell-mcp worker install-service` 會為目前使用者註冊 `local-shell-mcp-worker` 工作。它會立即啟動、重新開機後在該使用者登入時再次啟動、允許電池供電、忽略重複啟動並重試失敗執行。不需要管理員權限，也不會在使用者登入前執行。

所有平台使用相同的 lifecycle 命令：

```text
local-shell-mcp worker status
local-shell-mcp worker start
local-shell-mcp worker stop
local-shell-mcp worker restart
local-shell-mcp worker uninstall-service
```

worker 日誌儲存在 worker state directory 下的 `worker.log`。

## 能力

Worker 支援 shell 與 persistent shell session、tracked job、filesystem 操作、transfer internals、Python 執行、patch，以及在依賴已安裝時使用 Playwright。Git 透過 `run_shell(machine=...)` 執行標準命令。

## 安全性與版本

已加入的 worker 會讓 MCP client 取得對其設定環境的控制能力。請使用較短的 invite TTL、專用工作目錄或帳號，檢查 audit log，並在任務完成後撤銷 worker。產生的邀請會安裝與 control server 版本相符的 worker code。

## 疑難排解

worker 未出現時，檢查對外 HTTPS 存取、public base URL 可達性、邀請是否過期、系統時間以及 control-server log。
