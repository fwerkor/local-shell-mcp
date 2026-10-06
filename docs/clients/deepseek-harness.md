# DeepSeek Harness (DSH)

`local-shell-mcp` can be installed directly into a DeepSeek Harness Web profile. The repository ships a DSH-aware bridge that keeps the complete LSM tool surface, maps each DSH Session to a stable v4 logical-session identity, and contributes **Live Workspace** as a native DSH conversation view.

LSM remains the authority for execution state: local and remote machines, logical Sessions and Goal plans, persistent terminals, jobs, browser sessions, Dynamic MCP, file links, audit data, and the Live Workspace timeline all stay in the LSM controller.

## Recommended topology

Run DSH and LSM directly on the same machine:

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

In this layout, the machine running LSM is the LSM `local` target. If LSM itself runs in a container, `local` means that container, not automatically the DSH host.

LSM listens on `0.0.0.0:8765` by default, while the DSH bundle connects through loopback by default. Remote Workers and other external clients can use the same controller when the network, firewall, public URL, and authentication are configured appropriately.

## Install

Start LSM first:

```bash
local-shell-mcp --mode mcp
```

Then install the dedicated DSH npm package into the DSH Web profile:

```bash
dsh plugin --profile web add local-shell-mcp-dsh
```

The DSH npm package uses the same release version as LSM. For development from a checkout:

```bash
dsh plugin --profile web add .
```

The bundle loads `local-shell-mcp-dsh` from `cordis.patch.yml`. DSH receives the model-facing LSM tools under the normal MCP namespace, for example:

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

The bridge deliberately keeps the complete model-facing LSM catalog, including Remote Worker capabilities. The internal `live_workspace_reconnect` app-only tool is used by the bridge but is not exposed to the model. If a deployment wants a smaller model tool set, apply a later DSH-side `ctx.tools.restrict()` policy instead of removing capabilities from the LSM bundle.

## DSH Session and LSM logical Session binding

The integration is based on the v4 logical-session runtime. Each DSH Session gets its own upstream Streamable HTTP MCP client. The bridge also sends an opaque, deterministic session-affinity value derived from the DSH Session id.

That gives the following identity chain:

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

Tool activity from different DSH conversations therefore does not merge into one Live Workspace timeline. A DSH restart recreates the MCP transport with the same affinity, so the existing v4 logical Session and active run remain attached as long as the LSM controller still owns that Session.

The bridge also pings active MCP clients periodically so LSM's normal MCP idle-session cleanup does not break long-lived DSH conversations.

## Live Workspace inside DSH

The DSH browser plugin adds a **Live Workspace** entry to `conversation.view`. It reuses the existing v4 Live Workspace implementation rather than maintaining a second UI/state model.

The view is scoped to the current DSH Session and shows the corresponding LSM logical Session, Plan/Goal state, Activity, terminals, files, diff, jobs, remotes, and audit data. Live Workspace actions such as **Ask** and Goal auto-continuation are routed back into the same DSH conversation.

The DSH host obtains Live Workspace credentials server-side through that Session's own LSM MCP connection. Tokens are not placed in the DSH conversation or model-visible tool result.

## Why HTTP instead of stdio

Remote Workers use more than MCP tools. They require the controller's `/remote/*` HTTP routes for registration, polling, heartbeats, result delivery, and transfer traffic. A stdio-only child process would not preserve that service plane and would also create a second controller state domain.

Using the already-running LSM HTTP service keeps one authority for Remote Workers, browser state, jobs, Dynamic MCP, audit data, file links, logical Sessions, and Live Workspace.

## Configuration

The DSH Host bridge accepts these environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `DSH_LSM_MCP_URL` | `http://127.0.0.1:8765/mcp` | LSM Streamable HTTP MCP endpoint used by DSH. |
| `DSH_LSM_AUTHORIZATION` | unset | Optional complete `Authorization` header value, such as `Bearer ...`. |
| `DSH_LSM_TOOL_CALL_TIMEOUT_MS` | `120000` | Per-tool-call timeout in milliseconds. |
| `DSH_LSM_KEEPALIVE_INTERVAL_MS` | `30000` | Ping interval for preserving long-lived per-Session MCP identity; minimum 5000 ms. |
| `DSH_LSM_BROWSER_URL` | unset | Browser-reachable LSM origin for Live Workspace when it differs from the Host-side MCP origin. |

Same-host deployments normally need no authorization header because LSM's configured localhost auth bypass is enabled by default. Do not expose an unauthenticated LSM service on a public network.

For a protected remote LSM controller:

```bash
export DSH_LSM_MCP_URL='https://lsm.example.com/mcp'
export DSH_LSM_AUTHORIZATION='Bearer <token>'
dsh --profile web
```

The bridge sends fixed upstream headers; it does not run an interactive OAuth authorization/refresh flow on behalf of DSH.

### Remote DSH Web browsers

`DSH_LSM_MCP_URL` is resolved by the DSH **Host** process. Live Workspace API requests, however, run in the user's browser. If DSH is hosted remotely and LSM returns a loopback URL that is not reachable from that browser, set a browser-reachable LSM origin:

```bash
export DSH_LSM_BROWSER_URL='https://lsm.example.com'
```

The Live Workspace token still authorizes the browser API requests.

## Remote Workers

Remote Worker mode remains available through DSH. `mcp__lsm__remote_manage`, `mcp__lsm__remote_transfer`, and ordinary LSM tools with a `machine` argument use the same controller and remote-worker state as other LSM clients.

If workers connect from outside the controller host, configure LSM's public URL and network exposure as usual. DSH itself may continue to use `127.0.0.1:8765/mcp`.

## Lifecycle and failure behavior

The bundle does not launch another LSM process. It can start while LSM is unavailable: the catalog connection reconnects with backoff and synchronizes the tool catalog after LSM appears.

Model tool calls are **not automatically replayed** after an ambiguous transport failure, because replaying a mutating shell/file/remote call could execute it twice. The stable session-affinity key and keepalive handle normal MCP transport recreation and idle periods without changing v4 logical-session ownership; an actual LSM controller replacement still follows the normal durable Session recovery rules of that deployment.

Removing the plugin only removes the DSH-side integration:

```bash
dsh plugin --profile web remove local-shell-mcp-dsh
```

It does not stop LSM.

## Verify the installation

Inspect the composed DSH profile:

```bash
dsh --profile web --dump-config
```

The output should contain a row similar to:

```text
id: local-shell-mcp
name: local-shell-mcp-dsh
url: http://127.0.0.1:8765/mcp
```

Once LSM is online, DSH should expose `mcp__lsm__*` tools including:

```text
mcp__lsm__run_shell
mcp__lsm__remote_manage
mcp__lsm__remote_transfer
mcp__lsm__browser_session
mcp__lsm__session_manage
```

In DSH Web, a non-empty conversation also exposes the **Live Workspace** conversation view. If the integration is absent, check `DSH_LSM_MCP_URL`, LSM `/healthz`, `/mcp` reachability, the DSH Host log, and—when only the embedded UI fails—`DSH_LSM_BROWSER_URL`.
