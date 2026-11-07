<!-- i18n-source-sha256: d7d01bc3f36f434c8e66c3fb6f65c2934937c5b2937dd9e8ba7beefc018fd14f -->
# Выбор runtime и модель развёртывания

`local-shell-mcp` имеет два взаимодополняющих решения:

1. **Runtime**: как запускается процесс сервера и какой workspace он контролирует.
2. **Интерфейс**: используйте дополнительный [unified web workspace](../getting-started/web-workspace.md) или подключите внешний клиент MCP, например Gemini или ChatGPT.

Рекомендуемый ежедневный интерфейс — это автономное веб-рабочее пространство (чат, проекты и страницы управления LSM). Он развертывается отдельно от контроллера. Docker, расширение VS Code, двоичные файлы выпуска, установки Python и режим stdio — это способы запуска контроллера; внешние чат-приложения остаются дополнительными клиентами.

```text
Runtime layer                      Exposure layer                 Client layer
-------------------------------    ---------------------------    ----------------------
Docker Создать локальное только HTTP Единое веб-рабочее пространство
VS Code extension                  HTTPS reverse proxy/tunnel     Generic MCP client
Standalone binary                  stdio process pipe             VS Code extension UI
pipx / source checkout             remote-worker outbound join    REST-style diagnostics
```

Обычная самостоятельная установка:

```text
Браузер -> https://chat.example.com (единое веб-рабочее пространство)
        -> аутентифицированный контроллер local-shell-mcp
        -> контролируемое рабочее пространство и исходящие работники
Дополнительный внешний клиент -> https://mcp.example.com/mcp
```

Локальная схема MCP client может быть проще:

```text
Local MCP client
  -> starts local-shell-mcp --mode stdio
  -> controlled workspace
```

**Рекомендуется:** Для публичного доступа используйте сервер с публичным адресом или пересылку трафика через публичный сервер с обратным HTTPS-прокси. **Не рекомендуется:** Скорость загрузки со стороны клиента через Cloudflare Tunnel может быть очень низкой, из-за чего отправка и передача файлов становятся неудобными. Используйте только при отсутствии возможности развертывания или пересылки через публичный сервер. ([Public HTTPS exposure](../clients/connectivity.md))

## Матрица выбора runtime

