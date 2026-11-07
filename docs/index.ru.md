<!-- i18n-source-sha256: f8fefdb11bbe7b5b755fd59ee829b2771e8c2e9694d5b9db40f8693f53c16960 -->
<div class="hero-shell" markdown>
<span class="hero-eyebrow">Автономное рабочее пространство ИИ · Плоскость управления MCP</span>

# local-shell-mcp

Чат, проекты, файлы, терминалы, удаленные машины и инструменты искусственного интеллекта в одном локальном интерфейсе. Подключайте внешние клиенты MCP, когда они вам понадобятся.

<div class="hero-actions" markdown>
[Начать](getting-started/quickstart.md){ .hero-action .hero-action--primary }
[Web workspace](getting-started/web-workspace.md){ .hero-action .hero-action--secondary }
[Справочник tools](reference/tools.md){ .hero-action .hero-action--secondary }
</div>
</div>

<div class="feature-grid" markdown>
<div class="feature-card" markdown>
### Настоящая coding environment
Запускайте tests, изучайте repositories, patch files, работайте с Git и сохраняйте audit trail через один MCP endpoint.
</div>

<div class="feature-card" markdown>
### Единое веб-рабочее пространство
Используйте встроенный чат и историю проектов вместе с файлами контроллера, терминалами, рабочим столом, сеансами, пультами дистанционного управления и аудитом. Внешние клиенты MCP остаются необязательными.
</div>

<div class="feature-card" markdown>
### Управление remote machines
Подключайте NAT, firewall или HPC machines через outbound worker connections без открытия SSH ports.
</div>
</div>

## Что предоставляет

`local-shell-mcp` предоставляет единое автономное рабочее пространство для искусственного интеллекта и сервер MCP для внешних клиентов. Он предоставляет оболочку, постоянную оболочку, файловую систему, поиск, исправления, Git, Playwright, аудит, устойчивые логические сеансы с дополнительными планами целей, токенизированную ссылку на файл и инструменты удаленной работы через аутентифицированные конечные точки MCP.

Используйте, когда AI должен изучать repository, запускать tests, редактировать files, работать с Git, собирать browser evidence, создавать downloadable artifacts или управлять remote machine, которая может только исходяще подключаться к control server.

## Архитектура

```text
Runtime layer: Docker / VS Code extension / binary / Python / stdio
Exposure layer: localhost / HTTPS proxy / tunnel / stdio pipe
Клиентский уровень: унифицированный клиент WebUI/Gemini/ChatGPT/универсальный клиент MCP.
Controlled workspace: /workspace or configured workspace root
Optional remote workers: outbound machine connections
```

Предполагаемая isolation boundary — container или VM, где запущен service.

## Начать по сценарию

| Сценарий | Начать здесь | Почему |
|---|---|---|
| Основное рабочее пространство браузера | [Unified web workspace](getting-started/web-workspace.md) | Чат, проекты и страницы управления LSM с общим логином |
| Первое развертывание контроллера | [Quickstart](getting-started/quickstart.md) | Рекомендуемый бинарник, OAuth и первый вход |
| Выбор runtime layer | [Runtime choices](guides/deployment.md) | Объясняет Docker, VS Code, binary, Python и stdio как отдельные runtime options |
| Подключение Gemini Spark | [Gemini Custom Apps](getting-started/gemini-spark.md) | Право на участие, URL-адрес HTTPS MCP, OAuth и тестирование |
| Добавить ChatGPT как client | [ChatGPT connector](getting-started/chatgpt-connector.md) | Endpoint, OAuth, первый безопасный prompt, tool discovery |
| Добавить LSM в DeepSeek Harness | [Плагин DeepSeek Harness](clients/deepseek-harness.md) | Установить repository как DSH bundle, сохранив полный набор LSM tools и remote-worker capabilities |
| Запуск из VS Code | [VS Code extension runtime](installation/vscode-extension.md) | Editor-launched runtime и заметки по host safety |
| Научиться работать с toolset | [Usage patterns](guides/usage-patterns.md) | Prompt templates и руководство по выбору tools |
| Понять каждый tool | [Tools reference](reference/tools.md) | Purpose, inputs, returns, combinations и notes для каждого tool |
| Подключить HPC, NPU/GPU или server node | [Remote workers](guides/remote-workers.md) | Outbound worker join flow и remote tool usage |
| Поделиться generated files | [File links](guides/file-links.md) | Tokenized download URL с TTL и revoke |
| Усилить безопасность deployment | [Security](security.md) | Isolation, OAuth, workspace scope и audit logs |

## Основные семейства tools

| Семейство | Примеры | Назначение |
|---|---|---|
| Shell and Python | `run_shell`, `run_python`, `shell_start` | Builds, tests, scripts, long-running processes |
| Files and search | `file_tree`, `file_grep`, `file_read`, `file_patch` | Repository inspection и precise edits |
| Git | `run_shell`, `run_shell`, `run_shell`, `run_shell` | Reviewable source-control workflows |
| Sessions и goals | `session_manage`, `plan_manage` | Durable task handoff, отчёты о прогрессе и необязательный Goal mode |
| Browser | `browser_session`, `browser_snapshot`, `browser_act`, `browser_run_script` | Persistent interaction, UI checks, screenshots, rendered docs и page text |
| File links | `link_create`, `link_revoke` | Скачивание generated artifacts из chat |
| Remote workers | `remote_manage`, `run_shell`, `remote_transfer` | Machines за NAT, firewall или cluster login flows |

## Типовые workflows

### Кодирование в рабочей веб-пространстве

1. Запустите контроллер LSM и дополнительный [unified web workspace](getting-started/web-workspace.md).
2. Откройте `/ui` и войдите в систему, используя учетную запись LSM.
3. Настройте конечную точку модели и откройте новый разговор.
4. Попросите модель проверить репозиторий и сначала выполнить проверки только для чтения.
5. После одобрения разрешите patch files, tests, diff review, commit и push.
6. Проверяйте audit log для задач с file links или remote systems.

### Remote HPC или accelerator host

1. Создайте одноразовый remote worker invite.
2. Вставьте generated command на remote host.
3. Используйте обычные tools с `machine`; Git через `run_shell`, transfer через `remote_transfer`.
4. После task revoke worker.

### Генерация artifacts

1. Пусть AI создаст file внутри `/workspace`.
2. Создайте tokenized file link с TTL/download limits.
3. Поделитесь link в chat.
4. После завершения revoke его.

## Язык

Этот site строится нативным MkDocs i18n plugin. Используйте language selector в header для переключения между English и переведёнными pages. Pages без перевода fallback на English.
