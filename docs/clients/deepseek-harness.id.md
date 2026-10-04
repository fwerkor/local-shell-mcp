<!-- i18n-source-sha256: 6fa729155fcc9e524eb3f8081b80d40ceb72c59f5ece4b311809350005468851 -->
# DeepSeek Harness (DSH)

`local-shell-mcp` dapat diinstal langsung ke DeepSeek Harness Web profile. Repository menyediakan DSH-aware bridge yang mempertahankan seluruh LSM tool surface, memetakan setiap DSH Session ke identity logical-session v4 yang stabil, dan menambahkan **Live Workspace** sebagai native DSH conversation view. LSM tetap menjadi authority untuk execution state: machine local/remote, logical Session dan Goal Plan, persistent terminal, job, browser session, Dynamic MCP, file link, audit, dan Live Workspace timeline.

## Topologi yang disarankan

Jalankan DSH dan LSM langsung pada machine yang sama. Setiap DSH Session memakai koneksi MCP LSM tersendiri dan default terhubung ke `127.0.0.1:8765/mcp`.

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

Machine yang menjalankan LSM adalah target LSM `local`. Jika LSM berjalan dalam container, `local` berarti container tersebut, bukan otomatis host DSH. LSM default listen di `0.0.0.0:8765`, sedangkan bundle DSH memakai loopback; dengan network, firewall, public URL, dan authentication yang benar, controller yang sama juga dapat melayani Remote Workers dan client eksternal.

## Instalasi

Mulai LSM lebih dulu:

```bash
local-shell-mcp --mode mcp
```

Kemudian instal repository ini ke DSH Web profile:

```bash
dsh plugin --profile web add local-shell-mcp-dsh
```

Untuk production, pin Git spec ke release tag atau commit yang telah direview. Untuk development dari checkout, instal directory saat ini:

```bash
dsh plugin --profile web add .
```

Bundle memuat `local-shell-mcp-dsh` dari `cordis.patch.yml`; DSH menerima model-facing LSM tools di namespace MCP normal, misalnya:

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

Bridge sengaja mempertahankan katalog LSM lengkap, termasuk Remote Workers. Tool internal app-only `live_workspace_reconnect` hanya untuk bridge dan tidak diekspos ke model. Jika perlu model tool set lebih kecil, terapkan `ctx.tools.restrict()` di sisi DSH setelahnya, bukan menghapus capability dari LSM bundle.

## Binding DSH Session dan LSM logical Session

Integrasi berbasis v4 logical-session runtime. Setiap DSH Session punya upstream Streamable HTTP MCP client sendiri; bridge juga mengirim opaque deterministic session-affinity dari DSH Session id sehingga membentuk identity chain stabil berikut:

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

Tool activity dari DSH conversation berbeda tidak bercampur dalam satu Live Workspace timeline. Restart DSH membuat ulang MCP transport dengan affinity yang sama, sehingga logical Session dan active run tetap attached selama LSM controller masih memiliki Session. Bridge juga ping MCP client aktif secara berkala agar idle cleanup normal LSM tidak memutus conversation panjang.

## Live Workspace di dalam DSH

DSH browser plugin menambahkan **Live Workspace** ke `conversation.view` dan menggunakan kembali implementasi v4. View scoped ke DSH Session saat ini dan menampilkan logical Session, Plan/Goal state, Activity, terminal, file, diff, jobs, remotes, serta audit. **Ask** dan Goal auto-continuation dirutekan kembali ke DSH conversation yang sama. Credential diperoleh DSH host secara server-side melalui MCP connection Session itu dan tidak masuk ke conversation atau model-visible tool result.

## Mengapa HTTP, bukan stdio

Remote Workers membutuhkan lebih dari MCP tools: route HTTP `/remote/*` controller menangani registration, polling, heartbeats, result delivery, dan transfer traffic. Child process stdio-only akan kehilangan service plane dan membuat controller state domain kedua. Menggunakan LSM HTTP service yang sudah berjalan menjaga satu authority untuk Remote Workers, browser state, jobs, Dynamic MCP, audit, file links, logical Sessions, dan Live Workspace.

