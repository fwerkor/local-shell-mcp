# 安全说明

公开部署使用 OAuth。保持 `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` 和 `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` 足够强，并避免泄露。

默认情况下，路径操作限制在工作区内，敏感路径片段会被拦截。Full-container 模式会关闭内置工作区和路径限制，应只用于一次性容器或 VM。

生成的文件下载链接是公开 bearer URL。它们依赖高熵 token、TTL、可选下载次数限制、可选大小限制和撤销机制。
