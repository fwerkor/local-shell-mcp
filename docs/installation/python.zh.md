# Python、pipx 与源码运行时

Python 运行时适合开发、调试，以及 Python 包管理比 Docker 更容易维护的环境。它运行的服务与 Docker 和二进制运行时相同。

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

用于项目开发：

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e '.[dev,docs]'
LOCAL_SHELL_MCP_WORKSPACE_ROOT=/tmp/local-shell-mcp-workspace local-shell-mcp --mode mcp
```

运行检查：

```bash
ruff check .
pytest -q
mkdocs build --strict
```

## 浏览器设置

Python 包依赖 Playwright，但宿主机上可能仍需要安装浏览器二进制：

```bash
python -m playwright install chromium
```

部分 Linux 宿主机还需要额外浏览器系统依赖。Docker 大多能避免这些问题，因为镜像基于 Playwright base image。

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
