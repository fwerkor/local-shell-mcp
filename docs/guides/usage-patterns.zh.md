# 使用模式与提示词指南

`local-shell-mcp` 暴露的是强工具集。好的结果依赖清晰的工作方式：先检查，再小步行动，随后验证，并说明改动了什么。

## 通用操作循环

大多数编程任务可以使用这个循环：

1. 检查：`environment_info`、`tree_view`、`run_shell_tool`、`grep_search`、`read_file`。
2. 计划：让模型识别最小相关文件和测试。
3. 编辑：使用 `edit_file`、`apply_patch` 或 shell 命令。
4. 验证：用 `run_shell_tool` 或持久 shell 运行定向测试或构建。
5. 复查：需要时使用 `run_shell_tool`、`secret_scan`、`audit_tail`。
6. 提交或导出：通过 `run_shell_tool` 执行明确的 Git CLI 命令，或使用 `create_file_link`。

## 工具选择

| 任务 | 优先使用 | 避免 |
|---|---|---|
| 快速一次性命令 | `run_shell_tool` | 每个命令都启动持久 shell |
| 长时间开发服务器、REPL、watch 任务 | `shell_start` + `shell_read` + `shell_send` | 用阻塞式 `run_shell_tool` 等到超时 |
| 结构化分析或生成文件 | `run_python_tool` | 用脆弱的 shell 管道处理复杂 JSON / 文本 |
| 小范围精确编辑 | `edit_file` | 无必要地重写整个文件 |
| 同一文件多处替换 | `edit_file` | 不重新读取文件就反复做陈旧编辑 |
| 多文件补丁 | `apply_patch` | 临时拼接 shell 编辑命令 |
| 查找文件 | `tree_view`、`glob_search` | 对大型仓库做完整递归列表 |
| 查找代码 | `grep_search` | 盲目读取大量文件 |
| 浏览器证据 | `browser_capture_tool`、`browser_get_text_tool` | 只根据页面名或路由猜测 |
| 可下载产物 | `create_file_link` | 在聊天中粘贴大型二进制内容 |
| 远程机器任务 | 普通工具加 `machine`，以及 `transfer_path` | 在出站 worker 模式足够时开放入站 SSH |

## 提示词模板

### 只读仓库摸底

```text
使用 local-shell-mcp。检查仓库结构和 git 状态。不要修改文件。先总结主要组件、能推断出的测试命令以及明显风险，再考虑后续改动。
```

### 聚焦修复 bug

```text
使用 local-shell-mcp 修复这个 bug。先用最小相关命令复现或定位问题。编辑前读取相关文件。做最小补丁，运行定向验证，然后展示 git diff 和实际运行的测试。未经我批准不要提交。
```

### 提交并推送工作流

```text
使用 local-shell-mcp。检查 git status 和 diff，运行相关测试，运行 secret_scan，创建一个聚焦的提交并写简洁提交信息，然后推送当前分支。不要包含缓存、构建产物或无关格式化。
```

### 长时间进程

```text
在持久 shell session 中启动开发服务器，读取输出直到服务就绪，然后使用浏览器工具验证页面。保留 session id，验证后关闭该 session。
```

### 远程 worker 任务

```text
使用名为 <machine> 的已连接远程 worker。先调用 environment_info(machine=<machine>) 和 list_files(machine=<machine>)。只在配置的远程工作目录内操作。短命令用 run_shell_tool，长时间任务用 shell_start 或 job_start。
```

## 处理仓库

开源改动建议流程：

1. 用 `run_shell_tool` 检查是否有未提交改动。
2. 如果任务依赖上游状态，使用 `run_shell_tool` 并检查分支。
3. 编辑前用 `grep_search` 和 `read_file` 定位相关代码。
4. 做最小补丁。
5. 先跑定向测试；可行时再跑更广的测试。
6. 提交或推送前运行 `secret_scan`。
7. 提交信息简洁描述行为变化。

当维护者需要可审查历史时，每个逻辑改动单独一个提交。

## 处理生成产物

对于 PDF、报告、截图、压缩包或日志：

1. 在工作区内生成文件。
2. 验证文件存在且大小符合预期。
3. 使用 `create_file_link`，设置较短 TTL 和可选 `max_downloads`。
4. 不再需要时撤销链接。

不要为私钥、凭据目录或无关个人数据创建公开链接。

## 处理远程机器

当机器能发起出站 HTTPS、但无法接收入站 SSH 时，远程 worker 模式很有用。

推荐做法：

- 用 `remote_invite` 或 `remote_rename_machine` 给机器取清晰名称。
- 操作前检查 `environment_info`。
- 用 `transfer_path` 处理控制端与 worker、或 worker 之间的文件和目录传输。
- 任务结束后用 `remote_revoke_machine` 撤销 worker。

## 反模式

除非环境是一次性的，且你理解后果，否则避免这些指令：

- 在宿主机启动的服务上“全局安装任何需要的东西”。
- 没有时间边界或验证标准地“跑到能用为止”。
- 在包含生成产物的仓库里“提交所有东西”。
- 为了方便暴露整个 home 目录。
- 为整个工作区创建文件链接。
- 在公开部署中使用 `LOCAL_SHELL_MCP_AUTH_MODE=none`。
