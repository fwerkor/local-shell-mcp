<!-- i18n-source-sha256: b6bf2276867332a25b6e63b3b4cf21045262a9a9535422c02722906d87a2132a -->
# البدء السريع

يبدأ هذا الدليل تشغيل وحدة تحكم LSM ويفتح واجهة المتصفح الخاصة بها. [unified web workspace](web-workspace.md) هي التجربة اليومية الموصى بها؛ إنها عبارة عن مكدس دردشة اختياري تم نشره بشكل منفصل. يمكن لعملاء ChatGPT وGemini وعملاء MCP الخارجيين الآخرين الاتصال بنفس وحدة التحكم. انظر [runtime choices and deployment model](../guides/deployment.md).

نوصي **بملف Controller تنفيذي واحد** من [GitHub Releases](https://github.com/fwerkor/local-shell-mcp/releases/latest)، دون Python أو Docker أو نسخة مصدر. المثال خاص بـ **Linux x86_64**؛ للأنظمة الأخرى انظر [دليل الملف التنفيذي](../installation/binary.md).

## المتطلبات

- الملف التنفيذي المتوافق و`curl` (مثال Linux x86_64).
- HTTPS عام فقط عند وصول مستخدمين عن بُعد أو عملاء MCP خارجيين.
- مجلد عمل منفصل بصلاحيات محدودة.
- PIN قوي لمسؤول OAuth وسر JWT عشوائي.

!!! warning
    يمكن للنموذج المتصل تشغيل الـ workspace المضبوط. شغّل الخدمة داخل container أو VM قابل للتخلص منه وتجنب mount موارد التحكم في host.

## 1. تنزيل الملف التنفيذي وإعداده

نزّل الملف التنفيذي الواحد وأنشئ سر JWT:

```bash
mkdir -p ~/lsm && cd ~/lsm
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp
chmod +x local-shell-mcp
./local-shell-mcp --help
openssl rand -hex 32
```

أنشئ `.env` وغيّر PIN وسر JWT الافتراضيين (باستخدام `openssl rand -hex 32`). الملف التنفيذي **لا يحمّل** `.env` تلقائياً.

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. تشغيل الخادم

شغّل الملف التنفيذي مباشرة:

```bash
chmod 600 .env
set -a
. ./.env
set +a
mkdir -p workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspace"
./local-shell-mcp --mode mcp
```

تحقق من الحالة في طرفية أخرى:

```bash
curl -i http://127.0.0.1:8765/healthz
```

الاستجابة الصحيحة HTTP `200`. استخدم مدير خدمات وحساباً محدود الصلاحيات للتشغيل الدائم.

## 3. إتاحة HTTPS

للوصول البعيد، استخدم خادماً عاماً أو وكيلاً عكسياً HTTPS مثل Caddy أو Nginx أو Traefik، مع تمرير الموقع كاملاً بما فيه الملفات إلى:

```text
http://127.0.0.1:8765
```

تحقق من HTTPS:

```bash
curl -i https://your-public-host.example.com/healthz
```

**لا يُنصح باستخدام Cloudflare Tunnel** لنقل الملفات لأن الرفع من العميل قد يكون بطيئاً. يُفضّل خادم عام أو وكيل عكسي/تحويل منافذ مع إبقاء OAuth مفعّلاً. البديل: [Docker](../installation/docker.md).

## 4. افتح مساحة عمل المتصفح

افتح تسجيل دخول وحدة التحكم:

```text
https://your-public-host.example.com/ui
```

للدردشة والمشاريع وصفحات التحكم المتكاملة اتبع [unified web workspace guide](web-workspace.md). تتوفر واجهة WebUI الأصلية خفيفة الوزن عند عدم تثبيت الدردشة.

## 5. تأكيد الوصول إلى الأدوات بأمان

اطلب من النموذج:

```text
استخدم local-shell-mcp. استدعِ environment_get أولًا، ثم اعرض جذر workspace. لا تعدّل الملفات بعد.
```

أدوات read-only المتوقعة:

- `environment_get`
- `file_list`
- `file_tree`
- `file_read`

## 6. البدء بمهمة برمجية محدودة

مثال جيد لأول مهمة:

```text
افحص هذا repository، ولخّص تخطيط المشروع، وشغّل مجموعة الاختبارات الحالية إذا كانت واضحة، ولا تغيّر الملفات.
```

بعد تأكيد الاتصال، أعط تعليمات أكثر تحديدًا:

```text
أصلح الاختبار الفاشل. اقرأ الملفات ذات الصلة أولًا، وأنشئ أصغر patch ممكن، وشغّل الاختبار المستهدف، ثم اعرض git diff. لا تنشئ commit حتى أوافق.
```

## التحديث

استبدل الملف التنفيذي ثم أعد تشغيل Controller:

```bash
# Stop the running Controller before replacing the executable.
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp.new
chmod +x local-shell-mcp.new
./local-shell-mcp.new --version
mv local-shell-mcp.new local-shell-mcp
# Restart the Controller process or service.
curl -i http://127.0.0.1:8765/healthz
```

لـ Docker Compose حدّث الحاوية؛ تثبيت المصدر: [Python](../installation/python.md).

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

## الصفحات التالية

| الحاجة | الصفحة |
|---|---|
| فهم خيارات runtime وclient | [خيارات runtime ونموذج النشر](../guides/deployment.md) |
| التشغيل باستخدام Docker Compose | [Docker Compose runtime](../installation/docker.md) |
| التشغيل من VS Code | [VS Code extension runtime](../installation/vscode-extension.md) |
| التشغيل باستخدام release binary | [Runtime binary مستقل](../installation/binary.md) |
| التشغيل باستخدام Python أو source checkout | [Python runtimes](../installation/python.md) |
| استخدم واجهة الدردشة والتحكم الموحدة | [Unified web workspace](web-workspace.md) |
| أضف الجوزاء سبارك كعميل | [Gemini Custom Apps](gemini-spark.md) |
| إضافة ChatGPT كـ client | [ChatGPT connector](chatgpt-connector.md) |
| اختيار الأدوات وكتابة prompts أفضل | [أنماط الاستخدام](../guides/usage-patterns.md) |
| توصيل جهاز HPC أو NPU/GPU أو NAT | [Workers البعيدة](../guides/remote-workers.md) |
| فهم جميع أدوات MCP | [مرجع الأدوات](../reference/tools.md) |
