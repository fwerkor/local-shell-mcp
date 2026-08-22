# 远程 worker

远程 worker 适用于能够发起出站 HTTP(S)、但无法接收入站 SSH 的机器。

```text
MCP 客户端 -> 控制服务 -> 出站轮询 worker -> 远程机器
```

## 基本流程

1. 使用 `remote_manage(action="invite", ...)` 创建一次性邀请。
2. 在远程机器上执行生成的命令。
3. 使用 `remote_manage(action="list")` 确认注册成功。
4. 在普通工具中指定 `machine="<worker-name>"`，例如 `environment_get`、`run_shell`、`file_read` 或 `browser_capture_tool`。
5. 使用 `remote_transfer` 处理控制端到 worker、worker 到控制端以及 worker 到 worker 的文件或目录传输。
6. 使用 `remote_manage(action="rename", ...)` 重命名，或用 `remote_manage(action="revoke", ...)` 撤销 worker。

只有 worker 管理继续使用 `remote_*` 名称。执行、shell、job、文件、patch 和浏览器操作在本地与远程使用同一 Schema。指定 `machine` 时会额外要求 `remote:use` OAuth scope。

## 持久化 worker

邀请结果会同时返回适用于不同平台的命令：

- `persistent_command` 在 Linux 或 macOS 上安装并启动用户服务。
- `powershell_persistent_command` 通过 PowerShell 在 Windows 上安装并启动用户计划任务。

在 Windows 上，`local-shell-mcp worker install-service` 会为当前用户注册 `local-shell-mcp-worker` 计划任务。任务会立即启动，并在重启后该用户登录时再次启动；它允许电池供电运行、忽略重复启动，并在异常退出后重试。该方式不需要管理员权限，但不会在用户登录前运行。

所有平台使用相同的生命周期命令：

```text
local-shell-mcp worker status
local-shell-mcp worker start
local-shell-mcp worker stop
local-shell-mcp worker restart
local-shell-mcp worker uninstall-service
```

worker 日志位于 worker 状态目录中的 `worker.log`。

## 能力与安全

worker 支持 shell、持久终端、tracked job、文件操作、传输、Python、patch，以及已安装依赖时的 Playwright。Git 通过 `run_shell(machine=...)` 执行标准 CLI。

加入 worker 相当于允许 MCP 客户端控制其配置环境。应使用较短邀请 TTL、专用工作目录或账户，保留审计日志，并在任务结束后撤销 worker。生成的邀请会安装与控制服务匹配的 worker 版本。

## 故障排查

如果 worker 未出现，检查出站 HTTPS、公开 base URL、邀请是否过期、系统时间以及控制服务日志。
