# Stdio 運行時

stdio 模式用於本地 MCP 客戶端：客戶端把 `local-shell-mcp` 作爲子進程啓動，並通過標準輸入 / 輸出通信。

它不是公開 HTTP 部署方式。ChatGPT 網頁或 App 不能直接使用 stdio，因爲 ChatGPT 無法在你的機器上啓動進程。

## 何時使用 stdio

適合使用 stdio 模式的情況：

- 你的 MCP 客戶端支持基於命令的 server 定義。
- 客戶端和受控工作區位於同一臺機器。
- 你不需要 OAuth、公開 HTTPS、反向代理或隧道。
- 你希望客戶端管理服務生命週期。

不適合使用 stdio 模式的情況：

- 客戶端是 ChatGPT 網頁或 App。
- 多個遠程客戶端需要共享同一個服務。
- 你需要通過 HTTP 提供帶 token 的文件下載。
- 你需要通過 HTTP 提供遠程 worker 加入路由。

## 命令

```bash
LOCAL_SHELL_MCP_WORKSPACE_ROOT=/path/to/workspace local-shell-mcp --mode stdio
```

通用 MCP 客戶端配置通常類似：

```json
{
  "mcpServers": {
    "local-shell-mcp": {
      "command": "local-shell-mcp",
      "args": ["--mode", "stdio"],
      "env": {
        "LOCAL_SHELL_MCP_WORKSPACE_ROOT": "/path/to/workspace"
      }
    }
  }
}
```

按你的客戶端 schema 調整。不同客戶端可能把這個區塊叫作 `servers`、`tools`、`mcpServers` 或 `contextServers`。

## 與 HTTP 模式的行爲差異

| 項目 | stdio 模式 | HTTP MCP 模式 |
|---|---|---|
| 傳輸 | stdin / stdout | HTTP streamable MCP 端點 |
| 端點 | 無 | `/mcp` |
| OAuth | 不需要 | 公網使用時建議開啓 |
| 健康檢查端點 | 無 | `/healthz`、`/readyz` |
| ChatGPT 公網使用 | 不支持 | 支持，需要 HTTPS |
| 服務生命週期 | 客戶端啓動進程 | 你管理進程或運行時 |

除此之外，工具面仍是同一套服務端實現，具體可用性取決於配置和客戶端支持。

## 安全說明

stdio 模式通常直接在宿主機上以 MCP 客戶端同一用戶身份運行。使用較窄的 workspace root，避免廣泛文件系統訪問。除非 stdio 本身運行在一次性容器或 VM 中，否則保持 full-container 模式關閉。
