<!-- i18n-source-sha256: 276e9356b895a85759d31467512bdc530c9baa216a368df4ef1bccce39530d0e -->
<div class="hero-shell" markdown>
<span class="hero-eyebrow">مساحة عمل الذكاء الاصطناعي ذاتية الاستضافة · طائرة التحكم MCP</span>

# local-shell-mcp

الدردشة والمشاريع والملفات والمحطات الطرفية والأجهزة البعيدة وأدوات الذكاء الاصطناعي في واجهة واحدة مستضافة ذاتيًا. قم بتوصيل عملاء MCP الخارجيين عندما تحتاج إليهم.

<div class="hero-actions" markdown>
[ابدأ](getting-started/quickstart.md){ .hero-action .hero-action--primary }
[Web workspace](getting-started/web-workspace.md){ .hero-action .hero-action--secondary }
[مرجع الأدوات](reference/tools.md){ .hero-action .hero-action--secondary }
</div>
</div>

<div class="feature-grid" markdown>
<div class="feature-card" markdown>
### بيئة برمجة حقيقية
شغّل الاختبارات وافحص repositories وعدّل الملفات واستخدم Git واحتفظ بـ audit trail عبر MCP endpoint واحد.
</div>

<div class="feature-card" markdown>
### مساحة عمل الويب الموحدة
استخدم سجل الدردشة والمشروع المدمج إلى جانب ملفات وحدة التحكم والمحطات الطرفية وسطح المكتب والجلسات وأجهزة التحكم عن بعد والتدقيق. يظل عملاء MCP الخارجيون اختياريين.
</div>

<div class="feature-card" markdown>
### التحكم في الأجهزة البعيدة
أرفق أجهزة خلف NAT أو firewall أو HPC عبر اتصالات worker صادرة دون فتح منافذ SSH.
</div>
</div>

## ما الذي يقدمه

يوفر `local-shell-mcp` مساحة عمل AI موحدة ذاتية الاستضافة وخادم MCP للعملاء الخارجيين. إنه يوفر Shell، وShell المستمر، ونظام الملفات، والبحث، والتصحيح، وGit، وPlaywright، والتدقيق، وجلسات منطقية متينة مع خطط الأهداف الاختيارية، وارتباط الملفات المميز، وأدوات العمل عن بعد من خلال نقاط نهاية MCP المصادق عليها.

استخدمه عندما يحتاج الذكاء الاصطناعي إلى فحص repository أو تشغيل tests أو تحرير files أو استخدام Git أو جمع browser evidence أو إنتاج downloadable artifacts أو التحكم في remote machine لا تستطيع سوى الاتصال الصادر إلى control server.

## البنية

```text
طبقة Runtime: Docker / VS Code extension / binary / Python / stdio
طبقة Exposure: localhost / HTTPS proxy / tunnel / stdio pipe
طبقة العميل: WebUI / Gemini / ChatGPT / عميل MCP الموحد
Workspace المضبوط: /workspace or configured workspace root
Remote workers اختيارية: outbound machine connections
```

حد العزل المقصود هو الـ container أو VM الذي يشغل الخدمة.

## ابدأ حسب السيناريو

