<!-- i18n-source-sha256: 6fa729155fcc9e524eb3f8081b80d40ceb72c59f5ece4b311809350005468851 -->
# DeepSeek Harness (DSH)

`local-shell-mcp` को सीधे DeepSeek Harness Web profile में install किया जा सकता है। Repository का DSH-aware bridge पूरा LSM tool surface रखता है, हर DSH Session को stable v4 logical-session identity से map करता है और **Live Workspace** को native DSH conversation view के रूप में जोड़ता है। Execution state का authority LSM ही रहता है: local/remote machines, logical Sessions और Goal Plans, persistent terminals, jobs, browser sessions, Dynamic MCP, file links, audit और Live Workspace timeline।

## अनुशंसित topology

DSH और LSM को एक ही machine पर सीधे चलाना बेहतर है। हर DSH Session अपनी अलग LSM MCP connection उपयोग करती है और default `127.0.0.1:8765/mcp` से जुड़ती है।

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

LSM चलाने वाली machine LSM का `local` target है। यदि LSM container में है तो `local` उस container को दर्शाता है, DSH host को नहीं। LSM default `0.0.0.0:8765` पर listen करता है और DSH bundle loopback उपयोग करता है; सही network/firewall/public URL/auth configuration के साथ वही controller Remote Workers और बाहरी clients भी संभाल सकता है।

## इंस्टॉल

पहले LSM शुरू करें:

```bash
local-shell-mcp --mode mcp
```

फिर dedicated DSH npm package को DSH Web profile में install करें:

```bash
dsh plugin --profile web add local-shell-mcp-dsh
```

DSH npm package, LSM के समान release version का उपयोग करता है। Checkout से development के लिए current directory install करें:

```bash
dsh plugin --profile web add .
```

Bundle `cordis.patch.yml` से `local-shell-mcp-dsh` load करता है और normal MCP namespace में model-facing LSM tools देता है, जैसे:

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

Bridge Remote Workers सहित पूरा LSM catalog जानबूझकर रखता है। Internal app-only `live_workspace_reconnect` सिर्फ bridge के लिए है और model को expose नहीं होता। छोटा model tool set चाहिए तो बाद में DSH-side `ctx.tools.restrict()` लगाएँ, LSM bundle से capabilities न हटाएँ।

## DSH Session और LSM logical Session binding

Integration v4 logical-session runtime पर आधारित है। हर DSH Session का अपना upstream Streamable HTTP MCP client होता है; bridge DSH Session id से opaque deterministic session-affinity भी भेजता है, जिससे यह stable identity chain बनती है:

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

अलग DSH conversations की tool activity एक Live Workspace timeline में merge नहीं होती। DSH restart पर उसी affinity से MCP transport फिर बनता है, इसलिए LSM controller के पास Session रहने तक logical Session/active run attached रहते हैं। Bridge active MCP clients को periodically ping भी करता है ताकि normal idle cleanup long-lived conversations न तोड़े।

## DSH के अंदर Live Workspace

DSH browser plugin `conversation.view` में **Live Workspace** जोड़ता है और existing v4 implementation reuse करता है। View current DSH Session तक scoped है और logical Session, Plan/Goal state, Activity, terminals, files, diff, jobs, remotes और audit दिखाता है। **Ask** और Goal auto-continuation उसी DSH conversation में लौटते हैं। Credentials DSH host server-side उस Session की MCP connection से लेता है; conversation या model-visible tool result में नहीं डालता।

## stdio की जगह HTTP क्यों

Remote Workers को MCP tools के अलावा registration, polling, heartbeats, result delivery और transfer traffic के लिए controller के `/remote/*` HTTP routes चाहिए। stdio-only child process service plane खो देगा और दूसरा controller state domain बनाएगा। Existing LSM HTTP service उपयोग करने से Remote Workers, browser state, jobs, Dynamic MCP, audit, file links, logical Sessions और Live Workspace का authority एक रहता है।

## Configuration

DSH Host bridge ये environment variables स्वीकार करता है:

