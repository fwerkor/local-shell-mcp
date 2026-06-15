# local-shell-mcp 中文文档

面向 ChatGPT Developer Mode 和其它 MCP 客户端的本地控制平面。它把受控工作区、shell、文件、Git、浏览器自动化、文件链接和远程节点统一暴露为 MCP 工具。

## Documentation paths

- [快速开始](getting-started/quickstart.md)
- [ChatGPT 连接器](getting-started/chatgpt-connector.md)
- [远程节点](guides/remote-workers.md)
- [安全说明](security.md)
- [故障排查](troubleshooting.md)

## Core architecture

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## Key safety rule

公网部署必须启用 OAuth；不要挂载 Docker socket、宿主机根目录或长期凭据。
