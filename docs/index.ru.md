# Документация local-shell-mcp

Локальная плоскость управления для ChatGPT Developer Mode и других MCP-клиентов. Она предоставляет контролируемое рабочее пространство, shell, файлы, Git, автоматизацию браузера, ссылки на файлы и удалённые worker как MCP-инструменты.

## Разделы документации

- [Быстрый старт](getting-started/quickstart.md)
- [Коннектор ChatGPT](getting-started/chatgpt-connector.md)
- [Удалённые worker](guides/remote-workers.md)
- [Безопасность](security.md)
- [Диагностика](troubleshooting.md)

## Основная архитектура

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## Ключевое правило безопасности

В публичных развертываниях включайте OAuth и не монтируйте Docker socket, корень хоста или долгосрочные учётные данные.
