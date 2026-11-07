<!-- i18n-source-sha256: 3575b9b50708261678473f74b66076f0c14807ccd7f7c3e60b4d1e897ac778df -->
# 快速开始

本指南启动 LSM 控制器并打开其浏览器界面。 [unified web workspace](web-workspace.md)为推荐日常体验；它是一个单独部署的、可选的聊天堆栈。 ChatGPT、Gemini 和其他外部 MCP 客户端可以连接到同一控制器。请参阅 [runtime choices and deployment model](../guides/deployment.md)。

最推荐的 Controller 部署方式是**直接从源码仓库运行**，并使用独立、受限的运行环境。Docker Compose 是可选的替代方案。

## 要求

- Git、Python 3.11+，以及可用的 `venv` / `pip`。
- 仅当远程用户或外部 MCP 客户端需要连接时，才需要公网 HTTPS 地址。
- 独立且权限范围明确的工作区目录。
- 强随机 OAuth 管理 PIN 和 JWT 密钥。

!!! warning
    接入的模型可以操作配置的工作区。建议在一次性容器或虚拟机中运行服务，并避免挂载宿主机控制资源。

## 1. 克隆并配置

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
cp .env.example .env
chmod 600 .env
openssl rand -hex 32
```

编辑 `.env`，替换示例 PIN 和 JWT 密钥（可使用 `openssl rand -hex 32` 的输出）。源码运行时**不会自动加载** `.env`。

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. 启动服务

```bash
mkdir -p workspaces/default
set -a
. ./.env
set +a
. .venv/bin/activate
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspaces/default"
local-shell-mcp --mode mcp
```

另开一个终端检查状态：

```bash
curl -i http://127.0.0.1:8765/healthz
```

正常响应为 HTTP `200`。前一个终端应保持运行；长期部署请交给服务管理器。

## 3. 暴露 HTTPS

远程访问推荐直接部署在公网服务器上，或使用 Caddy、Nginx、Traefik 等 HTTPS 反向代理/端口转发，将完整站点（包括上传和下载）转发到：

```text
http://127.0.0.1:8765
```

配置 HTTPS 后检查：

```bash
curl -i https://your-public-host.example.com/healthz
```

**不推荐 Cloudflare Tunnel** 用于需要传输文件的部署：其客户端上传较慢，可能影响文件传输。条件允许时优先采用公网服务器直连或常规反向代理/转发。公网端点必须保留 OAuth。Docker 方案见 [Docker 运行时指南](../installation/docker.md)。

## 4.打开浏览器工作区

打开控制器登录：

```text
https://your-public-host.example.com/ui
```

对于聊天、项目和集成控制页面，请关注 [unified web workspace guide](web-workspace.md)。原始轻量级WebUI在未安装聊天时可用。

## 5. 安全确认工具访问

先让模型执行：

```text
Use local-shell-mcp. First call environment_get, then list the workspace root. Do not modify files yet.
```

预期只读工具包括：

- `environment_get`
- `file_list`
- `file_tree`
- `file_read`

## 6. 从有边界的任务开始

适合作为第一次任务的提示：

```text
Inspect this repository, summarize the project layout, run the existing test suite if one is obvious, and do not change files.
```

确认连接正常后，再给出更具体的修改任务：

```text
Fix the failing test. Read the relevant files first, make the smallest patch, run the targeted test, then show git diff. Do not commit until I approve.
```

## 更新

更新源码、重新安装可编辑包，然后重启 Controller 进程或服务：

```bash
git pull --ff-only
python -m pip install -e .
# Restart the Controller process or service after updating.
curl -i http://127.0.0.1:8765/healthz
```

如果选择 Docker Compose，请改为更新容器：

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

## 下一步

| 需求 | 页面 |
|---|---|
| 理解运行时与客户端关系 | [运行时与客户端模型](../guides/deployment.md) |
| 使用 Docker Compose 运行 | [Docker Compose 运行时](../installation/docker.md) |
| 从 VS Code 启动运行时 | [VS Code 扩展运行时](../installation/vscode-extension.md) |
| 使用独立二进制运行 | [独立二进制运行时](../installation/binary.md) |
| 使用 Python、pipx 或源码运行 | [Python 运行时](../installation/python.md) |
| 使用统一的聊天和控制界面 | [统一 Web 工作区](web-workspace.md) |
| 添加 Gemini Spark 作为客户端 | [Gemini 自定义应用](gemini-spark.md) |
| 添加 ChatGPT 客户端 | [ChatGPT 连接器](chatgpt-connector.md) |
| 选择工具并写更好的提示词 | [使用模式](../guides/usage-patterns.md) |
| 连接 HPC、NPU/GPU 或 NAT 机器 | [远程节点](../guides/remote-workers.md) |
| 理解每一个 MCP 工具 | [工具参考](../reference/tools.md) |
