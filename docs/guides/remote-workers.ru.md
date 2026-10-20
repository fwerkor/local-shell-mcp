<!-- i18n-source-sha256: d3c380d9a5d9a43019b0be2b5e9accc0d6e0c785d77226005db60c5721672ba6 -->
# Удалённые workers

Remote workers позволяют `local-shell-mcp` управлять машинами, которые могут отправлять исходящие HTTP(S)-запросы, но не могут принимать входящие SSH-соединения.

```text
MCP client -> control server -> outbound polling worker -> remote machine
```

## Базовый процесс

1. Создайте приглашение через `remote_manage(action="invite", ...)`.
2. Выполните созданную команду на удалённой машине.
3. Подтвердите регистрацию с помощью `remote_manage(action="list")`.
4. Вызывайте обычные инструменты с `machine="<worker-name>"`, например `environment_get`, `run_shell`, `file_read` или `browser_run_script`.
5. Используйте `remote_transfer` для запуска отслеживаемой передачи файла или каталога controller-to-worker, worker-to-controller или worker-to-worker. Затем используйте `job_list` или `job_tail`; остановить или повторить можно через `job_stop` или `job_retry`.
6. Переименовывайте или отзывайте workers через `remote_manage(action="rename", ...)` или `remote_manage(action="revoke", ...)`.

Только администрирование workers использует имена `remote_*`. Операции execution, shell, job, filesystem, patch и browser используют одинаковую schema локально и удалённо. Указание machine дополнительно требует OAuth scope `remote:use`.

## Постоянные workers

Результат приглашения содержит платформенные команды:

- `persistent_command` устанавливает и запускает user service на Linux/macOS.
- `powershell_persistent_command` устанавливает и запускает Windows user task из PowerShell.

В Windows `local-shell-mcp worker install-service` регистрирует задачу `local-shell-mcp-worker` для текущего пользователя. Она запускается сразу, снова запускается при входе этого пользователя после reboot, допускает работу от батареи, игнорирует повторный запуск и повторяет неудачные выполнения. Права администратора не нужны, а до входа пользователя задача не запускается.

На всех платформах используются одинаковые lifecycle commands:

```text
local-shell-mcp worker status
local-shell-mcp worker start
local-shell-mcp worker stop
local-shell-mcp worker restart
local-shell-mcp worker uninstall-service
```

Worker log хранится в worker state directory как `worker.log`.

## Возможности

Workers поддерживают shell/persistent shell sessions, tracked jobs, filesystem operations, transfer internals, Python execution, patches и Playwright при наличии зависимостей. Git использует стандартные команды через `run_shell(machine=...)`.

## Безопасность и версии

Подключённый worker даёт MCP client контроль над настроенной средой. Используйте короткие invite TTL, отдельные work directories или accounts, проверяйте audit logs и отзывайте workers после задачи. Сгенерированное приглашение устанавливает worker code той же версии, что и control server.

## Диагностика

Если worker не появляется, проверьте исходящий HTTPS-доступ, достижимость public base URL, срок приглашения, системное время и logs control server.
