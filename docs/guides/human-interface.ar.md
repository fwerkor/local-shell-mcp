<!-- i18n-source-sha256: 5f07217e742810704f1919224f6cf68bf7b4f5ecf635fadd5ec4d21b072ce6b2 -->
# واجهة المستخدم

يوفر `local-shell-mcp` واجهتين بشريتين متوافقتين فوق نفس service API وworkspace وسجل persistent terminals وسجل remote workers وسجل تدقيق MCP:

- **Web UI** لوحة معلومات أصلية في المتصفح ومهيأة للفحص التشغيلي السريع.
- **OpenTUI** التطبيق الكامل الموجّه للطرفية، ويظل متاحًا داخل المتصفح وكأمر طرفية أصلي.

لا ينشئ أي من الوضعين control plane منفصلًا. تبديل الواجهة لا يغير الأجهزة المتصلة أو Sessions أو jobs أو الصلاحيات أو بيانات التدقيق.

## تشغيل الخدمة

شغّل `local-shell-mcp` بالطريقة المعتادة:

```bash
local-shell-mcp --mode mcp
```

## ChatGPT Live Workspace

عندما يعرض ChatGPT تطبيقات MCP، يفتح `workspace_open(session_id=...)` عرضًا تعاونيًا عائمًا للـ **Logical Session المحددة صراحةً**. تحتفظ الـ Session بحالة المهمة الدائمة—objective وprogress وPlan وActivity—بينما يعرض Live Workspace هذه الحالة والنشاط المباشر وأدوات التحكم البشرية فقط. ولا يستنتج هوية المهمة من MCP transport.

يكون التسليم الصريح المعتاد كالتالي:

```text
session_manage(action="start", objective=...)
        -> session_id
... استدعاءات الأدوات مع logical_session_id=session_id
... session_manage(action="report", session_id=...) ...
محادثة ChatGPT جديدة
يمرر المستخدم session_id السابقة
session_manage(action="resume", session_id=...)
        -> progress وPlan وActivity الحديثة الموجودة
workspace_open(session_id=...)
        -> عرض الـ Session نفسها
```

`session_id` هي هوية المهمة الدائمة الوحيدة. لا يجوز للـ Agent سرد Session من محادثة أخرى أو استنتاجها أو اختيارها تلقائيًا. لمتابعة العمل في محادثة جديدة، يمرر المستخدم `session_id` الموجودة صراحةً. ينبغي للـ Agent إبلاغ المستخدم بالـ `session_id` النشطة بعد start/resume، وعند نقاط التقدم المهمة، وقبل إنهاء turn حتى يمكن تسليمها يدويًا. لا ترتبط Sessions بـ machine أو working directory؛ وتستمر معاملات الأدوات العادية في اختيار الأهداف local/remote والمسارات.

يتيح Plan اختياري عبر `plan_manage` وضع Goal mode للـ Session. إذا كان Plan في حالة active ولم يحدث agent activity لمدة 15 دقيقة، يمكن لـ Live Workspace المرتبط أن يطلب من ChatGPT المتابعة. تستأنف continuation نفس `session_id` الصريحة وتقتصر على 10 محاولات سواء قُبلت أم رُفضت. لا تتم متابعة Plans ذات الحالات blocked أو completed أو cancelled تلقائيًا؛ ويظل Plan active الذي أصبحت كل steps فيه completed أو skipped مؤهلًا لـ continuation ختامية حتى يتمكن الـ Agent المستأنف من إنهاء Plan. تعدّل أدوات pause/resume/cancel البشرية الـ Plan المملوك للـ Session بدلًا من حالة Live Workspace المؤقتة.

## واجهة المتصفح

افتح:

```text
http://127.0.0.1:8765/ui
```

في النشر العام استخدم HTTPS origin المضبوط:

```text
https://your-public-host.example.com/ui
```

تستخدم واجهة المتصفح خادم OAuth ونطاقات scope نفسها المستخدمة في MCP. تكون هيكلية الصفحة والموارد الثابتة عامة حتى يمكن تحميل شاشة الدخول، بينما تبقى `/api/ui/*` وWebSocket الخاص بطرفية OpenTUI محمية. تُخزَّن access tokens فقط في session storage للمتصفح.

### اختيار الواجهة

توفر شاشة OAuth مدخلين:

