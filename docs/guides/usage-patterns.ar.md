<!-- i18n-source-sha256: 382c9edbbba8fa4fb3aab11dcc4127ba80bff8c7104bdedffdf66b9bbcdb744a -->
# أنماط الاستخدام ودليل كتابة prompts

يعرض `local-shell-mcp` أدوات قوية. تعتمد النتائج الجيدة على طلب الفحص أولًا، والعمل بخطوات صغيرة، وإجراء التحقق، وشرح ما تغيّر.

## حلقة التشغيل العامة

استخدم هذه الحلقة في معظم مهام البرمجة:

1. الفحص: `environment_get` و`file_tree` و`file_grep` و`file_read` و`run_shell` لأوامر مثل `git status`.
2. التخطيط: اطلب من النموذج تحديد أقل مجموعة من الملفات والاختبارات المعنية.
3. التحرير: استخدم `file_edit` أو `file_patch` أو أوامر shell.
4. التحقق: شغّل الاختبارات أو builds المستهدفة باستخدام `run_shell` أو shells دائمة.
5. المراجعة: شغّل `git diff` عبر `run_shell`، ثم استخدم `secret_scan` و`audit_tail` عند الحاجة.
6. Commit/export: استخدم أوامر Git CLI صريحة عبر `run_shell` أو `link_create`.

## اختيار الأداة

| المهمة | يفضّل | تجنّب |
|---|---|---|
| أمر one-shot قصير | `run_shell` | بدء shell دائم لكل أمر |
| Dev server أو REPL أو watch task طويل | `shell_start` + `shell_read` + `shell_send` | حجب `run_shell` حتى timeout |
| تحليل منظم أو إنشاء ملفات | `run_python` | Shell pipelines هشة لمعالجة JSON/text معقد |
| تعديل exact صغير | `file_edit` | إعادة كتابة ملف كامل دون حاجة |
| استبدال واحد أو عدة استبدالات في ملف | `file_edit` with an `edits` array | تكرار edits قديمة دون إعادة القراءة |
| Patch لعدة ملفات | `file_patch` | تعديلات shell مرتجلة |
| العثور على الملفات | `file_tree`, `file_glob` | قوائم recursive كاملة لمستودعات كبيرة |
| العثور على code | `file_grep` | قراءة ملفات كثيرة بلا هدف |
| أدلة من المتصفح | `browser_snapshot`, `browser_run_script` | التخمين من أسماء الصفحات أو routes |
| Artefacts قابلة للتنزيل | `link_create` | لصق محتوى binary كبير في chat |
| العمل على جهاز بعيد | normal tools with `machine`, plus `remote_transfer` | فتح inbound SSH عندما يكفي outbound worker |

## استدعاء الأدوات من CLI

بالنسبة إلى سكربتات shell وعمليات CI، يستدعي `lsm call <tool>` مجموعة الأدوات المسجلة نفسها عبر loopback controller الجاري تشغيله، لذلك تبقى حالة remote workers وcontroller محفوظة.

```bash
lsm call run_shell --json '{"command":"uname -a"}'
printf '%s\n' '{"path":"README.md"}' | lsm call file_read
```

استخدم `--session s_...` لربط الاستدعاء بـ Logical Session. في إعداد Docker Compose الموثق يبقى `LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN` الخام فقط في ملف `.env` المملوك للمضيف والمقيد الصلاحيات، بينما يمرر Compose إلى controller قيمة التحقق SHA-256 فقط؛ ويمكن لتخطيطات runtime المنفصلة الأخرى استخدام `--token-file <path>`. الخيار `--direct` يتجاوز controller ويطبق إعدادات runtime من `.env` الحالي داخل العملية، ولا يحقن host CLI token في بيئة الأداة، ويعمل محليًا فقط. لا يُقبل Human UI token مطلقًا على `/mcp`؛ ويجب على controller في إعدادات runtime المنفصلة ضبط `LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN_SHA256` المطابق.

## قوالب prompt

### استكشاف repository للقراءة فقط