| Время выполнения | Лучшее для | Граница изоляции | Источник инструментальной цепочки | Внешний доступ MCP | Страница |
|---|---|---|---|---|---|
| **Исходники (рекомендуется)** / `pipx` | Python-native использование, debugging, development | Host virtualenv or VM | Python package плюс host tools | Добавить HTTPS proxy или tunnel | [Python install](../installation/python.md) |
| Докер Составление | Изолированные одноразовые контейнеры | Контейнер | Образ экономичного контроллера; устанавливать наборы инструментов для конкретных задач отдельно | Добавьте HTTPS-прокси или туннель | [Docker Compose](../installation/docker.md) |
| Docker Compose + туннельная коляска | Не рекомендуется: Пересылка через публичный сервер; Cloudflare Tunnel только в крайнем случае | Контейнер | Изображение проекта | Пересылка через публичный сервер; Cloudflare Tunnel только в крайнем случае | [Docker Compose](../installation/docker.md#cloudflare-tunnel-sidecar) |
| VS Code extension | Запуск/остановка server из editor workspace | Обычно host process | Host tools плюс настроенный executable | Добавить внешний HTTPS tunnel/proxy для ChatGPT | [VS Code extension](../installation/vscode-extension.md) |
| Standalone binary | Hosts/VM, где Docker недоступен | Host or VM | Host tools плюс настроенный executable | Добавить HTTPS proxy или tunnel | [Standalone binary](../installation/binary.md) |
| Stdio mode | Локальные MCP clients, которые напрямую запускают процессы | Client process boundary | Host tools плюс настроенный executable | Нельзя использовать с ChatGPT web/app | [Stdio mode](../installation/stdio.md) |

## Матрица подключения client

| Интерфейс | Требуется общедоступный HTTPS. | Использует `/mcp` | Требуется OAuth | Типичное время выполнения |
|---|---:|---:|---:|---|
| Единое веб-рабочее пространство LSM | Да для удаленного доступа; также возможен локальный прокси | Внутренне | вход в ЛСМ | Контроллер плюс отдельный веб-стек |
| Gemini Spark / Пользовательские приложения | Да | Да | Да, для публичного использования | Любой HTTP-контроллер |
| ChatGPT custom MCP connector | Да | Да | Да для публичного использования | Docker, VS Code extension, binary, or Python |
| Generic local MCP client over stdio | Нет | Нет | Нет | `local-shell-mcp --mode stdio` |
| Generic HTTP MCP client | Обычно нет для localhost; да через сети | Да | Рекомендуется вне localhost | Any HTTP runtime |
| VS Code extension helper flow | Только если нужен ChatGPT | Да при копировании ChatGPT URL | Рекомендуется для ChatGPT | VS Code-launched runtime |

См. [unified web workspace](../getting-started/web-workspace.md), [Gemini Spark](../getting-started/gemini-spark.md), [ChatGPT connector](../getting-started/chatgpt-connector.md), [generic MCP clients](../clients/generic-mcp.md) и [network connectivity](../clients/connectivity.md).

## Что контролирует каждый runtime

Каждый runtime запускает один и тот же server code и при включении предоставляет те же семейства MCP tools:

- Shell и persistent shell sessions.
- Filesystem, search и patch tools.
- Операции Git.
- Browser automation через Playwright.
- Audit log и task-state tools.
- Tokenized file links.
- Optional remote-worker lifecycle и machine-routed tools.

Различается не абстрактный API, а **operating environment** за ним.

| Вопрос | Docker Compose | VS Code extension | Binary / Python |
|---|---|---|---|
| Где выполняются команды? | В container | Обычно в host workspace | В process environment host или VM |
| Default workspace? | Mounted `/workspace` | Текущая папка VS Code или настроенный path | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` |
| Предустановлены ли компиляторы и браузеры? | Нет; установить то, что нужно для задачи | Только если установлено на хосте | Только если установлено на хосте |
| Легко сбросить? | Пересоздать container и workspace volume | Зависит от workspace | Зависит от host/VM |
| Подходит для произвольной установки пакетов? | Да, если disposable | Рискованнее на host | Рискованнее вне VM |

## Рекомендуемый выбор

Рекомендуется **развёртывание непосредственно из исходников** в изолированной среде; см. [руководство по Python/исходникам](../installation/python.md). Docker Compose — альтернатива.

Используйте **расширение VS Code**, если рабочий процесс запускается из редактора и вам нужен локальный модуль запуска. Это все еще время выполнения. Удаленным веб-клиентам необходим доступный HTTPS-прокси или туннель.

Используйте **standalone binary**, если Docker недоступен, но VM, container host или dedicated user account уже обеспечивают boundary.

Используйте **`pipx` или source install** для development/debugging самого `local-shell-mcp` или когда Python-based environment удобнее поддерживать.

Используйте **stdio mode** только для локальных MCP clients, которые могут spawn server process. Это не публичное deployment и не используется напрямую ChatGPT web/app.

## Правило публичного endpoint

Для внешних клиентов HTTP MCP, таких как Gemini и ChatGPT, конечная точка MCP:

```text
https://your-public-host.example.com/mcp
```

`LOCAL_SHELL_MCP_PUBLIC_BASE_URL` — только origin:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

Не добавляйте `/mcp` к `LOCAL_SHELL_MCP_PUBLIC_BASE_URL`.

## Страницы runtime

- [Docker Compose](../installation/docker.md)
- [VS Code extension](../installation/vscode-extension.md)
- [Standalone binary](../installation/binary.md)
- [Python, `pipx`, and source install](../installation/python.md)
- [Stdio mode](../installation/stdio.md)

## Страницы client

- [Unified web workspace](../getting-started/web-workspace.md)
- [Gemini Spark / Custom Apps](../getting-started/gemini-spark.md)
- [ChatGPT connector](../getting-started/chatgpt-connector.md)
- [Generic MCP clients](../clients/generic-mcp.md)
- [Public HTTPS exposure](../clients/connectivity.md)
