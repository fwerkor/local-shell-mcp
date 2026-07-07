# 工具參考

本頁是 `local-shell-mcp` 暴露給 MCP 客戶端的人工可讀工具參考。工具名、參數名和返回字段保持代碼標識符，便於與 MCP schema、審計日誌和運行時返回值對應。

普通工具返回結構化 `ToolResult`，包含 `ok`、`message` 和 `data`。連接器式 `search` / `fetch` 爲兼容連接器發現，返回 JSON 字符串。除非啓用 full-container 策略，文件系統和 shell 操作都受 `LOCAL_SHELL_MCP_WORKSPACE_ROOT` 限制。遠程工具在已連接 worker 上執行，並帶有機器選擇參數。

## 如何選擇工具

| 需求 | 推薦順序 |
|---|---|
| 第一次連接檢查 | `environment_info` -> `tree_view` -> `git_status_tool` |
| 定位代碼 | `tree_view` -> `glob_search` / `grep_search` -> `read_file` |
| 精確修改文件 | `read_file` -> `edit_file` / `multi_edit_file` / `apply_patch` -> `git_diff_tool` |
| 運行命令 | 一次性命令用 `run_shell_tool`；長時間會話用持久 shell 工具 |
| 提交代碼 | `git_status_tool` -> `git_diff_tool` -> `secret_scan` -> `git_add_tool` -> `git_commit_tool` |
| 採集瀏覽器證據 | `browser_get_text_tool`、`browser_screenshot_tool`、`browser_pdf_tool` |
| 分享生成文件 | `create_file_link` -> `list_file_links` -> `revoke_file_link` |
| 操作另一臺機器 | `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> `remote_*` 工具 |

## 連接器與發現

| 工具 | 用途 | 關鍵輸入 | 返回 |
|---|---|---|---|
| `search` | 搜索工作區文件，並返回 ChatGPT 連接器兼容結果。適合只讀發現，不建議作爲主要編程工具。 | `query`：普通發現查詢字符串。 | 連接器兼容 JSON 字符串。 |
| `fetch` | 讀取由 `search` 返回 id 對應的工作區文件。 | `id`：連接器式文件標識符。 | 連接器兼容 JSON 字符串。 |

## 環境、審計和任務狀態

| 工具 | 用途 | 關鍵輸入 | 常見組合 |
|---|---|---|---|
| `environment_info` | 返回工作區、認證、策略和基礎環境探測信息。 | 無。 | 第一次連接後先調用，再用 `tree_view`。 |
| `version_info` | 返回運行時版本、包版本、Python 版本、平臺和可執行路徑。 | 無。 | 升級後覈對實際運行版本。 |
| `audit_tail` | 讀取最近審計日誌。 | `lines`：行數，默認 `100`。 | 敏感操作後複查工具調用。 |
| `todo_read_tool` | 讀取 agent todo 列表。 | 無。 | 恢復多步驟任務上下文。 |
| `todo_write_tool` | 寫入 agent todo 列表。 | `todos`：包含 id、content、status、priority 的記錄列表。 | 長任務前建立計劃。 |
| `secret_scan` | 提交或推送前掃描工作區文本文件中的常見密鑰。 | `cwd`、`glob`、`max_results`。 | `git_diff_tool` 後、`git_commit_tool` 前。 |

## 文件系統與搜索

| 工具 | 用途 | 關鍵輸入 | 注意事項 |
|---|---|---|---|
| `list_files` | 列出目錄下文件和子目錄。 | `path`、`recursive`、`max_entries`。 | 適合快速目錄檢查。 |
| `tree_view` | 返回緊湊目錄樹。 | `cwd`、`depth`、`max_entries`。 | 大倉庫先用它摸底。 |
| `glob_search` | 按 glob 查找路徑。 | `pattern`、`cwd`、`max_results`。 | 適合找文件名或擴展名。 |
| `grep_search` | 用 ripgrep 搜索文件內容。 | `query`、`cwd`、`glob`、`regex`、`case_sensitive`、`max_results`。 | 適合定位代碼符號或文本。 |
| `read_file` | 讀取 UTF-8 文本文件，可按行範圍讀取。 | `path`、`start_line`、`end_line`。 | 編輯前必須讀取目標內容。 |
| `read_many_files` | 批量讀取多個 UTF-8 文本文件。 | `paths`、`start_line`、`end_line`。 | 適合同類小文件對比。 |
| `write_file` | 創建或整體替換 UTF-8 文件。 | `path`、`content`、`overwrite`。 | 對已有文件優先用精確編輯工具。 |
| `edit_file` | 用精確文本替換修改文件。 | `path`、`old`、`new`、`replace_all`。 | `old` 必須完全匹配。 |
| `multi_edit_file` | 對同一文件應用多處精確替換。 | `path`、`edits`。 | 修改前先讀取，避免陳舊上下文。 |
| `apply_patch` | 應用 unified diff。 | `patch`、`cwd`。 | 適合多文件或較大補丁。 |
| `delete_file_or_dir` | 刪除文件或目錄。 | `path`、`recursive`。 | 非空目錄必須顯式 `recursive=true`。 |

## Shell、Python、持久會話和 job

| 工具 | 用途 | 關鍵輸入 | 注意事項 |
|---|---|---|---|
| `run_shell_tool` | 運行一次性非交互 shell 命令。 | `command`、`cwd`、`timeout_s`、`max_output_bytes`。 | 用於測試、構建、包查詢、短命令。 |
| `run_python_tool` | 寫入臨時 Python 文件並執行。 | `code`、`cwd`、`timeout_s`。 | 適合結構化分析、JSON / 文本處理、生成文件。 |
| `shell_start` | 啓動持久 shell session。 | `cwd`、`name`、`command`。 | 適合 REPL、開發服務器、watch 任務。 |
| `shell_read` | 讀取持久 shell 最近輸出。 | `session_id`、`lines`。 | 與 `shell_start` 搭配。 |
| `shell_send` | 向持久 shell 發送輸入。 | `session_id`、`input_text`、`enter`。 | 可用於交互進程或繼續命令。 |
| `shell_list` | 列出活動持久 shell。 | 無。 | 不確定 session id 時使用。 |
| `shell_kill` | 終止持久 shell session。 | `session_id`。 | 驗證後清理長時間進程。 |
| `job_start` | 啓動帶追蹤的長時間 job。 | `command`、`cwd`、`name`。 | 適合構建、服務器、實驗、watch。 |
| `job_list` | 列出已追蹤 job。 | `include_finished`。 | 查看運行 / 退出狀態。 |
| `job_tail` | 讀取 job 最近輸出。 | `job_id`、`lines`。 | 跟蹤長任務進度。 |
| `job_stop` | 停止已追蹤 job。 | `job_id`。 | 任務結束或卡住時使用。 |
| `job_retry` | 用原命令重試已停止或退出的 job。 | `job_id`。 | 修復環境後重跑。 |

## Git

| 工具 | 用途 | 關鍵輸入 | 常見用法 |
|---|---|---|---|
| `git_status_tool` | 顯示 git 狀態和 remote。 | `cwd`。 | 任何修改前先調用。 |
| `git_diff_tool` | 顯示 diff，可選擇 staged 或統計。 | `cwd`、`staged`、`path`、`stat`。 | 修改後複查。 |
| `git_add_tool` | stage 路徑。 | `cwd`、`paths`。 | 提交前只 stage 相關文件。 |
| `git_commit_tool` | 創建提交。 | `cwd`、`message`、`all_changes`。 | 提交前先跑測試和 `secret_scan`。 |
| `git_push_tool` | 推送當前 HEAD。 | `cwd`、`remote`、`branch`、`set_upstream`。 | 需要明確推送目標。 |
| `git_pull_tool` | 拉取當前分支。 | `cwd`、`ff_only`。 | 默認 fast-forward only。 |
| `git_fetch_tool` | fetch remote。 | `cwd`、`remote`、`prune`。 | 檢查上游狀態。 |
| `git_checkout_tool` | 切換或創建分支。 | `cwd`、`ref`、`create`。 | 創建修復分支或切換引用。 |
| `git_log_tool` | 顯示最近提交。 | `cwd`、`max_count`。 | 理解歷史。 |
| `git_show_tool` | 查看提交、對象或指定 ref 下文件。 | `cwd`、`ref`、`path`。 | 對比歷史文件。 |
| `git_reset_tool` | 執行 git reset。 | `cwd`、`mode`、`ref`。 | 有破壞性，需明確目標。 |

## 瀏覽器和 Playwright

| 工具 | 用途 | 關鍵輸入 | 典型場景 |
|---|---|---|---|
| `browser_get_text_tool` | 打開 URL 並返回選擇器可見文本。 | `url`、`selector`、`browser`、`wait_until`。 | 驗證頁面內容。 |
| `browser_eval_tool` | 打開 URL 並執行 JavaScript。 | `url`、`javascript`、`browser`、`wait_until`。 | 檢查頁面狀態。 |
| `browser_screenshot_tool` | 保存頁面截圖。 | `url`、`output_path`、`full_page`、`width`、`height`。 | UI 證據或視覺檢查。 |
| `browser_pdf_tool` | 用 Chromium 保存頁面 PDF。 | `url`、`output_path`、`width`、`height`。 | 文檔或報告導出。 |
| `playwright_install_tool` | 安裝 Playwright 瀏覽器二進制。 | `browser`、`with_deps`。 | 瀏覽器缺失時使用。 |
| `playwright_run_script_tool` | 運行完整 Python Playwright 腳本。 | `script`、`cwd`、`timeout_s`。 | 多頁面、多步驟或複雜檢查。 |

## 文件下載鏈接

| 工具 | 用途 | 關鍵輸入 | 安全點 |
|---|---|---|---|
| `create_file_link` | 爲工作區文件創建臨時公開下載 URL。 | `path`、`ttl_s`、`filename`、`max_downloads`。 | bearer URL，按需設置短 TTL。 |
| `list_file_links` | 列出已生成文件鏈接。 | `include_expired`。 | 檢查活動鏈接。 |
| `revoke_file_link` | 撤銷文件鏈接。 | `token`。 | 分享結束後關閉訪問。 |

## 遠程 worker 管理

| 工具 | 用途 | 關鍵輸入 | 說明 |
|---|---|---|---|
| `remote_invite` | 創建一次性遠程 worker 加入命令。 | `name`、`workdir`、`ttl_s`。 | 在遠程機器上運行生成命令。 |
| `remote_list_machines` | 列出已連接遠程 worker。 | 無。 | 確認機器在線。 |
| `remote_rename_machine` | 重命名遠程 worker。 | `machine`、`new_name`。 | 便於區分多臺機器。 |
| `remote_revoke_machine` | 撤銷並移除遠程 worker。 | `machine`。 | 任務結束後清理。 |
| `remote_environment_info` | 返回遠程工作區、認證、策略和基礎環境。 | `machine`。 | 遠程操作前先調用。 |

## 遠程文件系統、搜索和傳輸

| 工具 | 用途 | 關鍵輸入 |
|---|---|---|
| `remote_list_files` | 列出遠程目錄。 | `machine`、`path`、`recursive`、`max_entries`。 |
| `remote_tree_view` | 返回遠程目錄樹。 | `machine`、`cwd`、`depth`、`max_entries`。 |
| `remote_glob_search` | 遠程 glob 查找。 | `machine`、`pattern`、`cwd`、`max_results`。 |
| `remote_grep_search` | 遠程內容搜索。 | `machine`、`query`、`cwd`、`glob`、`regex`。 |
| `remote_read_file` | 讀取遠程文本文件。 | `machine`、`path`、`start_line`、`end_line`。 |
| `remote_read_many_files` | 批量讀取遠程文件。 | `machine`、`paths`、`start_line`、`end_line`。 |
| `remote_write_file` | 寫入遠程文件。 | `machine`、`path`、`content`、`overwrite`。 |
| `remote_edit_file` | 精確替換遠程文件文本。 | `machine`、`path`、`old`、`new`。 |
| `remote_multi_edit_file` | 對遠程單文件做多處精確替換。 | `machine`、`path`、`edits`。 |
| `remote_apply_patch` | 在遠程 worker 上應用 unified diff。 | `machine`、`patch`、`cwd`。 |
| `remote_delete_file_or_dir` | 刪除遠程文件或目錄。 | `machine`、`path`、`recursive`。 |
| `remote_push_file` | 從控制服務工作區複製文件到遠程 worker。 | `local_path`、`machine`、`remote_path`。 |
| `remote_pull_file` | 從遠程 worker 複製文件到控制服務工作區。 | `machine`、`remote_path`、`local_path`。 |
| `remote_push_dir` | 從控制服務複製目錄到遠程 worker。 | `local_path`、`machine`、`remote_path`。 |
| `remote_pull_dir` | 從遠程 worker 複製目錄到控制服務。 | `machine`、`remote_path`、`local_path`。 |
| `remote_copy_file` | 通過控制服務在兩個遠程 worker 之間複製文件。 | `src_machine`、`src_path`、`dst_machine`、`dst_path`。 |
| `remote_copy_dir` | 通過控制服務在兩個遠程 worker 之間複製目錄。 | `src_machine`、`src_path`、`dst_machine`、`dst_path`。 |

## 遠程 shell、job、Git 與瀏覽器

| 工具 | 用途 |
|---|---|
| `remote_run_shell_tool` | 在遠程 worker 上運行一次性 shell 命令。 |
| `remote_run_python_tool` | 在遠程 worker 上運行臨時 Python 腳本。 |
| `remote_shell_start` / `remote_shell_read` / `remote_shell_send` / `remote_shell_kill` / `remote_shell_list` | 管理遠程持久 shell session。 |
| `remote_job_start` / `remote_job_list` / `remote_job_tail` / `remote_job_stop` / `remote_job_retry` | 管理遠程長時間 job。 |
| `remote_git_status_tool`、`remote_git_diff_tool`、`remote_git_add_tool`、`remote_git_commit_tool`、`remote_git_push_tool`、`remote_git_pull_tool`、`remote_git_fetch_tool`、`remote_git_checkout_tool`、`remote_git_log_tool`、`remote_git_show_tool`、`remote_git_reset_tool` | 在遠程 worker 上執行對應 Git 操作。 |
| `remote_browser_get_text_tool`、`remote_browser_eval_tool`、`remote_browser_screenshot_tool`、`remote_browser_pdf_tool`、`remote_playwright_install_tool`、`remote_playwright_run_script_tool` | 在遠程 worker 上執行瀏覽器 / Playwright 操作。 |

## 使用建議

- 先用只讀工具確認上下文，再使用寫入、shell、Git 或遠程工具。
- 對可能產生風險的調用填寫 `purpose` 或 `explanation`，便於審計。
- 對長時間任務使用持久 session 或 job，不要讓一次性命令無意義地阻塞到超時。
- 修改後用 `git_diff_tool` 複查；提交前用 `secret_scan`。
- 遠程 worker 任務完成後撤銷機器，文件鏈接使用完後撤銷 token。
