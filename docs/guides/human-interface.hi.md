<!-- i18n-source-sha256: 5f07217e742810704f1919224f6cf68bf7b4f5ecf635fadd5ec4d21b072ce6b2 -->
# मानव इंटरफ़ेस

`local-shell-mcp` एक ही service API, workspace, persistent terminal registry, remote-worker registry और MCP audit log पर दो compatible human interfaces देता है:

- **Web UI** तेज़ operational inspection के लिए अनुकूलित native browser dashboard है।
- **OpenTUI** पूर्ण terminal-oriented application है और browser के अंदर तथा native terminal command दोनों रूपों में उपलब्ध रहता है।

कोई भी mode अलग control plane नहीं बनाता। Interface बदलने से connected machines, Sessions, jobs, permissions या audit data नहीं बदलते।

## Service शुरू करें

`local-shell-mcp` को सामान्य रूप से शुरू करें:

```bash
local-shell-mcp --mode mcp
```

## ChatGPT Live Workspace

जब ChatGPT MCP Apps render करता है, `workspace_open(session_id=...)` **स्पष्ट रूप से चुने गए Logical Session** का floating collaborative view खोलता है। durable task state—objective, progress, Plan और Activity—Session में रहता है; Live Workspace केवल उस state, live activity और human controls को दिखाता है। यह MCP transport से task identity का अनुमान कभी नहीं लगाता।

एक सामान्य explicit handoff इस प्रकार है:

```text
session_manage(action="start", objective=...)
        -> session_id
... logical_session_id=session_id के साथ tool calls
... session_manage(action="report", session_id=...) ...
नई ChatGPT conversation
user पिछला session_id देता है
session_manage(action="resume", session_id=...)
        -> मौजूदा progress, Plan और recent Activity
workspace_open(session_id=...)
        -> उसी Session का view
```

`session_id` एकमात्र durable task identity है। Agent को दूसरी conversation की Session को list, infer या automatically select नहीं करना चाहिए। नई conversation में काम जारी रखने के लिए user मौजूदा `session_id` स्पष्ट रूप से देता है। Agent को start/resume के बाद, महत्वपूर्ण progress checkpoints पर और turn समाप्त करने से पहले active `session_id` बताना चाहिए ताकि manual handoff हो सके। Sessions machine या working directory से bind नहीं होतीं; सामान्य tool parameters local/remote targets और paths चुनते रहते हैं।

वैकल्पिक `plan_manage` Plan Session के लिए Goal mode चालू करता है। यदि Plan active है और 15 मिनट तक agent activity नहीं होती, तो जुड़ा हुआ Live Workspace ChatGPT से जारी रखने को कह सकता है। Continuation उसी explicit `session_id` को resume करता है और accepted/rejected दोनों को मिलाकर अधिकतम 10 attempts तक सीमित है। blocked, completed और cancelled Plan auto-continue नहीं होते; ऐसा active Plan जिसके सभी steps completed या skipped हैं, cleanup continuation के लिए eligible रहता है ताकि resumed agent Plan को finish कर सके। Human pause/resume/cancel controls अस्थायी Live Workspace state की जगह Session-owned Plan को update करते हैं।

## Browser interface

खोलें:

```text
http://127.0.0.1:8765/ui
```

Public deployment में configured HTTPS origin का उपयोग करें:

```text
https://your-public-host.example.com/ui
```

Browser interface वही OAuth server और scopes उपयोग करता है जो MCP करता है। Login screen लोड हो सके इसलिए page shell और static assets public हैं, जबकि `/api/ui/*` और OpenTUI terminal WebSocket सुरक्षित रहते हैं। Access tokens केवल browser session storage में रखे जाते हैं।

### Interface चुनें

OAuth screen दो entry points देती है:

- **Open Web UI** authorize करके native dashboard खोलता है।
- **Continue to OpenTUI** authorize करके terminal interface खोलता है और पिछला browser behavior बनाए रखता है।

Authorization के बाद sidebar का interface selector बिना दोबारा login किए Web UI और OpenTUI के बीच बदल सकता है। OpenTUI पर अस्थायी रूप से जाने पर वर्तमान native page याद रखा जाता है।

Routes bookmark की जा सकती हैं:

```text
/ui/#/overview
/ui/#/machines
/ui/#/workloads
/ui/#/activity
/ui/#/console
```

`#/web` और `#/dashboard`, Overview के aliases हैं। `#/tui` और `#/opentui`, Console के aliases हैं।

## Native Web UI

Native Web UI मौजूदा human-interface API को हर पाँच सेकंड में poll करता है और terminal cells की जगह browser-native controls render करता है। OpenTUI चुने जाने तक PTY शुरू नहीं होता।

### Overview

Overview सबसे उच्च प्राथमिकता वाली operational जानकारी पहले दिखाता है:

- Controller health और वर्तमान LSM version।
- Online और offline machine counts।
- Active tracked jobs और persistent terminal sessions।
- CPU, memory, workspace disk, load, network throughput और uptime।
- Worker state, resource thresholds, failed jobs और failed MCP calls से बने alerts।
- हाल की model-originated MCP activity।

### Machines

Machines स्थानीय controller और connected remote workers को status, platform, version, work directory, capabilities और last-seen जानकारी के साथ दिखाता है।

