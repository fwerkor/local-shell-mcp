<!-- i18n-source-sha256: 1d80cfbe14747fb0691e91065f582d1e47eb36921d8b27da1648dcd26114a2e5 -->
# Python、pipx 与源码运行时

日常部署优先使用 [单文件二进制](binary.md)。Python、pipx 和源码安装用于开发、调试、定制等场景。

本页覆盖三个相关场景：

- `pipx install local-shell-mcp`：用户级可执行文件安装。
- `pip install local-shell-mcp`：安装到已有虚拟环境。
- 可编辑源码 checkout：开发或调试项目本身。

## pipx 安装

对普通用户而言，`pipx` 是最干净的 Python 安装方式：它会为命令创建独立虚拟环境，同时把可执行文件暴露到 `PATH`。

```bash
pipx install local-shell-mcp
local-shell-mcp --help
```

启动本地 HTTP MCP 服务：

```bash
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
local-shell-mcp --mode mcp
```

检查健康状态：

```bash
curl -i http://127.0.0.1:8765/healthz
```

## 虚拟环境安装

当你已经手动管理 Python 环境时，使用这种方式：

```bash
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install local-shell-mcp
local-shell-mcp --mode mcp
```

该进程使用宿主机上已安装的工具。Python 包不会替你安装编译器、Git、浏览器系统依赖或项目依赖。

## 可编辑源码 checkout

源码方式主要用于开发和定制；普通部署应使用 [单文件二进制](binary.md)。公网认证与 HTTPS 配置见 [快速开始](../getting-started/quickstart.md)。

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e .
cp .env.example .env
# Replace the example OAuth secrets in .env before starting.
set -a
. ./.env
set +a
mkdir -p workspaces/default
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspaces/default"
local-shell-mcp --mode mcp
```

运行检查：

```bash
python -m pip install -e '.[dev,docs]'
ruff check .
pytest -q
mkdocs build --strict
```

## 浏览器设置

Playwright 是可选依赖，只有需要浏览器自动化时才需安装对应 Python 包和浏览器。

```bash
python -m pip install -e '.[browser]'
python -m playwright install chromium
```

浏览器支持是可选功能；基础 Docker 镜像不包含 Playwright 或浏览器。

## 公开 HTTP MCP 使用

对于 ChatGPT 或其它公开 HTTP MCP 客户端，配置与其它 HTTP 运行时相同的公开 origin 和 OAuth 设置，然后通过反向代理或隧道暴露本地端口。

公开 MCP 端点是：

```text
https://your-public-host.example.com/mcp
```

## 开发模式

| 模式 | 命令 | 用途 |
|---|---|---|
| MCP HTTP | `local-shell-mcp --mode mcp` | 通过 HTTP 使用完整 MCP 客户端，包括位于 HTTPS 之后的 ChatGPT |
| REST 风格 HTTP | `local-shell-mcp --mode http` | 诊断或兼容端点，不是 ChatGPT 主要路径 |
| stdio | `local-shell-mcp --mode stdio` | 由本地 MCP 客户端启动进程 |

`mode=both` 是保留值，目前不应作为单进程模式使用。

## 宿主机运行时安全

除非放在 VM 或容器中，Python 安装会以你的宿主机用户身份运行。保持工作区范围较窄，关闭 full-container 模式，不要把工作区指向 home 目录。

对于不可信仓库、依赖包安装较多的任务，或更重视可重置性的工作流，使用 Docker Compose。
