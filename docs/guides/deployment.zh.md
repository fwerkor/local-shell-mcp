# 运行时选择与部署模型

`local-shell-mcp` 有两个相互独立的选择：

1. **运行时**：服务进程如何运行，以及它控制哪个工作区。
2. **客户端连接**：ChatGPT 或其它 MCP 客户端如何连接到这个服务。

不要把 ChatGPT 当作部署方式。ChatGPT 是客户端。Docker、VS Code 扩展、Release 二进制、Python 安装和 stdio 模式才是运行时选择。

```text
运行时层                         暴露层                         客户端层
-------------------------------  -----------------------------  ----------------------
Docker Compose                   仅本地 HTTP                    ChatGPT 自定义 MCP
VS Code 扩展                     HTTPS 反向代理 / 隧道          通用 MCP 客户端
独立二进制                       stdio 进程管道                 VS Code 扩展 UI
pipx / 源码 checkout             远程 worker 出站加入           REST 风格诊断接口
```

常见的公开部署形态是：

```text
ChatGPT
  -> https://mcp.example.com/mcp
  -> 反向代理或隧道
  -> local-shell-mcp 运行时
  -> 受控工作区
```

本地 MCP 客户端可以更简单：

```text
本地 MCP 客户端
  -> 启动 local-shell-mcp --mode stdio
  -> 受控工作区
```

## 运行时选择矩阵

| 运行时 | 适合场景 | 隔离边界 | 工具链来源 | ChatGPT 公网访问 | 页面 |
|---|---|---|---|---|---|
| Docker Compose | 大多数 coding-agent 任务和可重复工作区 | 容器 | 项目镜像包含较完整的默认工具链 | 添加 HTTPS 代理或隧道 | [Docker Compose](../installation/docker.md) |
| Docker Compose + tunnel sidecar | 使用 Cloudflare Tunnel 的单栈公开部署 | 容器 | 项目镜像 | Compose 的 `tunnel` profile 内置 | [Docker Compose](../installation/docker.md#cloudflare-tunnel-sidecar) |
| VS Code 扩展 | 从编辑器工作区启动或停止服务 | 通常是宿主机进程 | 宿主机工具，以及配置的可执行文件 | 为 ChatGPT 添加外部 HTTPS 隧道或代理 | [VS Code 扩展](../installation/vscode-extension.md) |
| 独立二进制 | Docker 不可用，但已有 VM、容器宿主机或专用账号作为边界 | 宿主机或 VM | 宿主机工具 | 添加 HTTPS 代理或隧道 | [独立二进制](../installation/binary.md) |
| `pipx` / 源码安装 | Python 原生使用、调试、开发 | 宿主机 virtualenv 或 VM | Python 包加宿主机工具 | 添加 HTTPS 代理或隧道 | [Python 安装](../installation/python.md) |
| stdio 模式 | 由本地 MCP 客户端直接拉起工具进程 | 客户端进程边界 | 宿主机工具 | ChatGPT 网页或 App 不能直接使用 | [stdio 模式](../installation/stdio.md) |

## 客户端连接矩阵

| 客户端路径 | 需要公网 HTTPS | 使用 `/mcp` | 需要 OAuth | 常见运行时 |
|---|---:|---:|---:|---|
| ChatGPT 自定义 MCP 连接器 | 是 | 是 | 公网使用时需要 | Docker、VS Code 扩展、二进制或 Python |
| 通过 stdio 的通用本地 MCP 客户端 | 否 | 否 | 否 | `local-shell-mcp --mode stdio` |
| 通用 HTTP MCP 客户端 | localhost 通常不需要；跨网络需要 | 是 | localhost 之外建议开启 | 任意 HTTP 运行时 |
| VS Code 扩展辅助流程 | 只有 ChatGPT 需要连接时才需要 | 复制 ChatGPT URL 时使用 | 用于 ChatGPT 时建议开启 | VS Code 启动的运行时 |

另见 [ChatGPT 连接器](../getting-started/chatgpt-connector.md)、[通用 MCP 客户端](../clients/generic-mcp.md) 和 [网络连通性](../clients/connectivity.md)。

## 每种运行时控制什么

每种运行时都会启动同一套服务代码，并在启用时暴露同样的 MCP 工具族：

- Shell 和持久 shell session。
- 文件系统、搜索和补丁工具。
- Git 操作。
- 基于 Playwright 的浏览器自动化。
- 审计日志和任务状态工具。
- 带 token 的文件链接。
- 可选的远程 worker 生命周期和远程工具。

区别不在抽象 API，而在 API 背后的**操作环境**。

| 问题 | Docker Compose | VS Code 扩展 | 二进制 / Python |
|---|---|---|---|
| 命令在哪里运行？ | 容器内 | 通常在宿主机工作区 | 宿主机或 VM 的进程环境 |
| 默认工作区是什么？ | 挂载的 `/workspace` | 当前 VS Code 文件夹或配置路径 | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` |
| 是否预装编译器和浏览器？ | 基本齐全 | 取决于宿主机 | 取决于宿主机 |
| 是否容易重置？ | 删除并重建容器和工作区卷 | 取决于工作区 | 取决于宿主机或 VM |
| 是否适合任意包安装？ | 如果是一次性环境，适合 | 直接宿主机上风险更高 | 除非在 VM 中，否则风险更高 |

## 推荐选择

除非有明确理由，否则优先使用 **Docker Compose**。它提供最清晰的安全边界和最完整的默认工具链。

当工作流从编辑器开始，且你需要本地启动器时，使用 **VS Code 扩展**。它仍然是运行时。它本身不会让服务被 ChatGPT 访问；在 ChatGPT 网页或 App 中使用时，还需要添加隧道或反向代理。

当 Docker 不可用，但已有 VM、容器宿主机或专用用户账号提供边界时，使用**独立二进制**。

当你在开发或调试 `local-shell-mcp` 本身，或 Python 环境更容易维护时，使用 **`pipx` 或源码安装**。

**stdio 模式**只适合能够启动服务进程的本地 MCP 客户端。它不是公开部署方式，也不能被 ChatGPT 网页或 App 直接使用。

## 公开端点规则

对于 ChatGPT 这类 HTTP MCP 客户端，MCP 端点是：

```text
https://your-public-host.example.com/mcp
```

`LOCAL_SHELL_MCP_PUBLIC_BASE_URL` 只填写 origin：

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

不要把 `/mcp` 追加到 `LOCAL_SHELL_MCP_PUBLIC_BASE_URL`。

## 运行时页面

- [Docker Compose](../installation/docker.md)
- [VS Code 扩展](../installation/vscode-extension.md)
- [独立二进制](../installation/binary.md)
- [Python、`pipx` 和源码安装](../installation/python.md)
- [stdio 模式](../installation/stdio.md)

## 客户端页面

- [ChatGPT 连接器](../getting-started/chatgpt-connector.md)
- [通用 MCP 客户端](../clients/generic-mcp.md)
- [公开 HTTPS 暴露](../clients/connectivity.md)
