<div class="hero-shell" markdown>
<span class="hero-eyebrow">ChatGPT-compatible MCP control plane</span>

# local-shell-mcp

让 ChatGPT 或其它 MCP 客户端在受控环境中使用真实 Shell、工作区、Git、浏览器自动化、文件分享和远程节点能力。

<div class="hero-actions" markdown>
[快速开始](getting-started/quickstart.md){ .hero-action .hero-action--primary }
[选择运行时](guides/deployment.md){ .hero-action .hero-action--secondary }
[工具参考](reference/tools.md){ .hero-action .hero-action--secondary }
</div>
</div>

<div class="feature-grid" markdown>
<div class="feature-card" markdown>
### 真实编程环境
在一个 MCP 端点里运行测试、检查仓库、修改文件、操作 Git，并保留审计记录。
</div>

<div class="feature-card" markdown>
### 运行时和客户端分层
Docker、VS Code 扩展、二进制、Python 和 stdio 是运行时；ChatGPT 和其它 MCP 客户端是接入层。
</div>

<div class="feature-card" markdown>
### 远程机器控制
通过远程节点的出站连接控制 NAT、防火墙或 HPC 环境后的机器，无需开放 SSH 入站端口。
</div>
</div>

## 它提供什么

`local-shell-mcp` 会把一个受控的本地或容器工作区暴露给 ChatGPT 和其它 MCP 客户端。它提供 Shell、持久 Shell、文件系统、搜索、补丁、Git、Playwright、审计、todo、临时文件链接和远程节点工具，并支持 ChatGPT 兼容的 MCP over HTTP 与 OAuth。

适用场景包括：检查仓库、运行测试、修改代码、操作 Git、采集网页证据、生成可下载产物，或者控制只能主动连接控制端的远程机器。

## 架构

```text
运行时层：Docker / VS Code 扩展 / 二进制 / Python / stdio
网络层：localhost / HTTPS 反向代理 / 隧道 / stdio 管道
客户端层：ChatGPT / 通用 MCP 客户端 / 编辑器辅助入口
受控工作区：/workspace 或配置的 workspace root
可选远程节点：远程机器主动连接控制端
```

建议把容器或虚拟机作为隔离边界。

## 按场景选择入口

| 场景 | 阅读页面 | 原因 |
|---|---|---|
| 第一次部署给 ChatGPT 使用 | [快速开始](getting-started/quickstart.md) | Docker Compose、OAuth 和 `/mcp` 基础路径 |
| 选择运行时层 | [运行时选择](guides/deployment.md) | 把 Docker、VS Code、二进制、Python 和 stdio 与客户端接入分开说明 |
| 把 ChatGPT 作为客户端接入 | [ChatGPT 连接器](getting-started/chatgpt-connector.md) | 端点、OAuth、首次安全提示和工具发现 |
| 从 VS Code 启动运行时 | [VS Code 扩展运行时](installation/vscode-extension.md) | 编辑器启动、设置和主机安全边界 |
| 学习如何使用工具集 | [使用模式](guides/usage-patterns.md) | 提示词模板和工具选择建议 |
| 理解所有工具 | [工具参考](reference/tools.md) | 每个工具的用途、参数、返回值、组合方式和注意事项 |
| 连接 HPC、NPU/GPU 或服务器节点 | [远程节点](guides/remote-workers.md) | 出站 worker 加入流程和远程工具用法 |
| 分享生成的文件 | [文件链接](guides/file-links.md) | 带 TTL 和撤销能力的临时下载链接 |
| 加固公开部署 | [安全](security.md) | 隔离、OAuth、工作区范围和审计日志 |

## 主要工具族

| 工具族 | 示例 | 用途 |
|---|---|---|
| Shell 和 Python | `run_shell_tool`, `run_python_tool`, `shell_start` | 构建、测试、脚本、长时间进程 |
| 文件和搜索 | `tree_view`, `grep_search`, `read_file`, `apply_patch` | 仓库检查和精确修改 |
| Git | `run_shell_tool`, `run_shell_tool`, `run_shell_tool`, `run_shell_tool` | 可审查的源码管理流程 |
| 浏览器 | `browser_capture_tool`, `browser_get_text_tool`, `playwright_run_script_tool` | UI 检查、截图、渲染文档、页面文本 |
| 文件链接 | `create_file_link`, `revoke_file_link` | 从聊天中下载生成产物 |
| 远程节点 | `remote_invite`, `run_shell_tool`, `transfer_path` | NAT、防火墙或集群登录流程后的机器 |

## 典型工作流

### 用 ChatGPT 编程

1. 选择 Docker Compose、VS Code 扩展、二进制或 Python 等运行时，并在专用工作区启动。
2. 如果 ChatGPT 需要访问该运行时，先配置网络入口。
3. 把公开 `/mcp` 端点添加到 ChatGPT。
4. 先让 ChatGPT 检查仓库并执行只读检查。
5. 确认后再让它修改文件、运行测试、检查 diff、提交和推送。
6. 涉及文件链接或远程系统时查看审计日志。

### 远程 HPC 或加速卡主机

1. 创建一次性远程节点邀请。
2. 在远程主机上粘贴生成的命令。
3. 通过普通工具的 `machine` 参数操作远程节点；Git 使用 `run_shell_tool`，路径传输使用 `transfer_path`。
4. 任务结束后撤销该节点。

### 产物生成

1. 让 AI 在 `/workspace` 下生成文件。
2. 创建带 TTL 或下载次数限制的临时文件链接。
3. 在聊天中分享链接。
4. 使用结束后撤销链接。

## 语言

本站使用 MkDocs 原生 i18n 插件构建。可以通过顶部语言选择器切换语言；尚未翻译的页面会回退到英文版本。
