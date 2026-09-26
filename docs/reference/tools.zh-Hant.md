<!-- i18n-source-sha256: 13df63c51bc29aa49ae386e7c96e1f729d23914343856b4d20f8776ca0a2acda -->
# 工具參考

本頁由實際 MCP tool schema 產生。公開工具介面變更後，執行 `python scripts/generate-tools-reference.py` 更新 English 參考頁。

大多數工具回傳包含 `ok`、`message` 和 `data` 的結構化 `ToolResult`。`workspace_open` 回傳用於渲染 MCP App 的模型可見狀態。多數執行與檔案工具接受可選 `machine`；省略時操作 controller workspace，指定時操作已連線 worker。Git 操作刻意透過 `run_shell` 或其他 shell 工具執行，而不提供專用 Git wrapper。

## 選擇指南

| 需求 | 建議工具 |
|---|---|
| 在 ChatGPT 中監控執行或協作 | `workspace_open` |
| 檢查環境 | `environment_get`, `file_tree`, `file_read` |
| 執行短指令或 Git 操作 | `run_shell` |
| 執行互動式或長任務 | `shell_start` or `job_start` |
| 精確修改檔案 | `file_edit` or `file_patch` |
| 傳輸檔案或目錄 | `remote_transfer` |
| 探索外部 MCP capability | `mcp_tool_search`, then `mcp_tool_inspect` |
| 與頁面互動 | `browser_session`, `browser_snapshot`, then `browser_act` |
| 執行自訂 browser 邏輯 | `browser_run_script` |
| Control a native desktop app | `gui_list`, `gui_state`, then `gui_action` |
| 在遠端機器工作 | 使用相同工具並提供 `machine`；僅 worker 管理使用 `remote_*` |

## 互動式 workspace

### `workspace_open`

開啟或重用顯示明確指定 Logical Session 的 Live Workspace。傳入 session_manage 回傳的目前 session_id。Workspace 不會從 MCP transport 推斷任務身分；沒有活動 Logical Session 時必須明確傳入 null。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `session_id` | `string \| null` | required |  |
| `machine` | `string \| null` | `null` |  |
| `cwd` | `string` | `"."` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

## 環境、Skills 與任務狀態

### `environment_get`

回傳本機或 remote machine 的版本、workspace、驗證、policy 與環境資訊。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

### `skill_list`

列出已安裝 Agent Skills，但不載入完整 instructions。MCP tool surface 保持固定；Skill directory 新增或移除會在下一次呼叫反映。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_load`

依 `skill_list` 回傳的精確名稱載入一個已安裝 Skill，回傳完整 `SKILL.md` instructions 與 related file paths。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_read`

讀取一個已安裝 Skill 的 related text file。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `name` | `string` | required |  |
| `path` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `secret_scan`

在 commit 或 push 前掃描 local workspace 文字檔案中的常見 secrets。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `max_results` | `integer` | `200` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `session_manage`

管理單一持久 Logical Session。start 建立新任務並回傳其 session_id。resume 只會繼續使用者明確提供、或本對話中已經存在的 session_id。除 start 外的所有 action 都必須提供 session_id。Action：start、resume、get、report、finish、cancel、delete。report 接受 summary/findings/next/blockers/objective/label；delete 需要 terminal Session。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `action` | `string` | required |  |
| `session_id` | `string \| null` | `null` |  |
| `label` | `string \| null` | `null` |  |
| `objective` | `string \| null` | `null` |  |
| `summary` | `string \| null` | `null` |  |
| `findings` | `array[string] \| null` | `null` |  |
| `next` | `string \| null` | `null` |  |
| `blockers` | `array[string] \| null` | `null` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `plan_manage`

管理明確 Logical Session 的可選 Goal mode。活動 plan 在 15 分鐘沒有 agent activity 後啟用自動 continuation，最多 10 次。session_id 必須是 session_manage 回傳的同一個持久 id。Action：start、get、update、block、resume、finish、cancel。start 需要 objective 與 steps；finish 要求所有 steps 都是 completed 或 skipped。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `action` | `string` | required |  |
| `session_id` | `string` | required |  |
| `objective` | `string \| null` | `null` |  |
| `steps` | `array[object] \| null` | `null` |  |
| `step_id` | `string \| null` | `null` |  |
| `status` | `string \| null` | `null` |  |
| `text` | `string \| null` | `null` |  |
| `note` | `string \| null` | `null` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `audit_tail`

讀取最近的 local audit log entries。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `lines` | `integer` | `100` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Shell 與 jobs

### `run_shell`

在本機或 remote machine 執行一次非互動 shell command。適合應快速完成的 build、test、package-manager、Git 與 inspection command；長時間、互動式或 streaming process 應使用 `shell_start` 或 `job_start`。可選 purpose/explanation 欄位可說明執行原因。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `max_output_bytes` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

### `run_python`

在本機或 remote machine 寫入並執行短 Python script。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `code` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

### `shell_start`

在本機或 remote machine 啟動 persistent interactive shell。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `command` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

### `shell_send`

