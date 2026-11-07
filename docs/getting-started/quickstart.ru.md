<!-- i18n-source-sha256: a9820f08198cf8e823f59550928c07346f9669f2dbec46d3b8cd523c34034e01 -->
# Быстрый старт

Это руководство запускает контроллер LSM и открывает его интерфейс браузера. [unified web workspace](web-workspace.md) — рекомендуемый ежедневный опыт; это отдельно развернутый дополнительный стек чата. ChatGPT, Gemini и другие внешние клиенты MCP могут подключаться к одному и тому же контроллеру. См. [runtime choices and deployment model](../guides/deployment.md).

## Требования

- Docker Engine с Compose v2.
- Общедоступная конечная точка HTTPS, если необходимо подключиться удаленным пользователям или внешним клиентам MCP.
- Отдельный каталог workspace.
- Длинные случайные OAuth admin PIN и JWT secret.

!!! warning
    Подключённая модель может управлять настроенным workspace. Запускайте сервис в одноразовом container или VM и не монтируйте ресурсы управления host.

## 1. Клонирование и настройка

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python scripts/init_compose_env.py
```

Измените `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. Запуск сервера

```bash
mkdir -p workspaces/default
docker compose up -d
```

Проверьте состояние:

```bash
docker compose ps
docker compose logs --tail=100 local-shell-mcp
curl -i http://127.0.0.1:8765/healthz
```

Исправный ответ возвращает HTTP `200`.

## 3. Публикация по HTTPS

**Рекомендуется:** Для публичного доступа используйте сервер с публичным адресом или пересылку трафика через публичный сервер с обратным HTTPS-прокси.

**Не рекомендуется:** Скорость загрузки со стороны клиента через Cloudflare Tunnel может быть очень низкой, из-за чего отправка и передача файлов становятся неудобными. Используйте только при отсутствии возможности развертывания или пересылки через публичный сервер. Configure `CLOUDFLARE_TUNNEL_TOKEN` in `.env` only when choosing the optional tunnel sidecar.

Для sidecar Cloudflare Tunnel:

```bash
docker compose --profile tunnel up -d
```

В Cloudflare Zero Trust направьте public hostname на:

```text
http://local-shell-mcp:8765
```

При использовании Caddy, Nginx, Traefik, Nginx Proxy Manager или другого reverse proxy перенаправьте HTTPS traffic на `127.0.0.1:8765` или сетевой адрес container.

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

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Если используется профиль tunnel:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
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
