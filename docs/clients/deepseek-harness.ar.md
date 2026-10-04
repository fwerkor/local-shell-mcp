<!-- i18n-source-sha256: 6fa729155fcc9e524eb3f8081b80d40ceb72c59f5ece4b311809350005468851 -->
# DeepSeek Harness (DSH)

يمكن تثبيت `local-shell-mcp` مباشرة في DeepSeek Harness Web profile. يتضمن repository bridge واعيًا بـ DSH يحافظ على كامل LSM tool surface، ويربط كل DSH Session بهوية v4 logical-session ثابتة، ويضيف **Live Workspace** كـ DSH conversation view أصلية. يبقى LSM هو authority لحالة التنفيذ كلها: الأجهزة local/remote، وlogical Sessions وGoal Plans، وpersistent terminals وjobs وbrowser sessions وDynamic MCP وfile links وaudit وLive Workspace timeline.

## البنية الموصى بها

يُنصح بتشغيل DSH وLSM مباشرة على الجهاز نفسه. تستخدم كل DSH Session اتصال LSM MCP مستقلًا ويتصل افتراضيًا بـ `127.0.0.1:8765/mcp`.

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

الجهاز الذي يشغّل LSM هو target `local`. إذا كان LSM داخل container فإن `local` يعني ذلك container لا DSH host تلقائيًا. يستمع LSM افتراضيًا على `0.0.0.0:8765` ويستخدم DSH bundle loopback؛ ومع إعداد الشبكة وfirewall وpublic URL والمصادقة يمكن لنفس controller خدمة Remote Workers وعملاء خارجيين.

## التثبيت

ابدأ LSM أولًا:

```bash
local-shell-mcp --mode mcp
```

ثم ثبّت repository في DSH Web profile:

```bash
dsh plugin --profile web add local-shell-mcp-dsh
```

في production ثبّت Git spec على release tag أو commit تمت مراجعته. للتطوير من checkout ثبّت المجلد الحالي:

```bash
dsh plugin --profile web add .
```

يحمّل bundle `local-shell-mcp-dsh` من `cordis.patch.yml` ويعرض DSH أدوات LSM model-facing ضمن MCP namespace المعتاد، مثل:

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

يحافظ bridge عمدًا على LSM catalog كاملًا بما في ذلك Remote Workers. الأداة الداخلية app-only `live_workspace_reconnect` للـ bridge فقط ولا تظهر للنموذج. لتقليل model tool set استخدم لاحقًا `ctx.tools.restrict()` في DSH بدل حذف قدرات LSM bundle.

## ربط DSH Session وLSM logical Session

يعتمد التكامل على v4 logical-session runtime. لكل DSH Session upstream Streamable HTTP MCP client خاص بها، ويرسل bridge session-affinity معتمة وحتمية مشتقة من DSH Session id لتكوين سلسلة الهوية التالية:

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

لذلك لا تختلط tool activity من DSH conversations مختلفة في Live Workspace timeline واحدة. بعد restart DSH يُعاد إنشاء MCP transport بنفس affinity وتظل logical Session وactive run مرتبطة ما دام LSM controller يملك Session. كما يرسل bridge ping دوريًا كي لا يقطع idle cleanup العادي المحادثات الطويلة.

## Live Workspace داخل DSH

يضيف DSH browser plugin **Live Workspace** إلى `conversation.view` ويعيد استخدام تنفيذ v4 الحالي. الـ view مقيّدة بـ DSH Session الحالية وتعرض logical Session وPlan/Goal state وActivity وterminals وfiles وdiff وjobs وremotes وaudit. تعود **Ask** وGoal auto-continuation إلى DSH conversation نفسها. يحصل DSH host على credentials server-side عبر اتصال MCP الخاص بتلك Session، ولا توضع في conversation أو model-visible tool result.

## لماذا HTTP بدل stdio

Remote Workers تحتاج إلى أكثر من MCP tools: routes `/remote/*` HTTP للـ controller تتولى registration وpolling وheartbeats وresult delivery وtransfer traffic. child process يعمل بـ stdio فقط سيفقد service plane وينشئ controller state domain ثانية. استخدام LSM HTTP service القائمة يبقي authority واحدة لكل Remote Workers وbrowser state وjobs وDynamic MCP وaudit وfile links وlogical Sessions وLive Workspace.