向 persistent local/remote shell session 傳送輸入。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `input_text` | `string` | required |  |
| `enter` | `boolean` | `true` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

### `shell_read`

讀取 persistent local/remote shell session 的最近輸出。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

### `shell_stop`

終止 persistent local/remote shell session。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

### `shell_list`

列出本機或 remote machine 上的 persistent shell sessions。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

### `job_start`

在本機或 remote machine 啟動被追蹤的 long-running job。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

### `job_list`

列出本機或 remote machine 上被追蹤的 jobs。活動中的 jobs 會優先回傳；`limit` 會限制在 1-1000 範圍內。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `include_finished` | `boolean` | `true` |  |
| `limit` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

### `job_tail`

讀取被追蹤 local/remote job 的最近輸出。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

### `job_stop`

停止被追蹤的 local/remote job。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

### `job_retry`

重新啟動已停止或退出的被追蹤 local/remote job。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

## 檔案與傳輸

### `file_list`

列出本機或 remote machine 上的檔案與目錄。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `path` | `string` | `"."` |  |
| `recursive` | `boolean` | `false` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

### `file_tree`

回傳本機或 remote machine 上緊湊的 directory tree。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `depth` | `integer` | `3` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

### `file_glob`

依 glob 在本機或 remote machine 尋找 paths。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `pattern` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `max_results` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

### `file_grep`

搜尋本機或 remote machine 的檔案內容。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `query` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `regex` | `boolean` | `true` |  |
| `case_sensitive` | `boolean` | `true` |  |
| `max_results` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

### `file_read`

讀取本機或 remote machine 上一個檔案或一組檔案。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `path` | `string \| array[string]` | required |  |
| `start_line` | `integer \| null` | `null` |  |
| `end_line` | `integer \| null` | `null` |  |
| `binary_preview` | `string \| null` | `null` |  |
| `binary_preview_bytes` | `integer` | `256` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

### `image_view`

將 PNG、JPEG、GIF 或 WebP 檔案作為原生 MCP image content 檢視；需要視覺檢查時優先於 `file_read`。Remote image 重用現有 file-transfer protocol，因此 worker 不需要額外 image-specific RPC。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `path` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

### `file_write`

在本機或 remote machine 寫入 UTF-8 text file。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `path` | `string` | required |  |
| `content` | `string` | required |  |
| `overwrite` | `boolean` | `true` |  |
| `encoding` | `string` | `"utf-8"` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

### `file_edit`

對一個本機或 remote file 套用一個或多個 exact-text edits。每個 edit 包含 old、new 與可選 `replace_all`；old 必須完全相符，包括 whitespace 與 indentation。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `path` | `string` | required |  |
| `edits` | `array[TextEdit]` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

### `file_delete`

刪除本機或 remote file/directory。`recursive=false` 只能刪除檔案或空目錄；非空目錄必須使用 `recursive=true`，並應謹慎操作。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `path` | `string` | required |  |
| `recursive` | `boolean` | `false` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

### `file_patch`

在本機或遠端檢查並套用 unified diff 或 file_patch envelope。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `patch` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

### `remote_transfer`

啟動受追蹤的 job，在 controller 與遠端機器之間複製檔案或目錄。遠端上傳使用可續傳的 raw-binary chunk；使用 `job_list`、`job_tail`、`job_stop` 和 `job_retry` 管理傳輸。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `source_path` | `string` | required |  |
| `destination_path` | `string` | required |  |
| `source_machine` | `string \| null` | `null` |  |
| `destination_machine` | `string \| null` | `null` |  |
| `overwrite` | `boolean` | `false` |  |
| `chunk_size` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

必須至少指定 `source_machine` 和 `destination_machine` 之一。省略的端點代表 controller workspace；來源可以是檔案或目錄。

### `link_create`

為本機檔案建立暫時 browser-accessible URL。預設為 attachment download；需在 browser 或 Markdown image 直接渲染時設 `inline=true`。Link 是 public bearer URL，由 high-entropy token、TTL、可選 download-count limit 與明確 revocation 保護。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `path` | `string` | required |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `filename` | `string \| null` | `null` |  |
| `max_downloads` | `integer \| null` | `null` |  |
| `inline` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_list`

列出已產生的 local file download URLs。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `include_expired` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_revoke`

撤銷已產生的 local file download URL。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `token` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## 動態 MCP gateway

### `mcp_manage`

註冊、列出、讀取、啟用、停用、refresh、移除或更新 dynamic MCP servers 的隔離 environment/headers。`stdio` transport 使用 command/args/cwd，`streamable_http` transport 使用 url。Secret env/header values 會私密持久化且永不回傳。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `action` | `string` | required |  |
| `name` | `string \| null` | `null` |  |
| `transport` | `string \| null` | `null` |  |
| `command` | `string \| null` | `null` |  |
| `args` | `array[string] \| null` | `null` |  |
| `cwd` | `string \| null` | `null` |  |
| `url` | `string \| null` | `null` |  |
| `env` | `object \| null` | `null` |  |
| `headers` | `object \| null` | `null` |  |
| `enabled` | `boolean` | `true` |  |
| `overwrite` | `boolean` | `false` |  |
| `refresh` | `boolean` | `true` |  |
| `key` | `string \| null` | `null` |  |
| `value` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_search`

搜尋已啟用 dynamic MCP servers 的 cached lightweight tool summaries。Dynamic tools 不會進入本 server 的 `tools/list`；呼叫前先用回傳的 `<server>:<tool>` 名稱搭配 `mcp_tool_inspect`。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `query` | `string` | `""` |  |
| `server` | `string \| null` | `null` |  |
| `limit` | `integer` | `20` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_inspect`

