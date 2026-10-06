<!-- i18n-source-sha256: e2dd23efea9768d971fa8a8be723f55cfcac3279adfc82e4185a803e3f05de1e -->
# Runtime Docker Compose

Docker Compose — рекомендуемый runtime для большинства пользователей. Он даёт модели контролируемый Linux workspace, воспроизводимый toolchain, persistent credentials, поддержку browser automation и простой путь обновления.

Это выбор runtime. Его можно подключить к ChatGPT, универсальному HTTP MCP client или оставить локальным для тестирования.

## Что входит в Docker image

Image основан на Playwright Python image и устанавливает широкий development toolchain. Цель — позволить AI coding agent работать с разными repositories без пересборки runtime для каждого проекта.

Включённые категории:

| Категория | Примеры |
|---|---|
| Shell и inspection | Bash, curl, wget, jq, ripgrep, tree, tmux, patch, file |
| Git и credentials | Git, GitHub CLI, OpenSSH client, credential persistence volume |
| C/C++ build | build-essential, clang, cmake, ninja, autoconf, automake, gdb, lldb |
| Python | Python, pip, venv, pipx, package development dependencies |
| JavaScript/TypeScript | Node.js, npm, yarn, pnpm, TypeScript, ts-node |
| Другие языки | Go, Rust, Java, Ruby, PHP, Perl, Lua, R |
| Browser automation | Playwright browsers and browser dependencies |
| Document tooling | LibreOffice, Pandoc, Poppler utilities, OCR tooling |

Точный состав image — convenience layer, а не стабильный API. Project-specific dependencies должны оставаться в workspace или project build scripts.

## Базовый локальный запуск

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python -c 'from pathlib import Path; import secrets; p=Path(".env"); s=p.read_text(); p.write_text(s.replace("LOCAL_SHELL_MCP_UI_LOCAL_TOKEN=", "LOCAL_SHELL_MCP_UI_LOCAL_TOKEN=" + secrets.token_urlsafe(48), 1))'
chmod 600 .env
mkdir -p workspaces/default
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Сгенерированный локальный token хранится в принадлежащем хосту `.env` (режим `0600`) и передаётся в контейнер через Compose. Поэтому `lsm call` на хосте может аутентифицироваться в loopback controller без чтения состояния, принадлежащего контейнеру.

Стандартный Compose file привязывает service к localhost:

```text
127.0.0.1:8765 -> container:8765
```

Это подходит для локального тестирования и reverse proxy на том же host.

## Layout workspace

Стандартный Compose runtime монтирует:

| Host path / volume | Container path | Назначение |
|---|---|---|
| `./workspaces/default` | `/workspace` | Контролируемый workspace, видимый tools |
| `local-shell-mcp-credentials` volume | `/persist/credentials` | Persistent Git/GitHub/SSH/GPG-style credential state |

Используйте один workspace directory на trust boundary. Не монтируйте весь home directory только ради удобства.

## Обязательные public settings

Для ChatGPT или публичного HTTP MCP client настройте `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

JWT secret можно сгенерировать командой:

```bash
openssl rand -hex 32
```

Public MCP URL:

```text
https://your-public-host.example.com/mcp
```

## Cloudflare Tunnel sidecar

Compose file содержит optional service `cloudflared` за profile `tunnel`. Он запускает tunnel рядом с MCP server.

Настройте `.env`:

```env
CLOUDFLARE_TUNNEL_TOKEN=<token from Cloudflare Tunnel>
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=<strong pin>
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=<strong random secret>
```

Запустите оба service:

```bash
docker compose --profile tunnel up -d
```

В Cloudflare Zero Trust направьте public hostname на:

```text
http://local-shell-mcp:8765
```

Это Cloudflare Tunnel, а не Cloudflare Access. `local-shell-mcp` по-прежнему сам обрабатывает OAuth для ChatGPT.
Compose service доверяет forwarded headers, потому что published port ограничен localhost; это сохраняет public caller address для OAuth PIN rate limiting. Если container port публикуется напрямую, замените `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS=*` на явные адреса trusted reverse proxies.

## Reverse proxy без tunnel sidecar

Если уже используется Caddy, Nginx, Traefik или Nginx Proxy Manager, оставьте обычный Compose service и перенаправьте HTTPS на:

```text
http://127.0.0.1:8765
```

Proxy должен передавать эти routes без удаления paths:

| Route | Назначение |
|---|---|
| `/mcp` | MCP streamable HTTP endpoint |
| `/healthz`, `/readyz` | Health checks |
| `/.well-known/oauth-protected-resource` | OAuth resource metadata |
| `/.well-known/oauth-authorization-server` | OAuth authorization-server metadata |
| `/oauth/register` | Dynamic client registration |
| `/oauth/authorize` | Browser authorization page |
| `/oauth/token` | Token exchange |
| `/downloads/<token>` | Optional generated file downloads |
| `/join/<token>`, `/remote/*` | Optional remote-worker bootstrap / polling |

Требования к поведению proxy см. в [network connectivity](../clients/connectivity.md).

## Full-container mode

`LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=false` ограничивает filesystem operations workspace. Это более безопасный default.

Устанавливайте `true` только если container намеренно disposable и model должен управлять всем container filesystem. При включении удаляются built-in command/path denylist restrictions.

```env
LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true
```

Не включайте full-container mode в host-launched runtime вроде VS Code extension или binary, работающего напрямую на ноутбуке.

## Credentials

Docker runtime может хранить common developer credentials в dedicated volume. Это удобно для GitHub CLI login, Git HTTPS credential helpers, `.netrc`, SSH config и GPG state.

Считайте credential volume sensitive. Предпочитайте repository-scoped deploy keys, fine-grained tokens или short-lived credentials. Не помещайте broad personal credentials в workspace, который model может свободно читать.

SSH-agent forwarding возможен через mount socket агента, но расширяет доверие container на active agent. Используйте только если понимаете exposure.

## Обновления

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

С tunnel sidecar:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
curl -i http://127.0.0.1:8765/healthz
```

После upgrade сначала попросите client выполнить read-only check:

```text
Используй local-shell-mcp. Вызови environment_get и file_list для корня workspace. Не изменяй файлы.
```

## Диагностика

| Симптом | Проверка |
|---|---|
| `/healthz` не работает локально | `docker compose ps`, `docker compose logs --tail=200 local-shell-mcp` |
| ChatGPT не обнаруживает tools | Public URL должен заканчиваться `/mcp`; `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` не должен содержать `/mcp` |
| OAuth page не работает | Admin PIN и JWT secret должны быть заданы для публичных OAuth deployments |
| Tools не видят files | Проверьте, что нужный host directory смонтирован в `/workspace` |
| Browser tools не работают | Проверьте актуальность Playwright image; попробуйте `run_shell` для target browser |
| Git auth исчез | Проверьте credential volume и использование того же volume после пересоздания container |
