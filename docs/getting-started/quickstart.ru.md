<!-- i18n-source-sha256: b6bf2276867332a25b6e63b3b4cf21045262a9a9535422c02722906d87a2132a -->
# Быстрый старт

Это руководство запускает контроллер LSM и открывает его интерфейс браузера. [unified web workspace](web-workspace.md) — рекомендуемый ежедневный опыт; это отдельно развернутый дополнительный стек чата. ChatGPT, Gemini и другие внешние клиенты MCP могут подключаться к одному и тому же контроллеру. См. [runtime choices and deployment model](../guides/deployment.md).

Рекомендуется **один исполняемый файл Controller** из [GitHub Releases](https://github.com/fwerkor/local-shell-mcp/releases/latest): Python, Docker и исходники не нужны. Пример для **Linux x86_64**; другие платформы: [руководство по бинарникам](../installation/binary.md).

## Требования

- Подходящий исполняемый файл и `curl` (пример Linux x86_64).
- Публичный HTTPS только для удалённых пользователей или внешних клиентов MCP.
- Отдельная рабочая папка с ограниченным доступом.
- Надёжный PIN администратора OAuth и случайный секрет JWT.

!!! warning
    Подключённая модель может управлять настроенным workspace. Запускайте сервис в одноразовом container или VM и не монтируйте ресурсы управления host.

## 1. Загрузка исполняемого файла и настройка

Скачайте единый файл и создайте секрет JWT:

```bash
mkdir -p ~/lsm && cd ~/lsm
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp
chmod +x local-shell-mcp
./local-shell-mcp --help
openssl rand -hex 32
```

Создайте `.env`, заменив пример PIN и секрета JWT (используйте `openssl rand -hex 32`). Бинарник **не загружает** `.env` автоматически.

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. Запуск сервера

Запустите скачанный файл напрямую:

```bash
chmod 600 .env
set -a
. ./.env
set +a
mkdir -p workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspace"
./local-shell-mcp --mode mcp
```

Проверьте состояние в другом терминале:

```bash
curl -i http://127.0.0.1:8765/healthz
```

Нормальный ответ — HTTP `200`. Для постоянной работы используйте менеджер служб и ограниченную учётную запись.

## 3. Публикация по HTTPS

Для удалённого доступа используйте публичный сервер или обратный HTTPS-прокси (Caddy/Nginx/Traefik). Перенаправляйте весь сайт, включая загрузки файлов, на:

```text
http://127.0.0.1:8765
```

Проверьте HTTPS:

```bash
curl -i https://your-public-host.example.com/healthz
```

**Cloudflare Tunnel не рекомендуется** для передачи файлов: загрузка с клиента может быть медленной. Предпочтите публичный сервер или обычный прокси/проброс портов, оставив OAuth. Альтернатива: [Docker](../installation/docker.md).

## 4. Откройте рабочую область браузера.

Откройте логин контроллера:

```text
https://your-public-host.example.com/ui
```

Для доступа к чату, проектам и интегрированным страницам управления перейдите по адресу [unified web workspace guide](web-workspace.md). Исходный облегченный веб-интерфейс доступен, если чат не установлен.

## 5. Безопасная проверка доступа к инструментам

Попросите модель:

```text
Используй local-shell-mcp. Сначала вызови environment_get, затем перечисли корень workspace. Пока не изменяй файлы.
```

Ожидаемые read-only tools:

- `environment_get`
- `file_list`
- `file_tree`
- `file_read`

## 6. Начните с ограниченной coding-задачи

Хорошая первая задача:

```text
Изучи этот repository, кратко опиши структуру проекта, запусти существующий набор тестов, если он очевиден, и не меняй файлы.
```

После подтверждения соединения дайте более точные указания:

```text
Исправь падающий тест. Сначала прочитай соответствующие файлы, сделай минимальный patch, запусти целевой тест, затем покажи git diff. Не делай commit до моего подтверждения.
```

## Обновление

Замените исполняемый файл и перезапустите Controller:

```bash
# Stop the running Controller before replacing the executable.
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp.new
chmod +x local-shell-mcp.new
./local-shell-mcp.new --version
mv local-shell-mcp.new local-shell-mcp
# Restart the Controller process or service.
curl -i http://127.0.0.1:8765/healthz
```

Для Docker Compose обновите контейнер. Установка из исходников: [Python](../installation/python.md).

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

## Следующие страницы

| Задача | Страница |
|---|---|
| Понять выбор runtime и client | [Выбор runtime и модель развёртывания](../guides/deployment.md) |
| Запуск через Docker Compose | [Docker Compose runtime](../installation/docker.md) |
| Запуск из VS Code | [VS Code extension runtime](../installation/vscode-extension.md) |
| Запуск через release binary | [Автономный binary runtime](../installation/binary.md) |
| Запуск через Python или source checkout | [Python runtimes](../installation/python.md) |
| Используйте единый чат и интерфейс управления | [Unified web workspace](web-workspace.md) |
| Добавьте Gemini Spark в качестве клиента | [Gemini Custom Apps](gemini-spark.md) |
| Добавить ChatGPT как client | [ChatGPT connector](chatgpt-connector.md) |
| Выбирать инструменты и писать лучшие prompts | [Сценарии использования](../guides/usage-patterns.md) |
| Подключить HPC, NPU/GPU или NAT машину | [Удалённые workers](../guides/remote-workers.md) |
| Понять все MCP tools | [Справочник инструментов](../reference/tools.md) |
