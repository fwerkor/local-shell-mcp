<div dir="rtl" markdown>

# توثيق local-shell-mcp

طبقة تحكم محلية لـ ChatGPT Developer Mode وعملاء MCP الآخرين. توفر مساحة عمل مضبوطة و shell وملفات و Git وأتمتة متصفح وروابط ملفات وعمالاً بعيدين كأدوات MCP.

## Documentation paths

- [البدء السريع](getting-started/quickstart.md)
- [موصل ChatGPT](getting-started/chatgpt-connector.md)
- [العاملون البعيدون](guides/remote-workers.md)
- [الأمان](security.md)
- [استكشاف الأخطاء](troubleshooting.md)

## Core architecture

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## Key safety rule

في النشر العام فعّل OAuth ولا تربط Docker socket أو جذر المضيف أو بيانات اعتماد طويلة الأمد.

</div>
