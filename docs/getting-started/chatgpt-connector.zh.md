# ChatGPT 连接器

本页说明如何把 ChatGPT 作为客户端接入。它不负责选择运行时。使用本页前，先通过 Docker、VS Code 扩展、独立二进制或 Python 安装方式启动 `local-shell-mcp` 服务。

`local-shell-mcp` 面向 ChatGPT Developer Mode 和完整 MCP 客户端设计。同时，它也提供只读的连接器式 `search` 和 `fetch` 工具，便于客户端发现文件内容。

## 运行时前置条件

先选择并启动一个运行时：

| 运行时 | 页面 |
|---|---|
| Docker Compose | [Docker Compose 运行时](../installation/docker.md) |
| VS Code 扩展 | [VS Code 扩展运行时](../installation/vscode-extension.md) |
| 独立二进制 | [独立二进制运行时](../installation/binary.md) |
| Python / pipx / 源码 | [Python 运行时](../installation/python.md) |

然后通过 ChatGPT 可访问的网络路径暴露这个运行时。网络入口与反向代理要求见 [网络连通性](../clients/connectivity.md)。

## 公共 URL

ChatGPT 必须通过 HTTPS 访问服务。MCP 端点是：

```text
https://your-public-host.example.com/mcp
```

确保 `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` 只填写公开源站地址：

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

不要在 `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` 后面追加 `/mcp`。

## OAuth 设置

公开部署建议使用以下配置：

```env
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=<long random value>
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=<long random value>
LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S=0
```

访问令牌默认不会自动过期，因为较长的编程会话可能超过短令牌寿命。需要撤销访问时，可以轮换 JWT secret，或使用全新的状态重新部署。

## 添加连接器

1. 打开 ChatGPT 的连接器设置或 Developer Mode 的 MCP 设置。
2. 添加自定义 MCP 服务器。
3. 输入 MCP URL：`https://your-public-host.example.com/mcp`。
4. 完成 OAuth 授权。
5. 审核并批准工具列表。

## 第一次提示词

```text
使用 local-shell-mcp。先调用 environment_info，然后列出工作区根目录。暂时不要修改文件。
```

这个提示只验证连通性，不会主动修改文件。

## 推荐操作规则

给模型明确边界：

- 除非另有说明，只在 `/workspace` 内工作。
- 提交前先运行测试。
- 推送前使用 `secret_scan`。
- 只对可以分享的文件使用 `create_file_link`。
- 长时间进程优先使用持久 shell session。
- 汇总所有修改过文件的命令。

## 工具发现问题

如果 ChatGPT 能完成认证，但没有显示预期工具：

- 确认端点以 `/mcp` 结尾。
- 检查 `LOCAL_SHELL_MCP_REQUIRE_AUTH_FOR_MCP_DISCOVERY`。
- 检查反向代理请求头与请求体大小限制。
- 查看 `docker compose logs --tail=200 local-shell-mcp`。
- 确认服务运行在 `mcp` 或 `both` 模式。

## 安全说明

公开部署应保持 OAuth 开启。不要在公网暴露未认证的完整 MCP 工具。每个被批准的工具都应视为已接入模型实际权限的一部分。
