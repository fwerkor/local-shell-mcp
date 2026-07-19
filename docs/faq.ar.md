# الأسئلة الشائعة

تجمع هذه الصفحة مشكلات متكررة في Client والوكيل العكسي قد تبدو كأعطال في LSM رغم أن الخادم نفسه يعمل بصورة سليمة.

## لماذا لا تتوفر بعض الأدوات في ChatGPT بعد ترقية LSM؟

### الأعراض

- لا تظهر الأدوات الجديدة في ChatGPT.
- يستمر ChatGPT في محاولة استدعاء أداة حُذفت أو أُعيدت تسميتها أو دُمجت.
- تكون الأداة موجودة، لكن الاستدعاء يفشل لأن ChatGPT يرسل مخطط إدخال أقدم.
- لا تؤدي إعادة تشغيل LSM أو بدء محادثة جديدة إلى حل المشكلة.

### السبب

قد يحتفظ ChatGPT بلقطة ثابتة للأدوات ومخططات الإدخال التي كانت متاحة عند فحص MCP App أو اعتمادها أو نشرها. عندما يغيّر إصدار LSM قيمة `tools/list`، لا يوجد ضمان بأن تتحدث هذه اللقطة تلقائياً. وليست ذاكرة مؤقتة قصيرة ذات مدة انتهاء موثقة.

### الحل

=== "وضع المطور أو اتصال شخصي"

    1. افتح **ChatGPT Settings → Apps**.
    2. افتح LSM App واستخدم **Refresh** لإعادة فحص الأدوات.
    3. إذا لم يتوفر Refresh، احذف App القديمة وأضف نقطة MCP نفسها من جديد.
    4. ابدأ محادثة جديدة بعد اعتماد قائمة الأدوات المحدثة.

=== "App منشورة في ChatGPT Business"

    لا يمكن حالياً تحديث أدوات أو بيانات App مخصصة منشورة في مكانها. يجب على مسؤول مساحة العمل إنشاء App جديدة، وفحص نقطة LSM الحالية، ونشر البديل، ثم إيقاف App القديمة.

=== "ChatGPT Enterprise أو Edu"

    يستطيع المسؤول فتح **Workspace Settings → Apps → LSM App → … → Action control → Refresh**، ومراجعة الفروق، وتفعيل actions الجديدة عند الحاجة.

راجع [issue #70](https://github.com/fwerkor/local-shell-mcp/issues/70) و[وثائق OpenAI الخاصة بـ MCP Apps](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt).

## لماذا تستمر WebUI في إعادة الاتصال خلف Nginx؟

### الأعراض

- تُحمّل صفحة WebUI وتسجيل OAuth بصورة طبيعية.
- لا تظهر TUI.
- تتكرر الحالات `Connecting` و`Connection error` و`Reconnecting`.
- يعمل الاتصال المباشر بالمنفذ `8765`.

### السبب

تعرض واجهة المتصفح TUI الأصلية عبر PTY WebSocket. نقطة الاتصال الافتراضية هي `/ui/ws`، ومع `ui_path` مخصص تصبح `${ui_path}/ws`. لا يمرر `proxy_pass` العادي في Nginx تلقائياً ترويسات hop-by-hop المطلوبة لترقية WebSocket.

### الحل

فعّل HTTP/1.1 ومرر ترويستي `Upgrade` و`Connection`:

```nginx
# ضع map داخل كتلة http.
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 443 ssl;
    server_name lsm.example.com;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;
    }
}
```

تحقق من الإعداد ثم أعد تحميل Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

في Nginx Proxy Manager، فعّل **Websockets Support** في Proxy Host. إذا استمرت إعادة الاتصال، أضف ترويسات الترقية المكافئة في Advanced.

### التحقق

افتح أدوات المطور، وأعد تحميل WebUI، وافحص طلب `/ui/ws`. يعيد الاتصال السليم:

```text
101 Switching Protocols
```

راجع [issue #71](https://github.com/fwerkor/local-shell-mcp/issues/71).