```text
استخدم local-shell-mcp. افحص layout الـ repository وgit status. لا تعدّل الملفات. لخّص المكونات الرئيسية وأوامر الاختبار التي يمكن استنتاجها وأي مخاطر واضحة قبل إجراء تغييرات.
```

### إصلاح bug محدد

```text
استخدم local-shell-mcp لإصلاح bug. أعد إنتاجه أو حدّد موقعه أولًا بأصغر أمر ذي صلة. اقرأ الملفات قبل التحرير. أنشئ patch صغيرًا، وشغّل التحقق المستهدف، ثم اعرض git diff والاختبارات التي شُغلت بالتحديد. لا تنشئ commit حتى أوافق.
```

### Workflow للـ commit وpush

```text
استخدم local-shell-mcp. افحص git status وdiff، وشغّل الاختبارات المناسبة وsecret_scan، وأنشئ commit واحدًا مركزًا برسالة موجزة، ثم push للفرع الحالي. لا تضمّن caches أو build artifacts أو formatting غير مرتبط.
```

### عملية طويلة

```text
شغّل dev server في persistent shell session، واقرأ output حتى يصبح ready، ثم استخدم browser tools للتحقق من الصفحة. احتفظ بـ session id وأنهِ الجلسة بعد التحقق.
```

### مهمة Remote worker

```text
استخدم remote worker المتصل المسمى <machine>. استدعِ environment_get أولًا مع machine=<machine>، ثم file_list مع machine نفسها. اعمل فقط داخل remote workdir المضبوط. استخدم run_shell للأوامر القصيرة وshell_start أو job_start للعمل الطويل.
```

## العمل مع repositories

التسلسل الموصى به لتغييرات open-source:

1. شغّل `git status --short --branch` عبر `run_shell`.
2. استخدم أوامر Git CLI صريحة لـ fetch وفحص branches عندما تكون حالة upstream مهمة.
3. استخدم `file_grep` و`file_read` قبل التحرير.
4. أنشئ patch صغيرًا.
5. شغّل الاختبارات المستهدفة أولًا، ثم الاختبارات الأوسع عندما يكون ذلك عمليًا.
6. شغّل `secret_scan` قبل commit أو push.
7. نفّذ stage وcommit صريحين برسالة موجزة.

اطلب commit واحدًا لكل تغيير منطقي عندما يحتاج maintainers إلى تاريخ سهل المراجعة.

## العمل مع artefacts المُنشأة

بالنسبة إلى PDF وreports وscreenshots وarchives وlogs:

1. أنشئ الملف داخل workspace.
2. تحقق من وجود الملف وحجمه المتوقع.
3. استخدم `link_create` مع TTL قصير و`max_downloads` اختياري.
4. ألغِ link عندما لا يعود مطلوبًا.

لا تنشئ روابط عامة لمفاتيح خاصة أو directories للcredentials أو بيانات شخصية غير مرتبطة.

## العمل مع الأجهزة البعيدة

يكون Remote worker mode مفيدًا عندما يستطيع الجهاز إجراء طلبات HTTPS صادرة لكنه لا يستطيع قبول SSH وارد.

ممارسات جيدة:

- أنشئ الأجهزة أو أعد تسميتها باستخدام `remote_manage(action="invite", ...)` أو `remote_manage(action="rename", ...)`.
- استدعِ `environment_get(machine=...)` قبل العمل.
- استخدم `remote_transfer` لبدء transfer jobs بين controller/worker أو worker/worker ثم أدِرها بأدوات `job_*` العادية.
- ألغِ workers بعد المهمة باستخدام `remote_manage(action="revoke", ...)`.

## أنماط يجب تجنبها

تجنب هذه التعليمات إلا إذا كانت البيئة disposable وكانت النتائج مفهومة:

- “ثبّت عالميًا أي شيء مطلوب” على server يعمل مباشرة على host.
- “شغّل حتى يعمل” دون حدود زمنية أو معايير تحقق.
- “اعمل commit لكل شيء” في repository يحتوي artefacts مولدة.
- “اعرض home directory بالكامل” للراحة.
- “أنشئ file link للـ workspace بالكامل”.
- تشغيل public deployment مع `LOCAL_SHELL_MCP_AUTH_MODE=none`.
