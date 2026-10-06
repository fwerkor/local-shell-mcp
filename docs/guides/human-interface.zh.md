<!-- i18n-source-sha256: 5f07217e742810704f1919224f6cf68bf7b4f5ecf635fadd5ec4d21b072ce6b2 -->
# 人机界面

`local-shell-mcp` 在同一个服务 API、工作区、持久终端注册表、远程 worker 注册表和 MCP 审计日志之上提供两种兼容的人机界面：

- **Web UI** 是原生浏览器仪表盘，针对快速运行状态检查进行了优化。
- **OpenTUI** 是完整的终端式应用，既可在浏览器中使用，也可作为原生终端命令运行。

两种模式都不会创建独立的控制平面。切换界面不会改变已连接机器、Session、job、权限或审计数据。

## 启动服务

正常启动 `local-shell-mcp`：

```bash
local-shell-mcp --mode mcp
```

## ChatGPT Live Workspace

当 ChatGPT 支持渲染 MCP Apps 时，`workspace_open(session_id=...)` 会为**明确指定的 Logical Session** 打开悬浮式协作视图。Session 持有持久任务状态——objective、progress、Plan 和 Activity；Live Workspace 只负责展示这些状态、实时活动和人类控制。它不会从 MCP transport 推断任务身份。

典型的显式交接流程如下：

```text
session_manage(action="start", objective=...)
        -> session_id
... 工具调用统一传 logical_session_id=session_id
... session_manage(action="report", session_id=...) ...
新建 ChatGPT 对话
用户把之前的 session_id 传给新对话
session_manage(action="resume", session_id=...)
        -> 原有 progress、Plan 和近期 Activity
workspace_open(session_id=...)
        -> 查看同一个 Session
```

`session_id` 是唯一的持久任务身份。Agent 不得列出、推断或自动选择其它对话中的 Session。要在新对话继续工作，由用户明确传入已有的 `session_id`。Agent 应在 start/resume 后、重要进度汇报时以及结束当前 turn 前告知用户正在使用的 `session_id`，以便人工交接。Session 不绑定 machine 或 working directory；普通工具参数仍决定本地/远程目标和路径。

可选的 `plan_manage` Plan 会为 Session 启用 Goal mode。Plan active 且 15 分钟没有 agent activity 时，已关联的 Live Workspace 可以要求 ChatGPT 继续；续跑会 resume 同一个明确的 `session_id`，并限制为最多 10 次 continuation attempt（无论接受还是拒绝）。blocked、completed、cancelled Plan 不自动续跑；如果 active Plan 的所有 step 都已 completed/skipped，仍可触发一次用于收尾的 continuation，让 resumed agent 正式 finish Plan。人类的 pause/resume/cancel 控制修改的是 Session 持有的 Plan，而不是临时 Live Workspace state。

## 浏览器界面

打开：

```text
http://127.0.0.1:8765/ui
```

公网部署则使用配置的 HTTPS origin：

```text
https://your-public-host.example.com/ui
```

浏览器界面与 MCP 使用同一套 OAuth 服务和 scope。页面壳与静态资源保持公开，以便登录页面能够加载；`/api/ui/*` 和 OpenTUI 终端 WebSocket 仍受保护。访问令牌仅存储在浏览器 session storage 中。

### 选择界面

OAuth 页面提供两个入口：

- **Open Web UI**：授权并打开原生仪表盘。
- **Continue to OpenTUI**：授权并打开终端界面，保留此前的浏览器交互方式。

授权后，可通过侧边栏中的界面选择器在 Web UI 与 OpenTUI 之间切换，无需重新登录。临时切换到 OpenTUI 时，当前原生页面会被记住。

路由可加入书签：

```text
/ui/#/overview
/ui/#/machines
/ui/#/workloads
/ui/#/activity
/ui/#/console
```

`#/web` 和 `#/dashboard` 是 Overview 的别名；`#/tui` 和 `#/opentui` 是 Console 的别名。

## 原生 Web UI

原生 Web UI 每五秒轮询现有的人机界面 API，并使用浏览器原生控件而非终端字符单元进行渲染。只有选择 OpenTUI 后才会启动 PTY。

### Overview

Overview 优先展示最重要的运行信息：

- Controller 健康状态和当前 LSM 版本。
- 在线与离线机器数量。
- 活跃的 tracked job 和持久终端会话。
- CPU、内存、工作区磁盘、load、网络吞吐和 uptime。
- 根据 worker 状态、资源阈值、失败 job 和失败 MCP 调用生成的告警。
- 最近由模型发起的 MCP 活动。

### Machines

Machines 列出本地 controller 和已连接的远程 worker，并显示状态、平台、版本、工作目录、能力和 last-seen 信息。

### Workloads

