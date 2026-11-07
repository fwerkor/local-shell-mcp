<!-- i18n-source-sha256: 276e9356b895a85759d31467512bdc530c9baa216a368df4ef1bccce39530d0e -->
<div class="hero-shell" markdown>
<span class="hero-eyebrow">自托管AI工作区·MCP控制平面</span>

# local-shell-mcp

聊天、项目、文件、终端、远程机器和 AI 工具集中在一个自托管界面中。在需要时连接外部 MCP 客户端。

<div class="hero-actions" markdown>
[快速开始](getting-started/quickstart.md){ .hero-action .hero-action--primary }
[Web 工作区](getting-started/web-workspace.md){ .hero-action .hero-action--secondary }
[工具参考](reference/tools.md){ .hero-action .hero-action--secondary }
</div>
</div>

<div class="feature-grid" markdown>
<div class="feature-card" markdown>
### 真实编程环境
在一个 MCP 端点里运行测试、检查仓库、修改文件、操作 Git，并保留审计记录。
</div>

<div class="feature-card" markdown>
### 统一的网络工作空间
使用内置的聊天和项目历史记录以及控制器文件、终端、桌面、会话、远程和审核。外部 MCP 客户端保持可选。
</div>

<div class="feature-card" markdown>
### 远程机器控制
通过远程节点的出站连接控制 NAT、防火墙或 HPC 环境后的机器，无需开放 SSH 入站端口。
</div>
</div>

## 它提供什么

`local-shell-mcp` 为外部客户端提供统一的自托管 AI 工作区和 MCP 服务器。它通过经过身份验证的 MCP 端点提供 shell、持久 shell、文件系统、搜索、补丁、Git、Playwright、审计、持久逻辑会话以及可选的目标计划、标记化文件链接和远程工作人员工具。

适用场景包括：检查仓库、运行测试、修改代码、操作 Git、采集网页证据、生成可下载产物，或者控制只能主动连接控制端的远程机器。

## 架构

```text
运行时层：Docker / VS Code 扩展 / 二进制 / Python / stdio
网络层：localhost / HTTPS 反向代理 / 隧道 / stdio 管道
客户端层：统一WebUI / Gemini / ChatGPT /通用MCP客户端
受控工作区：/workspace 或配置的 workspace root
可选远程节点：远程机器主动连接控制端
```

建议把容器或虚拟机作为隔离边界。

## 按场景选择入口

| 场景 | 阅读页面 | 原因 |
|---|---|---|
| 主浏览器工作区 | [Unified web workspace](getting-started/web-workspace.md) | 具有共享登录名的聊天、项目和 LSM 控制页面 |
| 第一个控制器部署 | [Quickstart](getting-started/quickstart.md) | 推荐的源码部署、OAuth 与首次浏览器使用。 |
| 选择运行时层 | [运行时选择](guides/deployment.md) | 把 Docker、VS Code、二进制、Python 和 stdio 与客户端接入分开说明 |
| 连接 Gemini Spark | [Gemini Custom Apps](getting-started/gemini-spark.md) | 资格、HTTPS MCP URL、OAuth 和测试 |
| 把 ChatGPT 作为客户端接入 | [ChatGPT 连接器](getting-started/chatgpt-connector.md) | 端点、OAuth、首次安全提示和工具发现 |
| 把 LSM 接入 DeepSeek Harness | [DeepSeek Harness 插件](clients/deepseek-harness.md) | 把本仓库作为 DSH bundle 安装，同时保留完整的 LSM 工具与远程 worker 能力 |
| 从 VS Code 启动运行时 | [VS Code 扩展运行时](installation/vscode-extension.md) | 编辑器启动、设置和主机安全边界 |
| 学习如何使用工具集 | [使用模式](guides/usage-patterns.md) | 提示词模板和工具选择建议 |
| 理解所有工具 | [工具参考](reference/tools.md) | 每个工具的用途、参数、返回值、组合方式和注意事项 |
| 连接 HPC、NPU/GPU 或服务器节点 | [远程节点](guides/remote-workers.md) | 出站 worker 加入流程和远程工具用法 |
| 分享生成的文件 | [文件链接](guides/file-links.md) | 带 TTL 和撤销能力的临时下载链接 |
| 加固公开部署 | [安全](security.md) | 隔离、OAuth、工作区范围和审计日志 |

## 主要工具族

| 工具族 | 示例 | 用途 |
|---|---|---|
| Shell 和 Python | `run_shell`, `run_python`, `shell_start` | 构建、测试、脚本、长时间进程 |
| 文件和搜索 | `file_tree`, `file_grep`, `file_read`, `file_patch` | 仓库检查和精确修改 |
| Git | `run_shell`, `run_shell`, `run_shell`, `run_shell` | 可审查的源码管理流程 |
| Session 与 Goal | `session_manage`, `plan_manage` | 持久任务交接、进度报告和可选 Goal mode |
| 浏览器 | `browser_session`, `browser_snapshot`, `browser_act`、`browser_run_script` | 持久交互、UI 检查、截图、渲染文档、页面文本 |
| 文件链接 | `link_create`, `link_revoke` | 从聊天中下载生成产物 |
| 远程节点 | `remote_manage`, `run_shell`, `remote_transfer` | NAT、防火墙或集群登录流程后的机器 |

## 典型工作流

### 在 Web 工作区中编码

1. 启动 LSM 控制器和可选的 [unified web workspace](getting-started/web-workspace.md)。
2. 打开 `/ui` 并使用 LSM 身份登录。
3. 配置模型端点并打开新对话。
4. 要求模型检查存储库并首先运行只读检查。
5. 确认后再让它修改文件、运行测试、检查 diff、提交和推送。
6. 涉及文件链接或远程系统时查看审计日志。

### 远程 HPC 或加速卡主机

1. 创建一次性远程节点邀请。
2. 在远程主机上粘贴生成的命令。
3. 通过普通工具的 `machine` 参数操作远程节点；Git 使用 `run_shell`，路径传输使用 `remote_transfer`。
4. 任务结束后撤销该节点。

### 产物生成

1. 让 AI 在 `/workspace` 下生成文件。
2. 创建带 TTL 或下载次数限制的临时文件链接。
3. 在聊天中分享链接。
4. 使用结束后撤销链接。

## 语言

本站使用 MkDocs 原生 i18n 插件构建。可以通过顶部语言选择器切换语言；尚未翻译的页面会回退到英文版本。
