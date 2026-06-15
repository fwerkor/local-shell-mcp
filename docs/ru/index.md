# Документация local-shell-mcp

Локальная плоскость управления для ChatGPT Developer Mode и других MCP-клиентов. Она предоставляет контролируемое рабочее пространство, shell, файлы, Git, автоматизацию браузера, ссылки на файлы и удалённые workers как MCP-инструменты.

## Documentation paths

- [Быстрый старт](getting-started/quickstart.md)
- [Коннектор ChatGPT](getting-started/chatgpt-connector.md)
- [Удалённые workers](guides/remote-workers.md)
- [Безопасность](security.md)
- [Диагностика](troubleshooting.md)

## Core architecture

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## Key safety rule

Для публичного развертывания включайте OAuth и не монтируйте Docker socket, корень хоста или долговременные учётные данные.
