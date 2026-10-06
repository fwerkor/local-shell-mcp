<!-- i18n-source-sha256: f471795a57e16e999999f856000b779183d5b6c642ffc8c852c77e7faf3bc0dd -->
# Сценарии использования и руководство по prompting

`local-shell-mcp` предоставляет мощные tools. Хороший результат требует сначала осмотреть среду, действовать маленькими шагами, выполнять проверку и сообщать, что изменилось.

## Общий рабочий цикл

Для большинства coding-задач используйте этот цикл:

1. Inspect: `environment_get`, `file_tree`, `file_grep`, `file_read` и `run_shell` для команд вроде `git status`.
2. Plan: попросить модель определить минимальный набор файлов и tests.
3. Edit: использовать `file_edit`, `file_patch` или shell commands.
4. Verify: запускать targeted tests/builds через `run_shell` или persistent shells.
5. Review: запускать `git diff` через `run_shell`, затем при необходимости `secret_scan` и `audit_tail`.
6. Commit/export: явные Git CLI commands через `run_shell` или `link_create`.

## Выбор инструмента

| Задача | Предпочитать | Избегать |
|---|---|---|
| Короткая one-shot команда | `run_shell` | Запускать persistent shell для каждой команды |
| Долгий dev server, REPL, watch task | `shell_start` + `shell_read` + `shell_send` | Блокировать `run_shell` до timeout |
| Structured analysis / file generation | `run_python` | Хрупкие shell pipelines для сложного JSON/text |
| Маленький exact edit | `file_edit` | Переписывать файл целиком без необходимости |
| Одна или несколько замен в одном файле | `file_edit` with an `edits` array | Повторять stale edits без перечитывания |
| Multi-file patch | `file_patch` | Ad hoc shell edits |
| Поиск файлов | `file_tree`, `file_glob` | Полные recursive listings больших repositories |
| Поиск кода | `file_grep` | Читать много файлов вслепую |
| Browser evidence | `browser_snapshot`, `browser_run_script` | Угадывать по названиям страниц/routes |
| Downloadable artifacts | `link_create` | Вставлять большие binary data в chat |
| Работа на remote machine | normal tools with `machine`, plus `remote_transfer` | Открывать inbound SSH, когда достаточно outbound worker |

## Вызов инструментов из CLI

Для shell-скриптов и CI команда `lsm call <tool>` вызывает тот же набор зарегистрированных инструментов через работающий loopback controller, поэтому состояние remote worker и controller сохраняется.

```bash
lsm call run_shell --json '{"command":"uname -a"}'
printf '%s\n' '{"path":"README.md"}' | lsm call file_read
```

Параметр `--session s_...` связывает вызов с Logical Session. При Docker Compose команду можно запускать из корня repository — CLI обнаружит стандартный общий путь к token. Если controller использует другую runtime-файловую систему, укажите `--token-file <path>`. `--direct` обходит controller и работает только локально.

## Шаблоны prompt

### Read-only ориентация по repository

```text
Используй local-shell-mcp. Изучи layout repository и git status. Не меняй файлы. До изменений кратко опиши основные компоненты, предполагаемые test commands и очевидные риски.
```

### Точечное исправление bug

```text
Используй local-shell-mcp для исправления bug. Сначала воспроизведи или локализуй его минимальной релевантной командой. Прочитай файлы до редактирования. Сделай минимальный patch, запусти targeted verification, затем покажи git diff и точные tests. Не делай commit до моего подтверждения.
```

### Workflow commit и push

```text
Используй local-shell-mcp. Проверь git status и diff, запусти нужные tests и secret_scan, создай один focused commit с коротким message, затем push текущую branch. Не включай caches, build artifacts или несвязанный formatting.
```

### Долгий процесс

```text
Запусти dev server в persistent shell session, читай output до ready, затем проверь страницу browser tools. Сохрани session id и kill сессию после проверки.
```

### Задача Remote worker

```text
Используй подключённый remote worker <machine>. Сначала вызови environment_get с machine=<machine>, затем file_list с той же machine. Работай только в configured remote workdir. Для коротких команд используй run_shell, для долгих — shell_start или job_start.
```

## Работа с repositories

Рекомендуемая последовательность для open-source changes:

1. Запустить `git status --short --branch` через `run_shell`.
2. Fetch и inspect branches явными Git CLI командами, когда важен upstream state.
3. Использовать `file_grep` и `file_read` до edit.
4. Сделать минимальный patch.
5. Сначала targeted tests, затем более широкие, если это практично.
6. Запустить `secret_scan` перед commit/push.
7. Явно stage и commit с коротким message.

Просите один commit на logical change, если maintainers нужен удобный для review history.

## Работа с generated artifacts

Для PDF, reports, screenshots, archives или logs:

1. Сгенерировать файл внутри workspace.
2. Проверить наличие и ожидаемый размер.
3. Использовать `link_create` с коротким TTL и optional `max_downloads`.
4. Revoke ссылку, когда она больше не нужна.

Не создавайте public links для private keys, credential directories или несвязанных personal data.

## Работа с remote machines

Remote worker mode полезен, когда машина может выполнять outbound HTTPS requests, но не принимать inbound SSH.

Рекомендации:

- Создавать/переименовывать machines через `remote_manage(action="invite", ...)` или `remote_manage(action="rename", ...)`.
- Перед действиями вызывать `environment_get(machine=...)`.
- Через `remote_transfer` запускать controller/worker и worker/worker transfer jobs, затем управлять обычными `job_*` tools.
- После задачи revoke workers через `remote_manage(action="revoke", ...)`.

## Anti-patterns

Избегайте этих указаний, если среда не disposable или последствия не понятны:

- «Установи глобально всё необходимое» на server, запущенном на host.
- «Запускай, пока не заработает» без временных ограничений и verification criteria.
- «Commit всё» в repository с generated artifacts.
- «Expose весь home directory» ради удобства.
- «Создай file link на весь workspace».
- Public deployment с `LOCAL_SHELL_MCP_AUTH_MODE=none`.
