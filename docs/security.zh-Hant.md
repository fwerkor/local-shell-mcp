# 安全說明

公開部署使用 OAuth。保持 `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` 和 `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` 足夠強，並避免泄露。

默認情況下，路徑操作限制在工作區內，敏感路徑片段會被攔截。Full-container 模式會關閉內置工作區和路徑限制，應只用於一次性容器或 VM。

生成的文件下載鏈接是公開 bearer URL。它們依賴高熵 token、TTL、可選下載次數限制、可選大小限制和撤銷機制。
