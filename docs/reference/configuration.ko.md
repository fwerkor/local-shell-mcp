<!-- i18n-source-sha256: 5d2de552ba0ba0d1c76319ad9f87ab68e217fee6c607687f8260e14872e7dbcc -->
# 구성

Repository에는 복사 가능한 시작 파일 [`.env.example`](https://github.com/fwerkor/local-shell-mcp/blob/main/.env.example)이 포함됩니다. Docker Compose는 생성된 `.env`를 자동으로 읽고, 다른 runtime도 동일한 `LOCAL_SHELL_MCP_` environment variables를 사용할 수 있습니다. YAML은 binary 또는 source deployment를 위한 optional advanced input입니다. 파일을 명시적으로 만들고 `LOCAL_SHELL_MCP_CONFIG` 또는 `--config`로 선택합니다. Environment variables가 YAML values를 override하므로 의도적인 override가 아니라면 같은 setting을 두 곳에 정의하지 마십시오. YAML keys는 아래 field names를 사용합니다.

## 우선순위

1. `Settings`의 built-in defaults.
2. `LOCAL_SHELL_MCP_CONFIG` 또는 `--config`로 선택한 YAML config.
3. `LOCAL_SHELL_MCP_` prefix environment variables.
4. `--mode`, `--config`, `--remote`, `--no-remote` 같은 CLI flags. Settings load 전에 대응 environment values를 설정합니다.

## 최소 public configuration

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-long-random-secret
```

Local-only testing에서는 `auth_bypass_localhost`가 기본 활성화됩니다. Unauthenticated full MCP tools를 public network에 노출하지 마십시오.

## Settings reference

### Server 및 workspace

| YAML key | Environment variable | Default | Notes |
|---|---|---|---|
| `host` | `LOCAL_SHELL_MCP_HOST` | `'0.0.0.0'` |  |
| `port` | `LOCAL_SHELL_MCP_PORT` | `8765` |  |
| `forwarded_allow_ips` | `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS` | `'127.0.0.1'` | Uvicorn forwarded-header handling에서 신뢰할 proxy IP의 comma-separated list. Direct ingress가 제한된 경우에만 `*`를 사용합니다. |
| `mode` | `LOCAL_SHELL_MCP_MODE` | `'mcp'` | `mcp`, `http`, `stdio` 또는 예약된 `both` 값. |
| `workspace_root` | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | `PosixPath('/workspace')` |  |
| `state_dir` | `LOCAL_SHELL_MCP_STATE_DIR` | `PosixPath('/workspace/.local-shell-mcp')` |  |
| `audit_log_path` | `LOCAL_SHELL_MCP_AUDIT_LOG_PATH` | `PosixPath('/workspace/.local-shell-mcp/audit.jsonl')` |  |
| `agent_config_dir` | `LOCAL_SHELL_MCP_AGENT_CONFIG_DIR` | `PosixPath('/workspace/.local-shell-mcp/agent_config')` |  |
| `allow_full_container` | `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER` | `False` | True이면 workspace/path restrictions를 비활성화합니다. Disposable boundary 안에서만 사용하십시오. |
| `disable_local` | `LOCAL_SHELL_MCP_DISABLE_LOCAL` | `False` | Controller host를 shell/file/browser execution target으로 비활성화합니다. Remote workers와 control-plane services는 계속 사용할 수 있습니다. |
| `stateless_controller` | `LOCAL_SHELL_MCP_STATELESS_CONTROLLER` | `False` | Controller를 ephemeral/serverless instances에 적합하게 합니다. `disable_local`을 포함하고 local file links/wallpaper caching을 비활성화하며 `state_backend`를 기본 `memory`로 둡니다. Default `auth_mode=oauth`에서는 강한 `oauth_jwt_secret`을 명시 설정하십시오. |
| `state_backend` | `LOCAL_SHELL_MCP_STATE_BACKEND` | `'file'` | `file`, `memory`, `redis`. Serverless controller state가 cold start 이후에도 유지되어야 하면 Redis를 사용합니다. |
| `state_backend_url` | `LOCAL_SHELL_MCP_STATE_BACKEND_URL` | `None` | `state_backend=redis`의 Redis connection URL. Diagnostics에서는 redacted됩니다. |
| `state_backend_prefix` | `LOCAL_SHELL_MCP_STATE_BACKEND_PREFIX` | `'local-shell-mcp'` | Memory/Redis control-plane state namespace. |

### 제한

| YAML key | Environment variable | Default | Notes |
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
| `max_skills` | `LOCAL_SHELL_MCP_MAX_SKILLS` | `256` | 한 registry scan에서 반환하는 Skill directories 최대 수. |
| `max_skill_related_files` | `LOCAL_SHELL_MCP_MAX_SKILL_RELATED_FILES` | `1000` | 한 Skill에서 반환하는 related files 최대 수. |
| `max_skill_scan_entries` | `LOCAL_SHELL_MCP_MAX_SKILL_SCAN_ENTRIES` | `5000` | 한 `skill_list` registry scan 또는 direct Skill load에서 검사하는 filesystem entries 최대 수. |
| `max_skill_path_bytes` | `LOCAL_SHELL_MCP_MAX_SKILL_PATH_BYTES` | `200000` | 반환 related-file paths에 사용하는 UTF-8 bytes 최대치. |
| `max_read_many_files` | `LOCAL_SHELL_MCP_MAX_READ_MANY_FILES` | `100` |  |
| `max_read_many_total_bytes` | `LOCAL_SHELL_MCP_MAX_READ_MANY_TOTAL_BYTES` | `5000000` |  |
| `max_http_request_bytes` | `LOCAL_SHELL_MCP_MAX_HTTP_REQUEST_BYTES` | `16000000` | MCP, REST, OAuth, UI, remote-worker endpoints 전체에서 buffering하는 HTTP request body 최대치. |
| `max_job_log_bytes` | `LOCAL_SHELL_MCP_MAX_JOB_LOG_BYTES` | `10000000` | 각 long-running job attempt에서 유지하는 output bytes 최대치. |
| `max_jobs` | `LOCAL_SHELL_MCP_MAX_JOBS` | `1000` | 유지할 long-running job records 최대치. Active jobs는 prune하지 않습니다. |
| `max_audit_tail_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES` | `1000000` |  |
| `max_audit_log_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES` | `20000000` |  |
| `max_audit_archive_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_ARCHIVE_BYTES` | `512000000` |  |
| `max_tmp_files` | `LOCAL_SHELL_MCP_MAX_TMP_FILES` | `500` |  |
| `max_tmp_bytes` | `LOCAL_SHELL_MCP_MAX_TMP_BYTES` | `50000000` |  |
| `max_transfer_archive_entries` | `LOCAL_SHELL_MCP_MAX_TRANSFER_ARCHIVE_ENTRIES` | `100000` | Transferred directory archive unpack 시 허용할 entries 최대치. |
| `max_transfer_unpacked_bytes` | `LOCAL_SHELL_MCP_MAX_TRANSFER_UNPACKED_BYTES` | `10000000000` | Transferred directory archive에서 허용할 declared expanded bytes 최대치. |
| `max_concurrent_commands` | `LOCAL_SHELL_MCP_MAX_CONCURRENT_COMMANDS` | `4` |  |
| `max_tmux_sessions` | `LOCAL_SHELL_MCP_MAX_TMUX_SESSIONS` | `16` | tmux, ConPTY, native fallback backends 전체 persistent shell sessions 최대치. |

### File links

| YAML key | Environment variable | Default | Notes |
|---|---|---|---|
| `file_download_enabled` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED` | `True` |  |
| `file_download_default_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_TTL_S` | `3600` |  |
| `file_download_max_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_TTL_S` | `604800` |  |
| `file_download_default_max_downloads` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_MAX_DOWNLOADS` | `0` | `0`은 default download-count limit 없음. |
| `file_download_max_file_bytes` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_FILE_BYTES` | `0` | `0`은 download link의 configured file-size cap 없음. |

### Human interface

| YAML key | Environment variable | Default | Notes |
|---|---|---|---|
| `logical_sessions_enabled` | `LOCAL_SHELL_MCP_LOGICAL_SESSIONS_ENABLED` | `True` | `session_manage`와 `plan_manage`를 노출하고 일반 MCP tools에 필수이지만 null을 허용하는 `logical_session_id` 인수를 추가합니다. 끄면 Session 없는 더 작은 tool surface가 됩니다. |
| `live_workspace_enabled` | `LOCAL_SHELL_MCP_LIVE_WORKSPACE_ENABLED` | `True` | MCP App Live Workspace의 tools, resources 및 `/api/live/*` routes를 노출합니다. `ui_enabled`가 필요하며 `stdio` mode에서는 사용할 수 없습니다. |
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `True` | Native OpenTUI launcher, WebUI shell, PTY WebSocket, `/api/ui/*` routes를 mount합니다. |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `'/ui'` | 같은 service의 WebUI mount path. |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | `None` | OpenTUI executable resolution optional command override. |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `'bing'` | `bing`, `aurora`, `none`. |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | Inactive browser PTY timeout. `0`은 비활성화. |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | Concurrent browser OpenTUI PTYs 최대치. |

### Remote workers

| YAML key | Environment variable | Default | Notes |
|---|---|---|---|
| `remote_enabled` | `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `True` | `/join`, `/remote/*`, `remote_*` MCP tools를 제어합니다. |
| `remote_invite_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_INVITE_TTL_S` | `7200` |  |
| `remote_poll_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S` | `25` |  |
| `remote_job_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S` | `3600` |  |
| `remote_max_pending_jobs` | `LOCAL_SHELL_MCP_REMOTE_MAX_PENDING_JOBS` | `256` | Worker당 queued/pending jobs 최대치. |
| `remote_cancelled_job_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_CANCELLED_JOB_TTL_S` | `3600` | Timed-out queued jobs를 skip하기 위한 cancellation tombstones retention time. |
| `remote_transfer_strategy` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_STRATEGY` | `'auto'` | `auto`, `relay`, `direct`, `object_store`. `auto`는 enabled peer-direct, configured S3, bounded-memory controller relay 순으로 시도합니다. |
| `remote_peer_transfer_enabled` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ENABLED` | `False` | Destination worker의 one-shot HTTP receiver를 활성화해 worker-to-worker direct transfer를 수행합니다. VPC/Tailscale 같은 trusted private network에서만 활성화하십시오. |
| `remote_peer_transfer_bind_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_BIND_HOST` | `'0.0.0.0'` | One-shot destination-worker receiver bind address. |
| `remote_peer_transfer_advertise_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ADVERTISE_HOST` | `None` | Source worker에 advertise하는 address. Default는 destination worker hostname/FQDN. |
| `remote_peer_transfer_port` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_PORT` | `0` | Receiver port. `0`은 ephemeral port를 선택합니다. |
| `remote_peer_transfer_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_TIMEOUT_S` | `3600` | One-shot direct receiver lifetime/timeout. |
| `remote_transfer_s3_bucket` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_BUCKET` | `None` | Presigned worker-to-worker transfers용 optional S3-compatible bucket. `s3` extra가 필요합니다. |
| `remote_transfer_s3_prefix` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PREFIX` | `'local-shell-mcp'` | Temporary transfer objects의 object-key prefix. |
| `remote_transfer_s3_region` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_REGION` | `None` | Optional S3 region. |
| `remote_transfer_s3_endpoint_url` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_ENDPOINT_URL` | `None` | Optional S3-compatible endpoint URL. |
| `remote_transfer_s3_presign_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PRESIGN_TTL_S` | `3600` | Presigned PUT/GET URL lifetime. Transfer 후 temporary objects를 삭제합니다. |

### Shell 및 executable paths

| YAML key | Environment variable | Default | Notes |
|---|---|---|---|
| `shell_executable` | `LOCAL_SHELL_MCP_SHELL_EXECUTABLE` | `'/bin/bash'` |  |
| `shell_env_blocklist` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKLIST` | `['CLOUDFLARE_TUNNEL_TOKEN']` |  |
| `shell_env_blocked_prefixes` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKED_PREFIXES` | `['LOCAL_SHELL_MCP_', 'DOCKER_']` | Environment variables에서는 comma-separated, YAML에서는 list. |
| `tmux_bin` | `LOCAL_SHELL_MCP_TMUX_BIN` | `'tmux'` | Preferred tmux executable. 사용할 수 없으면 Linux release/Docker build는 bundled helper를 사용하고, 그 외에는 persistent shells가 native backend로 fallback합니다. |
| `rg_bin` | `LOCAL_SHELL_MCP_RG_BIN` | `'rg'` |  |
| `git_bin` | `LOCAL_SHELL_MCP_GIT_BIN` | `'git'` |  |
| `python_bin` | `LOCAL_SHELL_MCP_PYTHON_BIN` | `'python3'` |  |

### 인증 및 OAuth

| YAML key | Environment variable | Default | Notes |
|---|---|---|---|
| `auth_mode` | `LOCAL_SHELL_MCP_AUTH_MODE` | `'oauth'` | Public deployments에서는 `oauth`를 사용합니다. |
| `auth_bypass_localhost` | `LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST` | `True` |  |
| `require_auth_for_mcp_discovery` | `LOCAL_SHELL_MCP_REQUIRE_AUTH_FOR_MCP_DISCOVERY` | `True` | MCP initialization/tool discovery 전에 OAuth를 요구합니다. |
| `mcp_session_idle_timeout_s` | `LOCAL_SHELL_MCP_MCP_SESSION_IDLE_TIMEOUT_S` | `180` | Stateful Streamable HTTP sessions idle timeout. |
| `mcp_max_sessions` | `LOCAL_SHELL_MCP_MCP_MAX_SESSIONS` | `1024` | Concurrent stateful MCP sessions 최대치. |
| `public_base_url` | `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | `None` | External HTTPS origin. `/mcp`는 포함하지 않습니다. |
| `oauth_issuer` | `LOCAL_SHELL_MCP_OAUTH_ISSUER` | `None` |  |
| `oauth_resource` | `LOCAL_SHELL_MCP_OAUTH_RESOURCE` | `None` |  |
| `oauth_admin_pin` | `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` | `None` |  |
| `oauth_jwt_secret` | `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` | <generated or configured> |  |
| `oauth_access_token_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S` | `0` | `0`은 access tokens가 자동 expire하지 않음을 뜻합니다. |
| `oauth_code_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_CODE_TTL_S` | `300` |  |

### Built-in policy lists

| YAML key | Environment variable | Default | Notes |
|---|---|---|---|
| `command_denylist` | `LOCAL_SHELL_MCP_COMMAND_DENYLIST` | `[]` | Full-container mode 활성화 시 자동 clear됩니다. |
| `path_denylist` | `LOCAL_SHELL_MCP_PATH_DENYLIST` | `[]` | Full-container mode 활성화 시 자동 clear됩니다. |

## YAML 예제

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

Durable Redis state를 사용하는 serverless controller:

```yaml
mode: mcp
stateless_controller: true
state_backend: redis
state_backend_url: redis://redis.internal:6379/0
remote_transfer_strategy: auto
```

`stateless_controller`는 persistent controller volume 필요를 제거합니다. `memory` backend는 의도적으로 ephemeral하여 cold start 시 pending remote invites와 worker identities가 무효화되고 OAuth clients, jobs, audit records가 사라집니다. 이런 state가 durable worker revocation semantics를 포함해 cold start 이후에도 유지되어야 한다면 Redis를 사용하십시오. Default `auth_mode=oauth`에서는 최소 32 bytes random key material을 `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET`로 주입하십시오. Active remote RPC queues/futures는 process-local이므로 remote workers를 쓰는 deployment는 현재 하나의 active controller instance만 실행하고 여러 load-balanced controller replicas는 피해야 합니다.

## 운영 조언

- Container/VM이 disposable이 아니면 `allow_full_container=false`를 유지합니다.
- Public endpoint에서는 `auth_mode=oauth`를 유지합니다.
- Remote workers를 쓰지 않으면 `remote_enabled`를 비활성화합니다.
- Chat-downloadable artifacts가 필요 없으면 `file_download_enabled`를 비활성화합니다.
- Command/file/audit limits는 coding tasks에 충분하면서 accidental runaway output을 막을 만큼 낮게 설정합니다.
