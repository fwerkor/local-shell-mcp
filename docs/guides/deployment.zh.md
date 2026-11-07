<!-- i18n-source-sha256: d7d01bc3f36f434c8e66c3fb6f65c2934937c5b2937dd9e8ba7beefc018fd14f -->
# 运行时选择与部署模型

`local-shell-mcp` 有两个互补的决定：

1. **运行时**：服务进程如何运行，以及它控制哪个工作区。
2. **接口**：使用可选的 [unified web workspace](../getting-started/web-workspace.md)，或连接外部 MCP 客户端，例如 Gemini 或 ChatGPT。

推荐的日常界面是自托管 Web 工作区（聊天、项目和 LSM 控制页面）。它与控制器分开部署。 Docker、VS Code 扩展、发布二进制文件、Python 安装和 stdio 模式都是运行控制器的方式；外部聊天应用程序仍然是可选客户端。

```text
运行时层                         暴露层                         客户端层
-------------------------------  -----------------------------  ----------------------
Docker Compose 仅本地 HTTP 统一 Web 工作区
VS Code 扩展                     HTTPS 反向代理 / 隧道          通用 MCP 客户端
独立二进制                       stdio 进程管道                 VS Code 扩展 UI
pipx / 源码 checkout             远程 worker 出站加入           REST 风格诊断接口
```

常见的自托管设置是：

```text
浏览器 -> https://chat.example.com（统一网络工作区）
        -> 经过身份验证的 local-shell-mcp 控制器
        -> 受控工作区和外派员工
可选外部客户端 -> https://mcp.example.com/mcp
```

本地 MCP 客户端可以更简单：

```text
本地 MCP 客户端
  -> 启动 local-shell-mcp --mode stdio
  -> 受控工作区
```

**推荐：** 有条件时应直接部署到具有公网地址的服务器，或通过公网服务器配合 HTTPS 反向代理转发流量。 **不推荐：** Cloudflare Tunnel 客户端的上传速度可能非常慢，导致文件上传与传输功能难以正常使用。仅在无法公网部署或通过公网服务器转发时，才将其作为备选方案。 （[公开 HTTPS 暴露](../clients/connectivity.md)）

## 运行时选择矩阵

| 运行时 | 最适合 | 隔离边界 | 工具链源码 | 外部 MCP 访问 | 页面 |
|---|---|---|---|---|---|
| **源码 checkout（最推荐）** / `pipx` | Python 原生使用、调试、开发 | 宿主机 virtualenv 或 VM | Python 包加宿主机工具 | 添加 HTTPS 代理或隧道 | [Python 安装](../installation/python.md) |
| Docker 组合 | 一次性隔离容器和可重建工作区 | 集装箱 | 精益控制器形象；单独安装特定于任务的工具链 | 添加 HTTPS 代理或隧道 | [Docker Compose](../installation/docker.md) |
| Docker Compose + 隧道 sidecar | 不推荐: 通过公网服务器转发；Cloudflare Tunnel 仅作备选 | 集装箱 | 项目形象 | 通过公网服务器转发；Cloudflare Tunnel 仅作备选 | [Docker Compose](../installation/docker.md#cloudflare-tunnel-sidecar) |
| VS Code 扩展 | 从编辑器工作区启动或停止服务 | 通常是宿主机进程 | 宿主机工具，以及配置的可执行文件 | 为 ChatGPT 添加外部 HTTPS 隧道或代理 | [VS Code 扩展](../installation/vscode-extension.md) |
| 独立二进制 | Docker 不可用，但已有 VM、容器宿主机或专用账号作为边界 | 宿主机或 VM | 宿主机工具 | 添加 HTTPS 代理或隧道 | [独立二进制](../installation/binary.md) |
| stdio 模式 | 由本地 MCP 客户端直接拉起工具进程 | 客户端进程边界 | 宿主机工具 | ChatGPT 网页或 App 不能直接使用 | [stdio 模式](../installation/stdio.md) |

## 客户端连接矩阵

| 接口 | 需要公共 HTTPS | 使用 `/mcp` | 需要 OAuth | 典型运行时间 |
|---|---:|---:|---:|---|
| 统一 LSM Web 工作区 | 是的，用于远程访问；也可以使用本地代理 | 内部 | LSM登录 | 控制器加上独立的网络堆栈 |
| Gemini Spark / 自定义应用程序 | 是的 | 是的 | 是的，供公众使用 | 任何 HTTP 控制器 |
| ChatGPT 自定义 MCP 连接器 | 是 | 是 | 公网使用时需要 | Docker、VS Code 扩展、二进制或 Python |
| 通过 stdio 的通用本地 MCP 客户端 | 否 | 否 | 否 | `local-shell-mcp --mode stdio` |
| 通用 HTTP MCP 客户端 | localhost 通常不需要；跨网络需要 | 是 | localhost 之外建议开启 | 任意 HTTP 运行时 |
| VS Code 扩展辅助流程 | 只有 ChatGPT 需要连接时才需要 | 复制 ChatGPT URL 时使用 | 用于 ChatGPT 时建议开启 | VS Code 启动的运行时 |

请参阅 [unified web workspace](../getting-started/web-workspace.md)、[Gemini Spark](../getting-started/gemini-spark.md)、[ChatGPT connector](../getting-started/chatgpt-connector.md)、[generic MCP clients](../clients/generic-mcp.md) 和 [network connectivity](../clients/connectivity.md)。

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
| 是否预装了编译器和浏览器？ | 不;安装任务所需的内容 | 仅当安装在主机上时 | 仅当安装在主机上时 |
| 是否容易重置？ | 删除并重建容器和工作区卷 | 取决于工作区 | 取决于宿主机或 VM |
| 是否适合任意包安装？ | 如果是一次性环境，适合 | 直接宿主机上风险更高 | 除非在 VM 中，否则风险更高 |

## 推荐选择

**最推荐直接从源码仓库部署** Controller，并使用隔离的虚拟机、容器或受限账号。参见 [Python/源码安装指南](../installation/python.md)。Docker Compose 适合需要一次性隔离环境的场景。

当工作流程从编辑器启动并且您需要本地启动器时，请使用 **VS Code 扩展**。它仍然是一个运行时。远程 Web 客户端需要可访问的 HTTPS 代理或隧道。

当 Docker 不可用，但已有 VM、容器宿主机或专用用户账号提供边界时，使用**独立二进制**。

当你在开发或调试 `local-shell-mcp` 本身，或 Python 环境更容易维护时，使用 **`pipx` 或源码安装**。

**stdio 模式**只适合能够启动服务进程的本地 MCP 客户端。它不是公开部署方式，也不能被 ChatGPT 网页或 App 直接使用。

## 公开端点规则

对于外部 HTTP MCP 客户端（例如 Gemini 和 ChatGPT），MCP 端点是：

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

- [Unified web workspace](../getting-started/web-workspace.md)
- [Gemini Spark / Custom Apps](../getting-started/gemini-spark.md)
- [ChatGPT 连接器](../getting-started/chatgpt-connector.md)
- [通用 MCP 客户端](../clients/generic-mcp.md)
- [公开 HTTPS 暴露](../clients/connectivity.md)
