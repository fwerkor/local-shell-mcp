# Runtime 与 Client 模型

本页说明“Runtime 与 Client 模型”场景，并沿用文档站统一的 Runtime/Client 结构。

## 概览

Runtime 决定服务进程如何运行以及控制哪个工作区。Client 决定 ChatGPT 或其它 MCP 客户端如何连接。Docker、VS Code 扩展、独立二进制、Python/pipx/源码安装和 stdio 都是 Runtime 选择；ChatGPT 连接器、通用 HTTP MCP 客户端和 stdio MCP 客户端属于 Client 连接方式。

## 适用场景

- 当你选择的 Runtime 或 Client 路径与本页标题匹配时使用本页。
- 保持工作区根目录、公开 base URL、MCP endpoint、认证模式和主机可用工具一致。
- ChatGPT 网页或 App 需要暴露以 `/mcp` 结尾的 HTTPS MCP endpoint。
- 本地 MCP 客户端可按客户端能力选择 HTTP localhost 或 `local-shell-mcp --mode stdio`。

## 步骤

1. 先选择 Runtime 安装页面。
2. 启动 Runtime；如果使用 HTTP 模式，检查 `/healthz`。
3. 再选择 Client 连接页面。
4. 在 Client 中注册 MCP endpoint 或 stdio 命令。
5. 调用 `environment_info` 检查实际工作区和设置。

```text
Runtime: Docker / VS Code extension / binary / Python / stdio
Client:  ChatGPT connector / generic HTTP MCP / generic stdio MCP
Endpoint: https://your-host.example.com/mcp
```

## 验证

- `environment_info` 确认运行时设置和工作区。
- `tree_view` 确认可见文件。
- `git_status_tool` 确认仓库上下文。
- `run_shell_tool` 确认命令执行环境。

## 说明

优先使用小而可验证的步骤：查看、编辑、diff、测试、扫描、提交。大型任务也应拆成可审计的工具调用。
