<!-- i18n-source-sha256: 6fa729155fcc9e524eb3f8081b80d40ceb72c59f5ece4b311809350005468851 -->
# DeepSeek Harness (DSH)

`local-shell-mcp` có thể được cài trực tiếp vào DeepSeek Harness Web profile. Repository cung cấp DSH-aware bridge giữ toàn bộ LSM tool surface, ánh xạ mỗi DSH Session sang identity logical-session v4 ổn định và thêm **Live Workspace** như native DSH conversation view. LSM vẫn là authority của execution state: machine local/remote, logical Session và Goal Plan, persistent terminal, job, browser session, Dynamic MCP, file link, audit và Live Workspace timeline.

## Topology khuyến nghị

Nên chạy DSH và LSM trực tiếp trên cùng machine. Mỗi DSH Session dùng một LSM MCP connection riêng và mặc định kết nối `127.0.0.1:8765/mcp`.

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

Machine chạy LSM là target LSM `local`. Nếu LSM chạy trong container thì `local` là container đó, không tự động là DSH host. LSM mặc định listen `0.0.0.0:8765`, DSH bundle dùng loopback; khi network, firewall, public URL và authentication được cấu hình đúng, cùng controller cũng phục vụ Remote Workers và external clients.

## Cài đặt

Khởi động LSM trước:

```bash
local-shell-mcp --mode mcp
```

Sau đó cài gói npm DSH chuyên dụng vào DSH Web profile:

```bash
dsh plugin --profile web add local-shell-mcp-dsh
```

Gói npm DSH dùng cùng phiên bản release với LSM. Khi phát triển từ checkout, cài thư mục hiện tại:

```bash
dsh plugin --profile web add .
```

Bundle load `local-shell-mcp-dsh` từ `cordis.patch.yml`; DSH nhận model-facing LSM tools trong namespace MCP thông thường, ví dụ:

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

Bridge cố ý giữ toàn bộ LSM catalog, gồm Remote Workers. Tool internal app-only `live_workspace_reconnect` chỉ dành cho bridge và không expose cho model. Nếu cần model tool set nhỏ hơn, áp dụng `ctx.tools.restrict()` phía DSH sau đó thay vì xóa capability khỏi LSM bundle.

## Binding DSH Session và LSM logical Session

Integration dựa trên v4 logical-session runtime. Mỗi DSH Session có upstream Streamable HTTP MCP client riêng; bridge còn gửi opaque deterministic session-affinity từ DSH Session id, tạo identity chain ổn định sau:

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

Tool activity từ các DSH conversation khác nhau không trộn vào cùng Live Workspace timeline. DSH restart tạo lại MCP transport bằng cùng affinity, nên logical Session và active run vẫn attached miễn LSM controller còn sở hữu Session. Bridge cũng ping active MCP clients định kỳ để idle cleanup bình thường của LSM không ngắt conversation dài.

## Live Workspace bên trong DSH

DSH browser plugin thêm **Live Workspace** vào `conversation.view` và reuse implementation v4 hiện có. View scoped theo DSH Session hiện tại, hiển thị logical Session, Plan/Goal state, Activity, terminals, files, diff, jobs, remotes và audit. **Ask** và Goal auto-continuation được route về cùng DSH conversation. Credential được DSH host lấy server-side qua MCP connection của Session đó và không đi vào conversation hoặc model-visible tool result.

## Vì sao dùng HTTP thay vì stdio

Remote Workers cần hơn MCP tools: controller `/remote/*` HTTP routes xử lý registration, polling, heartbeats, result delivery và transfer traffic. Child process stdio-only sẽ mất service plane và tạo controller state domain thứ hai. Dùng LSM HTTP service đang chạy giữ một authority cho Remote Workers, browser state, jobs, Dynamic MCP, audit, file links, logical Sessions và Live Workspace.

## Cấu hình

DSH Host bridge nhận các environment variables sau:

| Variable | Default | Mục đích |
|---|---|---|
| `DSH_LSM_MCP_URL` | `http://127.0.0.1:8765/mcp` | LSM Streamable HTTP MCP endpoint DSH sử dụng. |
| `DSH_LSM_AUTHORIZATION` | unset | Optional giá trị header `Authorization` đầy đủ như `Bearer ...`. |
| `DSH_LSM_TOOL_CALL_TIMEOUT_MS` | `120000` | Timeout mỗi tool call tính bằng milliseconds. |
| `DSH_LSM_KEEPALIVE_INTERVAL_MS` | `30000` | Ping interval để giữ long-lived per-Session MCP identity; minimum 5000 ms. |
| `DSH_LSM_BROWSER_URL` | unset | Browser-reachable LSM origin khi khác Host-side MCP origin. |

Same-host deployment thường không cần authorization header vì LSM localhost auth bypass bật mặc định. Không expose LSM unauthenticated ra public network. Với protected remote controller, set endpoint và bearer token:

```bash
export DSH_LSM_MCP_URL='https://lsm.example.com/mcp'
export DSH_LSM_AUTHORIZATION='Bearer <token>'
dsh --profile web
```

Bridge gửi fixed upstream headers; không chạy interactive OAuth authorization/refresh flow thay DSH.

### Remote DSH Web browsers

`DSH_LSM_MCP_URL` được DSH **Host** process resolve, nhưng Live Workspace API requests chạy trong browser của user. Nếu DSH remote-hosted và LSM loopback URL không reachable từ browser, set browser-reachable LSM origin:

```bash
export DSH_LSM_BROWSER_URL='https://lsm.example.com'
```

Live Workspace token vẫn authorize các browser API requests này.

## Remote Workers

Remote Worker mode vẫn đầy đủ qua DSH. `mcp__lsm__remote_manage`, `mcp__lsm__remote_transfer` và normal LSM tools có `machine` dùng cùng controller và remote-worker state như client khác. Worker bên ngoài cần cấu hình LSM public URL/network exposure bình thường; DSH vẫn có thể dùng MCP loopback.

## Lifecycle và failure behavior

Bundle không launch process LSM khác. Nó có thể start khi LSM unavailable; catalog connection reconnect với backoff và sync tool catalog sau. Model tool calls không auto-replay sau ambiguous transport failure để tránh mutating call chạy hai lần. Stable affinity/keepalive xử lý normal transport recreation/idle; controller replacement thật tuân theo durable Session recovery của deployment. Remove plugin chỉ xóa DSH-side integration:

```bash
dsh plugin --profile web remove local-shell-mcp-dsh
```

Không dừng LSM.

## Verify cài đặt

Inspect composed DSH profile:

```bash
dsh --profile web --dump-config
```

Output cần có row tương tự với `id: local-shell-mcp`, `name: local-shell-mcp-dsh`, `url: http://127.0.0.1:8765/mcp`.

```text
id: local-shell-mcp
name: local-shell-mcp-dsh
url: http://127.0.0.1:8765/mcp
```

Khi LSM online, DSH nên expose ít nhất các `mcp__lsm__*` tools sau:

```text
mcp__lsm__run_shell
mcp__lsm__remote_manage
mcp__lsm__remote_transfer
mcp__lsm__browser_session
mcp__lsm__session_manage
```

Trong DSH Web, conversation non-empty còn có **Live Workspace** view. Nếu integration vắng mặt, kiểm tra `DSH_LSM_MCP_URL`, LSM `/healthz`, `/mcp` reachability, DSH Host log và `DSH_LSM_BROWSER_URL` nếu chỉ embedded UI lỗi.
