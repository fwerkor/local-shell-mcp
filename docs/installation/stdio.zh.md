# Stdio 运行时

stdio 模式用于本地 MCP 客户端：客户端把 `local-shell-mcp` 作为子进程启动，并通过标准输入 / 输出通信。

它不是公开 HTTP 部署方式。ChatGPT 网页或 App 不能直接使用 stdio，因为 ChatGPT 无法在你的机器上启动进程。

## 何时使用 stdio

适合使用 stdio 模式的情况：

- 你的 MCP 客户端支持基于命令的 server 定义。
- 客户端和受控工作区位于同一台机器。
- 你不需要 OAuth、公开 HTTPS、反向代理或隧道。
- 你希望客户端管理服务生命周期。

不适合使用 stdio 模式的情况：

- 客户端是 ChatGPT 网页或 App。
- 多个远程客户端需要共享同一个服务。
- 你需要通过 HTTP 提供带 token 的文件下载。
- 你需要通过 HTTP 提供远程 worker 加入路由。

## 命令

```bash
LOCAL_SHELL_MCP_WORKSPACE_ROOT=/path/to/workspace local-shell-mcp --mode stdio
```

通用 MCP 客户端配置通常类似：

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

按你的客户端 schema 调整。不同客户端可能把这个区块叫作 `servers`、`tools`、`mcpServers` 或 `contextServers`。

## 与 HTTP 模式的行为差异

| 项目 | stdio 模式 | HTTP MCP 模式 |
|---|---|---|
| 传输 | stdin / stdout | HTTP streamable MCP 端点 |
| 端点 | 无 | `/mcp` |
| OAuth | 不需要 | 公网使用时建议开启 |
| 健康检查端点 | 无 | `/healthz`、`/readyz` |
| ChatGPT 公网使用 | 不支持 | 支持，需要 HTTPS |
| 服务生命周期 | 客户端启动进程 | 你管理进程或运行时 |

除此之外，工具面仍是同一套服务端实现，具体可用性取决于配置和客户端支持。

## 安全说明

stdio 模式通常直接在宿主机上以 MCP 客户端同一用户身份运行。使用较窄的 workspace root，避免广泛文件系统访问。除非 stdio 本身运行在一次性容器或 VM 中，否则保持 full-container 模式关闭。
