<!-- i18n-source-sha256: e75cf6e4ffc3fe904983cd63b99b43c2877c4bdd99174b2d4a96393eff5d9e3f -->
# 统一 Web 工作区

**统一的 LSM Web 工作区**是日常使用 local-shell-mcp 的推荐入口。它将 AI 聊天、项目历史记录和 LSM 控制面结合在一个响应式界面中，基于经过定制并内置的 LibreChat 前端。您仍然可以连接外部 MCP 客户端，例如 [ChatGPT](chatgpt-connector.md) 或 [Gemini](gemini-spark.md)。

该工作区是**自托管且可选安装**：它是一个单独的 Web 服务，不是轻量 Controller 镜像、独立可执行文件或远程 Worker 安装包的一部分。仅部署 Controller 时保留原始浏览器 UI 和 OpenTUI。

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

1. [安装并启动 LSM Controller](quickstart.md) 与 OAuth、适当隔离的工作区和持久 `file` 或 `redis` 状态存储。安装 Docker Compose 并将存储库克隆到运行 Web 堆栈的主机。
2. 在同一站点上提供**两个 HTTPS 源**，例如用于控制器的 `https://lsm.example.org` 和用于工作区的 `https://chat.example.org`。聊天服务不会直接暴露在不受信任的网络上。
3. 使用 `openssl rand -hex 32` 生成一个桥接秘密。使用该密钥在 **控制器服务** 上配置这些环境变量，然后重新启动它：

```env
LOCAL_SHELL_MCP_LIBRECHAT_URL=https://chat.example.org
LOCAL_SHELL_MCP_LIBRECHAT_BRIDGE_SECRET=paste-the-same-64-hex-character-secret-on-both-services
```

4. 在仓库目录中，配置可选的 Web 堆栈。使用私有环境文件，或导出如下所示的值；生成不同的高强度密钥，并且不要提交它们：

```sh
export LSM_PUBLIC_ORIGIN=https://lsm.example.org
export LIBRECHAT_PUBLIC_URL=https://chat.example.org
export LSM_LIBRECHAT_BRIDGE_SECRET="paste-the-secret-from-controller-config"
export JWT_SECRET="$(openssl rand -hex 32)"
export JWT_REFRESH_SECRET="$(openssl rand -hex 32)"
export CREDS_KEY="$(openssl rand -hex 32)"
export CREDS_IV="$(openssl rand -hex 16)"
export MEILI_MASTER_KEY="$(openssl rand -hex 32)"
export LSM_DOCKER_NETWORK=local-shell-mcp_default
```

5. 生成包含私密配置的运行时文件，然后构建并启动独立的聊天服务栈：

```sh
python3 integrations/librechat/render_config.py
docker compose -f integrations/librechat/compose.yaml build chat
docker compose -f integrations/librechat/compose.yaml up -d
```

当使用根 Docker Compose 部署时，上面的 Controller 变量属于根 `.env` 并转发到容器。聊天服务值可以通过 shell 导出或私有环境文件提供。控制器容器必须可从指定 Docker 网络上位于 `http://local-shell-mcp:8765` 的聊天容器访问。将 `127.0.0.1:3080` 反向代理端口到聊天 HTTPS 源，保留外部主机，并遵循存储库中的 [部署与安全说明](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md)。 Web 堆栈运行 Node.js、MongoDB、Meilisearch 和 SearXNG；这些组件**不会**进入 Worker 安装包。这个单独的部署不是由存储库根目录中的普通 `docker compose up -d` 启动的。

## 登录并使用聊天功能

1. 打开 `https://lsm.example.org/ui`，使用 **LSM Controller** 登录进行身份验证，然后按照一次性切换进入 Web 工作区。您无需创建第二个 LibreChat 用户帐户。
2. 配置模型提供者。可选的 Web 堆栈默认将 OpenAI、Anthropic 和 Google 凭证公开为 `user_provided`：在聊天端点设置中输入您自己的提供商密钥，或在开始之前在聊天 Compose 环境中设置 `OPENAI_API_KEY`、`ANTHROPIC_API_KEY` 或 `GOOGLE_KEY`。在聊天中选择支持的型号。 **LSM 不包括模型或 API 积分。** Gemini Spark 的外部 MCP 连接与此处配置 Gemini 模型是分开的。
3. 创建对话。默认情况下启用 Web 搜索和 LSM 工具，但需遵守控制器权限。根据需要使用每个对话 **Web**、**LSM**、**外部 MCP** 和 **内存** 控件。
4. 从只读请求开始：“检查控制器状态并列出工作空间根目录。请勿修改文件。”
5. 导航到**文件**、**终端**、**桌面**、**会话**、**远程**或**审计**以进行直接检查和控制。

聊天上传（最多 32 MiB）存储在控制器工作区下，并且它们的绝对路径提供给模型。浏览器上传不会授予额外的文件权限。面向模型的工具调用通过 LSM 授权、审计和远程 Worker 路由器。

## 外部 MCP、安全和数据

使用工作区 MCP 侧边栏管理嵌套的外部 MCP 服务器。这支持本地 stdio 服务器和 HTTP 服务器，包括单独的私有环境变量和请求标头。秘密不会返回到浏览器。 **外部 MCP** 聊天切换允许搜索、检查和调用嵌套工具；当禁用本机 LSM 工具时，它不会授予模型 `mcp_manage`。 UI 管理受到正常控制器授权的保护。

聊天消息、项目和档案存储在服务器端 Web 堆栈的 MongoDB 中；搜索使用 Meilisearch。 Controller分别拥有工具权限、Worker身份、会话状态和审计。如果需要保留所有历史记录，请备份两个数据存储。聊天后台是LSM登录下的单用户；不要向公众公开其内部 API 或数据库。

UI 是独立的顶层应用，**不是 iframe**。如果未配置可选聊天服务，`/ui` 将继续为原始 LSM WebUI 提供服务。原生 OpenTUI 和外部客户端仍然受支持。

## 故障排除

- **重定向保留在原始 UI 上：** 检查 `LOCAL_SHELL_MCP_LIBRECHAT_URL`、持久控制器状态后端和 Web 堆栈的 HTTPS 反向代理。
- **登录或切换失败：**验证双方完全相同的 32 字节或更长的桥接密钥，匹配相同站点的来源、HTTPS 和服务器时钟。
- **聊天加载但无法应答：**设置实际模型端点或 API 凭证并检查聊天容器日志。
- **缺少 MCP 工具：** 验证控制器范围和每个对话切换；嵌套服务器注册表与 LibreChat MCP 数据库是分开的。
- **文件或会话显示为空：**验证聊天是否到达正确的控制器和工作区，并检查其 API 身份验证日志。

有关实现详细信息和更新，请参阅 [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md) 和 [human interface guide](../guides/human-interface.md)。
