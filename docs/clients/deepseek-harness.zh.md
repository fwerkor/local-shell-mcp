<!-- i18n-source-sha256: 6fa729155fcc9e524eb3f8081b80d40ceb72c59f5ece4b311809350005468851 -->
# DeepSeek Harness (DSH)

`local-shell-mcp` 可以直接安装到 DeepSeek Harness Web profile。仓库自带 DSH-aware bridge：保留完整 LSM 工具面，把每个 DSH Session 映射到稳定的 v4 logical-session identity，并把 **Live Workspace** 作为原生 DSH conversation view 注入。执行状态仍由 LSM 统一管理，包括本地/远程机器、logical Session 与 Goal Plan、持久终端、job、浏览器 session、Dynamic MCP、文件链接、审计数据和 Live Workspace timeline。

## 推荐拓扑

推荐让 DSH 与 LSM 直接运行在同一台机器上。每个 DSH Session 使用独立的 LSM MCP connection，并默认连接 `127.0.0.1:8765/mcp`。

```text
DSH Web
  |
  | one LSM MCP connection per DSH Session
  | 127.0.0.1:8765/mcp
  v
local-shell-mcp :8765
  |-- local execution = this LSM host
  |-- /mcp
  |-- /remote/*
  |-- /ui
  |-- Live Workspace / audit / browser / jobs / links
  |
  +--> Remote Workers
```

在这种布局里，运行 LSM 的机器就是 LSM 的 `local` target；如果 LSM 本身在容器中，`local` 指容器而不会自动指向 DSH host。LSM 默认监听 `0.0.0.0:8765`，DSH bundle 默认走 loopback；只要正确配置网络、防火墙、public URL 和认证，同一 controller 也能供 Remote Workers 与其它外部 client 使用。

## 安装

先启动 LSM：

```bash
local-shell-mcp --mode mcp
```

然后把独立发布的 DSH npm package 安装到 DSH Web profile：

```bash
dsh plugin --profile web add local-shell-mcp-dsh
```

DSH npm package 与 LSM 使用相同 release version；从 checkout 开发时仍可直接安装当前目录：

```bash
dsh plugin --profile web add .
```

bundle 通过 `cordis.patch.yml` 加载 `local-shell-mcp-dsh`。DSH 会在普通 MCP namespace 下看到面向模型的完整 LSM 工具，例如：

```text
mcp__lsm__run_shell
mcp__lsm__file_read
mcp__lsm__remote_manage
mcp__lsm__remote_transfer
mcp__lsm__browser_session
mcp__lsm__mcp_tool_search
mcp__lsm__session_manage
mcp__lsm__plan_manage
...
```

bridge 有意保留完整的 model-facing LSM catalog，包括 Remote Worker 能力。内部 app-only `live_workspace_reconnect` 只供 bridge 使用，不暴露给模型。若部署希望减少模型工具集，应在后续 DSH 层使用 `ctx.tools.restrict()`，而不是从 LSM bundle 删除能力。

## DSH Session 与 LSM logical Session 绑定

集成基于 v4 logical-session runtime。每个 DSH Session 都有自己的 upstream Streamable HTTP MCP client；bridge 还会根据 DSH Session id 生成不透明且确定性的 session-affinity 值，从而形成以下稳定身份链：

```text
DSH Session A
  -> stable LSM session affinity A
  -> v4 MCP session key A
  -> LSM logical Session / active run A
  -> Live Workspace A

DSH Session B
  -> stable LSM session affinity B
  -> v4 MCP session key B
  -> LSM logical Session / active run B
  -> Live Workspace B
```

不同 DSH conversation 的工具活动因此不会合并进同一个 Live Workspace timeline。DSH 重启后会用相同 affinity 重建 MCP transport，所以只要 LSM controller 仍拥有该 Session，原有 v4 logical Session 和 active run 会继续附着。bridge 还会定期 ping 活跃 MCP client，避免 LSM 的正常 idle-session cleanup 破坏长生命周期 DSH conversation。

## DSH 内的 Live Workspace

DSH browser plugin 会向 `conversation.view` 添加 **Live Workspace**，直接复用现有 v4 Live Workspace，而不维护第二套 UI/state model。该 view 按当前 DSH Session 隔离，展示对应 LSM logical Session、Plan/Goal state、Activity、终端、文件、diff、jobs、remotes 和 audit；**Ask** 与 Goal 自动续跑会回到同一 DSH conversation。Live Workspace credential 由 DSH host 通过该 Session 自己的 LSM MCP connection 在服务端获取，不会放进 DSH conversation 或模型可见 tool result。