- **Open Web UI** يمنح التفويض ويفتح لوحة المعلومات الأصلية.
- **Continue to OpenTUI** يمنح التفويض ويفتح واجهة الطرفية مع الحفاظ على سلوك المتصفح السابق.

بعد التفويض يمكن التبديل بين Web UI وOpenTUI من محدد الواجهة في الشريط الجانبي دون تسجيل دخول جديد. تُحفظ الصفحة الأصلية الحالية عند الانتقال مؤقتًا إلى OpenTUI.

يمكن حفظ المسارات في الإشارات المرجعية:

```text
/ui/#/overview
/ui/#/machines
/ui/#/workloads
/ui/#/activity
/ui/#/console
```

`#/web` و`#/dashboard` اسمان بديلان لـ Overview، و`#/tui` و`#/opentui` اسمان بديلان لـ Console.

## Web UI الأصلية

تستطلع Web UI الأصلية API واجهة المستخدم الحالية كل خمس ثوانٍ وتعرض عناصر تحكم أصلية للمتصفح بدل خلايا الطرفية. ولا تبدأ PTY حتى يتم اختيار OpenTUI.

### Overview

يعرض Overview المعلومات التشغيلية الأعلى أولوية أولًا:

- صحة controller وإصدار LSM الحالي.
- عدد الأجهزة المتصلة وغير المتصلة.
- tracked jobs النشطة وجلسات الطرفية الدائمة.
- CPU والذاكرة وقرص workspace وload ومعدل نقل الشبكة وuptime.
- التنبيهات الناتجة عن حالة workers وحدود الموارد وjobs الفاشلة واستدعاءات MCP الفاشلة.
- نشاط MCP الأخير الصادر عن النموذج.

### Machines

يعرض Machines الـ controller المحلي والworkers البعيدة المتصلة مع الحالة والمنصة والإصدار ودليل العمل والقدرات ومعلومات last-seen.

### Workloads

يجمع Workloads بين tracked jobs النشطة وجلسات shell الدائمة المستقلة. تبقى Web UI للقراءة فقط لهذه السجلات؛ استخدم OpenTUI لإدارة الجلسات التفاعلية.

### Activity

يجمع Activity بين التنبيهات الحالية ونشاط تدقيق MCP الأخير. لا تُضمَّن الأوامر وعمليات الملفات التي يدخلها الإنسان في سجل تدقيق MCP.

## OpenTUI في المتصفح

يؤدي اختيار **OpenTUI** إلى تشغيل تطبيق OpenTUI نفسه المستخدم في مشغل الطرفية الأصلي عند الحاجة. تحتفظ console المتصفح بما يلي:

- نقل PTY ثنائي موثّق عبر WebSocket.
- تغيير حجم الطرفية تلقائيًا وbackoff لإعادة الاتصال.
- التفاعل بالماوس مع عناصر تحكم OpenTUI.
- وضع ملء الشاشة واختصارات لوحة مفاتيح آمنة للمتصفح.
- مفاتيح اختصار للهاتف وتحكم صريح بلوحة المفاتيح البرمجية.
- دعم SIXEL وinline image عبر xterm.js.

لا ينشئ المتصفح PTY لـ OpenTUI ما دام المستخدم في وضع Web UI الأصلي.

## OpenTUI الأصلي

تضمّن ملفات release التنفيذية المستقلة runtime الخاص بـ OpenTUI للمنصة. احتفظ بالملف التنفيذي الرئيسي فقط، وشغّل الخدمة، ثم نفّذ:

```bash
local-shell-mcp tui
```

لا تطلب TUI الأصلية من المشغّل البشري تسجيل الدخول. في إعداد Docker Compose الموثّق، يعيد المشغّل استخدام dedicated CLI credential المحفوظة على المضيف فقط للوصول إلى Human UI API عبر loopback؛ ويمكن استخدام `--token-file` في ترتيبات split-runtime الأخرى. تستخدم مثيلات OpenTUI التي يشغّلها المتصفح credential داخل process الخاص بالـ controller تُنشأ عند الحاجة فقط ولا تُحفظ مطلقًا في state directory أو state backend. ولا يحصل reverse proxy على أي من هذين الـ bypass المحليين لمجرد اتصاله عبر loopback.

يمكن أيضًا لـ source checkout تشغيل TUI بعد تثبيت تبعيات Bun:

