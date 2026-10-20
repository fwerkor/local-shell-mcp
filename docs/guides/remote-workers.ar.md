<!-- i18n-source-sha256: d3c380d9a5d9a43019b0be2b5e9accc0d6e0c785d77226005db60c5721672ba6 -->
# Workers بعيدة

تسمح remote workers لـ `local-shell-mcp` بالتحكم في أجهزة تستطيع إرسال طلبات HTTP(S) صادرة لكنها لا تستطيع قبول اتصالات SSH واردة.

```text
MCP client -> control server -> outbound polling worker -> remote machine
```

## workflow أساسي

1. أنشئ دعوة باستخدام `remote_manage(action="invite", ...)`.
2. شغّل الأمر المُنشأ على الجهاز البعيد.
3. أكد التسجيل باستخدام `remote_manage(action="list")`.
4. استدعِ الأدوات العادية مع `machine="<worker-name>"`، مثل `environment_get` أو `run_shell` أو `file_read` أو `browser_run_script`.
5. استخدم `remote_transfer` لبدء نقل متتبع controller-to-worker أو worker-to-controller أو worker-to-worker لملف أو مجلد. تابعه عبر `job_list` أو `job_tail`، وأوقفه أو أعده عبر `job_stop` أو `job_retry`.
6. أعد تسمية workers أو ألغها عبر `remote_manage(action="rename", ...)` أو `remote_manage(action="revoke", ...)`.

إدارة workers فقط تستخدم أسماء `remote_*`. عمليات execution وshell وjob وfilesystem وpatch وbrowser تشترك في الـ schema نفسها محلياً وعن بُعد. تحديد machine يتطلب أيضاً OAuth scope ‏`remote:use`.

## Workers دائمة

تحتوي نتيجة الدعوة على أوامر خاصة بكل منصة:

- `persistent_command` يثبت ويشغّل user service على Linux أو macOS.
- `powershell_persistent_command` يثبت ويشغّل Windows user task من PowerShell.

على Windows، يسجل `local-shell-mcp worker install-service` المهمة `local-shell-mcp-worker` للمستخدم الحالي. تبدأ فوراً، وتبدأ مجدداً عند دخول ذلك المستخدم بعد reboot، وتسمح بالعمل على البطارية، وتتجاهل التشغيل المكرر، وتعيد محاولة التشغيل الفاشل. لا تحتاج صلاحيات administrator ولا تعمل قبل تسجيل دخول المستخدم.

استخدم أوامر lifecycle نفسها على جميع المنصات:

```text
local-shell-mcp worker status
local-shell-mcp worker start
local-shell-mcp worker stop
local-shell-mcp worker restart
local-shell-mcp worker uninstall-service
```

يُحفظ worker log في worker state directory باسم `worker.log`.

## القدرات

تدعم workers جلسات shell/persistent shell، وtracked jobs، وعمليات filesystem، وtransfer internals، وتنفيذ Python، وpatches، وPlaywright حيث تكون التبعيات مثبتة. يستخدم Git أوامر قياسية عبر `run_shell(machine=...)`.

## الأمان والإصدارات

يعطي worker المنضم MCP client تحكماً في بيئته المهيأة. استخدم invite TTLs قصيرة، وwork directories أو حسابات مخصصة، وراجع audit logs، وألغ workers بعد انتهاء المهمة. تثبت الدعوة المُنشأة worker code يطابق إصدار control server.

## استكشاف الأخطاء

إذا لم يظهر worker، فتحقق من وصول HTTPS الصادر، وإمكانية الوصول إلى public base URL، وانتهاء الدعوة، ووقت النظام، وlogs الخاصة بـ control server.
