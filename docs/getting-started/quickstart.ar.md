<!-- i18n-source-sha256: a9820f08198cf8e823f59550928c07346f9669f2dbec46d3b8cd523c34034e01 -->
# البدء السريع

يبدأ هذا الدليل تشغيل وحدة تحكم LSM ويفتح واجهة المتصفح الخاصة بها. [unified web workspace](web-workspace.md) هي التجربة اليومية الموصى بها؛ إنها عبارة عن مكدس دردشة اختياري تم نشره بشكل منفصل. يمكن لعملاء ChatGPT وGemini وعملاء MCP الخارجيين الآخرين الاتصال بنفس وحدة التحكم. انظر [runtime choices and deployment model](../guides/deployment.md).

## المتطلبات

- Docker Engine مع Compose v2.
- نقطة نهاية HTTPS عامة إذا كان يجب على المستخدمين البعيدين أو عملاء MCP الخارجيين الاتصال.
- دليل workspace مخصص.
- OAuth admin PIN وJWT secret طويلان وعشوائيان.

!!! warning
    يمكن للنموذج المتصل تشغيل الـ workspace المضبوط. شغّل الخدمة داخل container أو VM قابل للتخلص منه وتجنب mount موارد التحكم في host.

## 1. الاستنساخ والإعداد

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python scripts/init_compose_env.py
```

عدّل `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. تشغيل الخادم

```bash
mkdir -p workspaces/default
docker compose up -d
```

تحقق من الحالة:

```bash
docker compose ps
docker compose logs --tail=100 local-shell-mcp
curl -i http://127.0.0.1:8765/healthz
```

تعيد الاستجابة السليمة HTTP `200`.

## 3. إتاحة HTTPS

**موصى به:** استخدم خادمًا ذا عنوان عام، أو أعد توجيه حركة المرور عبر خادم عام باستخدام وكيل HTTPS عكسي.

**غير موصى به:** قد تكون سرعة الرفع من جهة العميل عبر Cloudflare Tunnel بطيئة جدًا، مما يجعل رفع الملفات ونقلها صعب الاستخدام. استخدمه فقط عند تعذّر النشر العام أو التوجيه عبر خادم عام. Configure `CLOUDFLARE_TUNNEL_TOKEN` in `.env` only when choosing the optional tunnel sidecar.

لاستخدام Cloudflare Tunnel sidecar:

```bash
docker compose --profile tunnel up -d
```

في Cloudflare Zero Trust وجّه public hostname إلى:

```text
http://local-shell-mcp:8765
```

مع Caddy أو Nginx أو Traefik أو Nginx Proxy Manager أو أي reverse proxy آخر، مرّر HTTPS traffic إلى `127.0.0.1:8765` أو عنوان شبكة الـ container.

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

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

إذا كنت تستخدم profile tunnel:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
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
