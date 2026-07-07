# 通用 MCP 客户端

`local-shell-mcp` 可供 ChatGPT 使用，也可供其它 MCP 客户端使用。客户端决定是通过 HTTP 连接，还是通过 stdio 启动服务。

## HTTP MCP 客户端

当服务已经在运行时，使用 HTTP 模式：

```bash
LOCAL_SHELL_MCP_WORKSPACE_ROOT=/path/to/workspace local-shell-mcp --mode mcp
```

本地端点：

```text
http://127.0.0.1:8765/mcp
```

网络端点：

```text
https://your-public-host.example.com/mcp
```

任何超出可信 localhost 范围可访问的端点都应使用 OAuth。

## Stdio MCP 客户端

当客户端自己启动服务进程时，使用 stdio 模式：

```bash
LOCAL_SHELL_MCP_WORKSPACE_ROOT=/path/to/workspace local-shell-mcp --mode stdio
```

典型客户端配置结构：

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

不同客户端 schema 不完全相同。有些叫 `mcpServers`，也有些使用其它名称。

## 连接器式 search / fetch

服务也暴露只读的连接器式 `search` 和 `fetch` 工具。它们适合基本文件发现，但不能替代完整 MCP 工具面。

使用 `/mcp` 才能获得完整的 shell、文件系统、Git、浏览器、文件链接和远程 worker 工具。

## 第一次安全检查

新客户端连接后，先执行：

```text
调用 environment_info，然后对工作区根目录调用 tree_view。暂时不要修改文件。
```

之后再运行带有明确编辑、测试和 Git 规则的有边界任务。
