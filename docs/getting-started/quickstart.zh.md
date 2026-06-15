# 快速开始

本页把 Docker Compose 作为第一个运行时，把 ChatGPT 作为第一个客户端。两者是独立选择：Docker、VS Code 扩展、二进制、Python 和 stdio 是运行时；ChatGPT 和通用 MCP 客户端是接入方式。完整关系见 [运行时与客户端模型](../guides/deployment.md)。

## 要求

- Docker Engine 与 Compose v2。
- 如果 ChatGPT 需要从公网访问，需要一个公开 HTTPS 端点。
- 一个专用工作区目录。
- 较长的随机 OAuth 管理 PIN 和 JWT 密钥。

!!! warning
    接入的模型可以操作配置的工作区。建议在一次性容器或虚拟机中运行服务，并避免挂载宿主机控制资源。

## 1. 克隆并配置

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
```

编辑 `.env`：

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
CLOUDFLARE_TUNNEL_TOKEN=
```

## 2. 启动服务

```bash
mkdir -p workspaces/default
docker compose up -d
```

检查状态：

```bash
docker compose ps
docker compose logs --tail=100 local-shell-mcp
curl -i http://127.0.0.1:8765/healthz
```

健康响应会返回 HTTP `200`。

## 3. 暴露 HTTPS

如果使用 Cloudflare Tunnel sidecar：

```bash
docker compose --profile tunnel up -d
```

在 Cloudflare Zero Trust 中，把公开 hostname 指向：

```text
http://local-shell-mcp:8765
```

如果使用 Caddy、Nginx、Traefik、Nginx Proxy Manager 或其它反向代理，把 HTTPS 流量转发到 `127.0.0.1:8765` 或容器网络地址。

## 4. 连接 ChatGPT

MCP 端点为：

```text
https://your-public-host.example.com/mcp
```

按照 [ChatGPT 连接器](chatgpt-connector.md) 完成 OAuth 和工具授权。

## 5. 安全确认工具访问

先让模型执行：

```text
Use local-shell-mcp. First call environment_info, then list the workspace root. Do not modify files yet.
```

预期只读工具包括：

- `environment_info`
- `list_files`
- `tree_view`
- `read_file`

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

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

如果使用 tunnel profile：

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
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
| 添加 ChatGPT 客户端 | [ChatGPT 连接器](chatgpt-connector.md) |
| 选择工具并写更好的提示词 | [使用模式](../guides/usage-patterns.md) |
| 连接 HPC、NPU/GPU 或 NAT 机器 | [远程节点](../guides/remote-workers.md) |
| 理解每一个 MCP 工具 | [工具参考](../reference/tools.md) |
