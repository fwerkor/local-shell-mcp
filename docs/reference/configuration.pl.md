<!-- i18n-source-sha256: 5d2de552ba0ba0d1c76319ad9f87ab68e217fee6c607687f8260e14872e7dbcc -->
# Konfiguracja

Repository dostarcza jeden kopiowalny starter file: [`.env.example`](https://github.com/fwerkor/local-shell-mcp/blob/main/.env.example). Docker Compose automatycznie odczytuje wynikowy `.env`, a inne runtimes mogą używać tych samych `LOCAL_SHELL_MCP_` environment variables. YAML pozostaje optional advanced input dla binary/source deployments; utwórz file explicit i wybierz go przez `LOCAL_SHELL_MCP_CONFIG` lub `--config`. Environment variables override YAML values, więc nie definiuj tego samego setting w obu miejscach, chyba że override jest zamierzony. YAML keys używają field names poniżej.

## Priorytet

1. Built-in defaults z `Settings`.
2. YAML config wybrana przez `LOCAL_SHELL_MCP_CONFIG` lub `--config`.
3. Environment variables z prefix `LOCAL_SHELL_MCP_`.
4. CLI flags takie jak `--mode`, `--config`, `--remote`, `--no-remote`, które ustawiają odpowiednie environment values przed settings load.

## Minimal public configuration

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-long-random-secret
```

Dla local-only testing `auth_bypass_localhost` jest default enabled. Nie expose unauthenticated full MCP tools w public network.

## Settings reference

### Server i workspace

| YAML key | Environment variable | Default | Uwagi |
|---|---|---|---|
| `host` | `LOCAL_SHELL_MCP_HOST` | `'0.0.0.0'` |  |
| `port` | `LOCAL_SHELL_MCP_PORT` | `8765` |  |
| `forwarded_allow_ips` | `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS` | `'127.0.0.1'` | Comma-separated trusted proxy IPs dla Uvicorn forwarded-header handling. Używaj `*` tylko przy ograniczonym direct ingress. |
| `mode` | `LOCAL_SHELL_MCP_MODE` | `'mcp'` | `mcp`, `http`, `stdio` lub zarezerwowana wartość `both`. |
| `workspace_root` | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | `PosixPath('/workspace')` |  |
| `state_dir` | `LOCAL_SHELL_MCP_STATE_DIR` | `PosixPath('/workspace/.local-shell-mcp')` |  |
| `audit_log_path` | `LOCAL_SHELL_MCP_AUDIT_LOG_PATH` | `PosixPath('/workspace/.local-shell-mcp/audit.jsonl')` |  |
| `agent_config_dir` | `LOCAL_SHELL_MCP_AGENT_CONFIG_DIR` | `PosixPath('/workspace/.local-shell-mcp/agent_config')` |  |
| `allow_full_container` | `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER` | `False` | Przy true wyłącza workspace/path restrictions; używaj tylko wewnątrz disposable boundaries. |
| `disable_local` | `LOCAL_SHELL_MCP_DISABLE_LOCAL` | `False` | Wyłącza controller host jako shell/file/browser execution target. Remote workers i control-plane services pozostają dostępne. |
| `stateless_controller` | `LOCAL_SHELL_MCP_STATELESS_CONTROLLER` | `False` | Przystosowuje controller do ephemeral/serverless instances: implikuje `disable_local`, wyłącza local file links/wallpaper caching i domyślnie ustawia `state_backend=memory`. Przy `auth_mode=oauth` explicit skonfiguruj silny `oauth_jwt_secret`. |
| `state_backend` | `LOCAL_SHELL_MCP_STATE_BACKEND` | `'file'` | `file`, `memory` lub `redis`. Użyj Redis, gdy serverless controller state musi przetrwać cold starts. |
| `state_backend_url` | `LOCAL_SHELL_MCP_STATE_BACKEND_URL` | `None` | Redis connection URL przy `state_backend=redis`. Redacted w diagnostics. |
| `state_backend_prefix` | `LOCAL_SHELL_MCP_STATE_BACKEND_PREFIX` | `'local-shell-mcp'` | Namespace dla memory/Redis control-plane state. |

### Limity

| YAML key | Environment variable | Default | Uwagi |
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
| `max_skills` | `LOCAL_SHELL_MCP_MAX_SKILLS` | `256` | Maximum Skill directories zwracanych przez jeden registry scan. |
| `max_skill_related_files` | `LOCAL_SHELL_MCP_MAX_SKILL_RELATED_FILES` | `1000` | Maximum related files zwracanych dla jednego Skill. |
| `max_skill_scan_entries` | `LOCAL_SHELL_MCP_MAX_SKILL_SCAN_ENTRIES` | `5000` | Maximum filesystem entries badanych przez jeden `skill_list` registry scan lub direct Skill load. |
| `max_skill_path_bytes` | `LOCAL_SHELL_MCP_MAX_SKILL_PATH_BYTES` | `200000` | Maximum UTF-8 bytes używanych przez returned related-file paths. |
| `max_read_many_files` | `LOCAL_SHELL_MCP_MAX_READ_MANY_FILES` | `100` |  |
| `max_read_many_total_bytes` | `LOCAL_SHELL_MCP_MAX_READ_MANY_TOTAL_BYTES` | `5000000` |  |
| `max_http_request_bytes` | `LOCAL_SHELL_MCP_MAX_HTTP_REQUEST_BYTES` | `16000000` | Maximum buffered HTTP request body dla endpointów MCP, REST, OAuth, UI i remote-worker. |
| `max_job_log_bytes` | `LOCAL_SHELL_MCP_MAX_JOB_LOG_BYTES` | `10000000` | Maximum retained output bytes dla każdej próby long-running job. |
| `max_jobs` | `LOCAL_SHELL_MCP_MAX_JOBS` | `1000` | Maximum retained long-running job records; active jobs nigdy nie są pruned. |
| `max_audit_tail_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES` | `1000000` |  |
| `max_audit_log_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES` | `20000000` |  |
| `max_audit_archive_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_ARCHIVE_BYTES` | `512000000` |  |
| `max_tmp_files` | `LOCAL_SHELL_MCP_MAX_TMP_FILES` | `500` |  |
| `max_tmp_bytes` | `LOCAL_SHELL_MCP_MAX_TMP_BYTES` | `50000000` |  |
| `max_transfer_archive_entries` | `LOCAL_SHELL_MCP_MAX_TRANSFER_ARCHIVE_ENTRIES` | `100000` | Maximum entries akceptowanych przy unpack transferred directory archive. |
| `max_transfer_unpacked_bytes` | `LOCAL_SHELL_MCP_MAX_TRANSFER_UNPACKED_BYTES` | `10000000000` | Maximum accepted declared expanded bytes dla transferred directory archive. |
| `max_concurrent_commands` | `LOCAL_SHELL_MCP_MAX_CONCURRENT_COMMANDS` | `4` |  |
| `max_tmux_sessions` | `LOCAL_SHELL_MCP_MAX_TMUX_SESSIONS` | `16` | Maximum persistent shell sessions przez backendy tmux, ConPTY i native fallback. |

### File links

| YAML key | Environment variable | Default | Uwagi |
|---|---|---|---|
| `file_download_enabled` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED` | `True` |  |
| `file_download_default_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_TTL_S` | `3600` |  |
| `file_download_max_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_TTL_S` | `604800` |  |
| `file_download_default_max_downloads` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_MAX_DOWNLOADS` | `0` | `0` oznacza brak default download-count limit. |
| `file_download_max_file_bytes` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_FILE_BYTES` | `0` | `0` oznacza brak configured file-size cap dla download links. |

### Human interface

| YAML key | Environment variable | Default | Uwagi |
|---|---|---|---|
| `logical_sessions_enabled` | `LOCAL_SHELL_MCP_LOGICAL_SESSIONS_ENABLED` | `True` | Udostępnia `session_manage` i `plan_manage` oraz dodaje do zwykłych narzędzi MCP wymagany, ale nullable argument `logical_session_id`. Wyłącz, aby uzyskać mniejszy tool surface bez Sessions. |
| `live_workspace_enabled` | `LOCAL_SHELL_MCP_LIVE_WORKSPACE_ENABLED` | `True` | Udostępnia tools, resources i trasy `/api/live/*` MCP App Live Workspace. Wymaga `ui_enabled` i nie jest dostępny w trybie `stdio`. |
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `True` | Mountuje native OpenTUI launcher, WebUI shell, PTY WebSocket i routes `/api/ui/*`. |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `'/ui'` | WebUI mount path na tym samym service. |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | `None` | Optional command override dla OpenTUI executable resolution. |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `'bing'` | `bing`, `aurora` lub `none`. |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | Inactive browser PTY timeout; `0` wyłącza. |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | Maximum concurrent browser OpenTUI PTYs. |

### Remote workers

| YAML key | Environment variable | Default | Uwagi |
|---|---|---|---|
| `remote_enabled` | `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `True` | Kontroluje `/join`, `/remote/*` i MCP tools `remote_*`. |
| `remote_invite_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_INVITE_TTL_S` | `7200` |  |
| `remote_poll_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S` | `25` |  |
| `remote_job_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S` | `3600` |  |
| `remote_max_pending_jobs` | `LOCAL_SHELL_MCP_REMOTE_MAX_PENDING_JOBS` | `256` | Maximum queued/pending jobs na worker. |
| `remote_cancelled_job_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_CANCELLED_JOB_TTL_S` | `3600` | Retention time cancellation tombstones używanych do pomijania timed-out queued jobs. |
| `remote_transfer_strategy` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_STRATEGY` | `'auto'` | `auto`, `relay`, `direct` lub `object_store`. `auto` próbuje enabled peer-direct, configured S3, a następnie bounded-memory controller relay. |
| `remote_peer_transfer_enabled` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ENABLED` | `False` | Optional włącza one-shot HTTP receiver na destination worker dla direct worker-to-worker transfer. Włączaj tylko w trusted private network, np. VPC/Tailscale. |
| `remote_peer_transfer_bind_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_BIND_HOST` | `'0.0.0.0'` | Bind address one-shot receiver na destination worker. |
| `remote_peer_transfer_advertise_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ADVERTISE_HOST` | `None` | Address advertised source worker; default destination worker hostname/FQDN. |
| `remote_peer_transfer_port` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_PORT` | `0` | Receiver port; `0` wybiera ephemeral port. |
| `remote_peer_transfer_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_TIMEOUT_S` | `3600` | Lifetime/timeout one-shot direct receiver. |
| `remote_transfer_s3_bucket` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_BUCKET` | `None` | Optional S3-compatible bucket dla presigned worker-to-worker transfers. Wymaga extra `s3`. |
| `remote_transfer_s3_prefix` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PREFIX` | `'local-shell-mcp'` | Object-key prefix dla temporary transfer objects. |
| `remote_transfer_s3_region` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_REGION` | `None` | Optional S3 region. |
| `remote_transfer_s3_endpoint_url` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_ENDPOINT_URL` | `None` | Optional S3-compatible endpoint URL. |
| `remote_transfer_s3_presign_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PRESIGN_TTL_S` | `3600` | Presigned PUT/GET URL lifetime. Temporary objects są usuwane po transfer. |

### Shell i executable paths

| YAML key | Environment variable | Default | Uwagi |
|---|---|---|---|
| `shell_executable` | `LOCAL_SHELL_MCP_SHELL_EXECUTABLE` | `'/bin/bash'` |  |
| `shell_env_blocklist` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKLIST` | `['CLOUDFLARE_TUNNEL_TOKEN']` |  |
| `shell_env_blocked_prefixes` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKED_PREFIXES` | `['LOCAL_SHELL_MCP_', 'DOCKER_']` | Comma-separated w environment variables; list w YAML. |
| `tmux_bin` | `LOCAL_SHELL_MCP_TMUX_BIN` | `'tmux'` | Preferred tmux executable. Jeśli niedostępny, Linux releases i Docker builds używają bundled helper; w przeciwnym razie persistent shells fallback do native backend. |
| `rg_bin` | `LOCAL_SHELL_MCP_RG_BIN` | `'rg'` |  |
| `git_bin` | `LOCAL_SHELL_MCP_GIT_BIN` | `'git'` |  |
| `python_bin` | `LOCAL_SHELL_MCP_PYTHON_BIN` | `'python3'` |  |

### Authentication i OAuth

| YAML key | Environment variable | Default | Uwagi |
|---|---|---|---|
| `auth_mode` | `LOCAL_SHELL_MCP_AUTH_MODE` | `'oauth'` | Używaj `oauth` dla public deployments. |
| `auth_bypass_localhost` | `LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST` | `True` |  |
| `require_auth_for_mcp_discovery` | `LOCAL_SHELL_MCP_REQUIRE_AUTH_FOR_MCP_DISCOVERY` | `True` | Wymaga OAuth przed MCP initialization i tool discovery. |
| `mcp_session_idle_timeout_s` | `LOCAL_SHELL_MCP_MCP_SESSION_IDLE_TIMEOUT_S` | `180` | Idle timeout dla Stateful Streamable HTTP sessions. |
| `mcp_max_sessions` | `LOCAL_SHELL_MCP_MCP_MAX_SESSIONS` | `1024` | Maximum concurrent stateful MCP sessions. |
| `public_base_url` | `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | `None` | External HTTPS origin. Nie zawieraj `/mcp`. |
| `oauth_issuer` | `LOCAL_SHELL_MCP_OAUTH_ISSUER` | `None` |  |
| `oauth_resource` | `LOCAL_SHELL_MCP_OAUTH_RESOURCE` | `None` |  |
| `oauth_admin_pin` | `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` | `None` |  |
| `oauth_jwt_secret` | `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` | <generated or configured> |  |
| `oauth_access_token_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S` | `0` | `0` oznacza, że access tokens nie expire automatycznie. |
| `oauth_code_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_CODE_TTL_S` | `300` |  |

### Built-in policy lists

| YAML key | Environment variable | Default | Uwagi |
|---|---|---|---|
| `command_denylist` | `LOCAL_SHELL_MCP_COMMAND_DENYLIST` | `[]` | Automatycznie clear przy enabled full-container mode. |
| `path_denylist` | `LOCAL_SHELL_MCP_PATH_DENYLIST` | `[]` | Automatycznie clear przy enabled full-container mode. |

## Przykład YAML

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

Serverless controller z durable Redis state:

```yaml
mode: mcp
stateless_controller: true
state_backend: redis
state_backend_url: redis://redis.internal:6379/0
remote_transfer_strategy: auto
```

`stateless_controller` usuwa potrzebę persistent controller volume. Backend `memory` jest celowo ephemeral: cold start invaliduje pending remote invites i worker identities oraz usuwa OAuth clients, jobs i audit records. Użyj Redis, gdy taki state musi przetrwać cold starts, w tym durable worker revocation semantics. Przy default `auth_mode=oauth` inject co najmniej 32 bytes random key material przez `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET`. Active remote RPC queues/futures są process-local, więc deployments używające remote workers powinny obecnie uruchamiać jedną active controller instance zamiast wielu load-balanced controller replicas.

## Wskazówki operacyjne

- Trzymaj `allow_full_container=false`, chyba że container/VM jest disposable.
- Trzymaj `auth_mode=oauth` dla każdego public endpoint.
- Wyłącz `remote_enabled`, jeśli nie używasz remote workers.
- Wyłącz `file_download_enabled`, jeśli nie potrzebujesz chat-downloadable artifacts.
- Ustaw command/file/audit limits wystarczająco wysoko dla coding tasks, ale wystarczająco nisko przeciw accidental runaway output.
