<!-- i18n-source-sha256: 5d2de552ba0ba0d1c76319ad9f87ab68e217fee6c607687f8260e14872e7dbcc -->
# Конфигурация

Repository поставляет один копируемый стартовый файл: [`.env.example`](https://github.com/fwerkor/local-shell-mcp/blob/main/.env.example). Docker Compose автоматически читает получившийся `.env`, а другие runtime могут использовать те же environment variables `LOCAL_SHELL_MCP_`. YAML остаётся optional advanced input для binary/source deployments; явно создайте файл и выберите его через `LOCAL_SHELL_MCP_CONFIG` или `--config`. Environment variables override YAML values, поэтому не определяйте одну настройку в обоих местах, если override не нужен намеренно. YAML keys используют field names ниже.

## Приоритет

1. Built-in defaults из `Settings`.
2. YAML config, выбранный `LOCAL_SHELL_MCP_CONFIG` или `--config`.
3. Environment variables с prefix `LOCAL_SHELL_MCP_`.
4. CLI flags `--mode`, `--config`, `--remote`, `--no-remote` и т. п.; они задают соответствующие environment values до загрузки settings.

## Минимальная public configuration

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-long-random-secret
```

Для local-only testing `auth_bypass_localhost` включён по умолчанию. Не публикуйте unauthenticated full MCP tools в public network.

## Справочник settings

### Server и workspace

| YAML key | Environment variable | Default | Примечания |
|---|---|---|---|
| `host` | `LOCAL_SHELL_MCP_HOST` | `'0.0.0.0'` |  |
| `port` | `LOCAL_SHELL_MCP_PORT` | `8765` |  |
| `forwarded_allow_ips` | `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS` | `'127.0.0.1'` | Comma-separated trusted proxy IPs для Uvicorn forwarded-header handling. Используйте `*` только при ограниченном direct ingress. |
| `mode` | `LOCAL_SHELL_MCP_MODE` | `'mcp'` | `mcp`, `http`, `stdio` или зарезервированное значение `both`. |
| `workspace_root` | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | `PosixPath('/workspace')` |  |
| `state_dir` | `LOCAL_SHELL_MCP_STATE_DIR` | `PosixPath('/workspace/.local-shell-mcp')` |  |
| `audit_log_path` | `LOCAL_SHELL_MCP_AUDIT_LOG_PATH` | `PosixPath('/workspace/.local-shell-mcp/audit.jsonl')` |  |
| `agent_config_dir` | `LOCAL_SHELL_MCP_AGENT_CONFIG_DIR` | `PosixPath('/workspace/.local-shell-mcp/agent_config')` |  |
| `allow_full_container` | `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER` | `False` | При true отключает workspace/path restrictions; используйте только внутри disposable boundary. |
| `disable_local` | `LOCAL_SHELL_MCP_DISABLE_LOCAL` | `False` | Отключает controller host как shell/file/browser execution target. Remote workers и control-plane services остаются доступны. |
| `stateless_controller` | `LOCAL_SHELL_MCP_STATELESS_CONTROLLER` | `False` | Делает controller пригодным для ephemeral/serverless instances: подразумевает `disable_local`, отключает local file links/wallpaper caching и по умолчанию ставит `state_backend=memory`. При `auth_mode=oauth` явно задайте сильный `oauth_jwt_secret`. |
| `state_backend` | `LOCAL_SHELL_MCP_STATE_BACKEND` | `'file'` | `file`, `memory` или `redis`. Redis нужен, когда serverless controller state должен переживать cold starts. |
| `state_backend_url` | `LOCAL_SHELL_MCP_STATE_BACKEND_URL` | `None` | Redis connection URL при `state_backend=redis`. Redacted в diagnostics. |
| `state_backend_prefix` | `LOCAL_SHELL_MCP_STATE_BACKEND_PREFIX` | `'local-shell-mcp'` | Namespace для memory/Redis control-plane state. |

### Лимиты

| YAML key | Environment variable | Default | Примечания |
|---|---|---|---|
| `default_timeout_s` | `LOCAL_SHELL_MCP_DEFAULT_TIMEOUT_S` | `60` |  |
| `max_timeout_s` | `LOCAL_SHELL_MCP_MAX_TIMEOUT_S` | `3600` |  |
| `max_output_bytes` | `LOCAL_SHELL_MCP_MAX_OUTPUT_BYTES` | `200000` |  |
| `max_file_read_bytes` | `LOCAL_SHELL_MCP_MAX_FILE_READ_BYTES` | `512000` |  |
| `max_file_write_bytes` | `LOCAL_SHELL_MCP_MAX_FILE_WRITE_BYTES` | `5000000` |  |
| `max_grep_results` | `LOCAL_SHELL_MCP_MAX_GREP_RESULTS` | `200` |  |
| `max_directory_entries` | `LOCAL_SHELL_MCP_MAX_DIRECTORY_ENTRIES` | `5000` |  |
| `max_glob_results` | `LOCAL_SHELL_MCP_MAX_GLOB_RESULTS` | `5000` |  |
| `max_tree_entries` | `LOCAL_SHELL_MCP_MAX_TREE_ENTRIES` | `5000` |  |
| `max_skills` | `LOCAL_SHELL_MCP_MAX_SKILLS` | `256` | Максимум Skill directories, возвращаемых одним registry scan. |
| `max_skill_related_files` | `LOCAL_SHELL_MCP_MAX_SKILL_RELATED_FILES` | `1000` | Максимум related files для одного Skill. |
| `max_skill_scan_entries` | `LOCAL_SHELL_MCP_MAX_SKILL_SCAN_ENTRIES` | `5000` | Максимум filesystem entries, исследуемых одним `skill_list` registry scan или direct Skill load. |
| `max_skill_path_bytes` | `LOCAL_SHELL_MCP_MAX_SKILL_PATH_BYTES` | `200000` | Максимум UTF-8 bytes для возвращаемых related-file paths. |
| `max_read_many_files` | `LOCAL_SHELL_MCP_MAX_READ_MANY_FILES` | `100` |  |
| `max_read_many_total_bytes` | `LOCAL_SHELL_MCP_MAX_READ_MANY_TOTAL_BYTES` | `5000000` |  |
| `max_http_request_bytes` | `LOCAL_SHELL_MCP_MAX_HTTP_REQUEST_BYTES` | `16000000` | Максимальный buffered HTTP request body для MCP, REST, OAuth, UI и remote-worker endpoints. |
| `max_job_log_bytes` | `LOCAL_SHELL_MCP_MAX_JOB_LOG_BYTES` | `10000000` | Максимум retained output bytes для каждой попытки long-running job. |
| `max_jobs` | `LOCAL_SHELL_MCP_MAX_JOBS` | `1000` | Максимум retained long-running job records; active jobs никогда не pruned. |
| `max_audit_tail_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES` | `1000000` |  |
| `max_audit_log_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES` | `20000000` |  |
| `max_audit_archive_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_ARCHIVE_BYTES` | `512000000` |  |
| `max_tmp_files` | `LOCAL_SHELL_MCP_MAX_TMP_FILES` | `500` |  |
| `max_tmp_bytes` | `LOCAL_SHELL_MCP_MAX_TMP_BYTES` | `50000000` |  |
| `max_transfer_archive_entries` | `LOCAL_SHELL_MCP_MAX_TRANSFER_ARCHIVE_ENTRIES` | `100000` | Максимум entries при распаковке transferred directory archive. |
| `max_transfer_unpacked_bytes` | `LOCAL_SHELL_MCP_MAX_TRANSFER_UNPACKED_BYTES` | `10000000000` | Максимум declared expanded bytes для transferred directory archive. |
| `max_concurrent_commands` | `LOCAL_SHELL_MCP_MAX_CONCURRENT_COMMANDS` | `4` |  |
| `max_tmux_sessions` | `LOCAL_SHELL_MCP_MAX_TMUX_SESSIONS` | `16` | Максимум persistent shell sessions во всех tmux, ConPTY и native fallback backends. |

### File links

| YAML key | Environment variable | Default | Примечания |
|---|---|---|---|
| `file_download_enabled` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED` | `True` |  |
| `file_download_default_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_TTL_S` | `3600` |  |
| `file_download_max_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_TTL_S` | `604800` |  |
| `file_download_default_max_downloads` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_MAX_DOWNLOADS` | `0` | `0` означает отсутствие default download-count limit. |
| `file_download_max_file_bytes` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_FILE_BYTES` | `0` | `0` означает отсутствие configured file-size cap для download links. |

### Human interface

| YAML key | Environment variable | Default | Примечания |
|---|---|---|---|
| `logical_sessions_enabled` | `LOCAL_SHELL_MCP_LOGICAL_SESSIONS_ENABLED` | `True` | Открывает `session_manage` и `plan_manage` и добавляет к обычным MCP-инструментам обязательный, но допускающий null аргумент `logical_session_id`. Отключите для более компактного набора инструментов без Sessions. |
| `live_workspace_enabled` | `LOCAL_SHELL_MCP_LIVE_WORKSPACE_ENABLED` | `True` | Открывает tools, resources и маршруты `/api/live/*` MCP App Live Workspace. Требует `ui_enabled` и недоступен в режиме `stdio`. |
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `True` | Монтирует native OpenTUI launcher, WebUI shell, PTY WebSocket и `/api/ui/*` routes. |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `'/ui'` | WebUI mount path на том же service. |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | `None` | Optional command override для OpenTUI executable resolution. |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `'bing'` | `bing`, `aurora` или `none`. |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | Inactive browser PTY timeout; `0` отключает его. |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | Максимум concurrent browser OpenTUI PTYs. |

### Remote workers

| YAML key | Environment variable | Default | Примечания |
|---|---|---|---|
| `remote_enabled` | `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `True` | Управляет `/join`, `/remote/*` и `remote_*` MCP tools. |
| `remote_invite_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_INVITE_TTL_S` | `7200` |  |
| `remote_poll_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S` | `25` |  |
| `remote_job_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S` | `3600` |  |
| `remote_max_pending_jobs` | `LOCAL_SHELL_MCP_REMOTE_MAX_PENDING_JOBS` | `256` | Максимум queued/pending jobs на worker. |
| `remote_cancelled_job_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_CANCELLED_JOB_TTL_S` | `3600` | Retention time cancellation tombstones для пропуска timed-out queued jobs. |
| `remote_transfer_strategy` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_STRATEGY` | `'auto'` | `auto`, `relay`, `direct` или `object_store`. `auto` пробует enabled peer-direct, затем configured S3, затем bounded-memory controller relay. |
| `remote_peer_transfer_enabled` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ENABLED` | `False` | Опционально включает one-shot HTTP receiver на destination worker для direct worker-to-worker transfer. Используйте только в trusted private network вроде VPC/Tailscale. |
| `remote_peer_transfer_bind_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_BIND_HOST` | `'0.0.0.0'` | Bind address one-shot receiver на destination worker. |
| `remote_peer_transfer_advertise_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ADVERTISE_HOST` | `None` | Address, advertised source worker; по умолчанию destination worker hostname/FQDN. |
| `remote_peer_transfer_port` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_PORT` | `0` | Receiver port; `0` выбирает ephemeral port. |
| `remote_peer_transfer_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_TIMEOUT_S` | `3600` | Lifetime/timeout one-shot direct receiver. |
| `remote_transfer_s3_bucket` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_BUCKET` | `None` | Optional S3-compatible bucket для presigned worker-to-worker transfers. Требует extra `s3`. |
| `remote_transfer_s3_prefix` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PREFIX` | `'local-shell-mcp'` | Object-key prefix для temporary transfer objects. |
| `remote_transfer_s3_region` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_REGION` | `None` | Optional S3 region. |
| `remote_transfer_s3_endpoint_url` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_ENDPOINT_URL` | `None` | Optional S3-compatible endpoint URL. |
| `remote_transfer_s3_presign_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PRESIGN_TTL_S` | `3600` | Lifetime presigned PUT/GET URL. Temporary objects удаляются после transfer. |

### Shell и paths исполняемых файлов

| YAML key | Environment variable | Default | Примечания |
|---|---|---|---|
| `shell_executable` | `LOCAL_SHELL_MCP_SHELL_EXECUTABLE` | `'/bin/bash'` |  |
| `shell_env_blocklist` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKLIST` | `['CLOUDFLARE_TUNNEL_TOKEN']` |  |
| `shell_env_blocked_prefixes` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKED_PREFIXES` | `['LOCAL_SHELL_MCP_', 'DOCKER_']` | Comma-separated в environment variables; list в YAML. |
| `tmux_bin` | `LOCAL_SHELL_MCP_TMUX_BIN` | `'tmux'` | Preferred tmux executable. Если недоступен, Linux releases и Docker builds используют bundled helper; иначе persistent shells fallback на native backend. |
| `rg_bin` | `LOCAL_SHELL_MCP_RG_BIN` | `'rg'` |  |
| `git_bin` | `LOCAL_SHELL_MCP_GIT_BIN` | `'git'` |  |
| `python_bin` | `LOCAL_SHELL_MCP_PYTHON_BIN` | `'python3'` |  |

### Аутентификация и OAuth

| YAML key | Environment variable | Default | Примечания |
|---|---|---|---|
| `auth_mode` | `LOCAL_SHELL_MCP_AUTH_MODE` | `'oauth'` | Для public deployments используйте `oauth`. |
| `auth_bypass_localhost` | `LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST` | `True` |  |
| `require_auth_for_mcp_discovery` | `LOCAL_SHELL_MCP_REQUIRE_AUTH_FOR_MCP_DISCOVERY` | `True` | Требует OAuth до MCP initialization и tool discovery. |
| `mcp_session_idle_timeout_s` | `LOCAL_SHELL_MCP_MCP_SESSION_IDLE_TIMEOUT_S` | `180` | Idle timeout для stateful Streamable HTTP sessions. |
| `mcp_max_sessions` | `LOCAL_SHELL_MCP_MCP_MAX_SESSIONS` | `1024` | Максимум concurrent stateful MCP sessions. |
| `public_base_url` | `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | `None` | External HTTPS origin. Не включайте `/mcp`. |
| `oauth_issuer` | `LOCAL_SHELL_MCP_OAUTH_ISSUER` | `None` |  |
| `oauth_resource` | `LOCAL_SHELL_MCP_OAUTH_RESOURCE` | `None` |  |
| `oauth_admin_pin` | `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` | `None` |  |
| `oauth_jwt_secret` | `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` | <generated or configured> |  |
| `oauth_access_token_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S` | `0` | `0` означает, access tokens не expire автоматически. |
| `oauth_code_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_CODE_TTL_S` | `300` |  |

### Встроенные policy lists

| YAML key | Environment variable | Default | Примечания |
|---|---|---|---|
| `command_denylist` | `LOCAL_SHELL_MCP_COMMAND_DENYLIST` | `[]` | Автоматически очищается при включении full-container mode. |
| `path_denylist` | `LOCAL_SHELL_MCP_PATH_DENYLIST` | `[]` | Автоматически очищается при включении full-container mode. |

## Пример YAML

```yaml
host: 0.0.0.0
port: 8765
mode: mcp
workspace_root: /workspace
auth_mode: oauth
remote_enabled: true
disable_local: false
logical_sessions_enabled: true
live_workspace_enabled: true
ui_enabled: true
ui_path: /ui
file_download_enabled: true
shell_env_blocked_prefixes:
  - LOCAL_SHELL_MCP_
  - DOCKER_
```

Serverless controller с durable Redis state:

```yaml
mode: mcp
stateless_controller: true
state_backend: redis
state_backend_url: redis://redis.internal:6379/0
remote_transfer_strategy: auto
```

`stateless_controller` устраняет необходимость в persistent controller volume. Backend `memory` намеренно ephemeral: cold start invalidates pending remote invites и worker identities и удаляет OAuth clients, jobs и audit records. Используйте Redis, если любой такой state должен переживать cold starts, включая durable worker revocation semantics. При default `auth_mode=oauth` передайте минимум 32 bytes random key material через `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET`. Active remote RPC queues/futures process-local, поэтому deployments с remote workers пока должны запускать один active controller instance, а не несколько load-balanced controller replicas.

## Операционные рекомендации

- Оставляйте `allow_full_container=false`, если container/VM не disposable.
- Для любого public endpoint оставляйте `auth_mode=oauth`.
- Отключайте `remote_enabled`, если remote workers не используются.
- Отключайте `file_download_enabled`, если chat-downloadable artifacts не нужны.
- Ограничения command/file/audit должны быть достаточно высокими для coding tasks, но достаточно низкими для предотвращения accidental runaway output.
