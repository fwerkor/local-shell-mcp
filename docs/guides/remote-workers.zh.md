# 远程 worker

远程 worker 适用于能够发起出站 HTTP(S)、但无法接收入站 SSH 的机器。

```text
MCP 客户端 -> 控制服务 -> 出站轮询 worker -> 远程机器
```

## 基本流程

1. 使用 `remote_invite` 创建一次性邀请。
2. 在远程机器上执行生成的命令。
3. 使用 `remote_list_machines` 确认注册成功。
4. 在普通工具中指定 `machine="<worker-name>"`，例如 `environment_info`、`run_shell_tool`、`read_file` 或 `browser_capture_tool`。
5. 使用 `transfer_path` 处理控制端到 worker、worker 到控制端以及 worker 到 worker 的文件或目录传输。
6. 使用 `remote_rename_machine` 重命名，或用 `remote_revoke_machine` 撤销 worker。

只有 worker 管理继续使用 `remote_*` 名称。执行、shell、job、文件、patch 和浏览器操作在本地与远程使用同一 Schema。指定 `machine` 时会额外要求 `remote:use` OAuth scope。

## 能力与安全

worker 支持 shell、持久终端、tracked job、文件操作、传输、Python、patch，以及已安装依赖时的 Playwright。Git 通过 `run_shell_tool(machine=...)` 执行标准 CLI。

加入 worker 相当于允许 MCP 客户端控制其配置环境。应使用较短邀请 TTL、专用工作目录或账户，保留审计日志，并在任务结束后撤销 worker。生成的邀请会安装与控制服务匹配的 worker 版本。

## 故障排查

如果 worker 未出现，检查出站 HTTPS、公开 base URL、邀请是否过期、系统时间以及控制服务日志。
