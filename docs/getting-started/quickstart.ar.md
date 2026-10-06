<!-- i18n-source-sha256: 51bfe29de540492ab1da2df9479464641bb335796b0538357235fac5b4a2e446 -->
# البدء السريع

يستخدم هذا الدليل Docker Compose كأول runtime وChatGPT كأول client. وهما خياران مستقلان: Docker وVS Code extension وbinary وPython وstdio خيارات runtime؛ وChatGPT وعملاء MCP العامون خيارات client. راجع [خيارات runtime ونموذج النشر](../guides/deployment.md) لرؤية الخريطة الكاملة.

## المتطلبات

- Docker Engine مع Compose v2.
- HTTPS endpoint عام إذا كان ChatGPT سيتصل من الويب.
- دليل workspace مخصص.
- OAuth admin PIN وJWT secret طويلان وعشوائيان.

!!! warning
    يمكن للنموذج المتصل تشغيل الـ workspace المضبوط. شغّل الخدمة داخل container أو VM قابل للتخلص منه وتجنب mount موارد التحكم في host.

## 1. الاستنساخ والإعداد

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python -c 'from pathlib import Path; import secrets; p=Path(".env"); s=p.read_text(); p.write_text(s.replace("LOCAL_SHELL_MCP_UI_LOCAL_TOKEN=", "LOCAL_SHELL_MCP_UI_LOCAL_TOKEN=" + secrets.token_urlsafe(48), 1))'
chmod 600 .env
```

عدّل `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
CLOUDFLARE_TUNNEL_TOKEN=
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

لاستخدام Cloudflare Tunnel sidecar:

```bash
docker compose --profile tunnel up -d
```

في Cloudflare Zero Trust وجّه public hostname إلى:

```text
http://local-shell-mcp:8765
```

مع Caddy أو Nginx أو Traefik أو Nginx Proxy Manager أو أي reverse proxy آخر، مرّر HTTPS traffic إلى `127.0.0.1:8765` أو عنوان شبكة الـ container.

## 4. توصيل ChatGPT

استخدم MCP endpoint التالي:

```text
https://your-public-host.example.com/mcp
```

اتبع [دليل موصل ChatGPT](chatgpt-connector.md) لإكمال OAuth والموافقة على الأدوات.

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
| إضافة ChatGPT كـ client | [ChatGPT connector](chatgpt-connector.md) |
| اختيار الأدوات وكتابة prompts أفضل | [أنماط الاستخدام](../guides/usage-patterns.md) |
| توصيل جهاز HPC أو NPU/GPU أو NAT | [Workers البعيدة](../guides/remote-workers.md) |
| فهم جميع أدوات MCP | [مرجع الأدوات](../reference/tools.md) |
