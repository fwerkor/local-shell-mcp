# ملف تنفيذي مستقل

تشرح هذه الصفحة سيناريو “ملف تنفيذي مستقل” وتحافظ على بنية Runtime/Client المشتركة في الموقع.

## نظرة عامة

يحدد Runtime كيفية تشغيل عملية الخادم وأي مساحة عمل يتحكم بها. يحدد Client كيفية اتصال ChatGPT أو أي عميل MCP آخر. Docker وإضافة VS Code والملفات التنفيذية المستقلة وتثبيتات Python/pipx/المصدر و stdio هي خيارات Runtime؛ أما موصل ChatGPT وعميل MCP HTTP العام وعميل MCP عبر stdio فهي اتصالات Client.

## متى تستخدمه

- استخدم هذه الصفحة عندما يطابق مسار Runtime أو Client المختار عنوان الصفحة.
- حافظ على اتساق جذر مساحة العمل و base URL العام و MCP endpoint ونمط المصادقة والأدوات المتاحة على المضيف.
- بالنسبة إلى ChatGPT web/app، انشر MCP endpoint عبر HTTPS ينتهي بـ `/mcp`.
- بالنسبة إلى عملاء MCP المحليين، استخدم HTTP localhost أو `local-shell-mcp --mode stdio` حسب دعم العميل.

## الخطوات

1. اختر صفحة تثبيت Runtime أولاً.
2. شغّل Runtime وتحقق من `/healthz` عند استخدام وضع HTTP.
3. اختر بعد ذلك صفحة اتصال Client.
4. سجّل MCP endpoint أو أمر stdio في Client.
5. استدعِ `environment_info` للتحقق من مساحة العمل والإعدادات الفعلية.

```text
Runtime: Docker / VS Code extension / binary / Python / stdio
Client:  ChatGPT connector / generic HTTP MCP / generic stdio MCP
Endpoint: https://your-host.example.com/mcp
```

## التحقق

- `environment_info` يؤكد إعدادات Runtime ومساحة العمل.
- `tree_view` يؤكد الملفات المرئية.
- `run_shell_tool` يؤكد بيئة الأوامر.

## ملاحظات

فضّل الخطوات الصغيرة القابلة للتحقق: الفحص، التعديل، مراجعة diff، الاختبار، الفحص الأمني، ثم commit. يجب أيضاً تقسيم المهام الكبيرة إلى استدعاءات أدوات قابلة للتدقيق.
