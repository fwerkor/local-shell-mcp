<!-- i18n-source-sha256: d3c380d9a5d9a43019b0be2b5e9accc0d6e0c785d77226005db60c5721672ba6 -->
# 远程 workers

Remote worker 让 `local-shell-mcp` 可以控制只能发起出站 HTTP(S) 请求、但无法接受入站 SSH 连接的机器。

```text
MCP client -> control server -> outbound polling worker -> remote machine
```

## 基本工作流

1. 使用 `remote_manage(action="invite", ...)` 创建邀请。
2. 在远程机器上运行生成的命令。
3. 使用 `remote_manage(action="list")` 确认注册。
4. 调用普通工具并指定 `machine="<worker-name>"`，例如 `environment_get`、`run_shell`、`file_read` 或 `browser_run_script`。
5. 使用 `remote_transfer` 启动受跟踪的 controller-to-worker、worker-to-controller 或 worker-to-worker 文件/目录传输。随后使用 `job_list` 或 `job_tail` 查看进度，并用 `job_stop` 或 `job_retry` 停止或重试。
6. 使用 `remote_manage(action="rename", ...)` 或 `remote_manage(action="revoke", ...)` 重命名或撤销 worker。

邀请码默认仅能注册一台 Worker（`max_uses=1`），增加 `max_uses` 可用于批量注册。多次使用时须留空 `name`。可选参数 `ttl_s` 默认两小时（7200 秒），最长七天（604800 秒）。

只有 worker 管理使用 `remote_*` 名称。执行、shell、job、filesystem、patch 和 browser 操作在本地和远程使用相同 schema。指定 machine 时还需要 `remote:use` OAuth scope。

## 持久化 worker

邀请结果包含平台特定命令：

- `persistent_command` 在 Linux 或 macOS 上安装并启动用户级服务。
- `powershell_persistent_command` 从 PowerShell 在 Windows 上安装并启动用户级任务。

在 Windows 上，`local-shell-mcp worker install-service` 会为当前用户注册 `local-shell-mcp-worker` 任务。该任务会立即启动、重启后在该用户登录时再次启动、允许电池供电、忽略重复启动并重试失败运行。不需要管理员权限，也不会在用户登录前运行。

所有平台都使用相同的 lifecycle 命令：

```text
local-shell-mcp worker status
local-shell-mcp worker start
local-shell-mcp worker stop
local-shell-mcp worker restart
local-shell-mcp worker uninstall-service
```

worker 日志保存在 worker state directory 下的 `worker.log`。

## 能力

Worker 支持 shell 和 persistent shell session、tracked job、filesystem 操作、transfer internals、Python 执行、patch，以及在依赖已安装时使用 Playwright。Git 通过 `run_shell(machine=...)` 执行标准命令。

## 安全与版本

已加入的 worker 会让 MCP client 获得对其配置环境的控制能力。请使用较短的 invite TTL、专用工作目录或账号，检查 audit log，并在任务完成后撤销 worker。生成的邀请会安装与 control server 版本匹配的 worker code。

## 故障排查

worker 未出现时，检查出站 HTTPS 访问、public base URL 可达性、邀请是否过期、系统时间以及 control-server log。
