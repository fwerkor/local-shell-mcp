<!-- i18n-source-sha256: b7c3dfd7dc21a498f8410a88a8a52094ca0349856dfa43d267e3fe7bb273685a -->
# 接入 Gemini Spark / 自定义应用

Gemini 的 **自定义连接应用** 功能（之前称为 **Spark**）允许符合条件的 Gemini 用户连接远程 MCP 服务器。 LSM 可以提供 MCP 端点。这是到 [统一 Web 工作区](web-workspace.md)、[ChatGPT](chatgpt-connector.md) 和其他 MCP 客户端的**替代客户端连接**；它不会替换或部署 LSM 控制器。

Google 目前将自定义应用限制为**年满 18 岁的美国用户**、使用**个人 Google 帐户**登录并**开启 Keep Activity**。该功能以**英语**提供。连接必须在 Gemini Web 应用程序上创建，尽管连接的应用程序稍后可以在移动设备上使用。可用性和 UI 标签可能会发生变化；请参阅 [Gemini 自定义应用官方说明](https://support.google.com/gemini/answer/17209137)。

## 连接前

- 启动 LSM 运行时（例如使用 [Docker Compose](../installation/docker.md)），并验证其运行状况。
- 通过**可公开访问的 HTTPS** 公开其 MCP 端点并保持 OAuth 启用。
- 准备好 Controller 的 OAuth 登录方式并仅批准您需要的范围。
- 使用受限的工作空间或容器。Gemini可能会请求对文件、机器和终端产生实际影响的操作。

在 Gemini 中输入的端点地址为：

```text
https://your-public-host.example.com/mcp
```

请勿输入 Web UI (`/ui`)、LibreChat URL 或不带 `/mcp` 的站点地址。公共部署不应禁用身份验证来解决连接错误。

## 连接Gemini

1. 在计算机上，打开 [Gemini](https://gemini.google.com/) 并使用符合要求的个人 Google 账号登录。
2. 打开 **设置和帮助 → 连接的应用程序**。根据当前界面，它可能位于**个人智能 → 连接的应用程序**下。
3. 在 **自定义应用** 下，选择 **添加自定义应用** 或使用自定义应用 URL 字段。
4. 粘贴 LSM HTTPS `/mcp` URL，然后选择 **下一步**。
5. 使用 LSM 控制器完成 OAuth 和同意流程。 LSM 支持 OAuth 发现和动态客户端注册。如果 Gemini 请求手动 OAuth 客户端凭据，请在继续之前检查其高级选项和 LSM OAuth 设置。
6. 在 Gemini 对话中，输入 `@` 并选择连接的自定义应用以请求 LSM 工具。

首先：“使用连接的 LSM 应用程序检查环境并列出工作区文件。请勿修改任何内容。”在尝试写入操作之前检查工具结果和Controller 审计日志。

## 限制和故障排除

- **无自定义应用选项：** 确认帐户、地区、年龄、语言与 Keep Activity 的使用条件。这是 Gemini 端的可用性限制，而不是 LSM 配置错误。
- **URL 被拒绝：** 使用外部可访问的 HTTPS `/mcp` 端点；检查 OAuth 发现和您的反向代理。
- **OAuth 失败：** 检查 LSM 授权屏幕、客户端注册、回调 URL 和授予的范围。请勿发布未经身份验证的 MCP 端点。
- **工具缺失或调用失败：** 客户端 MCP 工具/架构支持可能有所不同。尝试一个简单的只读调用并检查 LSM 审计日志；不保证与每个 Gemini 客户端功能完全兼容。
- **断开连接：**当不再需要时，返回**连接的应用程序**以禁用、取消链接或删除 LSM。

Google 的 [official guide](https://support.google.com/gemini/answer/17209137) 描述了最新的自定义应用流程和可用性。对于基于 CLI 的本地 Gemini 集成，请参阅 [Gemini CLI's MCP documentation](https://geminicli.com/docs/tools/mcp-server/)。 LSM [ChatGPT connector tutorial](chatgpt-connector.md) 仍然独立可用。
