# Docker Compose 运行时

Docker Compose 是大多数用户的推荐运行时。它为模型提供受控 Linux 工作区、可重复工具链、持久凭据、浏览器自动化支持，以及简单的升级路径。

这是运行时选择。它可以接入 ChatGPT、通用 HTTP MCP 客户端，也可以只在本地测试。

## Docker 镜像包含什么

镜像基于 Playwright Python 镜像，并安装较完整的开发工具链。目标是让 AI 编程代理能够处理许多仓库，而不必为每个项目重新构建运行时。

包含的类别：

| 类别 | 示例 |
|---|---|
| Shell 与检查 | Bash、curl、wget、jq、ripgrep、tree、tmux、patch、file |
| Git 与凭据 | Git、GitHub CLI、OpenSSH client、凭据持久化卷 |
| C/C++ 构建 | build-essential、clang、cmake、ninja、autoconf、automake、gdb、lldb |
| Python | Python、pip、venv、pipx、包开发依赖 |
| JavaScript/TypeScript | Node.js、npm、yarn、pnpm、TypeScript、ts-node |
| 其它语言 | Go、Rust、Java、Ruby、PHP、Perl、Lua、R |
| 浏览器自动化 | Playwright 浏览器和浏览器依赖 |
| 文档工具 | LibreOffice、Pandoc、Poppler 工具、OCR 工具 |

镜像内容应视为便利层，而不是稳定 API。项目特定依赖仍应放在工作区或项目构建脚本中。

## 基础本地运行

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
mkdir -p workspaces/default
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

默认 Compose 文件把服务绑定到 localhost：

```text
127.0.0.1:8765 -> container:8765
```

这适合本地测试，也适合同一主机上的反向代理。

## 工作区布局

默认 Compose 运行时挂载：

| 宿主机路径或卷 | 容器路径 | 用途 |
|---|---|---|
| `./workspaces/default` | `/workspace` | 工具可见的受控工作区 |
| `local-shell-mcp-credentials` volume | `/persist/credentials` | 持久 Git / GitHub / SSH / GPG 风格凭据状态 |

每个信任边界使用一个工作区目录。不要只为图方便就把整个 home 目录作为工作区。

## 公开访问所需设置

对于 ChatGPT 或其它公开 HTTP MCP 客户端，在 `.env` 中配置：

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

可以用下面的命令生成 JWT secret：

```bash
openssl rand -hex 32
```

公开 MCP URL 是：

```text
https://your-public-host.example.com/mcp
```

## Cloudflare Tunnel sidecar

Compose 文件包含一个可选的 `cloudflared` 服务，放在 `tunnel` profile 后面。它会把隧道与 MCP 服务放在同一套 Compose 中运行。

配置 `.env`：

```env
CLOUDFLARE_TUNNEL_TOKEN=<token from Cloudflare Tunnel>
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=<strong pin>
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=<strong random secret>
```

启动两个服务：

```bash
docker compose --profile tunnel up -d
```

在 Cloudflare Zero Trust 中，把公开 hostname 路由到：

```text
http://local-shell-mcp:8765
```

这是 Cloudflare Tunnel，不是 Cloudflare Access。`local-shell-mcp` 仍然自己处理 ChatGPT 的 OAuth。

## 不使用 tunnel sidecar 的反向代理

如果你已经运行 Caddy、Nginx、Traefik 或 Nginx Proxy Manager，保留普通 Compose 服务，并把 HTTPS 转发到：

```text
http://127.0.0.1:8765
```

代理必须原样转发这些路径，不能剥离路径前缀：

| 路由 | 用途 |
|---|---|
| `/mcp` | MCP streamable HTTP 端点 |
| `/healthz`, `/readyz` | 健康检查 |
| `/.well-known/oauth-protected-resource` | OAuth resource 元数据 |
| `/.well-known/oauth-authorization-server` | OAuth authorization-server 元数据 |
| `/oauth/register` | 动态客户端注册 |
| `/oauth/authorize` | 浏览器授权页面 |
| `/oauth/token` | token 交换 |
| `/downloads/<token>` | 可选的生成文件下载 |
| `/join/<token>`, `/remote/*` | 可选的远程 worker 引导和轮询 |

代理行为要求见 [网络连通性](../clients/connectivity.md)。

## Full-container 模式

`LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=false` 会把文件系统操作限制在工作区内。这是更安全的默认行为。

只有当容器是有意设计为一次性环境，且模型需要操作整个容器文件系统时，才设置为 `true`。启用后，内置命令和路径 denylist 限制会被移除。

```env
LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true
```

不要在 VS Code 扩展或直接运行在笔记本上的二进制这类宿主机运行时中启用 full-container 模式。

## 凭据

Docker 运行时可以在专用 volume 中持久化常见开发者凭据。这对 GitHub CLI 登录、Git HTTPS credential helper、`.netrc`、SSH 配置和 GPG 状态很有用。

把凭据 volume 视为敏感资源。优先使用仓库级 deploy key、细粒度 token 或短期凭据。不要把权限过大的个人凭据放进模型可自由读取的工作区。

也可以通过挂载 SSH agent socket 来转发 SSH agent，但这会把容器信任扩展到当前活动 agent。只在理解暴露面时使用。

## 更新

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

使用 tunnel sidecar 时：

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
curl -i http://127.0.0.1:8765/healthz
```

升级后，先让客户端执行只读检查：

```text
使用 local-shell-mcp。调用 environment_info，并对工作区根目录调用 list_files。不要修改文件。
```

## 故障排查

| 现象 | 检查 |
|---|---|
| 本地 `/healthz` 失败 | `docker compose ps`、`docker compose logs --tail=200 local-shell-mcp` |
| ChatGPT 无法发现工具 | 公开 URL 必须以 `/mcp` 结尾；`LOCAL_SHELL_MCP_PUBLIC_BASE_URL` 不能包含 `/mcp` |
| OAuth 页面失败 | 公开 OAuth 部署必须设置 admin PIN 和 JWT secret |
| 工具看不到文件 | 确认目标宿主机目录已挂载到 `/workspace` |
| 浏览器工具失败 | 确认 Playwright 镜像是最新的；可对目标浏览器尝试 `run_shell_tool` |
| Git 认证消失 | 检查凭据 volume，以及重建容器时是否使用了同一个 volume |
