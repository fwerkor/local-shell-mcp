# 獨立二進位

本頁是此主題的在地化頁面，保持與英文文件相同的 Runtime/Client 結構。

## 概覽

Runtime 是服务进程如何运行，Client 是 ChatGPT 或其它 MCP 客户端如何连接。Docker、VS Code 扩展、二进制、Python/pipx/source 和 stdio 属于 Runtime；ChatGPT connector、通用 HTTP MCP client 和 stdio MCP client 属于 Client 连接。

## 適用情境

- Use this page when the selected Runtime or Client path matches the title.
- Keep the workspace root, public base URL, MCP endpoint, authentication mode, and available host tools consistent.
- For ChatGPT web/app, expose an HTTPS MCP endpoint ending in `/mcp`.
- For local MCP clients, use HTTP localhost or `local-shell-mcp --mode stdio` depending on client support.

## 步驟

1. Choose the Runtime installation page first.
2. Start the Runtime and verify `/healthz` when HTTP mode is used.
3. Choose the Client connection page second.
4. Register the MCP endpoint or stdio command in the Client.
5. Call `environment_info` to verify the effective workspace and settings.

```text
Runtime: Docker / VS Code extension / binary / Python / stdio
Client:  ChatGPT connector / generic HTTP MCP / generic stdio MCP
Endpoint: https://your-host.example.com/mcp
```

## 驗證

- `environment_info` confirms runtime settings and workspace.
- `tree_view` confirms visible files.
- `git_status_tool` confirms repository context.
- `run_shell_tool` confirms the command environment.

## 說明

Prefer small, verifiable steps: inspect, edit, diff, test, scan, commit. Large tasks should still be decomposed into tool calls that can be audited.
