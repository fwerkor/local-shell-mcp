<!-- i18n-source-sha256: e2dd23efea9768d971fa8a8be723f55cfcac3279adfc82e4185a803e3f05de1e -->
# Runtime عبر Docker Compose

Docker Compose هو runtime الموصى به لمعظم المستخدمين. يمنح النموذج workspace Linux مضبوطًا وtoolchain قابلًا لإعادة الإنتاج وcredentials دائمة ودعم browser automation ومسار upgrade سهلًا.

هذا اختيار runtime. يمكن وصله بـ ChatGPT أو MCP client عام عبر HTTP أو إبقاؤه محليًا للاختبار.

## ما الذي تتضمنه Docker image

تعتمد image على Playwright Python image وتثبّت development toolchain واسعًا. الهدف أن يتمكن AI coding agent من العمل على repositories كثيرة دون إعادة بناء runtime لكل project.

الفئات المتضمنة:

| الفئة | أمثلة |
|---|---|
| Shell والفحص | Bash, curl, wget, jq, ripgrep, tree, tmux, patch, file |
| Git وcredentials | Git, GitHub CLI, OpenSSH client, credential persistence volume |
| C/C++ build | build-essential, clang, cmake, ninja, autoconf, automake, gdb, lldb |
| Python | Python, pip, venv, pipx, package development dependencies |
| JavaScript/TypeScript | Node.js, npm, yarn, pnpm, TypeScript, ts-node |
| لغات أخرى | Go, Rust, Java, Ruby, PHP, Perl, Lua, R |
| Browser automation | Playwright browsers and browser dependencies |
| Document tooling | LibreOffice, Pandoc, Poppler utilities, OCR tooling |

يجب اعتبار محتوى image الدقيق convenience layer وليس stable API. تبقى project-specific dependencies داخل workspace أو project build scripts.

## تشغيل محلي أساسي

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python -c 'from pathlib import Path; import secrets; p=Path(".env"); s=p.read_text(); p.write_text(s.replace("LOCAL_SHELL_MCP_UI_LOCAL_TOKEN=", "LOCAL_SHELL_MCP_UI_LOCAL_TOKEN=" + secrets.token_urlsafe(48), 1))'
chmod 600 .env
mkdir -p workspaces/default
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

يبقى الـ token المحلي المُنشأ داخل ملف `.env` المملوك للمضيف (بالصلاحية `0600`) ويمرره Compose إلى الحاوية. وبذلك يستطيع `lsm call` على المضيف المصادقة مع loopback controller من دون قراءة حالة مملوكة للحاوية.

يربط Compose file الافتراضي الخدمة بـ localhost:

```text
127.0.0.1:8765 -> container:8765
```

وهذا مناسب للاختبار المحلي ولـ reverse proxy يعمل على host نفسه.

## تخطيط Workspace

يقوم runtime الافتراضي لـ Compose بعمل mount لما يلي:

| Host path أو volume | Container path | الغرض |
|---|---|---|
| `./workspaces/default` | `/workspace` | Workspace مضبوط ظاهر للأدوات |
| `local-shell-mcp-credentials` volume | `/persist/credentials` | حالة credentials دائمة لـ Git/GitHub/SSH/GPG |

استخدم workspace directory واحدًا لكل trust boundary. لا تعمل mount للـ home directory بالكامل لمجرد الراحة.

## الإعدادات العامة المطلوبة