## 为什么使用 HTTP 而不是 stdio

Remote Workers 不只依赖 MCP tools，还需要 controller 的 `/remote/*` HTTP routes 完成注册、polling、heartbeat、结果回传和 transfer traffic。stdio-only child process 会破坏这条 service plane，并产生第二个 controller state domain。复用已经运行的 LSM HTTP service，可让 Remote Workers、browser state、jobs、Dynamic MCP、audit、file links、logical Sessions 和 Live Workspace 始终由同一个 authority 管理。

## 配置

DSH Host bridge 支持以下环境变量：

| 变量 | 默认值 | 用途 |
|---|---|---|
| `DSH_LSM_MCP_URL` | `http://127.0.0.1:8765/mcp` | DSH 使用的 LSM Streamable HTTP MCP endpoint。 |
| `DSH_LSM_AUTHORIZATION` | unset | 可选的完整 `Authorization` header，例如 `Bearer ...`。 |
| `DSH_LSM_TOOL_CALL_TIMEOUT_MS` | `120000` | 单次 tool call timeout，单位毫秒。 |
| `DSH_LSM_KEEPALIVE_INTERVAL_MS` | `30000` | 用于保持长生命周期 per-Session MCP identity 的 ping 间隔；最小 5000 ms。 |
| `DSH_LSM_BROWSER_URL` | unset | 当浏览器可访问的 LSM origin 与 Host-side MCP origin 不同时使用。 |

同机部署通常不需要 authorization header，因为 LSM 默认启用 localhost auth bypass；但不要把未认证的 LSM 服务暴露到公网。连接受保护的远程 LSM controller 时可设置 endpoint 与 bearer token：

```bash
export DSH_LSM_MCP_URL='https://lsm.example.com/mcp'
export DSH_LSM_AUTHORIZATION='Bearer <token>'
dsh --profile web
```

bridge 只发送固定 upstream headers，不代表 DSH 执行交互式 OAuth authorization/refresh flow。

### 远程 DSH Web 浏览器

`DSH_LSM_MCP_URL` 由 DSH **Host** process 解析，但 Live Workspace API request 运行在用户浏览器里。如果 DSH 远程托管，而 LSM 返回的 loopback URL 对浏览器不可达，就配置浏览器可达的 LSM origin：

```bash
export DSH_LSM_BROWSER_URL='https://lsm.example.com'
```

Live Workspace token 仍负责授权这些 browser API request。

## Remote Workers

通过 DSH 仍可完整使用 Remote Worker mode。`mcp__lsm__remote_manage`、`mcp__lsm__remote_transfer` 以及带 `machine` 参数的普通 LSM 工具都使用与其它 LSM client 相同的 controller 和 remote-worker state。若 worker 从 controller host 外部连接，按通常方式配置 LSM public URL 和网络暴露即可；DSH 自己仍可继续使用 `127.0.0.1:8765/mcp`。

## 生命周期与故障行为

bundle 不会再启动一个 LSM process。即使启动时 LSM 不可用也没关系：catalog connection 会按 backoff 重连，并在 LSM 出现后同步 tool catalog。模型 tool call 在不明确的 transport failure 后不会自动 replay，因为 mutating shell/file/remote call 重放可能执行两次。稳定 affinity key 与 keepalive 负责普通 MCP transport 重建和 idle period；真正替换 LSM controller 时仍遵循该部署正常的 durable Session recovery 规则。移除 plugin 只删除 DSH-side integration：

```bash
dsh plugin --profile web remove local-shell-mcp-dsh
```

它不会停止 LSM。

## 验证安装

检查组合后的 DSH profile：

```bash
dsh --profile web --dump-config
```

输出应包含类似 `id: local-shell-mcp`、`name: local-shell-mcp-dsh`、`url: http://127.0.0.1:8765/mcp` 的条目。LSM 在线后，DSH 应暴露如下 `mcp__lsm__*` 工具：

```text
id: local-shell-mcp
name: local-shell-mcp-dsh
url: http://127.0.0.1:8765/mcp
```

LSM 在线后，DSH 应暴露包括以下内容在内的 `mcp__lsm__*` 工具：

```text
mcp__lsm__run_shell
mcp__lsm__remote_manage
mcp__lsm__remote_transfer
mcp__lsm__browser_session
mcp__lsm__session_manage
```

在 DSH Web 中，非空 conversation 还应出现 **Live Workspace** conversation view。若集成缺失，检查 `DSH_LSM_MCP_URL`、LSM `/healthz`、`/mcp` 可达性、DSH Host log；若只有嵌入 UI 失败，再检查 `DSH_LSM_BROWSER_URL`。