## الإعداد

يقبل DSH Host bridge متغيرات البيئة التالية:

| المتغير | الافتراضي | الغرض |
|---|---|---|
| `DSH_LSM_MCP_URL` | `http://127.0.0.1:8765/mcp` | LSM Streamable HTTP MCP endpoint الذي يستخدمه DSH. |
| `DSH_LSM_AUTHORIZATION` | unset | قيمة `Authorization` header كاملة اختيارية مثل `Bearer ...`. |
| `DSH_LSM_TOOL_CALL_TIMEOUT_MS` | `120000` | Timeout لكل tool call بالمللي ثانية. |
| `DSH_LSM_KEEPALIVE_INTERVAL_MS` | `30000` | Ping interval للحفاظ على per-Session MCP identity طويلة العمر؛ الحد الأدنى 5000 ms. |
| `DSH_LSM_BROWSER_URL` | unset | LSM origin الذي يستطيع browser الوصول إليه إذا اختلف عن Host-side MCP origin. |

عادة لا تحتاج same-host deployments إلى authorization header لأن localhost auth bypass في LSM مفعّل افتراضيًا. لا تعرض LSM غير مصادق عليه على شبكة عامة. للـ controller البعيد المحمي اضبط endpoint وbearer token:

```bash
export DSH_LSM_MCP_URL='https://lsm.example.com/mcp'
export DSH_LSM_AUTHORIZATION='Bearer <token>'
dsh --profile web
```

يرسل bridge fixed upstream headers فقط ولا ينفذ interactive OAuth authorization/refresh flow نيابة عن DSH.

### متصفحات DSH Web البعيدة

يحل DSH **Host** process قيمة `DSH_LSM_MCP_URL`، لكن Live Workspace API requests تعمل داخل browser المستخدم. إذا كان DSH remote-hosted وكانت loopback URL الخاصة بـ LSM غير قابلة للوصول، اضبط browser-reachable LSM origin:

```bash
export DSH_LSM_BROWSER_URL='https://lsm.example.com'
```

يبقى Live Workspace token مسؤولًا عن authorization لهذه browser API requests.

## Remote Workers

يبقى Remote Worker mode متاحًا بالكامل عبر DSH. تستخدم `mcp__lsm__remote_manage` و`mcp__lsm__remote_transfer` وأدوات LSM العادية ذات `machine` نفس controller وremote-worker state. للـ workers الخارجية اضبط public URL وnetwork exposure كالمعتاد؛ ويمكن لـ DSH نفسه مواصلة استخدام MCP loopback.

## دورة الحياة وسلوك الأعطال

لا يشغّل bundle عملية LSM إضافية. يمكنه البدء وLSM غير متاح؛ تعيد catalog connection الاتصال مع backoff وتزامن الأدوات لاحقًا. لا يتم replay تلقائيًا لـ model tool calls بعد transport failure غامض كي لا تتكرر mutating calls. تتعامل stable affinity وkeepalive مع إعادة إنشاء transport وidle العاديين؛ أما استبدال controller فعليًا فيتبع durable Session recovery الخاصة بالـ deployment. إزالة plugin تزيل DSH-side integration فقط:

```bash
dsh plugin --profile web remove local-shell-mcp-dsh
```

ولا توقف LSM.

## التحقق من التثبيت

افحص DSH profile المركب:

```bash
dsh --profile web --dump-config
```

يجب أن يحتوي output على row مشابهة فيها `id: local-shell-mcp` و`name: local-shell-mcp-dsh` و`url: http://127.0.0.1:8765/mcp`.

```text
id: local-shell-mcp
name: local-shell-mcp-dsh
url: http://127.0.0.1:8765/mcp
```

بعد أن يصبح LSM online يجب أن يعرض DSH مثلًا أدوات `mcp__lsm__*` التالية:

```text
mcp__lsm__run_shell
mcp__lsm__remote_manage
mcp__lsm__remote_transfer
mcp__lsm__browser_session
mcp__lsm__session_manage
```

في DSH Web تعرض conversation غير الفارغة أيضًا **Live Workspace**. إذا غاب التكامل افحص `DSH_LSM_MCP_URL` و`/healthz` وreachability لـ `/mcp` وDSH Host log، و`DSH_LSM_BROWSER_URL` إذا فشل embedded UI فقط.
