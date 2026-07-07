<div class="hero-shell" markdown>
<span class="hero-eyebrow">ChatGPT-compatible MCP control plane</span>

# local-shell-mcp

讓 ChatGPT 或其它 MCP 客戶端在受控環境中使用真實 Shell、工作區、Git、瀏覽器自動化、文件分享和遠程節點能力。

<div class="hero-actions" markdown>
[快速開始](getting-started/quickstart.md){ .hero-action .hero-action--primary }
[選擇運行時](guides/deployment.md){ .hero-action .hero-action--secondary }
[工具參考](reference/tools.md){ .hero-action .hero-action--secondary }
</div>
</div>

<div class="feature-grid" markdown>
<div class="feature-card" markdown>
### 真實編程環境
在一個 MCP 端點裏運行測試、檢查倉庫、修改文件、操作 Git，並保留審計記錄。
</div>

<div class="feature-card" markdown>
### 運行時和客戶端分層
Docker、VS Code 擴展、二進制、Python 和 stdio 是運行時；ChatGPT 和其它 MCP 客戶端是接入層。
</div>

<div class="feature-card" markdown>
### 遠程機器控制
通過遠程節點的出站連接控制 NAT、防火牆或 HPC 環境後的機器，無需開放 SSH 入站端口。
</div>
</div>

## 它提供什麼

`local-shell-mcp` 會把一個受控的本地或容器工作區暴露給 ChatGPT 和其它 MCP 客戶端。它提供 Shell、持久 Shell、文件系統、搜索、補丁、Git、Playwright、審計、todo、臨時文件鏈接和遠程節點工具，並支持 ChatGPT 兼容的 MCP over HTTP 與 OAuth。

適用場景包括：檢查倉庫、運行測試、修改代碼、操作 Git、採集網頁證據、生成可下載產物，或者控制只能主動連接控制端的遠程機器。

## 架構

```text
運行時層：Docker / VS Code 擴展 / 二進制 / Python / stdio
網絡層：localhost / HTTPS 反向代理 / 隧道 / stdio 管道
客戶端層：ChatGPT / 通用 MCP 客戶端 / 編輯器輔助入口
受控工作區：/workspace 或配置的 workspace root
可選遠程節點：遠程機器主動連接控制端
```

建議把容器或虛擬機作爲隔離邊界。

## 按場景選擇入口

| 場景 | 閱讀頁面 | 原因 |
|---|---|---|
| 第一次部署給 ChatGPT 使用 | [快速開始](getting-started/quickstart.md) | Docker Compose、OAuth 和 `/mcp` 基礎路徑 |
| 選擇運行時層 | [運行時選擇](guides/deployment.md) | 把 Docker、VS Code、二進制、Python 和 stdio 與客戶端接入分開說明 |
| 把 ChatGPT 作爲客戶端接入 | [ChatGPT 連接器](getting-started/chatgpt-connector.md) | 端點、OAuth、首次安全提示和工具發現 |
| 從 VS Code 啓動運行時 | [VS Code 擴展運行時](installation/vscode-extension.md) | 編輯器啓動、設置和主機安全邊界 |
| 學習如何使用工具集 | [使用模式](guides/usage-patterns.md) | 提示詞模板和工具選擇建議 |
| 理解所有工具 | [工具參考](reference/tools.md) | 每個工具的用途、參數、返回值、組合方式和注意事項 |
| 連接 HPC、NPU/GPU 或服務器節點 | [遠程節點](guides/remote-workers.md) | 出站 worker 加入流程和遠程工具用法 |
| 分享生成的文件 | [文件鏈接](guides/file-links.md) | 帶 TTL 和撤銷能力的臨時下載鏈接 |
| 加固公開部署 | [安全](security.md) | 隔離、OAuth、工作區範圍和審計日誌 |

## 主要工具族

| 工具族 | 示例 | 用途 |
|---|---|---|
| Shell 和 Python | `run_shell_tool`, `run_python_tool`, `shell_start` | 構建、測試、腳本、長時間進程 |
| 文件和搜索 | `tree_view`, `grep_search`, `read_file`, `apply_patch` | 倉庫檢查和精確修改 |
| Git | `git_status_tool`, `git_diff_tool`, `git_commit_tool`, `git_push_tool` | 可審查的源碼管理流程 |
| 瀏覽器 | `browser_screenshot_tool`, `browser_get_text_tool`, `browser_eval_tool` | UI 檢查、截圖、渲染文檔、頁面文本 |
| 文件鏈接 | `create_file_link`, `revoke_file_link` | 從聊天中下載生成產物 |
| 遠程節點 | `remote_invite`, `remote_run_shell_tool`, `remote_push_file` | NAT、防火牆或集羣登錄流程後的機器 |

## 典型工作流

### 用 ChatGPT 編程

1. 選擇 Docker Compose、VS Code 擴展、二進制或 Python 等運行時，並在專用工作區啓動。
2. 如果 ChatGPT 需要訪問該運行時，先配置網絡入口。
3. 把公開 `/mcp` 端點添加到 ChatGPT。
4. 先讓 ChatGPT 檢查倉庫並執行只讀檢查。
5. 確認後再讓它修改文件、運行測試、檢查 diff、提交和推送。
6. 涉及文件鏈接或遠程系統時查看審計日誌。

### 遠程 HPC 或加速卡主機

1. 創建一次性遠程節點邀請。
2. 在遠程主機上粘貼生成的命令。
3. 通過 ChatGPT 使用 `remote_run_shell_tool`、`remote_read_file`、`remote_push_file` 和遠程 Git 工具。
4. 任務結束後撤銷該節點。

### 產物生成

1. 讓 AI 在 `/workspace` 下生成文件。
2. 創建帶 TTL 或下載次數限制的臨時文件鏈接。
3. 在聊天中分享鏈接。
4. 使用結束後撤銷鏈接。

## 語言

本站使用 MkDocs 原生 i18n 插件構建。可以通過頂部語言選擇器切換語言；尚未翻譯的頁面會回退到英文版本。
