<!-- i18n-source-sha256: 521e0f39c8823597b1468b2d63af978794cb28fda8c8e60230da0a96cff2d5c2 -->
# مساحة عمل الويب الموحدة

**مساحة عمل ويب LSM الموحدة** هي الطريقة الموصى بها لاستخدام local-shell-mcp يومًا بعد يوم. فهو يجمع بين دردشة الذكاء الاصطناعي وسجل المشروع ومستوى التحكم LSM في واجهة واحدة سريعة الاستجابة، استنادًا إلى واجهة LibreChat الأمامية المعدلة والمقدمة من البائع. لا يزال بإمكانك توصيل عملاء MCP الخارجيين مثل [ChatGPT](chatgpt-connector.md) أو [Gemini](gemini-spark.md).

مساحة العمل ** مستضافة ذاتيًا واختيارية للتثبيت **: إنها خدمة ويب منفصلة، ​​وليست جزءًا من الحد الأدنى من صورة وحدة التحكم، أو حزمة العامل المستقلة القابلة للتنفيذ أو البعيدة. تحتفظ عمليات النشر لوحدة التحكم فقط بواجهة مستخدم المتصفح الأصلية وOpenTUI.

## ماذا يوجد في مساحة العمل؟

| المنطقة | ما يمكنك القيام به |
|---|---|
| الدردشة والمشاريع | اختر نموذجًا تم تكوينه، وقم بإنشاء المحادثات، وتنظيم المشاريع، والعثور على الدردشات السابقة وأرشفة المحادثات. يبقى التاريخ على الخادم. |
| نظرة عامة على وحدة التحكم | عرض الحالة الصحية والنشاط الأخير والأجهزة المتصلة. |
| ملفات | تصفح وإدارة الملفات المحلية أو البعيدة. |
| المحطات | العمل مع المحطات الطرفية المستمرة على وحدة التحكم أو العمال. |
| سطح المكتب | فحص ومراقبة جلسات واجهة المستخدم الرسومية عن بعد. |
| الجلسات | فحص مهام LSM الدائمة ودورة حياتها. |
| أجهزة التحكم عن بعد | ربط وإدارة العمال الخارجيين. |
| التدقيق | فحص نشاط الأداة التي تم إنشاؤها بواسطة النموذج. |
| متداخل MCP | تسجيل وتحرير وتمكين وتعطيل وتحديث وإزالة خوادم MCP الخارجية خلف LSM. |

مسارات وحدة التحكم هي `/control/overview`، و`/control/files`، و`/control/terminals`، و`/control/desktop`، و`/control/sessions`، و`/control/remotes`، و`/control/audit`. يتم فتح الدردشة على `/c/new`. يتحكم مدير LSM MCP في **سجل MCP المتداخل الخاص بـ LSM**؛ ولا يقوم بإنشاء تسجيل ثانٍ في LibreChat.

## قم بنشر مكدس الدردشة الاختياري

1. [Install and start an LSM Controller](quickstart.md) with SQLite (now the default). On startup, durable historical state is imported automatically, retaining the original files for rollback.
2. Configure one HTTP/HTTPS Controller origin, for example `https://lsm.example.org`. Chat, terminals, files and remote controls share the same Python server and authentication.
3. To override the defaults, configure the Controller service environment:

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

4. Start the Controller from its Python package or standalone executable:

```sh
local-shell-mcp --mode mcp
```

5. The original React client is maintained in `ui/workspace/`. Bun is only required for building and releases; consult the [first-party WebUI build and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

Node.js, MongoDB, Meilisearch and the separate LibreChat Compose stack are no longer required at runtime. Workers remain ordinary Python packages.

**Migration status:** The Python Agent generation engine, SSE resume and tool approvals are still being ported. Do not deploy the draft branch as a replacement for a working production Controller.

## تسجيل الدخول واستخدام الدردشة

1. Open the LSM Controller `/ui` entrypoint and authenticate with its existing PIN or OAuth credentials. React and Controller APIs share this identity.
2. Configure an available model endpoint/API credential in LSM. The Python Agent provider engine is being migrated; the draft branch does not yet provide complete generation support.
3. Start a conversation after the Python Agent endpoints and SSE protocol pass the acceptance suite. Nested MCP, LSM tools and file uploads follow existing Controller permissions.
4. Start with a read-only request: “Check Controller status and list the workspace root. Do not modify files.”
5. Navigate to **Files**, **Terminals**, **Desktop**, **Sessions**, **Remotes** or **Audit** for direct inspection and control.

يتم تخزين تحميلات الدردشة (ما يصل إلى 32 ميجابايت) ضمن مساحة عمل وحدة التحكم ويتم توفير مساراتها المطلقة للنموذج. لا تمنح عمليات تحميل المتصفح أذونات إضافية للملفات. تمر استدعاءات الأداة التي تواجه النموذج من خلال ترخيص LSM والتدقيق وجهاز توجيه العامل عن بعد.

## MCP الخارجي والأمن والبيانات

استخدم الشريط الجانبي لمساحة العمل MCP لإدارة خوادم MCP الخارجية المتداخلة. وهذا يدعم خوادم stdio المحلية وخوادم HTTP، بما في ذلك متغيرات البيئة الخاصة المنفصلة ورؤوس الطلبات. لا يتم إرجاع الأسرار إلى المتصفح. يتيح تبديل الدردشة **External MCP** إمكانية البحث عن الأدوات المتداخلة وفحصها واستدعاءها؛ ولا يمنح النموذج `mcp_manage` عند تعطيل أدوات LSM الأصلية. إدارة واجهة المستخدم محمية بترخيص وحدة التحكم العادي.

Chats, projects, Agents, sessions, audits and Worker metadata share `.local-shell-mcp/lsm.sqlite3`; SQLite FTS5 provides local search. Non-database artifacts remain under `.local-shell-mcp/`.

The workspace is a first-party React application, not an iframe or separately hosted Web service. Python Workers and external MCP clients remain compatible.

## استكشاف الأخطاء وإصلاحها

- **Unable to start the WebUI:** check the Controller Python logs, SQLite initialization and bundled frontend archive. `LOCAL_SHELL_MCP_STATE_BACKEND=file` is an emergency storage recovery option.
- **Authentication fails:** use the existing Controller PIN/OAuth login. The React UI does not require a separate LibreChat account or bridge secret.
- **Chat loads but cannot answer:** the Python Agent generation and SSE port is still incomplete in this draft branch; do not deploy it to production.
- **Missing MCP tools:** check Controller authorization and the nested MCP registry; never expose `mcp_manage` to external-only model tools.
- **Files or sessions appear empty:** verify the Controller workspace, SQLite migration and authorized principal in its logs.

للحصول على تفاصيل التنفيذ والتحديثات، راجع [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md) و[human interface guide](../guides/human-interface.md).
