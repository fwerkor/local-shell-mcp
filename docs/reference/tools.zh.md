# 工具参考

本页是 `local-shell-mcp` 暴露给 MCP 客户端的人工可读工具参考。工具名、参数名和返回字段保持代码标识符，便于与 MCP schema、审计日志和运行时返回值对应。

普通工具返回结构化 `ToolResult`，包含 `ok`、`message` 和 `data`。连接器式 `search` / `fetch` 为兼容连接器发现，返回 JSON 字符串。除非启用 full-container 策略，文件系统和 shell 操作都受 `LOCAL_SHELL_MCP_WORKSPACE_ROOT` 限制。远程工具在已连接 worker 上执行，并带有机器选择参数。

## 如何选择工具

| 需求 | 推荐顺序 |
|---|---|
| 第一次连接检查 | `environment_info` -> `tree_view` -> `git_status_tool` |
| 定位代码 | `tree_view` -> `glob_search` / `grep_search` -> `read_file` |
| 精确修改文件 | `read_file` -> `edit_file` / `multi_edit_file` / `apply_patch` -> `git_diff_tool` |
| 运行命令 | 一次性命令用 `run_shell_tool`；长时间会话用持久 shell 工具 |
| 提交代码 | `git_status_tool` -> `git_diff_tool` -> `secret_scan` -> `git_add_tool` -> `git_commit_tool` |
| 采集浏览器证据 | `browser_get_text_tool`、`browser_screenshot_tool`、`browser_pdf_tool` |
| 分享生成文件 | `create_file_link` -> `list_file_links` -> `revoke_file_link` |
| 操作另一台机器 | `remote_invite` -> `remote_list_machines` -> `remote_environment_info` -> `remote_*` 工具 |

## 连接器与发现

| 工具 | 用途 | 关键输入 | 返回 |
|---|---|---|---|
| `search` | 搜索工作区文件，并返回 ChatGPT 连接器兼容结果。适合只读发现，不建议作为主要编程工具。 | `query`：普通发现查询字符串。 | 连接器兼容 JSON 字符串。 |
| `fetch` | 读取由 `search` 返回 id 对应的工作区文件。 | `id`：连接器式文件标识符。 | 连接器兼容 JSON 字符串。 |

## 环境、审计和任务状态

| 工具 | 用途 | 关键输入 | 常见组合 |
|---|---|---|---|
| `environment_info` | 返回工作区、认证、策略和基础环境探测信息。 | 无。 | 第一次连接后先调用，再用 `tree_view`。 |
| `version_info` | 返回运行时版本、包版本、Python 版本、平台和可执行路径。 | 无。 | 升级后核对实际运行版本。 |
| `audit_tail` | 读取最近审计日志。 | `lines`：行数，默认 `100`。 | 敏感操作后复查工具调用。 |
| `todo_read_tool` | 读取 agent todo 列表。 | 无。 | 恢复多步骤任务上下文。 |
| `todo_write_tool` | 写入 agent todo 列表。 | `todos`：包含 id、content、status、priority 的记录列表。 | 长任务前建立计划。 |
| `secret_scan` | 提交或推送前扫描工作区文本文件中的常见密钥。 | `cwd`、`glob`、`max_results`。 | `git_diff_tool` 后、`git_commit_tool` 前。 |

## Agent Skills

| 工具 | 用途 | 关键输入 | 注意事项 |
|---|---|---|---|
| `skills_list` | 重新扫描服务端 Skills 目录，列出已安装 Skill，不加载完整指令。 | 无。 | Skill 增删不会改变 MCP 工具列表。 |
| `skill_load` | 加载指定 Skill 的完整 `SKILL.md`。 | `name`：`skills_list` 返回的精确名称。 | 关联文件返回 Skill 内相对路径。 |
| `skill_read_file` | 安全读取指定 Skill 的一个关联文本文件。 | `name`、`path`：均使用 `skill_load` 返回的信息。 | 即使 Skill 目录位于工作区外也可读取；大小受运行时限制。 |

