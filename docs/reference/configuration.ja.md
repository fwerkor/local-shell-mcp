<!-- i18n-source-sha256: 5d2de552ba0ba0d1c76319ad9f87ab68e217fee6c607687f8260e14872e7dbcc -->
# 設定

Repository にはコピー可能な starter file [`.env.example`](https://github.com/fwerkor/local-shell-mcp/blob/main/.env.example) が含まれます。Docker Compose は作成した `.env` を自動的に読み取り、他の runtime でも同じ `LOCAL_SHELL_MCP_` environment variables を使用できます。YAML は binary/source deployment 向けの optional advanced input です。File を明示的に作成し、`LOCAL_SHELL_MCP_CONFIG` または `--config` で選択します。Environment variables は YAML values を override するため、意図的な override でない限り同じ setting を両方に定義しないでください。YAML keys は以下の field names を使います。

## 優先順位

1. `Settings` の built-in defaults。
2. `LOCAL_SHELL_MCP_CONFIG` または `--config` で選択された YAML config。
3. `LOCAL_SHELL_MCP_` prefix の environment variables。
4. `--mode`、`--config`、`--remote`、`--no-remote` などの CLI flags。Settings load 前に対応する environment values を設定します。

## 最小 public configuration

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-long-random-secret
```

Local-only testing では `auth_bypass_localhost` が default で有効です。Unauthenticated full MCP tools を public network に公開しないでください。

## Settings reference

### Server と workspace

| YAML key | Environment variable | Default | Notes |
|---|---|---|---|
| `host` | `LOCAL_SHELL_MCP_HOST` | `'0.0.0.0'` |  |
| `port` | `LOCAL_SHELL_MCP_PORT` | `8765` |  |
| `forwarded_allow_ips` | `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS` | `'127.0.0.1'` | Uvicorn forwarded-header handling で信頼する proxy IP の comma-separated list。Direct ingress が制限されている場合のみ `*` を使用します。 |
| `mode` | `LOCAL_SHELL_MCP_MODE` | `'mcp'` | `mcp`、`http`、`stdio`、または予約済みの `both` 値。 |
| `workspace_root` | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | `PosixPath('/workspace')` |  |
| `state_dir` | `LOCAL_SHELL_MCP_STATE_DIR` | `PosixPath('/workspace/.local-shell-mcp')` |  |
| `audit_log_path` | `LOCAL_SHELL_MCP_AUDIT_LOG_PATH` | `PosixPath('/workspace/.local-shell-mcp/audit.jsonl')` |  |
| `agent_config_dir` | `LOCAL_SHELL_MCP_AGENT_CONFIG_DIR` | `PosixPath('/workspace/.local-shell-mcp/agent_config')` |  |
| `allow_full_container` | `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER` | `False` | True のとき workspace/path restrictions を無効化します。Disposable boundary 内だけで使用してください。 |
| `disable_local` | `LOCAL_SHELL_MCP_DISABLE_LOCAL` | `False` | Controller host を shell/file/browser execution target として無効化します。Remote workers と control-plane services は引き続き利用できます。 |
| `stateless_controller` | `LOCAL_SHELL_MCP_STATELESS_CONTROLLER` | `False` | Controller を ephemeral/serverless instances 向けにします。`disable_local` を含み、local file links/wallpaper caching を無効化し、`state_backend` は default で `memory` になります。Default `auth_mode=oauth` では強い `oauth_jwt_secret` を明示設定してください。 |
| `state_backend` | `LOCAL_SHELL_MCP_STATE_BACKEND` | `'file'` | `file`、`memory`、`redis`。Serverless controller state を cold start 後も保持する必要がある場合は Redis を使用します。 |
| `state_backend_url` | `LOCAL_SHELL_MCP_STATE_BACKEND_URL` | `None` | `state_backend=redis` 時の Redis connection URL。Diagnostics では redacted されます。 |
| `state_backend_prefix` | `LOCAL_SHELL_MCP_STATE_BACKEND_PREFIX` | `'local-shell-mcp'` | Memory/Redis control-plane state の namespace。 |

### 制限

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
| `max_skills` | `LOCAL_SHELL_MCP_MAX_SKILLS` | `256` | 1 回の registry scan で返す Skill directories の上限。 |
| `max_skill_related_files` | `LOCAL_SHELL_MCP_MAX_SKILL_RELATED_FILES` | `1000` | 1 Skill について返す related files の上限。 |
| `max_skill_scan_entries` | `LOCAL_SHELL_MCP_MAX_SKILL_SCAN_ENTRIES` | `5000` | 1 回の `skill_list` registry scan または direct Skill load で調査する filesystem entries の上限。 |
| `max_skill_path_bytes` | `LOCAL_SHELL_MCP_MAX_SKILL_PATH_BYTES` | `200000` | 返却する related-file paths に使用する UTF-8 bytes の上限。 |
| `max_read_many_files` | `LOCAL_SHELL_MCP_MAX_READ_MANY_FILES` | `100` |  |
| `max_read_many_total_bytes` | `LOCAL_SHELL_MCP_MAX_READ_MANY_TOTAL_BYTES` | `5000000` |  |
| `max_http_request_bytes` | `LOCAL_SHELL_MCP_MAX_HTTP_REQUEST_BYTES` | `16000000` | MCP、REST、OAuth、UI、remote-worker endpoints 全体で buffering する HTTP request body の上限。 |
| `max_job_log_bytes` | `LOCAL_SHELL_MCP_MAX_JOB_LOG_BYTES` | `10000000` | 各 long-running job attempt で保持する output bytes の上限。 |
| `max_jobs` | `LOCAL_SHELL_MCP_MAX_JOBS` | `1000` | 保持する long-running job records の上限。Active jobs は prune されません。 |
| `max_audit_tail_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES` | `1000000` |  |
| `max_audit_log_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES` | `20000000` |  |
| `max_audit_archive_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_ARCHIVE_BYTES` | `512000000` |  |
| `max_tmp_files` | `LOCAL_SHELL_MCP_MAX_TMP_FILES` | `500` |  |
| `max_tmp_bytes` | `LOCAL_SHELL_MCP_MAX_TMP_BYTES` | `50000000` |  |
| `max_transfer_archive_entries` | `LOCAL_SHELL_MCP_MAX_TRANSFER_ARCHIVE_ENTRIES` | `100000` | Transferred directory archive の unpack 時に受け入れる entries の上限。 |
| `max_transfer_unpacked_bytes` | `LOCAL_SHELL_MCP_MAX_TRANSFER_UNPACKED_BYTES` | `10000000000` | Transferred directory archive で受け入れる declared expanded bytes の上限。 |
| `max_concurrent_commands` | `LOCAL_SHELL_MCP_MAX_CONCURRENT_COMMANDS` | `4` |  |
| `max_tmux_sessions` | `LOCAL_SHELL_MCP_MAX_TMUX_SESSIONS` | `16` | tmux、ConPTY、native fallback backends 全体の persistent shell sessions 上限。 |

### File links

| YAML key | Environment variable | Default | Notes |
|---|---|---|---|
| `file_download_enabled` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED` | `True` |  |
| `file_download_default_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_TTL_S` | `3600` |  |
| `file_download_max_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_TTL_S` | `604800` |  |
| `file_download_default_max_downloads` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_MAX_DOWNLOADS` | `0` | `0` は default download-count limit なし。 |
| `file_download_max_file_bytes` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_FILE_BYTES` | `0` | `0` は download link の configured file-size cap なし。 |

### Human interface

| YAML key | Environment variable | Default | Notes |
|---|---|---|---|
| `logical_sessions_enabled` | `LOCAL_SHELL_MCP_LOGICAL_SESSIONS_ENABLED` | `True` | `session_manage` と `plan_manage` を公開し、通常の MCP tools に required nullable の `logical_session_id` 引数を追加します。無効化すると Session なしの小さい tool surface になります。 |
| `live_workspace_enabled` | `LOCAL_SHELL_MCP_LIVE_WORKSPACE_ENABLED` | `True` | MCP App Live Workspace の tools、resources、`/api/live/*` routes を公開します。`ui_enabled` が必要で、`stdio` mode では利用できません。 |
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `True` | Native OpenTUI launcher、WebUI shell、PTY WebSocket、`/api/ui/*` routes を mount します。 |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `'/ui'` | 同一 service 上の WebUI mount path。 |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | `None` | OpenTUI executable resolution の optional command override。 |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `'bing'` | `bing`、`aurora`、`none`。 |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | Inactive browser PTY timeout。`0` で無効化します。 |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | Concurrent browser OpenTUI PTYs の上限。 |

### Remote workers

| YAML key | Environment variable | Default | Notes |
|---|---|---|---|
| `remote_enabled` | `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `True` | `/join`、`/remote/*`、`remote_*` MCP tools を制御します。 |
| `remote_invite_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_INVITE_TTL_S` | `7200` |  |
| `remote_poll_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S` | `25` |  |
| `remote_job_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S` | `3600` |  |
| `remote_max_pending_jobs` | `LOCAL_SHELL_MCP_REMOTE_MAX_PENDING_JOBS` | `256` | Worker ごとの queued/pending jobs 上限。 |
| `remote_cancelled_job_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_CANCELLED_JOB_TTL_S` | `3600` | Timed-out queued jobs を skip する cancellation tombstones の retention time。 |
| `remote_transfer_strategy` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_STRATEGY` | `'auto'` | `auto`、`relay`、`direct`、`object_store`。`auto` は enabled peer-direct、configured S3、bounded-memory controller relay の順に試行します。 |
| `remote_peer_transfer_enabled` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ENABLED` | `False` | Destination worker で one-shot HTTP receiver を有効化し、worker-to-worker direct transfer を行います。VPC/Tailscale など trusted private network のみで有効化してください。 |
| `remote_peer_transfer_bind_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_BIND_HOST` | `'0.0.0.0'` | One-shot destination-worker receiver の bind address。 |
| `remote_peer_transfer_advertise_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ADVERTISE_HOST` | `None` | Source worker に advertise する address。Default は destination worker hostname/FQDN。 |
| `remote_peer_transfer_port` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_PORT` | `0` | Receiver port。`0` は ephemeral port を選択します。 |
| `remote_peer_transfer_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_TIMEOUT_S` | `3600` | One-shot direct receiver の lifetime/timeout。 |
| `remote_transfer_s3_bucket` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_BUCKET` | `None` | Presigned worker-to-worker transfers 用の optional S3-compatible bucket。`s3` extra が必要です。 |
| `remote_transfer_s3_prefix` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PREFIX` | `'local-shell-mcp'` | Temporary transfer objects の object-key prefix。 |
| `remote_transfer_s3_region` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_REGION` | `None` | Optional S3 region。 |
| `remote_transfer_s3_endpoint_url` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_ENDPOINT_URL` | `None` | Optional S3-compatible endpoint URL。 |
| `remote_transfer_s3_presign_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PRESIGN_TTL_S` | `3600` | Presigned PUT/GET URL lifetime。Transfer 後に temporary objects を削除します。 |

### Shell と executable paths

| YAML key | Environment variable | Default | Notes |
|---|---|---|---|
| `shell_executable` | `LOCAL_SHELL_MCP_SHELL_EXECUTABLE` | `'/bin/bash'` |  |
| `shell_env_blocklist` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKLIST` | `['CLOUDFLARE_TUNNEL_TOKEN']` |  |
| `shell_env_blocked_prefixes` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKED_PREFIXES` | `['LOCAL_SHELL_MCP_', 'DOCKER_']` | Environment variables では comma-separated、YAML では list。 |
| `tmux_bin` | `LOCAL_SHELL_MCP_TMUX_BIN` | `'tmux'` | Preferred tmux executable。Unavailable の場合 Linux release/Docker build は bundled helper を使い、それ以外では persistent shells が native backend に fallback します。 |
| `rg_bin` | `LOCAL_SHELL_MCP_RG_BIN` | `'rg'` |  |
| `git_bin` | `LOCAL_SHELL_MCP_GIT_BIN` | `'git'` |  |
| `python_bin` | `LOCAL_SHELL_MCP_PYTHON_BIN` | `'python3'` |  |

### 認証と OAuth

| YAML key | Environment variable | Default | Notes |
|---|---|---|---|
| `auth_mode` | `LOCAL_SHELL_MCP_AUTH_MODE` | `'oauth'` | Public deployments では `oauth` を使用します。 |
| `auth_bypass_localhost` | `LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST` | `True` |  |
| `require_auth_for_mcp_discovery` | `LOCAL_SHELL_MCP_REQUIRE_AUTH_FOR_MCP_DISCOVERY` | `True` | MCP initialization/tool discovery 前に OAuth を要求します。 |
| `mcp_session_idle_timeout_s` | `LOCAL_SHELL_MCP_MCP_SESSION_IDLE_TIMEOUT_S` | `180` | Stateful Streamable HTTP sessions の idle timeout。 |
| `mcp_max_sessions` | `LOCAL_SHELL_MCP_MCP_MAX_SESSIONS` | `1024` | Concurrent stateful MCP sessions の上限。 |
| `public_base_url` | `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | `None` | External HTTPS origin。`/mcp` を含めません。 |
| `oauth_issuer` | `LOCAL_SHELL_MCP_OAUTH_ISSUER` | `None` |  |
| `oauth_resource` | `LOCAL_SHELL_MCP_OAUTH_RESOURCE` | `None` |  |
| `oauth_admin_pin` | `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` | `None` |  |
| `oauth_jwt_secret` | `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` | <generated or configured> |  |
| `oauth_access_token_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S` | `0` | `0` は access tokens が自動 expiration しないことを意味します。 |
| `oauth_code_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_CODE_TTL_S` | `300` |  |

### Built-in policy lists

| YAML key | Environment variable | Default | Notes |
|---|---|---|---|
| `command_denylist` | `LOCAL_SHELL_MCP_COMMAND_DENYLIST` | `[]` | Full-container mode 有効時に自動的に clear されます。 |
| `path_denylist` | `LOCAL_SHELL_MCP_PATH_DENYLIST` | `[]` | Full-container mode 有効時に自動的に clear されます。 |

## YAML 例

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

Durable Redis state を持つ serverless controller：

```yaml
mode: mcp
stateless_controller: true
state_backend: redis
state_backend_url: redis://redis.internal:6379/0
remote_transfer_strategy: auto
```

`stateless_controller` は persistent controller volume を不要にします。`memory` backend は意図的に ephemeral で、cold start により pending remote invites と worker identities が invalid になり、OAuth clients、jobs、audit records が失われます。これらの state（durable worker revocation semantics を含む）を cold start 後も保持する必要がある場合は Redis を使用してください。Default `auth_mode=oauth` では、少なくとも 32 bytes の random key material を `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` で注入します。Active remote RPC queues/futures は process-local なので、remote workers を使う deployment は現在 1 つの active controller instance を実行し、複数の load-balanced controller replicas は避けてください。

## 運用アドバイス

- Container/VM が disposable でない限り `allow_full_container=false` を維持します。
- Public endpoint では `auth_mode=oauth` を維持します。
- Remote workers を使わないなら `remote_enabled` を無効化します。
- Chat-downloadable artifacts が不要なら `file_download_enabled` を無効化します。
- Command/file/audit limits は coding tasks に十分な大きさとしつつ、accidental runaway output を抑えられる範囲にします。
