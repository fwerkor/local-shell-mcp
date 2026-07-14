# 独立二进制运行时

Release 二进制可以在没有 Docker、也没有 Python 环境的情况下运行 `local-shell-mcp`。当 Docker 不可用，或你已经有专用 VM、容器宿主机、实验室服务器、受限用户账号作为边界时，可以使用这个运行时。

这是运行时选择。ChatGPT 访问需要另外通过 HTTPS `/mcp` 端点配置。

## Release 产物

GitHub Releases 会为常见平台构建自包含可执行文件：

| 平台产物 | 压缩包 |
|---|---|
| `local-shell-mcp-linux-x86_64` | `.tar.gz` |
| `local-shell-mcp-linux-aarch64` | `.tar.gz` |
| `local-shell-mcp-macos-x86_64` | `.tar.gz` |
| `local-shell-mcp-macos-aarch64` | `.tar.gz` |
| `local-shell-mcp-windows-x86_64` | `.zip` |

每个压缩包包含可执行文件、README、license 和简短 quickstart 文件。

## 安装

1. 从 GitHub Releases 下载适合你平台的压缩包。
2. 解压。
3. 把可执行文件放到 `PATH` 中，或记录其绝对路径。
4. 运行 `local-shell-mcp --help`，确认二进制能启动。

Linux 和 macOS 通常需要设置可执行位：

```bash
chmod +x local-shell-mcp
./local-shell-mcp --help
```

Windows 用户应在 PowerShell 中运行 `local-shell-mcp.exe`，或把所在目录加入 `PATH`。

## 最小本地运行

```bash
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
local-shell-mcp --mode mcp
```

另开一个终端检查：

```bash
curl -i http://127.0.0.1:8765/healthz
```

## 公开 HTTP MCP 运行

对于 ChatGPT 或公开 HTTP MCP 客户端，需要配置这些类别：

| 设置 | 用途 |
|---|---|
| `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | 工具控制的目录 |
| `LOCAL_SHELL_MCP_HOST` 和 `LOCAL_SHELL_MCP_PORT` | 本地绑定地址和端口 |
| `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | 公开 HTTPS origin，不含 `/mcp` |
| `LOCAL_SHELL_MCP_AUTH_MODE` | 公开部署使用 `oauth` |
| OAuth PIN 和 JWT secret 设置 | 公开 OAuth 授权所需 |

通过反向代理或隧道暴露本地 HTTP 端口。公开端点是：

```text
https://your-public-host.example.com/mcp
```

## YAML 配置

YAML 配置可以保存非敏感运行时默认值：

```yaml
host: 127.0.0.1
port: 8765
mode: mcp
workspace_root: /srv/local-shell-mcp/workspace
auth_mode: oauth
public_base_url: https://your-public-host.example.com
```

运行：

```bash
local-shell-mcp --config /path/to/config.yaml
```

带有 `LOCAL_SHELL_MCP_` 前缀的环境变量会覆盖 YAML 值。

## 宿主机工具链责任

二进制打包的是 Python 应用本身，不包含所有开发者工具。MCP 工具会调用宿主机上可用的程序。

按任务需要安装工具：

| 能力 | 可考虑的宿主机包 |
|---|---|
| 搜索与 shell 易用性 | `ripgrep`、`tree`、`jq`、`curl`、`wget`；Linux 发行包已内置静态 tmux helper |
| Git 工作流 | `git`、`gh`、OpenSSH client、credential helper |
| Python 项目 | Python、pip、venv、项目特定编译器和头文件 |
| Node 项目 | Node.js、npm、pnpm、yarn |
| Rust / Go / Java / C++ | Cargo / rustc、Go、JDK、Maven / Gradle、编译器、CMake、Ninja |
| 浏览器自动化 | Playwright 浏览器二进制和系统依赖 |
| 文档转换 | LibreOffice、Pandoc、Poppler 工具 |

如果你不想维护这套宿主机工具链，使用 Docker Compose。

## 长时间服务

持久公开部署时，把二进制交给操作系统进程管理器运行。保持这些做法：

- 使用专用低权限 OS 账号。
- 使用专用工作区目录。
- 把敏感值保存在非公开可读文件之外。
- 失败后自动重启。
- 每次重启后检查 `/healthz`。
- 保留日志以便排查。

## 更新

1. 下载新版本对应平台的 release 压缩包。
2. 如有需要，校验 checksum。
3. 替换可执行文件。
4. 重启进程管理器。
5. 检查 `/healthz`。
6. 让客户端先运行 `environment_info`，再继续工作。

## 安全说明

二进制会以其操作系统用户的权限运行。公开部署时，尽量使用专用低权限用户、专用工作区，以及 VM 或容器边界。

不要让直接运行在个人宿主机上的二进制设置 `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true`。该设置面向一次性容器或 VM。