| Variable | Default | Purpose |
|---|---|---|
| `DSH_LSM_MCP_URL` | `http://127.0.0.1:8765/mcp` | DSH द्वारा उपयोग किया गया LSM Streamable HTTP MCP endpoint। |
| `DSH_LSM_AUTHORIZATION` | unset | Optional पूरा `Authorization` header value, जैसे `Bearer ...`। |
| `DSH_LSM_TOOL_CALL_TIMEOUT_MS` | `120000` | हर tool call timeout milliseconds में। |
| `DSH_LSM_KEEPALIVE_INTERVAL_MS` | `30000` | Long-lived per-Session MCP identity बनाए रखने का ping interval; minimum 5000 ms। |
| `DSH_LSM_BROWSER_URL` | unset | Browser-reachable LSM origin जब Host-side MCP origin से अलग हो। |

Same-host deployments को आम तौर पर authorization header नहीं चाहिए क्योंकि LSM localhost auth bypass default enabled है। Unauthenticated LSM को public network पर expose न करें। Protected remote controller के लिए endpoint और bearer token सेट करें:

```bash
export DSH_LSM_MCP_URL='https://lsm.example.com/mcp'
export DSH_LSM_AUTHORIZATION='Bearer <token>'
dsh --profile web
```

Bridge fixed upstream headers भेजता है; DSH की ओर से interactive OAuth authorization/refresh flow नहीं चलाता।

### Remote DSH Web browsers

`DSH_LSM_MCP_URL` DSH **Host** process resolve करता है, लेकिन Live Workspace API requests user browser में चलती हैं। Remote-hosted DSH में LSM loopback URL browser से reachable न हो तो browser-reachable LSM origin सेट करें:

```bash
export DSH_LSM_BROWSER_URL='https://lsm.example.com'
```

Live Workspace token इन browser API requests को authorize करता रहता है।

## Remote Workers

DSH के जरिए Remote Worker mode पूरा उपलब्ध रहता है। `mcp__lsm__remote_manage`, `mcp__lsm__remote_transfer` और `machine` वाले normal LSM tools वही controller और remote-worker state उपयोग करते हैं। External workers के लिए LSM public URL/network exposure सामान्य रूप से configure करें; DSH स्वयं loopback MCP endpoint उपयोग करता रह सकता है।

## Lifecycle और failure behavior

Bundle दूसरा LSM process शुरू नहीं करता। LSM unavailable होने पर भी शुरू हो सकता है; catalog connection backoff से reconnect कर tool catalog बाद में sync करता है। Ambiguous transport failure के बाद model tool calls auto-replay नहीं होते ताकि mutating call दो बार न चले। Stable affinity/keepalive normal transport recreation/idle संभालते हैं; वास्तविक controller replacement deployment के durable Session recovery rules का पालन करता है। Plugin remove केवल DSH-side integration हटाता है:

```bash
dsh plugin --profile web remove local-shell-mcp-dsh
```

यह LSM को बंद नहीं करता।

## Installation verify करें

Composed DSH profile inspect करें:

```bash
dsh --profile web --dump-config
```

Output में `id: local-shell-mcp`, `name: local-shell-mcp-dsh`, `url: http://127.0.0.1:8765/mcp` जैसी row होनी चाहिए।

```text
id: local-shell-mcp
name: local-shell-mcp-dsh
url: http://127.0.0.1:8765/mcp
```

LSM online होने पर DSH को उदाहरणतः ये `mcp__lsm__*` tools expose करने चाहिए:

```text
mcp__lsm__run_shell
mcp__lsm__remote_manage
mcp__lsm__remote_transfer
mcp__lsm__browser_session
mcp__lsm__session_manage
```

DSH Web में non-empty conversation **Live Workspace** view भी दिखाती है। Integration न हो तो `DSH_LSM_MCP_URL`, LSM `/healthz`, `/mcp` reachability, DSH Host log और केवल embedded UI failure में `DSH_LSM_BROWSER_URL` जाँचें।
