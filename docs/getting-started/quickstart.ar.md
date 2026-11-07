<!-- i18n-source-sha256: 3575b9b50708261678473f74b66076f0c14807ccd7f7c3e60b4d1e897ac778df -->
# البدء السريع

يبدأ هذا الدليل تشغيل وحدة تحكم LSM ويفتح واجهة المتصفح الخاصة بها. [unified web workspace](web-workspace.md) هي التجربة اليومية الموصى بها؛ إنها عبارة عن مكدس دردشة اختياري تم نشره بشكل منفصل. يمكن لعملاء ChatGPT وGemini وعملاء MCP الخارجيين الآخرين الاتصال بنفس وحدة التحكم. انظر [runtime choices and deployment model](../guides/deployment.md).

الطريقة الموصى بها هي **النشر المباشر من الشيفرة المصدرية** في بيئة معزولة؛ Docker Compose خيار بديل.

## المتطلبات

- Git وPython 3.11+ مع `venv` و`pip`.
- عنوان HTTPS عام فقط عند الحاجة إلى وصول عن بُعد أو عملاء MCP خارجيين.
- مجلد عمل مخصص بصلاحيات محدودة.
- رمز PIN قوي لمسؤول OAuth وسر JWT عشوائي.

!!! warning
    يمكن للنموذج المتصل تشغيل الـ workspace المضبوط. شغّل الخدمة داخل container أو VM قابل للتخلص منه وتجنب mount موارد التحكم في host.

## 1. الاستنساخ والإعداد

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
cp .env.example .env
chmod 600 .env
openssl rand -hex 32
```

عدّل `.env` واستبدل PIN وسر JWT الافتراضيين (استخدم `openssl rand -hex 32`). التشغيل من المصدر لا يحمّل `.env` تلقائياً.

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. تشغيل الخادم

```bash
mkdir -p workspaces/default
set -a
. ./.env
set +a
. .venv/bin/activate
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspaces/default"
local-shell-mcp --mode mcp
```

تحقق من الحالة في طرفية ثانية:

```bash
curl -i http://127.0.0.1:8765/healthz
```

الاستجابة السليمة هي HTTP `200`. استخدم مدير خدمات للتشغيل المستمر.

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

حدّث المصدر وأعد تثبيت الحزمة ثم أعد تشغيل Controller:

```bash
git pull --ff-only
python -m pip install -e .
# Restart the Controller process or service after updating.
curl -i http://127.0.0.1:8765/healthz
```

لنشر Docker Compose، حدّث الحاويات بدلاً من ذلك:

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