## Konfigurasi

DSH Host bridge menerima environment variables berikut:

| Variable | Default | Tujuan |
|---|---|---|
| `DSH_LSM_MCP_URL` | `http://127.0.0.1:8765/mcp` | LSM Streamable HTTP MCP endpoint yang digunakan DSH. |
| `DSH_LSM_AUTHORIZATION` | unset | Optional nilai header `Authorization` lengkap seperti `Bearer ...`. |
| `DSH_LSM_TOOL_CALL_TIMEOUT_MS` | `120000` | Timeout per tool call dalam milliseconds. |
| `DSH_LSM_KEEPALIVE_INTERVAL_MS` | `30000` | Ping interval untuk menjaga long-lived per-Session MCP identity; minimum 5000 ms. |
| `DSH_LSM_BROWSER_URL` | unset | Browser-reachable LSM origin jika berbeda dari Host-side MCP origin. |

Same-host deployment biasanya tidak membutuhkan authorization header karena LSM localhost auth bypass aktif default. Jangan expose LSM unauthenticated ke public network. Untuk protected remote controller, set endpoint dan bearer token:

```bash
export DSH_LSM_MCP_URL='https://lsm.example.com/mcp'
export DSH_LSM_AUTHORIZATION='Bearer <token>'
dsh --profile web
```

Bridge mengirim fixed upstream headers dan tidak menjalankan interactive OAuth authorization/refresh flow atas nama DSH.

### Remote DSH Web browsers

`DSH_LSM_MCP_URL` di-resolve oleh DSH **Host** process, tetapi Live Workspace API requests berjalan di browser user. Jika DSH remote-hosted dan LSM loopback URL tidak reachable dari browser, set browser-reachable LSM origin:

```bash
export DSH_LSM_BROWSER_URL='https://lsm.example.com'
```

Live Workspace token tetap mengotorisasi browser API requests tersebut.

## Remote Workers

Remote Worker mode tetap tersedia penuh melalui DSH. `mcp__lsm__remote_manage`, `mcp__lsm__remote_transfer`, dan normal LSM tools dengan `machine` memakai controller dan remote-worker state yang sama. Worker eksternal memerlukan konfigurasi public URL/network exposure LSM seperti biasa; DSH sendiri tetap dapat memakai MCP loopback.

## Lifecycle dan failure behavior

Bundle tidak menjalankan process LSM lain. Ia dapat mulai saat LSM unavailable; catalog connection reconnect dengan backoff lalu sync tool catalog saat LSM muncul. Model tool calls tidak auto-replay setelah ambiguous transport failure agar mutating call tidak dieksekusi dua kali. Stable affinity/keepalive menangani normal transport recreation/idle; replacement controller nyata mengikuti durable Session recovery deployment. Menghapus plugin hanya menghapus DSH-side integration:

```bash
dsh plugin --profile web remove local-shell-mcp-dsh
```

Tidak menghentikan LSM.

## Verifikasi instalasi

Inspect composed DSH profile:

```bash
dsh --profile web --dump-config
```

Output harus berisi row seperti `id: local-shell-mcp`, `name: local-shell-mcp-dsh`, `url: http://127.0.0.1:8765/mcp`.

```text
id: local-shell-mcp
name: local-shell-mcp-dsh
url: http://127.0.0.1:8765/mcp
```

Setelah LSM online, DSH harus mengekspos antara lain `mcp__lsm__*` tools berikut:

```text
mcp__lsm__run_shell
mcp__lsm__remote_manage
mcp__lsm__remote_transfer
mcp__lsm__browser_session
mcp__lsm__session_manage
```

Di DSH Web, conversation non-empty juga menampilkan **Live Workspace**. Jika integration tidak ada, periksa `DSH_LSM_MCP_URL`, LSM `/healthz`, `/mcp` reachability, DSH Host log, dan `DSH_LSM_BROWSER_URL` bila hanya embedded UI yang gagal.
