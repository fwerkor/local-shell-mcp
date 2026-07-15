# 工具参考

本页概述 `local-shell-mcp` 当前公开的 MCP 工具。英文参考页由实际 MCP Schema 自动生成，包含每个参数的类型和默认值。

除 connector 风格的 `search`、`fetch` 外，普通工具都返回包含 `ok`、`message`、`data` 的结构化 `ToolResult`。多数执行、文件和浏览器工具都接受可选的 `machine` 参数：省略时在控制端执行，指定时在对应远程 worker 执行，并额外要求 `remote:use` 权限。

Git 不再拥有专用 MCP 工具。请通过 `run_shell_tool` 执行标准 Git CLI，例如 `git status --short --branch`、`git diff`、`git commit` 和 `git push`。

## 工具分组

### Connector 与发现

`search`、`fetch`

### 环境、Skills 与任务状态

`environment_info`、`skills_list`、`skill_load`、`skill_read_file`、`secret_scan`、`todo_read_tool`、`todo_write_tool`、`audit_tail`

`environment_info` 已包含运行版本、Python、平台、可执行文件、工作区、权限策略和基础探测信息，因此不再单独暴露 `version_info`。

### Shell 与长期任务

`run_shell_tool`、`run_python_tool`、`shell_start`、`shell_send`、`shell_read`、`shell_kill`、`shell_list`、`job_start`、`job_list`、`job_tail`、`job_stop`、`job_retry`

- 短期、非交互命令使用 `run_shell_tool`。
- 需要交互的终端、REPL、TUI 使用 `shell_*`。
- 需要可跟踪、停止和重试的长期任务使用 `job_*`。

### 文件、搜索与传输

`list_files`、`tree_view`、`glob_search`、`grep_search`、`read_file`、`write_file`、`edit_file`、`delete_file_or_dir`、`apply_patch`、`transfer_path`

- `read_file.path` 可以是单个路径，也可以是路径数组。
- `edit_file.edits` 接受一个或多个精确替换项，不再区分单次与批量编辑工具。
- `transfer_path` 自动判断源是文件还是目录，并支持控制端到 worker、worker 到控制端以及 worker 到 worker。`source_machine` 或 `destination_machine` 至少指定一个。

### 浏览器自动化

`browser_get_text_tool`、`browser_capture_tool`、`playwright_run_script_tool`

- `browser_capture_tool` 通过 `capture_format="png"` 或 `"pdf"` 统一截图和 PDF 输出。
- 页面交互、JavaScript 求值、复杂流程由完整 Playwright 脚本处理。
- 浏览器安装使用普通 shell 命令，不再长期占用独立工具入口。

### 文件下载链接

`create_file_link`、`list_file_links`、`revoke_file_link`

链接使用高熵 bearer token，并支持 TTL、下载次数限制和主动撤销。

### 远程 worker 管理

`remote_invite`、`remote_list_machines`、`remote_rename_machine`、`remote_revoke_machine`

只有 worker 管理继续使用 `remote_*` 名称。实际执行使用普通工具及其 `machine` 参数。

## 常用流程

| 需求 | 推荐工具 |
|---|---|
| 检查环境 | `environment_info` → `tree_view` → `read_file` |
| Git 操作 | `run_shell_tool` 执行标准 Git CLI |
| 精确修改文件 | `read_file` → `edit_file` / `apply_patch` → 测试与 `git diff` |
| 长时间任务 | `job_start` → `job_tail` → `job_stop` / `job_retry` |
| 远程执行 | 同一工具增加 `machine` |
| 跨机器传输 | `transfer_path` |
| 浏览器证据 | `browser_get_text_tool` / `browser_capture_tool` |
