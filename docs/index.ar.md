# توثيق local-shell-mcp

طبقة تحكم محلية لـ ChatGPT Developer Mode وعملاء MCP الآخرين. تعرض مساحة عمل مضبوطة و shell والملفات و Git وأتمتة المتصفح وروابط الملفات والـ workers البعيدة كأدوات MCP.

## مسارات التوثيق

- [البدء السريع](getting-started/quickstart.md)
- [موصل ChatGPT](getting-started/chatgpt-connector.md)
- [Workers بعيدة](guides/remote-workers.md)
- [الأمان](security.md)
- [استكشاف الأخطاء](troubleshooting.md)

## البنية الأساسية

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## قاعدة الأمان الأساسية

في عمليات النشر العامة، فعّل OAuth ولا تركّب Docker socket أو جذر المضيف أو بيانات اعتماد طويلة الأمد.
