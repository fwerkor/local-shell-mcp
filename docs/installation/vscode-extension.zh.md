# VS Code 扩展运行时

VS Code 扩展是同一个 `local-shell-mcp` 服务的启动器和便捷 UI。它属于运行时选择，因为它会为当前编辑器工作区启动服务进程。

它不是 ChatGPT 连接器本身。从 ChatGPT 网页或 App 使用时，ChatGPT 仍然连接公开 HTTPS `/mcp` 端点。

## 扩展做什么

扩展会：

- 为当前 VS Code 工作区启动 `local-shell-mcp`。
- 停止和重启服务。
- 在 VS Code output channel 中显示服务输出。
- 检查 `/healthz`。
- 复制 MCP URL。
- 复制包含工作区和端点信息的 ChatGPT 设置提示词。

扩展不内置服务二进制。需要先单独安装 `local-shell-mcp`，如果它不在 `PATH` 中，再把扩展指向该可执行文件。

## 何时使用

适合使用这个运行时的情况：

- 你通常从 VS Code 文件夹开始工作。
- 你想使用按钮或命令面板流程，而不是手动启动终端命令。
- 项目依赖已经安装在宿主机上。
- 你处理的是可信仓库或范围很窄的工作区。
- 你接受只把该工作区暴露给模型。

更适合使用 Docker 的情况：

- 仓库不可信。
- 任务会安装任意包。
- 任务需要较完整的预装工具链。
- 你希望通过重建容器轻松重置环境。
- 你希望比宿主机账号更清晰的边界。

## 安装可执行文件

选择一种服务安装方式：

```bash
pipx install local-shell-mcp
```

或者下载适合你系统的 release 二进制，并把它放到 `PATH`。

然后安装 VSIX release 资产：

```bash
code --install-extension local-shell-mcp-vscode-<version>.vsix
```

也可以在命令面板中使用 **Extensions: Install from VSIX...**。

## 扩展设置

| 设置 | 用途 | 常见值 |
|---|---|---|
| `local-shell-mcp.executablePath` | 服务可执行文件路径 | `local-shell-mcp` 或绝对二进制路径 |
| `local-shell-mcp.host` | 本地服务绑定地址 | 本地使用 `127.0.0.1`；只在受控网络或代理后使用 `0.0.0.0` |
| `local-shell-mcp.port` | 本地服务端口 | `8765` |
| `local-shell-mcp.workspaceRoot` | 暴露给 MCP 的工作区 | 留空表示第一个 VS Code 文件夹，或填写明确路径 |
| `local-shell-mcp.authMode` | 认证模式 | ChatGPT 使用 `oauth`；可信 localhost 测试才用 `none` |
| `local-shell-mcp.publicBaseUrl` | 复制到提示词和 URL 中的公开 HTTPS origin | 例如 `https://mcp.example.com` |
| `local-shell-mcp.oauthAdminPin` | OAuth 授权 PIN | 公开使用时设置强随机值 |
| `local-shell-mcp.allowFullContainer` | full-container 行为开关 | 直接宿主机使用时保持 `false` |
| `local-shell-mcp.extraEnv` | 服务进程额外环境变量 | 只放项目所需且安全的值 |

## 基本流程

1. 在 VS Code 中打开项目文件夹。
2. 运行 **local-shell-mcp: Start Server**。
3. 运行 **local-shell-mcp: Show Server Status**，或在可用时运行 **Check Health**。
4. 对本地 MCP 客户端运行 **local-shell-mcp: Copy MCP URL**；对 ChatGPT 运行 **Copy ChatGPT Setup Prompt**。
5. 把端点添加到客户端。

本地端点通常类似：

```text
http://127.0.0.1:8765/mcp
```

这对本地客户端有用，但 ChatGPT 网页或 App 无法访问。

## 与 ChatGPT 一起使用

如果要让 ChatGPT 使用 VS Code 启动的服务，需要在本地端口前面添加 HTTPS 隧道或反向代理。

示例结构：

```text
ChatGPT
  -> https://your-public-host.example.com/mcp
  -> 隧道或反向代理
  -> 你机器上的 127.0.0.1:8765
  -> VS Code 启动的 local-shell-mcp 进程
```

设置：

```text
local-shell-mcp.publicBaseUrl = https://your-public-host.example.com
local-shell-mcp.authMode = oauth
local-shell-mcp.oauthAdminPin = <strong pin>
```

复制给 ChatGPT 的 URL 应以 `/mcp` 结尾：

```text
https://your-public-host.example.com/mcp
```

## 宿主机运行时安全

扩展通常以你的宿主机用户身份运行命令。这和一次性 Docker 容器有实质区别。

推荐规则：

- 只打开你希望模型控制的仓库。
- 保持 `allowFullContainer` 关闭。
- 不要把 workspace root 设为 home 目录。
- 不要在工作区中保留无关密钥。
- 提交和推送前使用 `secret_scan`。
- 对陌生仓库或需要大量安装包的任务优先使用 Docker。

## 常用提示词

复制设置提示词后，先从只读任务开始：

```text
使用 local-shell-mcp。先调用 environment_info，并对工作区调用 tree_view。暂时不要修改文件。
```

然后再进入有边界的编辑任务：

```text
修复这个工作区中的失败测试。先读取相关文件，做最小补丁，运行定向测试，并展示 git diff。未经我批准不要提交。
```

## 故障排查

| 现象 | 检查 |
|---|---|
| 扩展无法启动服务 | 确认 `local-shell-mcp.executablePath` 存在，并能在终端中运行 `--help` |
| ChatGPT 无法访问 | 本地 `127.0.0.1` URL 不是公网地址；配置隧道或代理并设置 `publicBaseUrl` |
| 工具暴露了错误文件夹 | 显式设置 `local-shell-mcp.workspaceRoot` |
| 重启后认证失败 | 通过 `extraEnv` 或运行时配置设置稳定的 OAuth admin PIN 和 JWT secret |
| 命令缺少依赖 | 在宿主机安装依赖，或切换到 Docker 运行时 |