| السيناريو | ابدأ هنا | لماذا |
|---|---|---|
| مساحة عمل المتصفح الأساسية | [Unified web workspace](getting-started/web-workspace.md) | صفحات التحكم في الدردشة والمشاريع وLSM مع تسجيل دخول مشترك |
| نشر وحدة التحكم الأولى | [Quickstart](getting-started/quickstart.md) | النشر من المصدر، OAuth وواجهة المتصفح الأولى. |
| اختيار runtime layer | [Runtime choices](guides/deployment.md) | يشرح Docker وVS Code وbinary وPython وstdio كخيارات runtime منفصلة |
| ربط الجوزاء سبارك | [Gemini Custom Apps](getting-started/gemini-spark.md) | الأهلية وعنوان URL الخاص بـ HTTPS MCP وOAuth والاختبار |
| إضافة ChatGPT كـ client | [ChatGPT connector](getting-started/chatgpt-connector.md) | Endpoint وOAuth وأول prompt آمن وtool discovery |
| إضافة LSM إلى DeepSeek Harness | [إضافة DeepSeek Harness](clients/deepseek-harness.md) | تثبيت repository كحزمة DSH مع إبقاء مجموعة أدوات LSM وremote workers كاملة |
| التشغيل من VS Code | [VS Code extension runtime](installation/vscode-extension.md) | Runtime مشغل من editor وملاحظات أمان host |
| تعلم تشغيل toolset | [Usage patterns](guides/usage-patterns.md) | قوالب prompt وإرشادات اختيار الأدوات |
| فهم كل tool | [Tools reference](reference/tools.md) | Purpose وinputs وreturns وcombinations وnotes لكل tool |
| توصيل HPC أو NPU/GPU أو server node | [Remote workers](guides/remote-workers.md) | Outbound worker join flow واستخدام الأدوات البعيدة |
| مشاركة الملفات المولدة | [File links](guides/file-links.md) | روابط download مميزة بـ token مع TTL وإلغاء |
| تقوية deployment | [Security](security.md) | Isolation وOAuth وworkspace scope وaudit logs |

## عائلات الأدوات الرئيسية

| العائلة | أمثلة | الاستخدام |
|---|---|---|
| Shell and Python | `run_shell`, `run_python`, `shell_start` | Builds وtests وscripts والعمليات الطويلة |
| Files and search | `file_tree`, `file_grep`, `file_read`, `file_patch` | فحص repository وتعديلات دقيقة |
| Git | `run_shell`, `run_shell`, `run_shell`, `run_shell` | Workflows source-control قابلة للمراجعة |
| Sessions وGoals | `session_manage`, `plan_manage` | تسليم دائم للمهام وتقارير تقدم وGoal mode اختياري |
| Browser | `browser_session`, `browser_snapshot`, `browser_act`, `browser_run_script` | تفاعل دائم وUI checks وscreenshots وdocs معروضة ونص الصفحة |
| File links | `link_create`, `link_revoke` | تنزيل artefacts مولدة من chat |
| Remote workers | `remote_manage`, `run_shell`, `remote_transfer` | أجهزة خلف NAT أو firewalls أو cluster login flows |

## Workflows نموذجية

### الترميز في مساحة عمل الويب

1. ابدأ تشغيل وحدة تحكم LSM و[unified web workspace](getting-started/web-workspace.md) الاختياري.
2. افتح `/ui` وقم بتسجيل الدخول باستخدام هوية LSM.
3. قم بتكوين نقطة نهاية النموذج وافتح محادثة جديدة.
4. اطلب من النموذج فحص المستودع وتشغيل عمليات التحقق للقراءة فقط أولاً.
5. بعد الموافقة اسمح بتعديل files وتشغيل tests ومراجعة diff وcommit وpush.
6. راجع audit log عندما تتضمن المهمة file links أو أنظمة بعيدة.

### Host بعيد لـ HPC أو accelerator

1. أنشئ remote worker invite لمرة واحدة.
2. الصق command المولد على remote host.
3. استخدم الأدوات العادية مع `machine`؛ Git عبر `run_shell` والنقل عبر `remote_transfer`.
4. ألغِ worker بعد المهمة.

### إنشاء artefacts

1. دع الذكاء الاصطناعي ينشئ file داخل `/workspace`.
2. أنشئ tokenized file link مع TTL/download limits.
3. شارك link في chat.
4. ألغِه عند الانتهاء.

## اللغة

يُبنى هذا الموقع باستخدام MkDocs i18n plugin الأصلي. استخدم language selector في header للتبديل بين English والصفحات المترجمة. الصفحات غير المترجمة fallback إلى English.
