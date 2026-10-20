<!-- i18n-source-sha256: 5d2de552ba0ba0d1c76319ad9f87ab68e217fee6c607687f8260e14872e7dbcc -->
# 設定

儲存庫提供一個可直接複製的起始檔案：[`.env.example`](https://github.com/fwerkor/local-shell-mcp/blob/main/.env.example)。Docker Compose 會自動讀取由此產生的 `.env`，其他 runtime 也可使用相同的 `LOCAL_SHELL_MCP_` 環境變數。YAML 仍是 binary 或原始碼部署的可選進階輸入；請明確建立設定檔，並以 `LOCAL_SHELL_MCP_CONFIG` 或 `--config` 選取。環境變數會覆寫 YAML，因此除非確實需要 override，否則不要在兩處重複定義同一設定。YAML key 使用下表列出的欄位名稱。

## 優先順序

1. `Settings` 中的內建預設值。
2. 由 `LOCAL_SHELL_MCP_CONFIG` 或 `--config` 選取的 YAML 設定。
3. 以 `LOCAL_SHELL_MCP_` 為前綴的環境變數。
4. `--mode`、`--config`、`--remote`、`--no-remote` 等 CLI flag；它們會在載入 settings 前設定對應環境值。

## 最小公開設定

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-long-random-secret
```

僅本機測試時，`auth_bypass_localhost` 預設啟用。不要在公開網路暴露未驗證的完整 MCP tools。

## 設定參考

### 伺服器與工作區

| YAML key | 環境變數 | 預設值 | 說明 |
|---|---|---|---|
| `host` | `LOCAL_SHELL_MCP_HOST` | `'0.0.0.0'` |  |
| `port` | `LOCAL_SHELL_MCP_PORT` | `8765` |  |
| `forwarded_allow_ips` | `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS` | `'127.0.0.1'` | Uvicorn forwarded-header 處理所信任的 proxy IP，以逗號分隔。僅在 direct ingress 已受限制時使用 `*`。 |
| `mode` | `LOCAL_SHELL_MCP_MODE` | `'mcp'` | `mcp`、`http`、`stdio`，或保留的 `both` 值。 |
| `workspace_root` | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | `PosixPath('/workspace')` |  |
| `state_dir` | `LOCAL_SHELL_MCP_STATE_DIR` | `PosixPath('/workspace/.local-shell-mcp')` |  |
| `audit_log_path` | `LOCAL_SHELL_MCP_AUDIT_LOG_PATH` | `PosixPath('/workspace/.local-shell-mcp/audit.jsonl')` |  |
| `agent_config_dir` | `LOCAL_SHELL_MCP_AGENT_CONFIG_DIR` | `PosixPath('/workspace/.local-shell-mcp/agent_config')` |  |
| `allow_full_container` | `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER` | `False` | 為 true 時停用 workspace/path 限制；僅用於 disposable boundary。 |
| `disable_local` | `LOCAL_SHELL_MCP_DISABLE_LOCAL` | `False` | 停用 controller host 作為 shell/file/browser 執行目標；remote workers 與 control-plane services 仍可使用。 |
| `stateless_controller` | `LOCAL_SHELL_MCP_STATELESS_CONTROLLER` | `False` | 讓 controller 適合 ephemeral/serverless instance：隱含 `disable_local`，停用 local file links/wallpaper caching，並預設將 `state_backend` 設為 `memory`。預設 `auth_mode=oauth` 時需明確設定強 `oauth_jwt_secret`。 |
| `state_backend` | `LOCAL_SHELL_MCP_STATE_BACKEND` | `'file'` | 可選 `file`、`memory` 或 `redis`。Serverless controller state 需跨 cold start 持久化時使用 Redis。 |
| `state_backend_url` | `LOCAL_SHELL_MCP_STATE_BACKEND_URL` | `None` | `state_backend=redis` 時的 Redis connection URL；diagnostics 中會遮蔽。 |
| `state_backend_prefix` | `LOCAL_SHELL_MCP_STATE_BACKEND_PREFIX` | `'local-shell-mcp'` | Memory/Redis control-plane state 的 namespace。 |

### 限制

| YAML key | 環境變數 | 預設值 | 說明 |
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
| `max_skills` | `LOCAL_SHELL_MCP_MAX_SKILLS` | `256` | 一次 registry scan 最多回傳的 Skill directory 數。 |
| `max_skill_related_files` | `LOCAL_SHELL_MCP_MAX_SKILL_RELATED_FILES` | `1000` | 單一 Skill 最多回傳的 related files 數。 |
| `max_skill_scan_entries` | `LOCAL_SHELL_MCP_MAX_SKILL_SCAN_ENTRIES` | `5000` | 一次 `skill_list` registry scan 或 direct Skill load 最多檢查的 filesystem entries。 |
| `max_skill_path_bytes` | `LOCAL_SHELL_MCP_MAX_SKILL_PATH_BYTES` | `200000` | 回傳 related-file paths 使用的 UTF-8 bytes 上限。 |
| `max_read_many_files` | `LOCAL_SHELL_MCP_MAX_READ_MANY_FILES` | `100` |  |
| `max_read_many_total_bytes` | `LOCAL_SHELL_MCP_MAX_READ_MANY_TOTAL_BYTES` | `5000000` |  |
| `max_http_request_bytes` | `LOCAL_SHELL_MCP_MAX_HTTP_REQUEST_BYTES` | `16000000` | MCP、REST、OAuth、UI 與 remote-worker endpoints 可緩衝 HTTP request body 的上限。 |
| `max_job_log_bytes` | `LOCAL_SHELL_MCP_MAX_JOB_LOG_BYTES` | `10000000` | 每次 long-running job attempt 保留的 output bytes 上限。 |
| `max_jobs` | `LOCAL_SHELL_MCP_MAX_JOBS` | `1000` | 保留的 long-running job records 上限；active jobs 不會被 prune。 |
| `max_audit_tail_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES` | `1000000` |  |
| `max_audit_log_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES` | `20000000` |  |
| `max_audit_archive_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_ARCHIVE_BYTES` | `512000000` |  |
| `max_tmp_files` | `LOCAL_SHELL_MCP_MAX_TMP_FILES` | `500` |  |
| `max_tmp_bytes` | `LOCAL_SHELL_MCP_MAX_TMP_BYTES` | `50000000` |  |
| `max_transfer_archive_entries` | `LOCAL_SHELL_MCP_MAX_TRANSFER_ARCHIVE_ENTRIES` | `100000` | 解包 transferred directory archive 時允許的 entry 上限。 |
| `max_transfer_unpacked_bytes` | `LOCAL_SHELL_MCP_MAX_TRANSFER_UNPACKED_BYTES` | `10000000000` | 接受 transferred directory archive 時宣告的 expanded bytes 上限。 |
| `max_concurrent_commands` | `LOCAL_SHELL_MCP_MAX_CONCURRENT_COMMANDS` | `4` |  |
| `max_tmux_sessions` | `LOCAL_SHELL_MCP_MAX_TMUX_SESSIONS` | `16` | tmux、ConPTY 與 native fallback backend 合計的 persistent shell sessions 上限。 |

### 檔案連結

| YAML key | 環境變數 | 預設值 | 說明 |
|---|---|---|---|
| `file_download_enabled` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED` | `True` |  |
| `file_download_default_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_TTL_S` | `3600` |  |
| `file_download_max_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_TTL_S` | `604800` |  |
| `file_download_default_max_downloads` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_MAX_DOWNLOADS` | `0` | `0` 表示預設不限制下載次數。 |
| `file_download_max_file_bytes` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_FILE_BYTES` | `0` | `0` 表示 file link 不設定檔案大小上限。 |

### 人機介面

| YAML key | 環境變數 | 預設值 | 說明 |
|---|---|---|---|
| `logical_sessions_enabled` | `LOCAL_SHELL_MCP_LOGICAL_SESSIONS_ENABLED` | `True` | 公開 `session_manage` 與 `plan_manage`，並為一般 MCP tools 加入必填但可為 null 的 `logical_session_id` 參數。關閉後可得到更精簡、無 Session 的工具面。 |
| `live_workspace_enabled` | `LOCAL_SHELL_MCP_LIVE_WORKSPACE_ENABLED` | `True` | 公開 MCP App Live Workspace 的 tools、resources 與 `/api/live/*` routes。需要同時啟用 `ui_enabled`，且在 `stdio` 模式下不可用。 |
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `True` | 掛載 native OpenTUI launcher、WebUI shell、PTY WebSocket 與 `/api/ui/*` routes。 |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `'/ui'` | WebUI 在相同 service 上的 mount path。 |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | `None` | 可選 OpenTUI executable command override。 |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `'bing'` | 可選 `bing`、`aurora` 或 `none`。 |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | Inactive browser PTY timeout；`0` 表示停用。 |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | 並行 browser OpenTUI PTY 上限。 |

### 遠端 worker

| YAML key | 環境變數 | 預設值 | 說明 |
|---|---|---|---|
| `remote_enabled` | `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `True` | 控制 `/join`、`/remote/*` 與 `remote_*` MCP tools。 |
| `remote_invite_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_INVITE_TTL_S` | `7200` |  |
| `remote_poll_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S` | `25` |  |
| `remote_job_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S` | `3600` |  |
| `remote_max_pending_jobs` | `LOCAL_SHELL_MCP_REMOTE_MAX_PENDING_JOBS` | `256` | 每個 worker 最多 queued/pending jobs。 |
| `remote_cancelled_job_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_CANCELLED_JOB_TTL_S` | `3600` | 用於跳過 timed-out queued jobs 的 cancellation tombstones 保留時間。 |
| `remote_transfer_strategy` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_STRATEGY` | `'auto'` | 可選 `auto`、`relay`、`direct` 或 `object_store`。`auto` 依序嘗試已啟用 peer-direct、已設定 S3，最後使用 bounded-memory controller relay。 |
| `remote_peer_transfer_enabled` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ENABLED` | `False` | 選擇性啟用 destination worker 上的一次性 HTTP receiver，用於 worker-to-worker direct transfer。僅應在 VPC/Tailscale 等 trusted private network 中啟用。 |
| `remote_peer_transfer_bind_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_BIND_HOST` | `'0.0.0.0'` | 一次性 destination-worker receiver 的 bind address。 |
| `remote_peer_transfer_advertise_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ADVERTISE_HOST` | `None` | 向 source worker 公布的地址；預設使用 destination worker hostname/FQDN。 |
| `remote_peer_transfer_port` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_PORT` | `0` | Receiver port；`0` 會選擇 ephemeral port。 |
| `remote_peer_transfer_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_TIMEOUT_S` | `3600` | 一次性 direct receiver 的 lifetime/timeout。 |
| `remote_transfer_s3_bucket` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_BUCKET` | `None` | 用於 presigned worker-to-worker transfers 的可選 S3-compatible bucket；需要 `s3` extra。 |
| `remote_transfer_s3_prefix` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PREFIX` | `'local-shell-mcp'` | Temporary transfer objects 的 object-key prefix。 |
| `remote_transfer_s3_region` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_REGION` | `None` | 可選 S3 region。 |
| `remote_transfer_s3_endpoint_url` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_ENDPOINT_URL` | `None` | 可選 S3-compatible endpoint URL。 |
| `remote_transfer_s3_presign_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PRESIGN_TTL_S` | `3600` | Presigned PUT/GET URL lifetime；transfer 後刪除 temporary objects。 |

### Shell 與可執行檔路徑

| YAML key | 環境變數 | 預設值 | 說明 |
|---|---|---|---|
| `shell_executable` | `LOCAL_SHELL_MCP_SHELL_EXECUTABLE` | `'/bin/bash'` |  |
| `shell_env_blocklist` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKLIST` | `['CLOUDFLARE_TUNNEL_TOKEN']` |  |
| `shell_env_blocked_prefixes` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKED_PREFIXES` | `['LOCAL_SHELL_MCP_', 'DOCKER_']` | 環境變數使用逗號分隔；YAML 使用 list。 |
| `tmux_bin` | `LOCAL_SHELL_MCP_TMUX_BIN` | `'tmux'` | 首選 tmux executable。無法使用時，Linux release 與 Docker build 使用 bundled helper；否則 persistent shell fallback 到 native backend。 |
| `rg_bin` | `LOCAL_SHELL_MCP_RG_BIN` | `'rg'` |  |
| `git_bin` | `LOCAL_SHELL_MCP_GIT_BIN` | `'git'` |  |
| `python_bin` | `LOCAL_SHELL_MCP_PYTHON_BIN` | `'python3'` |  |

### 驗證與 OAuth

| YAML key | 環境變數 | 預設值 | 說明 |
|---|---|---|---|
| `auth_mode` | `LOCAL_SHELL_MCP_AUTH_MODE` | `'oauth'` | 公開部署使用 `oauth`。 |
| `auth_bypass_localhost` | `LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST` | `True` |  |
| `require_auth_for_mcp_discovery` | `LOCAL_SHELL_MCP_REQUIRE_AUTH_FOR_MCP_DISCOVERY` | `True` | 在 MCP initialization 與 tool discovery 前要求 OAuth。 |
| `mcp_session_idle_timeout_s` | `LOCAL_SHELL_MCP_MCP_SESSION_IDLE_TIMEOUT_S` | `180` | Stateful Streamable HTTP sessions 的 idle timeout。 |
| `mcp_max_sessions` | `LOCAL_SHELL_MCP_MCP_MAX_SESSIONS` | `1024` | 並行 stateful MCP sessions 上限。 |
| `public_base_url` | `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | `None` | External HTTPS origin；不要包含 `/mcp`。 |
| `oauth_issuer` | `LOCAL_SHELL_MCP_OAUTH_ISSUER` | `None` |  |
| `oauth_resource` | `LOCAL_SHELL_MCP_OAUTH_RESOURCE` | `None` |  |
| `oauth_admin_pin` | `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` | `None` |  |
| `oauth_jwt_secret` | `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` | <generated or configured> |  |
| `oauth_access_token_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S` | `0` | `0` 表示 access token 不會自動過期。 |
| `oauth_code_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_CODE_TTL_S` | `300` |  |

### 內建策略清單

| YAML key | 環境變數 | 預設值 | 說明 |
|---|---|---|---|
| `command_denylist` | `LOCAL_SHELL_MCP_COMMAND_DENYLIST` | `[]` | 啟用 full-container mode 時自動清空。 |
| `path_denylist` | `LOCAL_SHELL_MCP_PATH_DENYLIST` | `[]` | 啟用 full-container mode 時自動清空。 |

## YAML 範例

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

使用持久 Redis state 的 serverless controller：

```yaml
mode: mcp
stateless_controller: true
state_backend: redis
state_backend_url: redis://redis.internal:6379/0
remote_transfer_strategy: auto
```

`stateless_controller` 可移除 controller 對持久 volume 的需求。`memory` backend 刻意設計為暫態：cold start 會使待處理 remote invite 與 worker identity 失效，並丟棄 OAuth clients、jobs 與 audit records。若這些 state（包括持久 worker revoke 語意）必須跨 cold start 保留，請使用 Redis。預設 `auth_mode=oauth` 時，至少透過 `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` 注入 32 bytes 隨機 key material。Active remote RPC queues/futures 屬於 process-local state，因此使用 remote workers 的部署目前應只執行一個 active controller instance，而不要使用多個 load-balanced controller replicas。

## 運維建議

- 除非 container 或 VM 可直接丟棄，否則保持 `allow_full_container=false`。
- 任何公開 endpoint 都保持 `auth_mode=oauth`。
- 若不使用 remote workers，停用 `remote_enabled`。
- 若從不需要可從 chat 下載的 artifacts，停用 `file_download_enabled`。
- Command、file 與 audit 限制需足以支援 coding tasks，同時足夠低以避免意外 runaway output。
