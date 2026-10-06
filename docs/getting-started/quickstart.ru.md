<!-- i18n-source-sha256: 51bfe29de540492ab1da2df9479464641bb335796b0538357235fac5b4a2e446 -->
# Быстрый старт

В этом руководстве Docker Compose используется как первый runtime, а ChatGPT — как первый client. Это независимые решения: Docker, VS Code extension, binary, Python и stdio — варианты runtime; ChatGPT и универсальные MCP-клиенты — варианты client. Полную схему см. в разделе [выбор runtime и модель развёртывания](../guides/deployment.md).

## Требования

- Docker Engine с Compose v2.
- Публичный HTTPS endpoint, если ChatGPT должен подключаться из Web.
- Отдельный каталог workspace.
- Длинные случайные OAuth admin PIN и JWT secret.

!!! warning
    Подключённая модель может управлять настроенным workspace. Запускайте сервис в одноразовом container или VM и не монтируйте ресурсы управления host.

## 1. Клонирование и настройка

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python -c 'from pathlib import Path; import secrets; p=Path(".env"); s=p.read_text(); p.write_text(s.replace("LOCAL_SHELL_MCP_UI_LOCAL_TOKEN=", "LOCAL_SHELL_MCP_UI_LOCAL_TOKEN=" + secrets.token_urlsafe(48), 1))'
chmod 600 .env
```

Измените `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
CLOUDFLARE_TUNNEL_TOKEN=
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

Для sidecar Cloudflare Tunnel:

```bash
docker compose --profile tunnel up -d
```

В Cloudflare Zero Trust направьте public hostname на:

```text
http://local-shell-mcp:8765
```

При использовании Caddy, Nginx, Traefik, Nginx Proxy Manager или другого reverse proxy перенаправьте HTTPS traffic на `127.0.0.1:8765` или сетевой адрес container.

## 4. Подключение ChatGPT

Используйте MCP endpoint:

```text
https://your-public-host.example.com/mcp
```

Следуйте [руководству по ChatGPT connector](chatgpt-connector.md), чтобы завершить OAuth и подтверждение инструментов.

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
| Добавить ChatGPT как client | [ChatGPT connector](chatgpt-connector.md) |
| Выбирать инструменты и писать лучшие prompts | [Сценарии использования](../guides/usage-patterns.md) |
| Подключить HPC, NPU/GPU или NAT машину | [Удалённые workers](../guides/remote-workers.md) |
| Понять все MCP tools | [Справочник инструментов](../reference/tools.md) |
