<!-- i18n-source-sha256: 5d2de552ba0ba0d1c76319ad9f87ab68e217fee6c607687f8260e14872e7dbcc -->
# Yapılandırma

Repository tek bir kopyalanabilir başlangıç dosyası sağlar: [`.env.example`](https://github.com/fwerkor/local-shell-mcp/blob/main/.env.example). Docker Compose oluşan `.env` dosyasını otomatik okur; diğer runtimes da aynı `LOCAL_SHELL_MCP_` environment variables değerlerini kullanabilir. YAML binary/source deployments için optional advanced input olarak kalır; dosyayı explicit oluşturup `LOCAL_SHELL_MCP_CONFIG` veya `--config` ile seçin. Environment variables YAML values değerlerini override eder; override bilinçli değilse aynı setting’i iki yerde tanımlamayın. YAML keys aşağıdaki field names değerlerini kullanır.

## Öncelik

1. `Settings` içindeki built-in defaults.
2. `LOCAL_SHELL_MCP_CONFIG` veya `--config` ile seçilen YAML config.
3. `LOCAL_SHELL_MCP_` prefix environment variables.
4. `--mode`, `--config`, `--remote`, `--no-remote` gibi CLI flags; settings load öncesinde karşılık gelen environment values değerlerini set eder.

## Minimal public configuration

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-long-random-secret
```

Local-only testing için `auth_bypass_localhost` default etkin. Public network üzerinde unauthenticated full MCP tools expose etmeyin.

## Settings reference

### Server ve workspace

| YAML key | Environment variable | Default | Notlar |
|---|---|---|---|
| `host` | `LOCAL_SHELL_MCP_HOST` | `'0.0.0.0'` |  |
| `port` | `LOCAL_SHELL_MCP_PORT` | `8765` |  |
| `forwarded_allow_ips` | `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS` | `'127.0.0.1'` | Uvicorn forwarded-header handling için comma-separated trusted proxy IPs. Direct ingress kısıtlıysa `*` kullanın. |
| `mode` | `LOCAL_SHELL_MCP_MODE` | `'mcp'` | `mcp`, `http`, `stdio` veya reserved `both` değeri. |
| `workspace_root` | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | `PosixPath('/workspace')` |  |
| `state_dir` | `LOCAL_SHELL_MCP_STATE_DIR` | `PosixPath('/workspace/.local-shell-mcp')` |  |
| `audit_log_path` | `LOCAL_SHELL_MCP_AUDIT_LOG_PATH` | `PosixPath('/workspace/.local-shell-mcp/audit.jsonl')` |  |
| `agent_config_dir` | `LOCAL_SHELL_MCP_AGENT_CONFIG_DIR` | `PosixPath('/workspace/.local-shell-mcp/agent_config')` |  |
| `allow_full_container` | `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER` | `False` | True olduğunda workspace/path restrictions kapatır; yalnız disposable boundaries içinde kullanın. |
| `disable_local` | `LOCAL_SHELL_MCP_DISABLE_LOCAL` | `False` | Controller host’u shell/file/browser execution target olarak devre dışı bırakır. Remote workers ve control-plane services kullanılabilir kalır. |
| `stateless_controller` | `LOCAL_SHELL_MCP_STATELESS_CONTROLLER` | `False` | Controller’ı ephemeral/serverless instances için uygun yapar: `disable_local` imply eder, local file links/wallpaper caching kapatır ve default `state_backend=memory` olur. `auth_mode=oauth` ile güçlü `oauth_jwt_secret` explicit yapılandırın. |
| `state_backend` | `LOCAL_SHELL_MCP_STATE_BACKEND` | `'file'` | `file`, `memory` veya `redis`. Serverless controller state cold starts sonrasında kalmalıysa Redis kullanın. |
| `state_backend_url` | `LOCAL_SHELL_MCP_STATE_BACKEND_URL` | `None` | `state_backend=redis` için Redis connection URL. Diagnostics içinde redacted. |
| `state_backend_prefix` | `LOCAL_SHELL_MCP_STATE_BACKEND_PREFIX` | `'local-shell-mcp'` | Memory/Redis control-plane state namespace. |

### Limitler

| YAML key | Environment variable | Default | Notlar |
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
| `max_skills` | `LOCAL_SHELL_MCP_MAX_SKILLS` | `256` | Bir registry scan tarafından döndürülen maximum Skill directories. |
| `max_skill_related_files` | `LOCAL_SHELL_MCP_MAX_SKILL_RELATED_FILES` | `1000` | Bir Skill için döndürülen maximum related files. |
| `max_skill_scan_entries` | `LOCAL_SHELL_MCP_MAX_SKILL_SCAN_ENTRIES` | `5000` | Bir `skill_list` registry scan veya direct Skill load tarafından incelenen maximum filesystem entries. |
| `max_skill_path_bytes` | `LOCAL_SHELL_MCP_MAX_SKILL_PATH_BYTES` | `200000` | Returned related-file paths için maximum UTF-8 bytes. |
| `max_read_many_files` | `LOCAL_SHELL_MCP_MAX_READ_MANY_FILES` | `100` |  |
| `max_read_many_total_bytes` | `LOCAL_SHELL_MCP_MAX_READ_MANY_TOTAL_BYTES` | `5000000` |  |
| `max_http_request_bytes` | `LOCAL_SHELL_MCP_MAX_HTTP_REQUEST_BYTES` | `16000000` | MCP, REST, OAuth, UI ve remote-worker endpoints genelinde maximum buffered HTTP request body. |
| `max_job_log_bytes` | `LOCAL_SHELL_MCP_MAX_JOB_LOG_BYTES` | `10000000` | Her long-running job attempt için maximum retained output bytes. |
| `max_jobs` | `LOCAL_SHELL_MCP_MAX_JOBS` | `1000` | Maximum retained long-running job records; active jobs asla pruned edilmez. |
| `max_audit_tail_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES` | `1000000` |  |
| `max_audit_log_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES` | `20000000` |  |
| `max_audit_archive_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_ARCHIVE_BYTES` | `512000000` |  |
| `max_tmp_files` | `LOCAL_SHELL_MCP_MAX_TMP_FILES` | `500` |  |
| `max_tmp_bytes` | `LOCAL_SHELL_MCP_MAX_TMP_BYTES` | `50000000` |  |
| `max_transfer_archive_entries` | `LOCAL_SHELL_MCP_MAX_TRANSFER_ARCHIVE_ENTRIES` | `100000` | Transferred directory archive unpack sırasında maximum accepted entries. |
| `max_transfer_unpacked_bytes` | `LOCAL_SHELL_MCP_MAX_TRANSFER_UNPACKED_BYTES` | `10000000000` | Transferred directory archive için maximum accepted declared expanded bytes. |
| `max_concurrent_commands` | `LOCAL_SHELL_MCP_MAX_CONCURRENT_COMMANDS` | `4` |  |
| `max_tmux_sessions` | `LOCAL_SHELL_MCP_MAX_TMUX_SESSIONS` | `16` | tmux, ConPTY ve native fallback backends genelinde maximum persistent shell sessions. |

### File links

| YAML key | Environment variable | Default | Notlar |
|---|---|---|---|
| `file_download_enabled` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED` | `True` |  |
| `file_download_default_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_TTL_S` | `3600` |  |
| `file_download_max_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_TTL_S` | `604800` |  |
| `file_download_default_max_downloads` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_MAX_DOWNLOADS` | `0` | `0` default download-count limit olmadığını belirtir. |
| `file_download_max_file_bytes` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_FILE_BYTES` | `0` | `0` download links için configured file-size cap olmadığını belirtir. |

### Human interface

| YAML key | Environment variable | Default | Notlar |
|---|---|---|---|
| `logical_sessions_enabled` | `LOCAL_SHELL_MCP_LOGICAL_SESSIONS_ENABLED` | `True` | `session_manage` ve `plan_manage` araçlarını sunar ve normal MCP tools için zorunlu ancak nullable `logical_session_id` argümanını ekler. Session içermeyen daha küçük bir tool surface için kapatın. |
| `live_workspace_enabled` | `LOCAL_SHELL_MCP_LIVE_WORKSPACE_ENABLED` | `True` | MCP App Live Workspace tools, resources ve `/api/live/*` route'larını sunar. `ui_enabled` gerektirir ve `stdio` modunda kullanılamaz. |
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `True` | Native OpenTUI launcher, WebUI shell, PTY WebSocket ve `/api/ui/*` routes mount eder. |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `'/ui'` | Aynı service üzerindeki WebUI mount path. |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | `None` | OpenTUI executable resolution için optional command override. |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `'bing'` | `bing`, `aurora` veya `none`. |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | Inactive browser PTY timeout; `0` kapatır. |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | Maximum concurrent browser OpenTUI PTYs. |

### Remote workers

| YAML key | Environment variable | Default | Notlar |
|---|---|---|---|
| `remote_enabled` | `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `True` | `/join`, `/remote/*` ve MCP tools `remote_*` kontrol eder. |
| `remote_invite_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_INVITE_TTL_S` | `7200` |  |
| `remote_poll_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S` | `25` |  |
| `remote_job_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S` | `3600` |  |
| `remote_max_pending_jobs` | `LOCAL_SHELL_MCP_REMOTE_MAX_PENDING_JOBS` | `256` | Worker başına maximum queued/pending jobs. |
| `remote_cancelled_job_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_CANCELLED_JOB_TTL_S` | `3600` | Timed-out queued jobs atlamak için cancellation tombstones retention time. |
| `remote_transfer_strategy` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_STRATEGY` | `'auto'` | `auto`, `relay`, `direct` veya `object_store`. `auto` enabled peer-direct, configured S3, sonra bounded-memory controller relay dener. |
| `remote_peer_transfer_enabled` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ENABLED` | `False` | Destination worker üzerinde one-shot HTTP receiver’ı optional etkinleştirerek direct worker-to-worker transfer yapar. Yalnız VPC/Tailscale gibi trusted private network içinde etkinleştirin. |
| `remote_peer_transfer_bind_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_BIND_HOST` | `'0.0.0.0'` | One-shot destination-worker receiver bind address. |
| `remote_peer_transfer_advertise_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ADVERTISE_HOST` | `None` | Source worker’a advertised address; default destination worker hostname/FQDN. |
| `remote_peer_transfer_port` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_PORT` | `0` | Receiver port; `0` ephemeral port seçer. |
| `remote_peer_transfer_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_TIMEOUT_S` | `3600` | One-shot direct receiver lifetime/timeout. |
| `remote_transfer_s3_bucket` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_BUCKET` | `None` | Presigned worker-to-worker transfers için optional S3-compatible bucket. `s3` extra gerekir. |
| `remote_transfer_s3_prefix` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PREFIX` | `'local-shell-mcp'` | Temporary transfer objects için object-key prefix. |
| `remote_transfer_s3_region` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_REGION` | `None` | Optional S3 region. |
| `remote_transfer_s3_endpoint_url` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_ENDPOINT_URL` | `None` | Optional S3-compatible endpoint URL. |
| `remote_transfer_s3_presign_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PRESIGN_TTL_S` | `3600` | Presigned PUT/GET URL lifetime. Transfer sonrası temporary objects silinir. |

### Shell ve executable paths

| YAML key | Environment variable | Default | Notlar |
|---|---|---|---|
| `shell_executable` | `LOCAL_SHELL_MCP_SHELL_EXECUTABLE` | `'/bin/bash'` |  |
| `shell_env_blocklist` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKLIST` | `['CLOUDFLARE_TUNNEL_TOKEN']` |  |
| `shell_env_blocked_prefixes` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKED_PREFIXES` | `['LOCAL_SHELL_MCP_', 'DOCKER_']` | Environment variables içinde comma-separated; YAML içinde list. |
| `tmux_bin` | `LOCAL_SHELL_MCP_TMUX_BIN` | `'tmux'` | Preferred tmux executable. Yoksa Linux releases/Docker builds bundled helper kullanır; diğer durumlarda persistent shells native backend’e fallback eder. |
| `rg_bin` | `LOCAL_SHELL_MCP_RG_BIN` | `'rg'` |  |
| `git_bin` | `LOCAL_SHELL_MCP_GIT_BIN` | `'git'` |  |
| `python_bin` | `LOCAL_SHELL_MCP_PYTHON_BIN` | `'python3'` |  |

### Authentication ve OAuth

| YAML key | Environment variable | Default | Notlar |
|---|---|---|---|
| `auth_mode` | `LOCAL_SHELL_MCP_AUTH_MODE` | `'oauth'` | Public deployments için `oauth` kullanın. |
| `auth_bypass_localhost` | `LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST` | `True` |  |
| `require_auth_for_mcp_discovery` | `LOCAL_SHELL_MCP_REQUIRE_AUTH_FOR_MCP_DISCOVERY` | `True` | MCP initialization ve tool discovery öncesi OAuth gerektirir. |
| `mcp_session_idle_timeout_s` | `LOCAL_SHELL_MCP_MCP_SESSION_IDLE_TIMEOUT_S` | `180` | Stateful Streamable HTTP sessions idle timeout. |
| `mcp_max_sessions` | `LOCAL_SHELL_MCP_MCP_MAX_SESSIONS` | `1024` | Maximum concurrent stateful MCP sessions. |
| `public_base_url` | `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | `None` | External HTTPS origin. `/mcp` eklemeyin. |
| `oauth_issuer` | `LOCAL_SHELL_MCP_OAUTH_ISSUER` | `None` |  |
| `oauth_resource` | `LOCAL_SHELL_MCP_OAUTH_RESOURCE` | `None` |  |
| `oauth_admin_pin` | `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` | `None` |  |
| `oauth_jwt_secret` | `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` | <generated or configured> |  |
| `oauth_access_token_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S` | `0` | `0` access tokens otomatik expire etmez demektir. |
| `oauth_code_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_CODE_TTL_S` | `300` |  |

### Built-in policy lists

| YAML key | Environment variable | Default | Notlar |
|---|---|---|---|
| `command_denylist` | `LOCAL_SHELL_MCP_COMMAND_DENYLIST` | `[]` | Full-container mode etkinleşince otomatik clear edilir. |
| `path_denylist` | `LOCAL_SHELL_MCP_PATH_DENYLIST` | `[]` | Full-container mode etkinleşince otomatik clear edilir. |

## YAML örneği

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

Durable Redis state kullanan serverless controller:

```yaml
mode: mcp
stateless_controller: true
state_backend: redis
state_backend_url: redis://redis.internal:6379/0
remote_transfer_strategy: auto
```

`stateless_controller` persistent controller volume gereksinimini kaldırır. `memory` backend bilerek ephemeral’dır: cold start pending remote invites ve worker identities değerlerini invalid eder; OAuth clients, jobs ve audit records silinir. Durable worker revocation semantics dahil bu state cold starts sonrasında korunacaksa Redis kullanın. Default `auth_mode=oauth` ile `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` üzerinden en az 32 bytes random key material inject edin. Active remote RPC queues/futures process-local olduğundan remote workers kullanan deployments şimdilik bir active controller instance çalıştırmalı, birden çok load-balanced controller replicas değil.

## Operasyon önerileri

- Container/VM disposable değilse `allow_full_container=false` tutun.
- Her public endpoint için `auth_mode=oauth` tutun.
- Remote workers kullanmıyorsanız `remote_enabled` kapatın.
- Chat-downloadable artifacts gerekmiyorsa `file_download_enabled` kapatın.
- Command/file/audit limits coding tasks için yeterli yüksek, accidental runaway output’u önleyecek kadar bounded olsun.
