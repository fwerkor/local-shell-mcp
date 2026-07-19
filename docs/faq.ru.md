# Часто задаваемые вопросы

На этой странице собраны повторяющиеся проблемы Client и обратного прокси, которые могут выглядеть как сбои LSM, хотя сам сервер работает нормально.

## Почему после обновления LSM некоторые инструменты недоступны в ChatGPT?

### Симптомы

- Новые инструменты не появляются в ChatGPT.
- ChatGPT продолжает вызывать удалённый, переименованный или объединённый инструмент.
- Инструмент существует, но вызов завершается ошибкой из-за старой схемы входных данных.
- Перезапуск LSM или новая беседа не помогают.

### Причина

ChatGPT может сохранять зафиксированный снимок инструментов и входных схем, доступных во время сканирования, одобрения или публикации MCP App. Если новая версия LSM изменяет `tools/list`, автоматическое обновление этого снимка не гарантируется. Это не кратковременный кэш с документированным сроком действия.

### Решение

=== "Режим разработчика или личное подключение"

    1. Откройте **ChatGPT Settings → Apps**.
    2. Откройте LSM App и нажмите **Refresh**, чтобы повторно просканировать инструменты.
    3. Если Refresh недоступен, удалите старую App и снова добавьте тот же MCP endpoint.
    4. После принятия нового списка инструментов начните новую беседу.

=== "Опубликованная App в ChatGPT Business"

    Опубликованная пользовательская App пока не может обновить инструменты или метаданные на месте. Администратор должен создать новую App, просканировать текущий endpoint LSM, опубликовать замену и вывести старую App из использования.

=== "ChatGPT Enterprise или Edu"

    Администратор может открыть **Workspace Settings → Apps → LSM App → … → Action control → Refresh**, проверить изменения и при необходимости включить новые actions.

См. [issue #70](https://github.com/fwerkor/local-shell-mcp/issues/70) и [документацию OpenAI по MCP Apps](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt).

## Почему WebUI постоянно переподключается за Nginx?

### Симптомы

- Страница WebUI и вход OAuth загружаются нормально.
- TUI не появляется.
- Состояние циклически меняется между `Connecting`, `Connection error` и `Reconnecting`.
- Прямое подключение к порту `8765` работает.

### Причина

Интерфейс браузера отображает нативную TUI через PTY WebSocket. Endpoint по умолчанию — `/ui/ws`; при пользовательском `ui_path` используется `${ui_path}/ws`. Обычный `proxy_pass` Nginx не передаёт автоматически hop-by-hop заголовки, необходимые для обновления протокола WebSocket.

### Решение

Включите HTTP/1.1 и передавайте заголовки `Upgrade` и `Connection`:

```nginx
# Разместите map в блоке http.
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

Проверьте конфигурацию и перезагрузите Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

В Nginx Proxy Manager включите **Websockets Support** для Proxy Host. Если переподключения продолжаются, добавьте эквивалентные заголовки в Advanced.

### Проверка

Откройте инструменты разработчика браузера, перезагрузите WebUI и проверьте запрос `/ui/ws`. Рабочее подключение возвращает:

```text
101 Switching Protocols
```

См. [issue #71](https://github.com/fwerkor/local-shell-mcp/issues/71).
