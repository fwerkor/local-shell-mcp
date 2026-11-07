<!-- i18n-source-sha256: d699e8855ee01b72db68087e8a5d8f3957c702641e7e6956f268604b8b1f9d2b -->
# خيارات Runtime ونموذج النشر

يحتوي `local-shell-mcp` على قرارين متكاملين:

1. **Runtime**: كيفية تشغيل عملية الخادم وما الـ workspace الذي تتحكم فيه.
2. **الواجهة**: استخدم [unified web workspace](../getting-started/web-workspace.md) الاختياري، أو قم بتوصيل عميل MCP خارجي مثل Gemini أو ChatGPT.

الواجهة اليومية الموصى بها هي مساحة عمل الويب المستضافة ذاتيًا (الدردشة والمشاريع وصفحات التحكم في LSM). يتم نشره بشكل منفصل عن وحدة التحكم. يُعد Docker، وملحق VS Code، وثنائيات الإصدار، وعمليات تثبيت Python، ووضع stdio طرقًا لتشغيل وحدة التحكم؛ تظل تطبيقات الدردشة الخارجية عملاء اختياريين.

```text
Runtime layer                      Exposure layer                 Client layer
-------------------------------    ---------------------------    ----------------------
يقوم Docker بإنشاء مساحة عمل ويب موحدة فقط لـ HTTP المحلي
VS Code extension                  HTTPS reverse proxy/tunnel     Generic MCP client
Standalone binary                  stdio process pipe             VS Code extension UI
pipx / source checkout             remote-worker outbound join    REST-style diagnostics
```

الإعداد الشائع للاستضافة الذاتية هو:

```text
المتصفح -> https://chat.example.com (مساحة عمل الويب الموحدة)
        -> وحدة التحكم المحلية Shell-mcp المصادق عليها
        -> مساحة العمل الخاضعة للرقابة والعمال الخارجيين
عميل خارجي اختياري -> https://mcp.example.com/mcp
```

يمكن أن يكون إعداد MCP client محلي أبسط:

```text
Local MCP client
  -> starts local-shell-mcp --mode stdio
  -> controlled workspace
```

**موصى به:** استخدم خادمًا ذا عنوان عام، أو أعد توجيه حركة المرور عبر خادم عام باستخدام وكيل HTTPS عكسي. **غير موصى به:** قد تكون سرعة الرفع من جهة العميل عبر Cloudflare Tunnel بطيئة جدًا، مما يجعل رفع الملفات ونقلها صعب الاستخدام. استخدمه فقط عند تعذّر النشر العام أو التوجيه عبر خادم عام. ([Public HTTPS exposure](../clients/connectivity.md))

## مصفوفة اختيار Runtime