推荐使用 `skills_list` -> `skill_load` -> 按需 `skill_read_file` -> 现有 shell、Git、浏览器或远程工具。三个工具都是固定的只读工具；只有 `skills_list` 扫描注册表，另外两个只访问指定 Skill。

## 文件系统与搜索

| 工具 | 用途 | 关键输入 | 注意事项 |
|---|---|---|---|
| `list_files` | 列出目录下文件和子目录。 | `path`、`recursive`、`max_entries`。 | 适合快速目录检查。 |
| `tree_view` | 返回紧凑目录树。 | `cwd`、`depth`、`max_entries`。 | 大仓库先用它摸底。 |
| `glob_search` | 按 glob 查找路径。 | `pattern`、`cwd`、`max_results`。 | 适合找文件名或扩展名。 |
| `grep_search` | 用 ripgrep 搜索文件内容。 | `query`、`cwd`、`glob`、`regex`、`case_sensitive`、`max_results`。 | 适合定位代码符号或文本。 |
| `read_file` | 读取 UTF-8 文本文件，可按行范围读取。 | `path`、`start_line`、`end_line`。 | 编辑前必须读取目标内容。 |
| `read_many_files` | 批量读取多个 UTF-8 文本文件。 | `paths`、`start_line`、`end_line`。 | 适合同类小文件对比。 |
| `write_file` | 创建或整体替换 UTF-8 文件。 | `path`、`content`、`overwrite`。 | 对已有文件优先用精确编辑工具。 |
| `edit_file` | 用精确文本替换修改文件。 | `path`、`old`、`new`、`replace_all`。 | `old` 必须完全匹配。 |
| `multi_edit_file` | 对同一文件应用多处精确替换。 | `path`、`edits`。 | 修改前先读取，避免陈旧上下文。 |
| `apply_patch` | 应用 unified diff。 | `patch`、`cwd`。 | 适合多文件或较大补丁。 |
| `delete_file_or_dir` | 删除文件或目录。 | `path`、`recursive`。 | 非空目录必须显式 `recursive=true`。 |

## Shell、Python、持久会话和 job

| 工具 | 用途 | 关键输入 | 注意事项 |
|---|---|---|---|
| `run_shell_tool` | 运行一次性非交互 shell 命令。 | `command`、`cwd`、`timeout_s`、`max_output_bytes`。 | 用于测试、构建、包查询、短命令。 |
| `run_python_tool` | 写入临时 Python 文件并执行。 | `code`、`cwd`、`timeout_s`。 | 适合结构化分析、JSON / 文本处理、生成文件。 |
| `shell_start` | 启动持久 shell session。 | `cwd`、`name`、`command`。 | 适合 REPL、开发服务器、watch 任务。 |
| `shell_read` | 读取持久 shell 最近输出。 | `session_id`、`lines`。 | 与 `shell_start` 搭配。 |
| `shell_send` | 向持久 shell 发送输入。 | `session_id`、`input_text`、`enter`。 | 可用于交互进程或继续命令。 |
| `shell_list` | 列出活动持久 shell。 | 无。 | 不确定 session id 时使用。 |
| `shell_kill` | 终止持久 shell session。 | `session_id`。 | 验证后清理长时间进程。 |
| `job_start` | 启动带追踪的长时间 job。 | `command`、`cwd`、`name`。 | 适合构建、服务器、实验、watch。 |
| `job_list` | 列出已追踪 job。 | `include_finished`。 | 查看运行 / 退出状态。 |
| `job_tail` | 读取 job 最近输出。 | `job_id`、`lines`。 | 跟踪长任务进度。 |
| `job_stop` | 停止已追踪 job。 | `job_id`。 | 任务结束或卡住时使用。 |
| `job_retry` | 用原命令重试已停止或退出的 job。 | `job_id`。 | 修复环境后重跑。 |

## Git

