<!-- i18n-source-sha256: 4eb43e1a065d72171aad5493848eb2f8c57361b110237c8816928e28f227a3d8 -->
# الاتصال بالشبكة

تحتاج MCP client عبر HTTP الموجودة خارج الجهاز إلى HTTPS origin يمكن الوصول إليه. تتناول هذه الصفحة توجيه الشبكة، وليس اختيار runtime.

ينتهي client endpoint عادةً بـ `/mcp`:

```text
https://your-public-host.example.com/mcp
```

إعداد public base URL للخادم هو الـ origin فقط:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

لا تضف `/mcp` إلى هذا base URL.

## خيارات الاتصال

**موصى به:** استخدم خادمًا ذا عنوان عام، أو أعد توجيه حركة المرور عبر خادم عام باستخدام وكيل HTTPS عكسي.

**غير موصى به:** قد تكون سرعة الرفع من جهة العميل عبر Cloudflare Tunnel بطيئة جدًا، مما يجعل رفع الملفات ونقلها صعب الاستخدام. استخدمه فقط عند تعذّر النشر العام أو التوجيه عبر خادم عام.


| الخيار | متى يُستخدم |
|---|---|
| Caddy | TLS تلقائي وبسيط |
| Nginx أو Nginx Proxy Manager | بنية Nginx موجودة |
| Traefik | توجيه container-native موجود |
| توجيه عبر خادم عام | استخدم خادمًا ذا عنوان عام، أو أعد توجيه حركة المرور عبر خادم عام باستخدام وكيل HTTPS عكسي. |
| Cloudflare Tunnel (غير موصى به) | إعادة التوجيه عبر خادم عام؛ وCloudflare Tunnel حل أخير |

## المسارات

مرّر الـ origin بالكامل إلى الخادم العامل. تشمل المسارات المهمة:

| المسار | الغرض |
|---|---|
| `/mcp` | MCP Streamable HTTP endpoint |
| `/healthz`, `/readyz` | فحوص الصحة |
| `/.well-known/...` | بيانات client discovery الوصفية |
| `/oauth/...` | مسار تفويض client |
| `/downloads/...` | روابط اختيارية للملفات المُنشأة |
| `/join/...`, `/remote/...` | مسار remote-worker اختياري |

## سلوك الوكيل

يجب أن يحافظ الوكيل على المسارات، ويمرر request bodies، ويدعم responses الطويلة، ويتجنب timeouts القصيرة جداً.

## الفحوص

```bash
curl -i http://127.0.0.1:8765/healthz
curl -i https://your-public-host.example.com/healthz
```

## أخطاء شائعة

| الخطأ | الإصلاح |
|---|---|
| استخدام `https://host` في ChatGPT بدلاً من `https://host/mcp` | أضف `/mcp` فقط إلى client endpoint |
| ضبط `LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://host/mcp` | اضبط الـ origin فقط |
| توجيه `/mcp` فقط | وجّه الـ origin بالكامل حتى تعمل discovery والتفويض أيضاً |
| تشغيل host runtime مع workspace واسع | استخدم workspace ضيقاً أو Docker |

## الاقتران المقترح

| Runtime | نمط الشبكة |
|---|---|
| Docker Compose على خادم | وكيل HTTPS عكسي |
| Docker Compose على جهاز منزلي | إعادة التوجيه عبر خادم عام؛ وCloudflare Tunnel حل أخير |
| VS Code extension على حاسوب محمول | توجيه عبر خادم عام |
| Binary على VM | Reverse proxy على VM أو حافة الشبكة |
| خادم تطوير Python/source | عادةً localhost فقط |
| Stdio mode | لا يوجد مسار HTTP؛ استخدم MCP client محلياً |