| وقت التشغيل | الأفضل ل | حد العزلة | مصدر سلسلة الأدوات | الوصول الخارجي لـ MCP | الصفحة |
|---|---|---|---|---|---|
| عامل الميناء يؤلف | معظم أعباء عمل وكيل الترميز ومساحات العمل القابلة للتكرار | حاوية | صورة وحدة التحكم الهزيلة؛ تثبيت سلاسل الأدوات الخاصة بالمهمة بشكل منفصل | أضف وكيل أو نفق HTTPS | [Docker Compose](../installation/docker.md) |
| Docker Compose + عربة جانبية للنفق | غير موصى به: إعادة التوجيه عبر خادم عام؛ وCloudflare Tunnel حل أخير | حاوية | صورة المشروع | إعادة التوجيه عبر خادم عام؛ وCloudflare Tunnel حل أخير | [Docker Compose](../installation/docker.md#cloudflare-tunnel-sidecar) |
| VS Code extension | بدء/إيقاف server من editor workspace | عادة process على host | أدوات host مع executable مضبوط | أضف HTTPS tunnel/proxy خارجيًا لـ ChatGPT | [VS Code extension](../installation/vscode-extension.md) |
| Standalone binary | Hosts أو VM بدون Docker | Host or VM | أدوات host مع executable مضبوط | أضف HTTPS proxy أو tunnel | [Standalone binary](../installation/binary.md) |
| `pipx` / source install | استخدام Python-native وdebugging وdevelopment | Host virtualenv or VM | Python package مع أدوات host | أضف HTTPS proxy أو tunnel | [Python install](../installation/python.md) |
| Stdio mode | MCP clients محليون يشغّلون العمليات مباشرة | Client process boundary | أدوات host مع executable مضبوط | غير قابل للاستخدام مع ChatGPT web/app | [Stdio mode](../installation/stdio.md) |

## مصفوفة اتصال Client

| واجهة | يتطلب HTTPS العام | يستخدم `/mcp` | يتطلب OAuth | وقت التشغيل النموذجي |
|---|---:|---:|---:|---|
| مساحة عمل الويب LSM الموحدة | نعم للوصول عن بعد؛ الوكيل المحلي ممكن أيضا | داخليا | تسجيل دخول LSM | وحدة تحكم بالإضافة إلى مكدس ويب منفصل |
| الجوزاء سبارك / تطبيقات مخصصة | نعم | نعم | نعم للاستخدام العام | أي وحدة تحكم HTTP |
| ChatGPT custom MCP connector | نعم | نعم | نعم للاستخدام العام | Docker, VS Code extension, binary, or Python |
| Generic local MCP client over stdio | لا | لا | لا | `local-shell-mcp --mode stdio` |
| Generic HTTP MCP client | غالبًا لا على localhost؛ نعم عبر الشبكات | نعم | موصى به خارج localhost | Any HTTP runtime |
| VS Code extension helper flow | فقط إذا كان ChatGPT سيتصل | نعم عند نسخ ChatGPT URL | موصى به لـ ChatGPT | VS Code-launched runtime |

راجع [unified web workspace](../getting-started/web-workspace.md)، و[Gemini Spark](../getting-started/gemini-spark.md)، و[ChatGPT connector](../getting-started/chatgpt-connector.md)، و[generic MCP clients](../clients/generic-mcp.md)، و[network connectivity](../clients/connectivity.md).

## ما الذي يتحكم فيه كل Runtime

يشغّل كل runtime نفس server code ويعرض عائلات MCP tools نفسها عند تفعيلها:

- Shell وpersistent shell sessions.
- Filesystem وsearch وpatch tools.
- عمليات Git.
- Browser automation عبر Playwright.
- Audit log وtask-state tools.
- Tokenized file links.
- Optional remote-worker lifecycle وmachine-routed tools.

الاختلاف ليس في API المجردة بل في **operating environment** خلفها.

| السؤال | Docker Compose | VS Code extension | Binary / Python |
|---|---|---|---|
| أين تعمل الأوامر؟ | داخل container | عادة في host workspace | في process environment على host أو VM |
| Default workspace؟ | Mounted `/workspace` | مجلد VS Code الحالي أو path مضبوط | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` |
| هل المترجمات والمتصفحات مثبتة مسبقًا؟ | لا؛ تثبيت ما تحتاجه المهمة | فقط إذا تم تثبيته على المضيف | فقط إذا تم تثبيته على المضيف |
| هل reset سهل؟ | أعد إنشاء container وworkspace volume | يعتمد على workspace | يعتمد على host/VM |
| مناسب لتثبيت packages عشوائية؟ | نعم إذا كان disposable | أكثر خطورة على host | أكثر خطورة خارج VM |

## الاختيار الموصى به

استخدم **Docker Compose** أولاً ما لم يكن لديك سبب لعدم القيام بذلك. إنه يوفر حدود أمان واضحة دون الحاجة إلى سلسلة أدوات تطوير كبيرة مثبتة مسبقًا.

استخدم **ملحق VS Code** عندما يبدأ سير العمل من محرر وتريد مشغلًا محليًا. لا يزال وقت التشغيل. يحتاج عملاء الويب عن بعد إلى وكيل HTTPS أو نفق يمكن الوصول إليه.

استخدم **standalone binary** عندما لا يتوفر Docker لكن VM أو container host أو dedicated user account يوفر boundary بالفعل.

استخدم **`pipx` أو source install** لتطوير/debugging `local-shell-mcp` نفسه أو عندما تكون بيئة Python أسهل في الإدارة.

استخدم **stdio mode** فقط مع MCP clients محليين يمكنهم spawn server process. فهو ليس public deployment ولا يستخدم مباشرة من ChatGPT web/app.

## قاعدة Public endpoint

بالنسبة لعملاء HTTP MCP الخارجيين مثل Gemini وChatGPT، فإن نقطة نهاية MCP هي:

```text
https://your-public-host.example.com/mcp
```

`LOCAL_SHELL_MCP_PUBLIC_BASE_URL` هو origin فقط:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

لا تضف `/mcp` إلى `LOCAL_SHELL_MCP_PUBLIC_BASE_URL`.

## صفحات Runtime

- [Docker Compose](../installation/docker.md)
- [VS Code extension](../installation/vscode-extension.md)
- [Standalone binary](../installation/binary.md)
- [Python, `pipx`, and source install](../installation/python.md)
- [Stdio mode](../installation/stdio.md)

## صفحات Client

- [Unified web workspace](../getting-started/web-workspace.md)
- [Gemini Spark / Custom Apps](../getting-started/gemini-spark.md)
- [ChatGPT connector](../getting-started/chatgpt-connector.md)
- [Generic MCP clients](../clients/generic-mcp.md)
- [Public HTTPS exposure](../clients/connectivity.md)