Workloads 合并展示活跃 tracked job 与独立的持久 shell 会话。Web UI 对这些记录保持只读；需要交互式会话管理时使用 OpenTUI。

### Activity

Activity 合并展示当前告警与近期 MCP 审计活动。人类输入的命令和文件操作不会写入 MCP 审计日志。

## 浏览器 OpenTUI

选择 **OpenTUI** 后，会按需启动与原生终端启动器相同的 OpenTUI 应用。浏览器 console 保留：

- 通过 WebSocket 传输的、经过认证的二进制 PTY。
- 自动终端 resize 和重连退避。
- 使用 OpenTUI 控件进行鼠标交互。
- 全屏模式以及浏览器安全的键盘快捷键。
- 移动端快捷键和显式软键盘控制。
- 通过 xterm.js 支持 SIXEL 和 inline image。

用户停留在原生 Web UI 模式时，浏览器不会创建 OpenTUI PTY。

## 原生 OpenTUI

独立 release 可执行文件内嵌对应平台的 OpenTUI runtime。只需保留主可执行文件，启动服务后运行：

```bash
local-shell-mcp tui
```

原生 TUI 不要求人工操作员登录。在文档给出的 Docker Compose 配置中，启动器会对 loopback Human UI API 复用仅保存在宿主机上的专用 CLI 凭据；其它 split-runtime 布局可使用 `--token-file`。由浏览器启动的 OpenTUI 使用仅存在于 controller 进程、按需创建的凭据，绝不会写入 state directory 或 state backend。反向代理不会仅因从 loopback 连接就获得这些本地 bypass。

源码 checkout 在安装 Bun 依赖后也可运行 TUI：

```bash
cd ui
bun install --frozen-lockfile
bun run build
cd ..
local-shell-mcp tui
```

只有本地服务使用非默认端口时才需要 `--api-base`：

```bash
local-shell-mcp tui --api-base http://127.0.0.1:9876/api/ui
```

## OpenTUI 页面

### Dashboard

Dashboard 是 OpenTUI 的运行概览。宽终端会分别显示节点、workload、告警、activity、系统信息和趋势区域；窄终端会将它们折叠为紧凑摘要，不产生横向滚动。

### Files

Files 是 LSM 原生的三栏文件管理器，可操作本地和远程机器。它支持创建、编辑、重命名、复制、移动、粘贴、删除、隐藏文件切换、刷新、文本预览、二进制预览和受限尺寸的图片缩略图。

### Terminals

Terminals 管理本地和远程机器上的持久 shell 会话。它支持完整命令输入、raw 交互输入、会话切换、创建与终止、近期输出，以及可折叠的 MCP 审计栏。

### Audit

Audit 读取有界 JSONL 审计日志，并支持 node、operation、event、session、search、time-range 和 sort 过滤以及记录详情查看。

### Remotes

Remotes 展示在线和离线远程 worker、能力、工作目录和系统元数据。它可以创建一次性 join invite、重命名节点或撤销其持久身份。

## OpenTUI 导航

原生终端和浏览器 console 中，顶部分类栏与底部上下文操作都可用鼠标点击。

| 按键 | 操作 |
|---|---|
| `Alt+1` … `Alt+5` | 打开 Dashboard、Files、Terminals、Remotes 或 Audit。 |
| `F2` … `F6` | 备用分类快捷键。 |
| `F1` | 打开键盘指南。 |
| `F9` | 刷新机器列表。 |
| `Alt+Q` | 退出原生 OpenTUI 进程，同时避免触发浏览器保留的 Ctrl 快捷键。 |

Terminals 使用 `Alt+N` 新建会话、`Alt+W` 终止所选会话、`Alt+A` 切换其审计栏、`Alt+R` 刷新，并用 `Alt+Left/Right` 切换会话。浏览器 console 会在浏览器级导航或菜单处理之前拦截这些组合键。

## 配置

| YAML key | 环境变量 | 默认值 | 用途 |
|---|---|---|---|
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `true` | 挂载或禁用人机界面。 |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `/ui` | MCP 服务上的浏览器界面挂载路径。 |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | auto | 覆盖原生 OpenTUI 可执行文件解析。 |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `bing` | 为 OpenTUI 浏览器 console 部署保留的壁纸设置。 |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | 浏览器 OpenTUI PTY 空闲达到该秒数后关闭；`0` 表示禁用超时。 |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | 浏览器 OpenTUI PTY 的最大并发会话数。 |

## 打包说明

- Docker 镜像包含 Web UI 资源和原生 OpenTUI runtime。
- 独立可执行文件内嵌 Web UI 资源和压缩后的平台 OpenTUI runtime。
- Python wheel 包含浏览器资源；原生 OpenTUI 需要 release 可执行文件，或安装了 Bun 依赖的源码 checkout。
- 两种界面都由与 MCP 相同的进程和端口提供，无需额外 Web 服务。
