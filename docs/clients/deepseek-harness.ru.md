<!-- i18n-source-sha256: 6fa729155fcc9e524eb3f8081b80d40ceb72c59f5ece4b311809350005468851 -->
# DeepSeek Harness (DSH)

`local-shell-mcp` можно напрямую установить в Web profile DeepSeek Harness. Repository содержит DSH-aware bridge, который сохраняет полный набор LSM tools, связывает каждую DSH Session со стабильной v4 logical-session identity и добавляет **Live Workspace** как native DSH conversation view. LSM остаётся authority для execution state: local/remote machines, logical Sessions и Goal Plans, persistent terminals, jobs, browser sessions, Dynamic MCP, file links, audit data и Live Workspace timeline.

## Рекомендуемая топология

Рекомендуется запускать DSH и LSM непосредственно на одной машине. Каждая DSH Session использует отдельное LSM MCP connection и по умолчанию подключается к `127.0.0.1:8765/mcp`.

```text
DSH Web
  |
  | one LSM MCP connection per DSH Session
  | 127.0.0.1:8765/mcp
  v
local-shell-mcp :8765
  |-- local execution = this LSM host
  |-- /mcp
  |-- /remote/*
  |-- /ui
  |-- Live Workspace / audit / browser / jobs / links
  |
  +--> Remote Workers
```

Машина с LSM является target `local`. Если LSM работает в container, `local` означает этот container, а не автоматически DSH host. LSM по умолчанию слушает `0.0.0.0:8765`, DSH bundle использует loopback; при правильных настройках сети, firewall, public URL и authentication тот же controller может обслуживать Remote Workers и другие external clients.

## Установка

Сначала запустите LSM:

```bash
local-shell-mcp --mode mcp
```

Затем установите repository в DSH Web profile:

```bash
dsh plugin --profile web add local-shell-mcp-dsh
```

Для production закрепите Git spec на проверенном release tag или commit. Для разработки из checkout установите текущий каталог:

```bash
dsh plugin --profile web add .
```

Bundle загружает `local-shell-mcp-dsh` из `cordis.patch.yml`; DSH получает model-facing LSM tools в обычном MCP namespace, например:

```text
mcp__lsm__run_shell
mcp__lsm__file_read
mcp__lsm__remote_manage
mcp__lsm__remote_transfer
mcp__lsm__browser_session
mcp__lsm__mcp_tool_search
mcp__lsm__session_manage
mcp__lsm__plan_manage
...
```

Bridge намеренно сохраняет полный LSM catalog, включая Remote Worker capabilities. Внутренний app-only `live_workspace_reconnect` используется только bridge и не виден модели. Для меньшего tool set применяйте позднее DSH-side `ctx.tools.restrict()`, а не удаляйте возможности из LSM bundle.

## Связь DSH Session и LSM logical Session

Интеграция основана на v4 logical-session runtime. У каждой DSH Session свой upstream Streamable HTTP MCP client, а bridge отправляет opaque deterministic session-affinity, полученную из DSH Session id. Это создаёт следующую стабильную identity chain:

```text
DSH Session A
  -> stable LSM session affinity A
  -> v4 MCP session key A
  -> LSM logical Session / active run A
  -> Live Workspace A

DSH Session B
  -> stable LSM session affinity B
  -> v4 MCP session key B
  -> LSM logical Session / active run B
  -> Live Workspace B
```

Tool activity разных DSH conversations не смешивается в одну Live Workspace timeline. После restart DSH MCP transport создаётся с той же affinity, поэтому существующие logical Session и active run сохраняются, пока LSM controller владеет Session. Bridge также периодически ping активные MCP clients, чтобы обычный idle cleanup LSM не прерывал долгие conversations.

## Live Workspace внутри DSH

DSH browser plugin добавляет **Live Workspace** в `conversation.view` и переиспользует существующую v4 реализацию вместо второго UI/state model. View scoped к текущей DSH Session и показывает logical Session, Plan/Goal state, Activity, terminals, files, diff, jobs, remotes и audit. **Ask** и Goal auto-continuation возвращаются в ту же DSH conversation. Credentials Live Workspace DSH host получает server-side через MCP connection этой Session; они не попадают в conversation или model-visible tool result.

