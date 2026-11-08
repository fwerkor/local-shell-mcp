<!-- i18n-source-sha256: 521e0f39c8823597b1468b2d63af978794cb28fda8c8e60230da0a96cff2d5c2 -->
# 统一 Web 工作区

**统一的 LSM Web 工作区**是日常使用 local-shell-mcp 的推荐入口。它将 AI 聊天、项目历史记录和 LSM 控制面结合在一个响应式界面中，基于经过定制并内置的 LibreChat 前端。您仍然可以连接外部 MCP 客户端，例如 [ChatGPT](chatgpt-connector.md) 或 [Gemini](gemini-spark.md)。

现在 Web 工作区集成在 LSM Controller 中，不再另行部署 LibreChat 服务。全部业务数据统一存储于 Python/SQLite 后端。

## 工作区里有什么？

| 模块 | 你能做什么 |
|---|---|
| 聊天和项目 | 选择配置的模型、创建对话、组织项目、查找过去的聊天记录并存档对话。历史记录保留在服务器上。 |
| Controller 总览 | 查看运行状况、最近的活动和连接的机器。 |
| 文件 | 浏览和管理本地或远程文件。 |
| 终端 | 使用Controller 或 Worker上的持久终端。 |
| 桌面 | 检查和控制远程 GUI 会话。 |
| 会议 | 检查持久的 LSM 任务及其生命周期。 |
| 遥控器 | 连接和管理外派员工。 |
| 审计 | 检查模型发起的工具活动。 |
| 嵌套MCP | 注册、编辑、启用、禁用、刷新和删除 LSM 后面的外部 MCP 服务器。 |

Controller 页面路由包括 `/control/overview`、`/control/files`、`/control/terminals`、`/control/desktop`、`/control/sessions`、`/control/remotes` 和 `/control/audit`。聊天页面地址为 `/c/new`。 LSM MCP 管理器控制 **LSM 的嵌套 MCP 注册表**；它不会在 LibreChat 中创建第二个注册表。

## 部署可选的聊天服务

1. 通过[快速入门](quickstart.md)安装 LSM Controller，默认启用 SQLite；原始状态会自动迁移，旧文件保留作为回滚来源。
2. 用户只需一个 HTTP/HTTPS 入口：`https://lsm.example.org`。聊天、终端、文件及远程控制都由同一个 Python Controller 提供。
3. 如需修改默认配置，可以在 Controller 服务环境中设置：

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

4. 使用源码部署或独立可执行文件启动 Controller：

```sh
local-shell-mcp --mode mcp
```

5. React 前端源码位于 `ui/workspace/`。仅在开发与打包时需要 Bun；参见[前端构建与安全说明](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md)。

Node.js、MongoDB、Meilisearch 和独立的 LibreChat Compose 服务都不再是运行时依赖。Worker 仍然是普通 Python 包。

**重构状态：** Python Agent 推理、SSE 恢复及工具协议仍在迁移，草稿 PR 暂不可替换生产部署。

## 登录并使用聊天功能

1. 打开 LSM Controller 的 `/ui` 入口，用原有 PIN 或 OAuth 完成认证；React 与控制面共享身份。
2. 在 LSM 中配置实际模型端点/API 凭证。Python Agent 后端仍在迁移中，草稿分支尚未完全支持生成。
3. 待 Python Agent 与 SSE 协议通过验收测试后即可正常新建对话；MCP、LSM 工具与文件上传继续沿用 Controller 权限。
4. 先进行只读请求：“检查 Controller 状态并列出工作区根目录，不修改文件。”
5. 通过文件、终端、桌面、会话、远程和审计页面直接查看与管理运行环境。

聊天上传（最多 32 MiB）存储在控制器工作区下，并且它们的绝对路径提供给模型。浏览器上传不会授予额外的文件权限。面向模型的工具调用通过 LSM 授权、审计和远程 Worker 路由器。

## 外部 MCP、安全和数据

使用工作区 MCP 侧边栏管理嵌套的外部 MCP 服务器。这支持本地 stdio 服务器和 HTTP 服务器，包括单独的私有环境变量和请求标头。秘密不会返回到浏览器。 **外部 MCP** 聊天切换允许搜索、检查和调用嵌套工具；当禁用本机 LSM 工具时，它不会授予模型 `mcp_manage`。 UI 管理受到正常控制器授权的保护。

聊天、项目、Agent、会话、审计及 Worker 状态统一使用 `.local-shell-mcp/lsm.sqlite3`，并使用 SQLite FTS5 搜索；文件产物仍在同目录下管理。

工作区是原生 React 页面，不使用 iframe 或独立 Web 服务；Worker 与外部 MCP 客户端保持兼容。

## 故障排除

- **WebUI 无法启动：** 查看 Python Controller 日志、SQLite 初始化和打包前端；紧急情况下可通过 `LOCAL_SHELL_MCP_STATE_BACKEND=file` 恢复文件存储。
- **登录失败：** 使用现有 Controller PIN/OAuth 认证，不再需要 LibreChat 独立账户或桥接密钥。
- **聊天界面可打开但无法应答：** 草稿分支的 Python Agent 与 SSE 迁移尚未完成，请勿部署到生产。
- **MCP 工具缺失：** 核对 Controller 权限与嵌套 MCP 注册表；仅外部 MCP 模式不暴露 `mcp_manage`。
- **文件或会话为空：** 检查 Controller 工作区、SQLite 数据迁移及认证身份。

有关实现详细信息和更新，请参阅 [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md) 和 [human interface guide](../guides/human-interface.md)。
