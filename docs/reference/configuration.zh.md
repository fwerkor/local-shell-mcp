<!-- i18n-source-sha256: 5d2de552ba0ba0d1c76319ad9f87ab68e217fee6c607687f8260e14872e7dbcc -->
# 配置

仓库提供一个可直接复制的起始文件：[`.env.example`](https://github.com/fwerkor/local-shell-mcp/blob/main/.env.example)。Docker Compose 会自动读取由此生成的 `.env`，其他 runtime 也可以使用相同的 `LOCAL_SHELL_MCP_` 环境变量。YAML 仍是 binary 或源码部署的可选高级输入；需要显式创建配置文件，并通过 `LOCAL_SHELL_MCP_CONFIG` 或 `--config` 选择。环境变量会覆盖 YAML，因此除非确实需要覆盖，否则不要在两处重复定义同一设置。YAML key 使用下表所列字段名。

## 优先级

1. `Settings` 中的内置默认值。
2. 由 `LOCAL_SHELL_MCP_CONFIG` 或 `--config` 选择的 YAML 配置。
3. 以 `LOCAL_SHELL_MCP_` 为前缀的环境变量。
4. `--mode`、`--config`、`--remote`、`--no-remote` 等 CLI flag；它们会在加载 settings 前设置对应环境值。

## 最小公共配置

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-long-random-secret
```

仅本地测试时，`auth_bypass_localhost` 默认启用。不要在公共网络上暴露未经认证的完整 MCP tools。

## 设置参考

### 服务器与工作区

| YAML key | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `host` | `LOCAL_SHELL_MCP_HOST` | `'0.0.0.0'` |  |
| `port` | `LOCAL_SHELL_MCP_PORT` | `8765` |  |
| `forwarded_allow_ips` | `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS` | `'127.0.0.1'` | Uvicorn forwarded-header 处理所信任的 proxy IP，逗号分隔。仅当 direct ingress 已受限制时才使用 `*`。 |
| `mode` | `LOCAL_SHELL_MCP_MODE` | `'mcp'` | `mcp`、`http`、`stdio`，或保留的 `both` 值。 |
| `workspace_root` | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | `PosixPath('/workspace')` |  |
| `state_dir` | `LOCAL_SHELL_MCP_STATE_DIR` | `PosixPath('/workspace/.local-shell-mcp')` |  |
| `audit_log_path` | `LOCAL_SHELL_MCP_AUDIT_LOG_PATH` | `PosixPath('/workspace/.local-shell-mcp/audit.jsonl')` |  |
| `agent_config_dir` | `LOCAL_SHELL_MCP_AGENT_CONFIG_DIR` | `PosixPath('/workspace/.local-shell-mcp/agent_config')` |  |
| `allow_full_container` | `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER` | `False` | 为 true 时关闭 workspace/path 限制；仅用于 disposable boundary。 |
| `disable_local` | `LOCAL_SHELL_MCP_DISABLE_LOCAL` | `False` | 禁止将 controller host 作为 shell/file/browser 执行目标；remote workers 与 control-plane services 仍可使用。 |
| `stateless_controller` | `LOCAL_SHELL_MCP_STATELESS_CONTROLLER` | `False` | 使 controller 适合 ephemeral/serverless instance：隐含 `disable_local`，关闭 local file links/wallpaper caching，并默认将 `state_backend` 设为 `memory`。默认 `auth_mode=oauth` 时必须显式配置强 `oauth_jwt_secret`。 |
| `state_backend` | `LOCAL_SHELL_MCP_STATE_BACKEND` | `'file'` | 可选 `file`、`memory` 或 `redis`。Serverless controller state 需要跨 cold start 持久化时使用 Redis。 |
| `state_backend_url` | `LOCAL_SHELL_MCP_STATE_BACKEND_URL` | `None` | `state_backend=redis` 时使用的 Redis connection URL；diagnostics 中会被脱敏。 |
| `state_backend_prefix` | `LOCAL_SHELL_MCP_STATE_BACKEND_PREFIX` | `'local-shell-mcp'` | Memory/Redis control-plane state 的 namespace。 |

### 限制

| YAML key | 环境变量 | 默认值 | 说明 |
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
| `max_skills` | `LOCAL_SHELL_MCP_MAX_SKILLS` | `256` | 一次 registry scan 最多返回的 Skill directory 数。 |
| `max_skill_related_files` | `LOCAL_SHELL_MCP_MAX_SKILL_RELATED_FILES` | `1000` | 单个 Skill 最多返回的 related files 数。 |
| `max_skill_scan_entries` | `LOCAL_SHELL_MCP_MAX_SKILL_SCAN_ENTRIES` | `5000` | 一次 `skill_list` registry scan 或 direct Skill load 最多检查的 filesystem entries。 |
| `max_skill_path_bytes` | `LOCAL_SHELL_MCP_MAX_SKILL_PATH_BYTES` | `200000` | 返回 related-file paths 使用的 UTF-8 bytes 上限。 |
| `max_read_many_files` | `LOCAL_SHELL_MCP_MAX_READ_MANY_FILES` | `100` |  |
| `max_read_many_total_bytes` | `LOCAL_SHELL_MCP_MAX_READ_MANY_TOTAL_BYTES` | `5000000` |  |
| `max_http_request_bytes` | `LOCAL_SHELL_MCP_MAX_HTTP_REQUEST_BYTES` | `16000000` | MCP、REST、OAuth、UI 与 remote-worker endpoints 可缓冲 HTTP request body 的上限。 |
| `max_job_log_bytes` | `LOCAL_SHELL_MCP_MAX_JOB_LOG_BYTES` | `10000000` | 每次 long-running job attempt 保留的 output bytes 上限。 |
| `max_jobs` | `LOCAL_SHELL_MCP_MAX_JOBS` | `1000` | 保留的 long-running job records 上限；active jobs 不会被 prune。 |
| `max_audit_tail_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES` | `1000000` |  |
| `max_audit_log_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES` | `20000000` |  |
| `max_audit_archive_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_ARCHIVE_BYTES` | `512000000` |  |
| `max_tmp_files` | `LOCAL_SHELL_MCP_MAX_TMP_FILES` | `500` |  |
| `max_tmp_bytes` | `LOCAL_SHELL_MCP_MAX_TMP_BYTES` | `50000000` |  |
| `max_transfer_archive_entries` | `LOCAL_SHELL_MCP_MAX_TRANSFER_ARCHIVE_ENTRIES` | `100000` | 解包 transferred directory archive 时允许的 entry 上限。 |
| `max_transfer_unpacked_bytes` | `LOCAL_SHELL_MCP_MAX_TRANSFER_UNPACKED_BYTES` | `10000000000` | 接受 transferred directory archive 时声明的 expanded bytes 上限。 |
| `max_concurrent_commands` | `LOCAL_SHELL_MCP_MAX_CONCURRENT_COMMANDS` | `4` |  |
| `max_tmux_sessions` | `LOCAL_SHELL_MCP_MAX_TMUX_SESSIONS` | `16` | tmux、ConPTY 与 native fallback backend 合计的 persistent shell sessions 上限。 |

### 文件链接

| YAML key | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `file_download_enabled` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED` | `True` |  |
| `file_download_default_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_TTL_S` | `3600` |  |
| `file_download_max_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_TTL_S` | `604800` |  |
| `file_download_default_max_downloads` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_MAX_DOWNLOADS` | `0` | `0` 表示默认不限制下载次数。 |
| `file_download_max_file_bytes` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_FILE_BYTES` | `0` | `0` 表示 file link 不设置配置级文件大小上限。 |

### 人机界面

| YAML key | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `logical_sessions_enabled` | `LOCAL_SHELL_MCP_LOGICAL_SESSIONS_ENABLED` | `True` | 公开 `session_manage` 与 `plan_manage`，并为普通 MCP tools 添加必填但可为 null 的 `logical_session_id` 参数。关闭后可获得更精简、无 Session 的工具面。 |
| `live_workspace_enabled` | `LOCAL_SHELL_MCP_LIVE_WORKSPACE_ENABLED` | `True` | 公开 MCP App Live Workspace 的 tools、resources 与 `/api/live/*` routes。需要同时启用 `ui_enabled`，且 `stdio` 模式下不可用。 |
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `True` | 挂载 native OpenTUI launcher、WebUI shell、PTY WebSocket 与 `/api/ui/*` routes。 |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `'/ui'` | WebUI 在同一 service 上的 mount path。 |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | `None` | 可选的 OpenTUI executable command override。 |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `'bing'` | 可选 `bing`、`aurora` 或 `none`。 |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | Inactive browser PTY timeout；`0` 表示禁用。 |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | 并发 browser OpenTUI PTY 的上限。 |

### 远程 worker

| YAML key | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `remote_enabled` | `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `True` | 控制 `/join`、`/remote/*` 与 `remote_*` MCP tools。 |
| `remote_invite_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_INVITE_TTL_S` | `7200` |  |
| `remote_poll_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S` | `25` |  |
| `remote_job_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S` | `3600` |  |
| `remote_max_pending_jobs` | `LOCAL_SHELL_MCP_REMOTE_MAX_PENDING_JOBS` | `256` | 每个 worker 最多 queued/pending jobs。 |
| `remote_cancelled_job_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_CANCELLED_JOB_TTL_S` | `3600` | 用于跳过 timed-out queued jobs 的 cancellation tombstones 保留时间。 |
| `remote_transfer_strategy` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_STRATEGY` | `'auto'` | 可选 `auto`、`relay`、`direct` 或 `object_store`。`auto` 依次尝试已启用 peer-direct、已配置 S3、最后使用 bounded-memory controller relay。 |
| `remote_peer_transfer_enabled` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ENABLED` | `False` | 选择性启用 destination worker 上的一次性 HTTP receiver，用于 worker-to-worker direct transfer。仅应在 VPC/Tailscale 等 trusted private network 中启用。 |
| `remote_peer_transfer_bind_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_BIND_HOST` | `'0.0.0.0'` | 一次性 destination-worker receiver 的 bind address。 |
| `remote_peer_transfer_advertise_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ADVERTISE_HOST` | `None` | 向 source worker 公布的地址；默认使用 destination worker hostname/FQDN。 |
| `remote_peer_transfer_port` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_PORT` | `0` | Receiver port；`0` 表示自动选择 ephemeral port。 |
| `remote_peer_transfer_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_TIMEOUT_S` | `3600` | 一次性 direct receiver 的 lifetime/timeout。 |
| `remote_transfer_s3_bucket` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_BUCKET` | `None` | 用于 presigned worker-to-worker transfers 的可选 S3-compatible bucket；需要 `s3` extra。 |
| `remote_transfer_s3_prefix` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PREFIX` | `'local-shell-mcp'` | 临时 transfer objects 的 object-key prefix。 |
| `remote_transfer_s3_region` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_REGION` | `None` | 可选 S3 region。 |
| `remote_transfer_s3_endpoint_url` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_ENDPOINT_URL` | `None` | 可选 S3-compatible endpoint URL。 |
| `remote_transfer_s3_presign_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PRESIGN_TTL_S` | `3600` | Presigned PUT/GET URL lifetime；transfer 后会删除 temporary objects。 |

### Shell 与可执行文件路径

| YAML key | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `shell_executable` | `LOCAL_SHELL_MCP_SHELL_EXECUTABLE` | `'/bin/bash'` |  |
| `shell_env_blocklist` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKLIST` | `['CLOUDFLARE_TUNNEL_TOKEN']` |  |
| `shell_env_blocked_prefixes` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKED_PREFIXES` | `['LOCAL_SHELL_MCP_', 'DOCKER_']` | 环境变量中使用逗号分隔；YAML 中使用 list。 |
| `tmux_bin` | `LOCAL_SHELL_MCP_TMUX_BIN` | `'tmux'` | 首选 tmux executable。不可用时，Linux release 与 Docker build 使用 bundled helper；否则 persistent shell fallback 到 native backend。 |
| `rg_bin` | `LOCAL_SHELL_MCP_RG_BIN` | `'rg'` |  |
| `git_bin` | `LOCAL_SHELL_MCP_GIT_BIN` | `'git'` |  |
| `python_bin` | `LOCAL_SHELL_MCP_PYTHON_BIN` | `'python3'` |  |

### 认证与 OAuth

| YAML key | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `auth_mode` | `LOCAL_SHELL_MCP_AUTH_MODE` | `'oauth'` | 公共部署使用 `oauth`。 |
| `auth_bypass_localhost` | `LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST` | `True` |  |
| `require_auth_for_mcp_discovery` | `LOCAL_SHELL_MCP_REQUIRE_AUTH_FOR_MCP_DISCOVERY` | `True` | 在 MCP initialization 与 tool discovery 前要求 OAuth。 |
| `mcp_session_idle_timeout_s` | `LOCAL_SHELL_MCP_MCP_SESSION_IDLE_TIMEOUT_S` | `180` | Stateful Streamable HTTP sessions 的 idle timeout。 |
| `mcp_max_sessions` | `LOCAL_SHELL_MCP_MCP_MAX_SESSIONS` | `1024` | 并发 stateful MCP sessions 上限。 |
| `public_base_url` | `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | `None` | External HTTPS origin；不要包含 `/mcp`。 |
| `oauth_issuer` | `LOCAL_SHELL_MCP_OAUTH_ISSUER` | `None` |  |
| `oauth_resource` | `LOCAL_SHELL_MCP_OAUTH_RESOURCE` | `None` |  |
| `oauth_admin_pin` | `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` | `None` |  |
| `oauth_jwt_secret` | `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` | <generated or configured> |  |
| `oauth_access_token_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S` | `0` | `0` 表示 access token 不自动过期。 |
| `oauth_code_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_CODE_TTL_S` | `300` |  |

### 内置策略列表

| YAML key | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `command_denylist` | `LOCAL_SHELL_MCP_COMMAND_DENYLIST` | `[]` | 启用 full-container mode 时自动清空。 |
| `path_denylist` | `LOCAL_SHELL_MCP_PATH_DENYLIST` | `[]` | 启用 full-container mode 时自动清空。 |

## YAML 示例

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

带持久 Redis state 的 serverless controller：

```yaml
mode: mcp
stateless_controller: true
state_backend: redis
state_backend_url: redis://redis.internal:6379/0
remote_transfer_strategy: auto
```

`stateless_controller` 可以移除 controller 对持久 volume 的需求。`memory` backend 有意设计为临时状态：cold start 会使待处理的 remote invite 与 worker identity 失效，并丢弃 OAuth clients、jobs 与 audit records。当这些 state（包括持久的 worker revoke 语义）必须跨 cold start 保存时，请使用 Redis。默认 `auth_mode=oauth` 时，至少通过 `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` 注入 32 bytes 随机 key material。Active remote RPC queues/futures 属于进程本地状态，因此使用 remote workers 的部署目前应只运行一个 active controller instance，而不要部署多个 load-balanced controller replicas。

## 运维建议

- 除非 container 或 VM 可随时销毁，否则保持 `allow_full_container=false`。
- 任何公共 endpoint 都保持 `auth_mode=oauth`。
- 如果不使用 remote workers，关闭 `remote_enabled`。
- 如果从不需要可在 chat 下载的 artifact，关闭 `file_download_enabled`。
- Command、file 与 audit 限制应足够支持 coding task，同时足够低以防止意外的 runaway output。
