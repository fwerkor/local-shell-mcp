# REST API

本頁說明「REST API」情境，並沿用文件站統一的 Runtime/Client 結構。

## 概覽

Runtime 決定服務程序如何執行以及控制哪個工作區。Client 決定 ChatGPT 或其他 MCP 用戶端如何連線。Docker、VS Code 擴充、獨立二進位、Python/pipx/原始碼安裝與 stdio 都是 Runtime 選項；ChatGPT 連接器、通用 HTTP MCP 用戶端與 stdio MCP 用戶端則是 Client 連線方式。

## 適用情境

- 當你選擇的 Runtime 或 Client 路徑與本頁標題相符時使用本頁。
- 保持工作區根目錄、公開 base URL、MCP endpoint、認證模式與主機可用工具一致。
- ChatGPT 網頁或 App 需要暴露以 `/mcp` 結尾的 HTTPS MCP endpoint。
- 本機 MCP 用戶端可依用戶端能力選擇 HTTP localhost 或 `local-shell-mcp --mode stdio`。

## 步驟

1. 先選擇 Runtime 安裝頁面。
2. 啟動 Runtime；如果使用 HTTP 模式，檢查 `/healthz`。
3. 再選擇 Client 連線頁面。
4. 在 Client 中註冊 MCP endpoint 或 stdio 命令。
5. 呼叫 `environment_info` 檢查實際工作區與設定。

```text
Runtime: Docker / VS Code extension / binary / Python / stdio
Client:  ChatGPT connector / generic HTTP MCP / generic stdio MCP
Endpoint: https://your-host.example.com/mcp
```

## 驗證

- `environment_info` 確認執行階段設定與工作區。
- `tree_view` 確認可見檔案。
- `git_status_tool` 確認儲存庫上下文。
- `run_shell_tool` 確認命令執行環境。

## 說明

優先使用小而可驗證的步驟：查看、編輯、diff、測試、掃描、提交。大型任務也應拆成可稽核的工具呼叫。