| 工具 | 用途 | 关键输入 | 常见用法 |
|---|---|---|---|
| `git_status_tool` | 显示 git 状态和 remote。 | `cwd`。 | 任何修改前先调用。 |
| `git_diff_tool` | 显示 diff，可选择 staged 或统计。 | `cwd`、`staged`、`path`、`stat`。 | 修改后复查。 |
| `git_add_tool` | stage 路径。 | `cwd`、`paths`。 | 提交前只 stage 相关文件。 |
| `git_commit_tool` | 创建提交。 | `cwd`、`message`、`all_changes`。 | 提交前先跑测试和 `secret_scan`。 |
| `git_push_tool` | 推送当前 HEAD。 | `cwd`、`remote`、`branch`、`set_upstream`。 | 需要明确推送目标。 |
| `git_pull_tool` | 拉取当前分支。 | `cwd`、`ff_only`。 | 默认 fast-forward only。 |
| `git_fetch_tool` | fetch remote。 | `cwd`、`remote`、`prune`。 | 检查上游状态。 |
| `git_checkout_tool` | 切换或创建分支。 | `cwd`、`ref`、`create`。 | 创建修复分支或切换引用。 |
| `git_log_tool` | 显示最近提交。 | `cwd`、`max_count`。 | 理解历史。 |
| `git_show_tool` | 查看提交、对象或指定 ref 下文件。 | `cwd`、`ref`、`path`。 | 对比历史文件。 |
| `git_reset_tool` | 执行 git reset。 | `cwd`、`mode`、`ref`。 | 有破坏性，需明确目标。 |

## 浏览器和 Playwright

| 工具 | 用途 | 关键输入 | 典型场景 |
|---|---|---|---|
| `browser_get_text_tool` | 打开 URL 并返回选择器可见文本。 | `url`、`selector`、`browser`、`wait_until`。 | 验证页面内容。 |
| `browser_eval_tool` | 打开 URL 并执行 JavaScript。 | `url`、`javascript`、`browser`、`wait_until`。 | 检查页面状态。 |
| `browser_screenshot_tool` | 保存页面截图。 | `url`、`output_path`、`full_page`、`width`、`height`。 | UI 证据或视觉检查。 |
| `browser_pdf_tool` | 用 Chromium 保存页面 PDF。 | `url`、`output_path`、`width`、`height`。 | 文档或报告导出。 |
| `playwright_install_tool` | 安装 Playwright 浏览器二进制。 | `browser`、`with_deps`。 | 浏览器缺失时使用。 |
| `playwright_run_script_tool` | 运行完整 Python Playwright 脚本。 | `script`、`cwd`、`timeout_s`。 | 多页面、多步骤或复杂检查。 |

## 文件下载链接

| 工具 | 用途 | 关键输入 | 安全点 |
|---|---|---|---|
| `create_file_link` | 为工作区文件创建临时公开下载 URL。 | `path`、`ttl_s`、`filename`、`max_downloads`。 | bearer URL，按需设置短 TTL。 |
| `list_file_links` | 列出已生成文件链接。 | `include_expired`。 | 检查活动链接。 |
| `revoke_file_link` | 撤销文件链接。 | `token`。 | 分享结束后关闭访问。 |

## 远程 worker 管理

| 工具 | 用途 | 关键输入 | 说明 |
|---|---|---|---|
| `remote_invite` | 创建一次性远程 worker 加入命令。 | `name`、`workdir`、`ttl_s`。 | 在远程机器上运行生成命令。 |
| `remote_list_machines` | 列出已连接远程 worker。 | 无。 | 确认机器在线。 |
| `remote_rename_machine` | 重命名远程 worker。 | `machine`、`new_name`。 | 便于区分多台机器。 |
| `remote_revoke_machine` | 撤销并移除远程 worker。 | `machine`。 | 任务结束后清理。 |
| `remote_environment_info` | 返回远程工作区、认证、策略和基础环境。 | `machine`。 | 远程操作前先调用。 |

## 远程文件系统、搜索和传输