回傳名為 `<server>:<tool>` 的 dynamic MCP tool 完整 cached schema；若 cache stale，先用 `mcp_manage` refresh server。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_call`

呼叫名為 `<server>:<tool>` 的 cached dynamic MCP tool。先用 `mcp_tool_search` 探索，再用 `mcp_tool_inspect` 檢查 schema；external MCP connection 僅在本次呼叫期間開啟。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `name` | `string` | required |  |
| `arguments` | `object \| null` | `null` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## 瀏覽器自動化

### `browser_session`

在本機或遠端啟動、列出、關閉或清理 persistent high-level browser sessions。`start` 可開啟 URL、重用 persistent `profile_id` 或載入 `storage_state_path`；`close` 可儲存 storage state。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `action` | `string` | required |  |
| `session_id` | `string \| null` | `null` |  |
| `browser` | `string` | `"chromium"` |  |
| `headless` | `boolean` | `true` |  |
| `width` | `integer` | `1440` |  |
| `height` | `integer` | `1000` |  |
| `url` | `string \| null` | `null` |  |
| `wait_until` | `string` | `"domcontentloaded"` |  |
| `profile_id` | `string \| null` | `null` |  |
| `storage_state_path` | `string \| null` | `null` |  |
| `save_storage_state_path` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

### `browser_snapshot`

擷取 persistent browser page：title、URL、bounded visible text、帶 `e1` 等 stable short refs 的 interactive elements、最近 page/network errors，以及可選 screenshot path。Page 導航或重新 snapshot 前，可直接將 refs 作為 `browser_act` targets。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `include_text` | `boolean` | `true` |  |
| `screenshot` | `boolean` | `true` |  |
| `full_page` | `boolean` | `false` |  |
| `max_text_chars` | `integer` | `100000` |  |
| `max_elements` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

### `browser_act`

在 persistent browser session 執行 structured actions，支援 navigate、new_page、close_page、click、fill、type、select、press、check、uncheck、hover、wait、wait_for_text、wait_for_url。Target 可為 `browser_snapshot` 的 `e1` 等 ref 或 CSS selector；只有 high-level actions 不足時才使用 `browser_run_script`。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `actions` | `array[object]` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `timeout_ms` | `integer` | `30000` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

### `browser_run_script`

在本機或 remote machine 執行完整 Python Playwright script。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `script` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。

## 桌面 GUI 自動化

### `gui_list`

List visible desktop application windows and GUI backend capabilities locally or remotely.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session for this tool call. Pass the session_id returned by session_manage while working in that task. Use null only when no Logical Session is active. This is the same durable session_id used by session_manage. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `gui_state`

Observe one desktop window before acting. Returns its accessibility elements plus an optional native MCP screenshot and a short-lived state_id. Prefer element_id actions; coordinate actions are relative to the observed window and are rejected if the window moved or resized.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `window_id` | `string` | required |  |
| `screenshot` | `boolean` | `true` |  |
| `include_elements` | `boolean` | `true` |  |
| `max_elements` | `integer` | `300` |  |
| `max_depth` | `integer` | `12` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session for this tool call. Pass the session_id returned by session_manage while working in that task. Use null only when no Logical Session is active. This is the same durable session_id used by session_manage. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `gui_action`

Execute GUI actions against a fresh gui_state observation locally or remotely. The state_id is single-use. Prefer semantic element_id targeting; raw x/y coordinates are window-relative. Supported actions are click, double_click, right_click, move, scroll, drag, type, key, set_value, focus, and wait.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `window_id` | `string` | required |  |
| `state_id` | `string` | required |  |
| `actions` | `array[GuiAction]` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session for this tool call. Pass the session_id returned by session_manage while working in that task. Use null only when no Logical Session is active. This is the same durable session_id used by session_manage. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

## 遠端 worker 管理

### `remote_manage`

使用 action=invite、list、revoke 或 rename 管理 remote workers。invite 接受 name/workdir/ttl_s；revoke 需要 machine；rename 需要 machine 與 new_name。

| 參數 | 類型 | 必填/預設值 | 說明 |
|---|---|---|---|
| `action` | `string` | required |  |
| `name` | `string \| null` | `null` |  |
| `workdir` | `string \| null` | `null` |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `new_name` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | 這次工具呼叫所屬的 Logical Session。處理該任務時，傳入 session_manage 回傳的 session_id。只有在沒有活動 Logical Session 時才使用 null。 |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

指定 `machine` 時，呼叫還需要 `remote:use`，並透過遠端 worker 協定執行。
