<!-- i18n-source-sha256: 521e0f39c8823597b1468b2d63af978794cb28fda8c8e60230da0a96cff2d5c2 -->
# Единое веб-рабочее пространство

**унифицированное веб-рабочее пространство LSM** — это рекомендуемый способ повседневного использования local-shell-mcp. Он объединяет чат AI, историю проекта и плоскость управления LSM в одном адаптивном интерфейсе, основанном на модифицированном интерфейсе LibreChat. Вы по-прежнему можете подключать внешние клиенты MCP, такие как [ChatGPT](chatgpt-connector.md) или [Gemini](gemini-spark.md).

Рабочая область **самостоятельная и необязательная для установки**: это отдельная веб-служба, а не часть минимального образа контроллера, отдельного исполняемого файла или пакета удаленного рабочего процесса. При развертывании только для контроллера сохраняется исходный пользовательский интерфейс браузера и OpenTUI.

## Что находится на рабочем месте?

| Площадь | Что вы можете сделать |
|---|---|
| Чат и проекты | Выбирайте настроенную модель, создавайте беседы, систематизируйте проекты, находите прошлые чаты и архивируйте беседы. История остаётся на сервере. |
| Обзор контроллера | Просматривайте состояние здоровья, недавнюю активность и подключенные машины. |
| Файлы | Просматривайте и управляйте локальными или удаленными файлами. |
| Терминалы | Работайте с постоянными терминалами на Контроллере или Воркёрах. |
| Рабочий стол | Проверяйте и контролируйте удаленные сеансы графического интерфейса. |
| Сессии | Изучите долгосрочные задачи LSM и их жизненный цикл. |
| Пульты | Подключайте и администрируйте исходящие рабочие процессы. |
| Аудит | Проверьте активность инструмента, созданного моделью. |
| Вложенный MCP | Регистрируйте, редактируйте, включайте, отключайте, обновляйте и удаляйте внешние серверы MCP за LSM. |

Маршруты контроллера: `/control/overview`, `/control/files`, `/control/terminals`, `/control/desktop`, `/control/sessions`, `/control/remotes` и `/control/audit`. Чат откроется по адресу `/c/new`. Менеджер LSM MCP управляет **вложенным реестром MCP LSM**; он не создает второй реестр в LibreChat.

## Разверните дополнительный стек чата

1. [Install and start an LSM Controller](quickstart.md) with SQLite (now the default). On startup, durable historical state is imported automatically, retaining the original files for rollback.
2. Configure one HTTP/HTTPS Controller origin, for example `https://lsm.example.org`. Chat, terminals, files and remote controls share the same Python server and authentication.
3. To override the defaults, configure the Controller service environment:

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

4. Start the Controller from its Python package or standalone executable:

```sh
local-shell-mcp --mode mcp
```

5. The original React client is maintained in `ui/workspace/`. Bun is only required for building and releases; consult the [first-party WebUI build and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

Node.js, MongoDB, Meilisearch and the separate LibreChat Compose stack are no longer required at runtime. Workers remain ordinary Python packages.

**Migration status:** The Python Agent generation engine, SSE resume and tool approvals are still being ported. Do not deploy the draft branch as a replacement for a working production Controller.

## Войдите и используйте чат

1. Open the LSM Controller `/ui` entrypoint and authenticate with its existing PIN or OAuth credentials. React and Controller APIs share this identity.
2. Configure an available model endpoint/API credential in LSM. The Python Agent provider engine is being migrated; the draft branch does not yet provide complete generation support.
3. Start a conversation after the Python Agent endpoints and SSE protocol pass the acceptance suite. Nested MCP, LSM tools and file uploads follow existing Controller permissions.
4. Start with a read-only request: “Check Controller status and list the workspace root. Do not modify files.”
5. Navigate to **Files**, **Terminals**, **Desktop**, **Sessions**, **Remotes** or **Audit** for direct inspection and control.

Загрузки чата (до 32 МБ) хранятся в рабочей области контроллера, а их абсолютные пути передаются в модель. Загрузка через браузер не предоставляет дополнительных разрешений для файлов. Вызовы инструментов, ориентированных на модель, проходят через авторизацию LSM, аудит и маршрутизатор удаленных работников.

## Внешний MCP, безопасность и данные

Используйте боковую панель MCP рабочей области для управления вложенными внешними серверами MCP. Это поддерживает локальные серверы stdio и HTTP-серверы, включая отдельные переменные частной среды и заголовки запросов. Секреты не возвращаются в браузер. Переключатель чата **Внешний MCP** позволяет осуществлять поиск, проверку и вызов вложенных инструментов; он не предоставляет модель `mcp_manage`, когда встроенные инструменты LSM отключены. Управление пользовательским интерфейсом защищено обычной авторизацией контроллера.

Chats, projects, Agents, sessions, audits and Worker metadata share `.local-shell-mcp/lsm.sqlite3`; SQLite FTS5 provides local search. Non-database artifacts remain under `.local-shell-mcp/`.

The workspace is a first-party React application, not an iframe or separately hosted Web service. Python Workers and external MCP clients remain compatible.

## Устранение неполадок

- **Unable to start the WebUI:** check the Controller Python logs, SQLite initialization and bundled frontend archive. `LOCAL_SHELL_MCP_STATE_BACKEND=file` is an emergency storage recovery option.
- **Authentication fails:** use the existing Controller PIN/OAuth login. The React UI does not require a separate LibreChat account or bridge secret.
- **Chat loads but cannot answer:** the Python Agent generation and SSE port is still incomplete in this draft branch; do not deploy it to production.
- **Missing MCP tools:** check Controller authorization and the nested MCP registry; never expose `mcp_manage` to external-only model tools.
- **Files or sessions appear empty:** verify the Controller workspace, SQLite migration and authorized principal in its logs.

Подробности реализации и обновления см. в разделах [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md) и [human interface guide](../guides/human-interface.md).