لـ ChatGPT أو MCP client عام عبر HTTP، اضبط `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

ولّد JWT secret بأمر مثل:

```bash
openssl rand -hex 32
```

Public MCP URL هو:

```text
https://your-public-host.example.com/mcp
```

## Cloudflare Tunnel sidecar

يتضمن Compose file خدمة `cloudflared` اختيارية خلف profile `tunnel`. تشغّل tunnel بجانب MCP server.

اضبط `.env`:

```env
CLOUDFLARE_TUNNEL_TOKEN=<token from Cloudflare Tunnel>
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=<strong pin>
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=<strong random secret>
```

شغّل الخدمتين:

```bash
docker compose --profile tunnel up -d
```

في Cloudflare Zero Trust وجّه public hostname إلى:

```text
http://local-shell-mcp:8765
```

هذا Cloudflare Tunnel وليس Cloudflare Access. يظل `local-shell-mcp` مسؤولًا عن OAuth الخاص بـ ChatGPT.
تثق خدمة Compose بـ forwarded headers لأن published port محصور في localhost؛ وهذا يحافظ على public caller address لعملية OAuth PIN rate limiting. إذا عرضت container port مباشرة، فاستبدل `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS=*` بالعناوين الصريحة للـ reverse proxies الموثوق بها.

## Reverse proxy بدون tunnel sidecar

إذا كنت تستخدم Caddy أو Nginx أو Traefik أو Nginx Proxy Manager بالفعل، فاحتفظ بخدمة Compose العادية ومرر HTTPS إلى:

```text
http://127.0.0.1:8765
```

يجب أن يمرر proxy هذه routes دون إزالة paths:

| Route | الغرض |
|---|---|
| `/mcp` | MCP streamable HTTP endpoint |
| `/healthz`, `/readyz` | Health checks |
| `/.well-known/oauth-protected-resource` | OAuth resource metadata |
| `/.well-known/oauth-authorization-server` | OAuth authorization-server metadata |
| `/oauth/register` | Dynamic client registration |
| `/oauth/authorize` | Browser authorization page |
| `/oauth/token` | Token exchange |
| `/downloads/<token>` | Optional generated file downloads |
| `/join/<token>`, `/remote/*` | Optional remote-worker bootstrap / polling |

راجع [network connectivity](../clients/connectivity.md) لمتطلبات سلوك proxy.

## Full-container mode

يحصر `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=false` عمليات filesystem داخل workspace. وهو default الأكثر أمانًا.

اضبطه على `true` فقط عندما يكون container disposable عمدًا ويُتوقع من model تشغيل كامل container filesystem. عند التفعيل تزال built-in command/path denylist restrictions.

```env
LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true
```

لا تفعّل full-container mode في runtime يعمل مباشرة على host مثل VS Code extension أو binary على حاسوبك.

## Credentials

يمكن لـ Docker runtime حفظ common developer credentials في dedicated volume. يفيد ذلك في GitHub CLI login وGit HTTPS credential helpers و`.netrc` وSSH config وGPG state.

عامل credential volume على أنه sensitive. فضّل repository-scoped deploy keys أو fine-grained tokens أو short-lived credentials. لا تضع broad personal credentials في workspace يستطيع model قراءته بحرية.

يمكن عمل SSH-agent forwarding عبر mount لـ agent socket، لكنه يوسّع الثقة من container إلى active agent. استخدمه فقط إذا فهمت exposure.

## التحديثات

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

مع tunnel sidecar:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
curl -i http://127.0.0.1:8765/healthz
```

بعد upgrade، اطلب من client أولًا read-only check:

```text
استخدم local-shell-mcp. استدعِ environment_get ثم نفّذ file_list على جذر workspace. لا تعدّل الملفات.
```

## استكشاف الأخطاء

| العَرَض | التحقق |
|---|---|
| `/healthz` يفشل محليًا | `docker compose ps`, `docker compose logs --tail=200 local-shell-mcp` |
| ChatGPT لا يكتشف tools | Public URL يجب أن ينتهي بـ `/mcp`؛ و`LOCAL_SHELL_MCP_PUBLIC_BASE_URL` يجب ألا يحتوي `/mcp` |
| صفحة OAuth تفشل | يجب ضبط admin PIN وJWT secret في public OAuth deployments |
| Tools لا ترى files | تأكد من mount الـ host directory المقصود إلى `/workspace` |
| Browser tools تفشل | تأكد أن Playwright image حديثة؛ جرّب `run_shell` للـ target browser |
| اختفى Git auth | تحقق من credential volume ومن أن container المعاد إنشاؤه يستخدم volume نفسه |
