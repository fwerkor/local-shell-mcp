# local-shell-mcp 文件

面向 ChatGPT Developer Mode 與其他 MCP 用戶端的本機控制平面。它將受控工作區、shell、檔案、Git、瀏覽器自動化、檔案連結與遠端 worker 暴露為 MCP 工具。

## 文件路徑

- [快速開始](getting-started/quickstart.md)
- [ChatGPT 連接器](getting-started/chatgpt-connector.md)
- [遠端 worker](guides/remote-workers.md)
- [安全](security.md)
- [疑難排解](troubleshooting.md)

## 核心架構

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## 關鍵安全規則

公開部署時啟用 OAuth，不要掛載 Docker socket、主機根目錄或長期憑據。