```bash
cd ui
bun install --frozen-lockfile
bun run build
cd ..
local-shell-mcp tui
```

استخدم `--api-base` فقط عندما تستخدم الخدمة المحلية منفذًا غير افتراضي:

```bash
local-shell-mcp tui --api-base http://127.0.0.1:9876/api/ui
```

## شاشات OpenTUI

### Dashboard

Dashboard هي النظرة التشغيلية العامة لـ OpenTUI. تعرض الطرفيات العريضة مناطق منفصلة لـ node وworkload وalert وactivity ومعلومات النظام والاتجاهات؛ وتطوي الطرفيات الأضيق هذه المعلومات في ملخصات مدمجة دون تمرير أفقي.

### Files

Files مدير ملفات أصلي من LSM بثلاث لوحات للأجهزة المحلية والبعيدة. يوفّر الإنشاء والتحرير وإعادة التسمية والنسخ والنقل واللصق والحذف وتبديل الملفات المخفية والتحديث ومعاينة النص ومعاينة الملفات الثنائية وصورًا مصغرة محدودة الحجم.

### Terminals

يدير Terminals جلسات shell الدائمة على الأجهزة المحلية والبعيدة. يدعم إدخال الأوامر الكاملة والإدخال التفاعلي raw وتبديل الجلسات وإنشاءها وإنهاءها والمخرجات الأخيرة وشريط تدقيق MCP قابلًا للطي.

### Audit

يقرأ Audit سجل تدقيق JSONL المحدود ويدعم مرشحات node وoperation وevent وsession وsearch وtime-range وsort مع فحص تفاصيل السجل.

### Remotes

يعرض Remotes workers البعيدة المتصلة وغير المتصلة وقدراتها وأدلة العمل وبيانات النظام الوصفية. ويمكنه إنشاء join invite لمرة واحدة أو إعادة تسمية node أو إلغاء هويته الدائمة.

## التنقل في OpenTUI

يمكن النقر بالماوس على شريط الفئات العلوي وإجراءات footer السياقية في الطرفيات الأصلية وconsole المتصفح.

| المفاتيح | الإجراء |
|---|---|
| `Alt+1` … `Alt+5` | يفتح Dashboard أو Files أو Terminals أو Remotes أو Audit. |
| `F2` … `F6` | اختصارات بديلة للفئات. |
| `F1` | فتح دليل لوحة المفاتيح. |
| `F9` | تحديث قائمة الأجهزة. |
| `Alt+Q` | إنهاء عملية OpenTUI الأصلية دون تشغيل اختصار Ctrl محجوز للمتصفح. |

يستخدم Terminals المفتاح `Alt+N` لجلسة جديدة، و`Alt+W` لإنهاء الجلسة المحددة، و`Alt+A` لتبديل شريط التدقيق، و`Alt+R` للتحديث، و`Alt+Left/Right` للتبديل بين الجلسات. تعترض console المتصفح هذه الاختصارات قبل تنقل المتصفح أو معالجة القوائم.

## الإعدادات

| مفتاح YAML | متغير البيئة | الافتراضي | الغرض |
|---|---|---|---|
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `true` | تركيب واجهات المستخدم أو تعطيلها. |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `/ui` | مسار تركيب واجهة المتصفح على خدمة MCP. |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | auto | تجاوز آلية تحديد ملف OpenTUI التنفيذي الأصلي. |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `bing` | إعداد الخلفية المحتفظ به لنشر console OpenTUI في المتصفح. |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | إغلاق PTY لـ OpenTUI في المتصفح بعد هذه الثواني من الخمول؛ `0` يعطّل المهلة. |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | الحد الأقصى لجلسات PTY المتزامنة لـ OpenTUI في المتصفح. |

## ملاحظات الحزم

- تتضمن صور Docker موارد Web UI وruntime الأصلي لـ OpenTUI.
- تضمّن الملفات التنفيذية المستقلة موارد Web UI وruntime مضغوطًا لـ OpenTUI خاصًا بالمنصة.
- تتضمن Python wheels موارد المتصفح؛ ويتطلب OpenTUI الأصلي ملف release تنفيذيًا أو source checkout مع تثبيت تبعيات Bun.
- تُقدَّم الواجهتان من العملية والمنفذ نفسيهما المستخدمين في MCP؛ ولا يلزم تشغيل خدمة ويب إضافية.