## Почему HTTP, а не stdio

Remote Workers требуют не только MCP tools, но и `/remote/*` HTTP routes для registration, polling, heartbeats, result delivery и transfer traffic. stdio-only child process потерял бы service plane и создал второй controller state domain. Использование уже работающего LSM HTTP service сохраняет единую authority для Remote Workers, browser state, jobs, Dynamic MCP, audit, file links, logical Sessions и Live Workspace.

## Конфигурация

DSH Host bridge принимает следующие environment variables:

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DSH_LSM_MCP_URL` | `http://127.0.0.1:8765/mcp` | LSM Streamable HTTP MCP endpoint для DSH. |
| `DSH_LSM_AUTHORIZATION` | unset | Необязательное полное значение header `Authorization`, например `Bearer ...`. |
| `DSH_LSM_TOOL_CALL_TIMEOUT_MS` | `120000` | Timeout одного tool call в миллисекундах. |
| `DSH_LSM_KEEPALIVE_INTERVAL_MS` | `30000` | Ping interval для сохранения long-lived per-Session MCP identity; минимум 5000 ms. |
| `DSH_LSM_BROWSER_URL` | unset | Доступный браузеру LSM origin, если он отличается от Host-side MCP origin. |

Same-host deployments обычно не требуют authorization header, так как localhost auth bypass LSM включён по умолчанию. Не публикуйте unauthenticated LSM service. Для protected remote controller задайте endpoint и bearer token:

```bash
export DSH_LSM_MCP_URL='https://lsm.example.com/mcp'
export DSH_LSM_AUTHORIZATION='Bearer <token>'
dsh --profile web
```

Bridge отправляет fixed upstream headers и не выполняет interactive OAuth authorization/refresh flow за DSH.

### Удалённые DSH Web browsers

`DSH_LSM_MCP_URL` разрешается DSH **Host** process, но Live Workspace API requests выполняются в браузере пользователя. Если remote-hosted DSH возвращает недоступную браузеру loopback URL LSM, задайте browser-reachable origin:

```bash
export DSH_LSM_BROWSER_URL='https://lsm.example.com'
```

Live Workspace token по-прежнему авторизует browser API requests.

## Remote Workers

Remote Worker mode полностью доступен через DSH. `mcp__lsm__remote_manage`, `mcp__lsm__remote_transfer` и обычные LSM tools с `machine` используют тот же controller и remote-worker state, что и другие clients. Для внешних workers настройте public URL и network exposure LSM как обычно; сам DSH может продолжать использовать loopback MCP endpoint.

## Жизненный цикл и сбои

Bundle не запускает другой LSM process. Он может стартовать при недоступном LSM: catalog connection reconnect с backoff и синхронизирует tools позже. Model tool calls не replay автоматически после неоднозначного transport failure, чтобы mutating calls не выполнялись дважды. Stable affinity и keepalive обслуживают нормальное пересоздание transport/idle; реальная замена controller следует durable Session recovery deployment. Удаление plugin удаляет только DSH-side integration:

```bash
dsh plugin --profile web remove local-shell-mcp-dsh
```

LSM при этом не останавливается.

## Проверка установки

Проверьте composed DSH profile:

```bash
dsh --profile web --dump-config
```

В выводе должна быть строка с `id: local-shell-mcp`, `name: local-shell-mcp-dsh`, `url: http://127.0.0.1:8765/mcp`.

```text
id: local-shell-mcp
name: local-shell-mcp-dsh
url: http://127.0.0.1:8765/mcp
```

Когда LSM online, DSH должен показывать, например, следующие `mcp__lsm__*` tools:

```text
mcp__lsm__run_shell
mcp__lsm__remote_manage
mcp__lsm__remote_transfer
mcp__lsm__browser_session
mcp__lsm__session_manage
```

В DSH Web непустая conversation также содержит **Live Workspace** view. Если integration отсутствует, проверьте `DSH_LSM_MCP_URL`, LSM `/healthz`, reachability `/mcp`, DSH Host log и `DSH_LSM_BROWSER_URL`, если проблема только во встроенном UI.