### Workloads

Workloads active tracked jobs और standalone persistent shell sessions को साथ दिखाता है। Web UI इन records के लिए read-only रहता है; interactive session management के लिए OpenTUI उपयोग करें।

### Activity

Activity वर्तमान alerts को हाल की MCP audit activity के साथ जोड़ता है। Human-entered commands और file operations MCP audit log में शामिल नहीं किए जाते।

## Browser OpenTUI

**OpenTUI** चुनने पर वही OpenTUI application lazy-start होता है जिसका उपयोग native terminal launcher करता है। Browser console में ये सुविधाएँ रहती हैं:

- WebSocket पर authenticated binary PTY transport।
- Automatic terminal resizing और reconnect backoff।
- OpenTUI controls के साथ mouse interaction।
- Fullscreen mode और browser-safe keyboard shortcuts।
- Mobile shortcut keys और explicit soft-keyboard control।
- xterm.js के माध्यम से SIXEL और inline image support।

जब तक user native Web UI mode में रहता है, browser OpenTUI PTY नहीं बनाता।

## Native OpenTUI

Standalone release executables platform OpenTUI runtime embed करते हैं। केवल main executable रखें, service शुरू करें, फिर चलाएँ:

```bash
local-shell-mcp tui
```

Native TUI मानव operator से login नहीं माँगता। documented Docker Compose setup में launcher loopback Human UI API के लिए वही host-only dedicated CLI credential उपयोग करता है; दूसरे split-runtime layouts में `--token-file` दिया जा सकता है। Browser से spawn हुई OpenTUI instance controller-process credential उपयोग करती है, जो lazily बनती है और state directory या state backend में कभी persist नहीं होती। केवल loopback से connect करने पर reverse proxy को इनमें से कोई local bypass नहीं मिलता।

Source checkout में Bun dependencies install करने के बाद TUI भी चलाया जा सकता है:

```bash
cd ui
bun install --frozen-lockfile
bun run build
cd ..
local-shell-mcp tui
```

`--api-base` केवल तब उपयोग करें जब local service non-default port उपयोग करती हो:

```bash
local-shell-mcp tui --api-base http://127.0.0.1:9876/api/ui
```

## OpenTUI screens

### Dashboard

Dashboard OpenTUI का operational overview है। Wide terminals node, workload, alert, activity, system-information और trend regions अलग-अलग दिखाते हैं; narrow terminals उन्हें horizontal scrolling के बिना compact summaries में collapse कर देते हैं।

### Files

Files स्थानीय और remote machines के लिए LSM-native three-pane file manager है। यह create, edit, rename, copy, move, paste, delete, hidden-file toggle, refresh, text preview, binary preview और bounded image thumbnails देता है।

### Terminals

Terminals स्थानीय और remote machines पर persistent shell sessions संभालता है। यह complete-command input, raw interactive input, session switching, session creation और termination, recent output तथा collapsible MCP audit rail समर्थित करता है।

### Audit

Audit bounded JSONL audit log पढ़ता है और node, operation, event, session, search, time-range तथा sort filters के साथ record-detail inspection देता है।

### Remotes

Remotes online और offline remote workers, capabilities, work directories और system metadata दिखाता है। यह one-time join invite बना सकता है, node rename कर सकता है या उसकी persistent identity revoke कर सकता है।

## OpenTUI navigation

Top category bar और contextual footer actions native terminals और browser console दोनों में mouse से click किए जा सकते हैं।

| Keys | Action |
|---|---|
| `Alt+1` … `Alt+5` | Dashboard, Files, Terminals, Remotes या Audit खोलें। |
| `F2` … `F6` | वैकल्पिक category shortcuts। |
| `F1` | Keyboard guide खोलें। |
| `F9` | Machine list refresh करें। |
| `Alt+Q` | Browser-reserved Ctrl shortcut चलाए बिना native OpenTUI process बंद करें। |

Terminals में `Alt+N` नई session के लिए, `Alt+W` selected session kill करने के लिए, `Alt+A` audit rail toggle करने के लिए, `Alt+R` refresh के लिए और `Alt+Left/Right` session बदलने के लिए है। Browser console browser-level navigation या menu handling से पहले इन chords को intercept करता है।

## Configuration

| YAML key | Environment variable | Default | Purpose |
|---|---|---|---|
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `true` | Human interfaces mount या disable करें। |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `/ui` | MCP service पर browser interface mount path। |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | auto | Native OpenTUI executable resolution override करें। |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `bing` | OpenTUI browser-console deployments के लिए wallpaper setting। |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | इतने seconds बाद inactive browser OpenTUI PTY बंद करें; `0` timeout disable करता है। |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | Concurrent browser OpenTUI PTY sessions की अधिकतम संख्या। |

## Packaging notes

- Docker images Web UI assets और native OpenTUI runtime शामिल करते हैं।
- Standalone executables Web UI assets और compressed platform OpenTUI runtime embed करते हैं।
- Python wheels browser assets शामिल करते हैं; native OpenTUI के लिए release executable या Bun dependencies वाला source checkout चाहिए।
- दोनों interfaces MCP वाले ही process और port से serve होते हैं; अतिरिक्त web service की आवश्यकता नहीं है।
