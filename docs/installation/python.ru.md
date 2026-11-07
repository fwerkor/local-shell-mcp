<!-- i18n-source-sha256: c8c0d8ebdbb123b9ac4af1fd288f30e8ca69037ca086486cb8027e2592f4b75a -->
# Python, pipx и source runtimes

**Рекомендуется установка непосредственно из репозитория исходников.** Используйте виртуальную среду Python и ограниченную рабочую папку. Docker Compose остаётся доступным.

Эта страница описывает три связанных случая:

- `pipx install local-shell-mcp`: user-level установка executable.
- `pip install local-shell-mcp`: установка в существующий virtual environment.
- Editable source checkout: разработка или отладка самого проекта.

## Установка pipx

`pipx` — наиболее чистый Python-based способ для обычных пользователей: команда получает собственный virtual environment, а executable становится доступным в `PATH`.

```bash
pipx install local-shell-mcp
local-shell-mcp --help
```

Запустите локальный HTTP MCP server:

```bash
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
local-shell-mcp --mode mcp
```

Проверьте состояние:

```bash
curl -i http://127.0.0.1:8765/healthz
```

## Установка в virtual environment

Используйте, если вы уже самостоятельно управляете Python environment:

```bash
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install local-shell-mcp
local-shell-mcp --mode mcp
```

Process использует инструменты, установленные на host. Python package не устанавливает за вас compiler, Git, browser system dependencies или project dependencies.

## Editable source checkout

Используйте для обычного развёртывания и разработки. Публичный доступ описан в [quickstart](../getting-started/quickstart.md).

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e .
cp .env.example .env
# Replace the example OAuth secrets in .env before starting.
set -a
. ./.env
set +a
mkdir -p workspaces/default
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspaces/default"
local-shell-mcp --mode mcp
```

Запустите проверки:

```bash
python -m pip install -e '.[dev,docs]'
ruff check .
pytest -q
mkdocs build --strict
```

## Настройка браузера

Playwright необязателен; установите библиотеку и браузер при необходимости.

```bash
python -m pip install -e '.[browser]'
python -m playwright install chromium
```

Установка браузера необязательна; базовый образ Docker не содержит Playwright или браузеров.

## Публичное использование HTTP MCP

Для ChatGPT или другого public HTTP MCP client настройте те же public-origin и OAuth параметры, что и для остальных HTTP runtimes, затем опубликуйте local port через reverse proxy или tunnel.

Публичный MCP endpoint:

```text
https://your-public-host.example.com/mcp
```

## Режимы разработки

| Mode | Command | Назначение |
|---|---|---|
| MCP HTTP | `local-shell-mcp --mode mcp` | Полноценные MCP clients по HTTP, включая ChatGPT за HTTPS |
| REST-style HTTP | `local-shell-mcp --mode http` | Диагностические или совместимые endpoints, не основной путь ChatGPT |
| stdio | `local-shell-mcp --mode stdio` | Локальные MCP clients, запускающие process |

`mode=both` зарезервирован и сейчас не должен использоваться как mode одного process.

## Безопасность host runtime

Python installs запускаются от вашего host user, если не помещены в VM/container. Ограничивайте workspace, держите full-container mode выключенным и не направляйте workspace на home directory.

Используйте Docker Compose для недоверенных repositories, задач с большим количеством package-manager операций и workflow, где resetability важнее интеграции с host.
