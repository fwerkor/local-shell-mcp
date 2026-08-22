# 使用模式與提示詞指南

`local-shell-mcp` 暴露的是強工具集。好的結果依賴清晰的工作方式：先檢查，再小步行動，隨後驗證，並說明改動了什麼。

## 通用操作循環

大多數編程任務可以使用這個循環：

1. 檢查：`environment_get`、`file_tree`、`run_shell`、`file_grep`、`file_read`。
2. 計劃：讓模型識別最小相關文件和測試。
3. 編輯：使用 `file_edit`、`file_patch` 或 shell 命令。
4. 驗證：用 `run_shell` 或持久 shell 運行定向測試或構建。
5. 複查：需要時使用 `run_shell`、`secret_scan`、`audit_tail`。
6. 提交或導出：透過 `run_shell` 執行明確的 Git CLI 命令，或使用 `link_create`。

## 工具選擇

| 任務 | 優先使用 | 避免 |
|---|---|---|
| 快速一次性命令 | `run_shell` | 每個命令都啓動持久 shell |
| 長時間開發服務器、REPL、watch 任務 | `shell_start` + `shell_read` + `shell_send` | 用阻塞式 `run_shell` 等到超時 |
| 結構化分析或生成文件 | `run_python` | 用脆弱的 shell 管道處理複雜 JSON / 文本 |
| 小範圍精確編輯 | `file_edit` | 無必要地重寫整個文件 |
| 同一文件多處替換 | `file_edit` | 不重新讀取文件就反覆做陳舊編輯 |
| 多文件補丁 | `file_patch` | 臨時拼接 shell 編輯命令 |
| 查找文件 | `file_tree`、`file_glob` | 對大型倉庫做完整遞歸列表 |
| 查找代碼 | `file_grep` | 盲目讀取大量文件 |
| 瀏覽器證據 | `browser_capture_tool`、`browser_get_text_tool` | 只根據頁面名或路由猜測 |
| 可下載產物 | `link_create` | 在聊天中粘貼大型二進制內容 |
| 遠端機器任務 | 一般工具加 `machine`，以及 `remote_transfer` | 在出站 worker 模式足夠時開放入站 SSH |

## 提示詞模板

### 只讀倉庫摸底

```text
使用 local-shell-mcp。檢查倉庫結構和 git 狀態。不要修改文件。先總結主要組件、能推斷出的測試命令以及明顯風險，再考慮後續改動。
```

### 聚焦修復 bug

```text
使用 local-shell-mcp 修復這個 bug。先用最小相關命令復現或定位問題。編輯前讀取相關文件。做最小補丁，運行定向驗證，然後展示 git diff 和實際運行的測試。未經我批准不要提交。
```

### 提交併推送工作流

```text
使用 local-shell-mcp。檢查 git status 和 diff，運行相關測試，運行 secret_scan，創建一個聚焦的提交併寫簡潔提交信息，然後推送當前分支。不要包含緩存、構建產物或無關格式化。
```

### 長時間進程

```text
在持久 shell session 中啓動開發服務器，讀取輸出直到服務就緒，然後使用瀏覽器工具驗證頁面。保留 session id，驗證後關閉該 session。
```

### 遠程 worker 任務

```text
使用名為 <machine> 的已連接遠端 worker。先呼叫 environment_get(machine=<machine>) 和 file_list(machine=<machine>)。只在配置的遠端工作目錄內操作。短命令用 run_shell，長時間任務用 shell_start 或 job_start。
```

## 處理倉庫

開源改動建議流程：

1. 用 `run_shell` 檢查是否有未提交改動。
2. 如果任務依賴上游狀態，使用 `run_shell` 並檢查分支。
3. 編輯前用 `file_grep` 和 `file_read` 定位相關代碼。
4. 做最小補丁。
5. 先跑定向測試；可行時再跑更廣的測試。
6. 提交或推送前運行 `secret_scan`。
7. 提交信息簡潔描述行爲變化。

當維護者需要可審查歷史時，每個邏輯改動單獨一個提交。

## 處理生成產物

對於 PDF、報告、截圖、壓縮包或日誌：

1. 在工作區內生成文件。
2. 驗證文件存在且大小符合預期。
3. 使用 `link_create`，設置較短 TTL 和可選 `max_downloads`。
4. 不再需要時撤銷鏈接。

不要爲私鑰、憑據目錄或無關個人數據創建公開鏈接。

## 處理遠程機器

當機器能發起出站 HTTPS、但無法接收入站 SSH 時，遠程 worker 模式很有用。

推薦做法：

- 用 `remote_manage(action="invite", ...)` 或 `remote_manage(action="rename", ...)` 給機器取清晰名稱。
- 操作前檢查 `environment_get`。
- 用 `remote_transfer` 處理控制端與 worker、或 worker 之間的檔案和目錄傳輸。
- 任務結束後用 `remote_manage(action="revoke", ...)` 撤銷 worker。

## 反模式

除非環境是一次性的，且你理解後果，否則避免這些指令：

- 在宿主機啓動的服務上“全局安裝任何需要的東西”。
- 沒有時間邊界或驗證標準地“跑到能用爲止”。
- 在包含生成產物的倉庫裏“提交所有東西”。
- 爲了方便暴露整個 home 目錄。
- 爲整個工作區創建文件鏈接。
- 在公開部署中使用 `LOCAL_SHELL_MCP_AUTH_MODE=none`。
