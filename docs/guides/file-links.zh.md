# 文件链接

`local-shell-mcp` 可以通过高熵 bearer URL 暴露受控工作区中的文件。当 AI 生成报告、压缩包、PDF、截图或其它需要从聊天中下载的产物时，这很有用。

## 何时使用文件链接

文件链接适合：

- 生成的 PDF 或报告。
- 截图和浏览器产物。
- 构建输出。
- 过大而不适合粘贴的日志。
- 准备用于人工检查的压缩包。

不要把文件链接用于密钥、私钥、凭据存储或无关个人数据。

## 典型流程

1. 在 `/workspace` 下生成或定位文件。
2. 调用 `create_file_link`，设置 TTL 和可选下载次数限制。
3. 分享返回的 URL。
4. 不再需要时撤销链接。

## 相关工具

| 工具 | 用途 |
|---|---|
| `create_file_link` | 为工作区文件创建带 token 的 URL。 |
| `list_file_links` | 显示活动链接。 |
| `revoke_file_link` | 在到期前禁用链接。 |

## 控制项

相关配置包括：

- `LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED`
- `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_TTL_S`
- `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_TTL_S`
- `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_MAX_DOWNLOADS`
- `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_FILE_BYTES`

对敏感产物使用较短 TTL；当链接只面向单个接收者时，设置最大下载次数。

## 安全说明

文件链接是 bearer URL。任何拿到 URL 的人都可以在链接过期、达到下载次数限制或被撤销前下载文件。应把它们视为临时密钥。