| 工具 | 用途 | 关键输入 |
|---|---|---|
| `remote_list_files` | 列出远程目录。 | `machine`、`path`、`recursive`、`max_entries`。 |
| `remote_tree_view` | 返回远程目录树。 | `machine`、`cwd`、`depth`、`max_entries`。 |
| `remote_glob_search` | 远程 glob 查找。 | `machine`、`pattern`、`cwd`、`max_results`。 |
| `remote_grep_search` | 远程内容搜索。 | `machine`、`query`、`cwd`、`glob`、`regex`。 |
| `remote_read_file` | 读取远程文本文件。 | `machine`、`path`、`start_line`、`end_line`。 |
| `remote_read_many_files` | 批量读取远程文件。 | `machine`、`paths`、`start_line`、`end_line`。 |
| `remote_write_file` | 写入远程文件。 | `machine`、`path`、`content`、`overwrite`。 |
| `remote_edit_file` | 精确替换远程文件文本。 | `machine`、`path`、`old`、`new`。 |
| `remote_multi_edit_file` | 对远程单文件做多处精确替换。 | `machine`、`path`、`edits`。 |
| `remote_apply_patch` | 在远程 worker 上应用 unified diff。 | `machine`、`patch`、`cwd`。 |
| `remote_delete_file_or_dir` | 删除远程文件或目录。 | `machine`、`path`、`recursive`。 |
| `remote_push_file` | 从控制服务工作区复制文件到远程 worker。 | `local_path`、`machine`、`remote_path`。 |
| `remote_pull_file` | 从远程 worker 复制文件到控制服务工作区。 | `machine`、`remote_path`、`local_path`。 |
| `remote_push_dir` | 从控制服务复制目录到远程 worker。 | `local_path`、`machine`、`remote_path`。 |
| `remote_pull_dir` | 从远程 worker 复制目录到控制服务。 | `machine`、`remote_path`、`local_path`。 |
| `remote_copy_file` | 通过控制服务在两个远程 worker 之间复制文件。 | `src_machine`、`src_path`、`dst_machine`、`dst_path`。 |
| `remote_copy_dir` | 通过控制服务在两个远程 worker 之间复制目录。 | `src_machine`、`src_path`、`dst_machine`、`dst_path`。 |

## 远程 shell、job、Git 与浏览器

| 工具 | 用途 |
|---|---|
| `remote_run_shell_tool` | 在远程 worker 上运行一次性 shell 命令。 |
| `remote_run_python_tool` | 在远程 worker 上运行临时 Python 脚本。 |
| `remote_shell_start` / `remote_shell_read` / `remote_shell_send` / `remote_shell_kill` / `remote_shell_list` | 管理远程持久 shell session。 |
| `remote_job_start` / `remote_job_list` / `remote_job_tail` / `remote_job_stop` / `remote_job_retry` | 管理远程长时间 job。 |
| `remote_git_status_tool`、`remote_git_diff_tool`、`remote_git_add_tool`、`remote_git_commit_tool`、`remote_git_push_tool`、`remote_git_pull_tool`、`remote_git_fetch_tool`、`remote_git_checkout_tool`、`remote_git_log_tool`、`remote_git_show_tool`、`remote_git_reset_tool` | 在远程 worker 上执行对应 Git 操作。 |
| `remote_browser_get_text_tool`、`remote_browser_eval_tool`、`remote_browser_screenshot_tool`、`remote_browser_pdf_tool`、`remote_playwright_install_tool`、`remote_playwright_run_script_tool` | 在远程 worker 上执行浏览器 / Playwright 操作。 |

## 使用建议

- 先用只读工具确认上下文，再使用写入、shell、Git 或远程工具。
- 对可能产生风险的调用填写 `purpose` 或 `explanation`，便于审计。
- 对长时间任务使用持久 session 或 job，不要让一次性命令无意义地阻塞到超时。
- 修改后用 `git_diff_tool` 复查；提交前用 `secret_scan`。
- 远程 worker 任务完成后撤销机器，文件链接使用完后撤销 token。
