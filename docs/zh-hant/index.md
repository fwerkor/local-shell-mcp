# local-shell-mcp 繁體中文文件

面向 ChatGPT Developer Mode 與其他 MCP 客戶端的本機控制平面。它將受控工作區、shell、檔案、Git、瀏覽器自動化、檔案連結與遠端節點統一暴露為 MCP 工具。

## Documentation paths

- [快速開始](getting-started/quickstart.md)
- [ChatGPT 連接器](getting-started/chatgpt-connector.md)
- [遠端節點](guides/remote-workers.md)
- [安全說明](security.md)
- [疑難排解](troubleshooting.md)

## Core architecture

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## Key safety rule

公開部署必須啟用 OAuth；不要掛載 Docker socket、主機根目錄或長期憑證。
