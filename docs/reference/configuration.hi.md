<!-- i18n-source-sha256: 5d2de552ba0ba0d1c76319ad9f87ab68e217fee6c607687f8260e14872e7dbcc -->
# Configuration

Repository एक copyable starter file देता है: [`.env.example`](https://github.com/fwerkor/local-shell-mcp/blob/main/.env.example)। Docker Compose उससे बने `.env` को automatically पढ़ता है, और अन्य runtimes वही `LOCAL_SHELL_MCP_` environment variables उपयोग कर सकते हैं। YAML binary/source deployments के लिए optional advanced input रहता है; file explicitly बनाएँ और `LOCAL_SHELL_MCP_CONFIG` या `--config` से चुनें। Environment variables YAML values को override करती हैं, इसलिए intentional override के अलावा वही setting दोनों जगह define न करें। YAML keys नीचे दिखाए field names उपयोग करती हैं।

## Precedence

1. `Settings` के built-in defaults।
2. `LOCAL_SHELL_MCP_CONFIG` या `--config` से चुनी YAML config।
3. `LOCAL_SHELL_MCP_` prefix वाली environment variables।
4. `--mode`, `--config`, `--remote`, `--no-remote` जैसे CLI flags, जो settings load से पहले corresponding environment values set करते हैं।

## Minimal public configuration

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-long-random-secret
```

Local-only testing के लिए `auth_bypass_localhost` default enabled है। Public network पर unauthenticated full MCP tools expose न करें।

## Settings reference

### Server और workspace

| YAML key | Environment variable | Default | Notes |
|---|---|---|---|
| `host` | `LOCAL_SHELL_MCP_HOST` | `'0.0.0.0'` |  |
| `port` | `LOCAL_SHELL_MCP_PORT` | `8765` |  |
| `forwarded_allow_ips` | `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS` | `'127.0.0.1'` | Uvicorn forwarded-header handling के लिए comma-separated trusted proxy IPs। Direct ingress restricted हो तभी `*` उपयोग करें। |
| `mode` | `LOCAL_SHELL_MCP_MODE` | `'mcp'` | `mcp`, `http`, `stdio`, या reserved `both` value. |
| `workspace_root` | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | `PosixPath('/workspace')` |  |
| `state_dir` | `LOCAL_SHELL_MCP_STATE_DIR` | `PosixPath('/workspace/.local-shell-mcp')` |  |
| `audit_log_path` | `LOCAL_SHELL_MCP_AUDIT_LOG_PATH` | `PosixPath('/workspace/.local-shell-mcp/audit.jsonl')` |  |
| `agent_config_dir` | `LOCAL_SHELL_MCP_AGENT_CONFIG_DIR` | `PosixPath('/workspace/.local-shell-mcp/agent_config')` |  |
| `allow_full_container` | `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER` | `False` | True होने पर workspace/path restrictions disable करता है; केवल disposable boundaries में उपयोग करें। |
| `disable_local` | `LOCAL_SHELL_MCP_DISABLE_LOCAL` | `False` | Controller host को shell/file/browser execution target के रूप में disable करता है। Remote workers और control-plane services उपलब्ध रहते हैं। |
| `stateless_controller` | `LOCAL_SHELL_MCP_STATELESS_CONTROLLER` | `False` | Controller को ephemeral/serverless instances के लिए उपयुक्त बनाता है: `disable_local` imply करता है, local file links/wallpaper caching बंद करता है और default `state_backend=memory` रखता है। Default `auth_mode=oauth` में strong `oauth_jwt_secret` explicitly configure करें। |
| `state_backend` | `LOCAL_SHELL_MCP_STATE_BACKEND` | `'file'` | `file`, `memory` या `redis`। Serverless controller state को cold starts के बाद रखना हो तो Redis उपयोग करें। |
| `state_backend_url` | `LOCAL_SHELL_MCP_STATE_BACKEND_URL` | `None` | `state_backend=redis` पर Redis connection URL। Diagnostics में redacted। |
| `state_backend_prefix` | `LOCAL_SHELL_MCP_STATE_BACKEND_PREFIX` | `'local-shell-mcp'` | Memory/Redis control-plane state namespace। |

### Limits

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
| `max_skills` | `LOCAL_SHELL_MCP_MAX_SKILLS` | `256` | एक registry scan से लौटने वाली Skill directories की maximum संख्या। |
| `max_skill_related_files` | `LOCAL_SHELL_MCP_MAX_SKILL_RELATED_FILES` | `1000` | एक Skill के लिए returned related files की maximum संख्या। |
| `max_skill_scan_entries` | `LOCAL_SHELL_MCP_MAX_SKILL_SCAN_ENTRIES` | `5000` | एक `skill_list` registry scan या direct Skill load में examined filesystem entries की maximum संख्या। |
| `max_skill_path_bytes` | `LOCAL_SHELL_MCP_MAX_SKILL_PATH_BYTES` | `200000` | Returned related-file paths के लिए maximum UTF-8 bytes। |
| `max_read_many_files` | `LOCAL_SHELL_MCP_MAX_READ_MANY_FILES` | `100` |  |
| `max_read_many_total_bytes` | `LOCAL_SHELL_MCP_MAX_READ_MANY_TOTAL_BYTES` | `5000000` |  |
| `max_http_request_bytes` | `LOCAL_SHELL_MCP_MAX_HTTP_REQUEST_BYTES` | `16000000` | MCP, REST, OAuth, UI और remote-worker endpoints पर maximum buffered HTTP request body। |
| `max_job_log_bytes` | `LOCAL_SHELL_MCP_MAX_JOB_LOG_BYTES` | `10000000` | हर long-running job attempt के maximum retained output bytes। |
| `max_jobs` | `LOCAL_SHELL_MCP_MAX_JOBS` | `1000` | Maximum retained long-running job records; active jobs prune नहीं होते। |
| `max_audit_tail_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES` | `1000000` |  |
| `max_audit_log_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES` | `20000000` |  |
| `max_audit_archive_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_ARCHIVE_BYTES` | `512000000` |  |
| `max_tmp_files` | `LOCAL_SHELL_MCP_MAX_TMP_FILES` | `500` |  |
| `max_tmp_bytes` | `LOCAL_SHELL_MCP_MAX_TMP_BYTES` | `50000000` |  |
| `max_transfer_archive_entries` | `LOCAL_SHELL_MCP_MAX_TRANSFER_ARCHIVE_ENTRIES` | `100000` | Transferred directory archive unpack करते समय maximum accepted entries। |
| `max_transfer_unpacked_bytes` | `LOCAL_SHELL_MCP_MAX_TRANSFER_UNPACKED_BYTES` | `10000000000` | Transferred directory archive के maximum accepted declared expanded bytes। |
| `max_concurrent_commands` | `LOCAL_SHELL_MCP_MAX_CONCURRENT_COMMANDS` | `4` |  |
| `max_tmux_sessions` | `LOCAL_SHELL_MCP_MAX_TMUX_SESSIONS` | `16` | tmux, ConPTY और native fallback backends में maximum persistent shell sessions। |

### File links

| YAML key | Environment variable | Default | Notes |
|---|---|---|---|
| `file_download_enabled` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED` | `True` |  |
| `file_download_default_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_TTL_S` | `3600` |  |
| `file_download_max_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_TTL_S` | `604800` |  |
| `file_download_default_max_downloads` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_MAX_DOWNLOADS` | `0` | `0` का अर्थ default download-count limit नहीं। |
| `file_download_max_file_bytes` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_FILE_BYTES` | `0` | `0` का अर्थ download links के लिए configured file-size cap नहीं। |

### Human interface

| YAML key | Environment variable | Default | Notes |
|---|---|---|---|
| `logical_sessions_enabled` | `LOCAL_SHELL_MCP_LOGICAL_SESSIONS_ENABLED` | `True` | `session_manage` और `plan_manage` को expose करता है और सामान्य MCP tools में required लेकिन nullable `logical_session_id` argument जोड़ता है। Session रहित छोटा tool surface पाने के लिए इसे disable करें। |
| `live_workspace_enabled` | `LOCAL_SHELL_MCP_LIVE_WORKSPACE_ENABLED` | `True` | MCP App Live Workspace के tools, resources और `/api/live/*` routes expose करता है। इसके लिए `ui_enabled` आवश्यक है और यह `stdio` mode में उपलब्ध नहीं है। |
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `True` | Native OpenTUI launcher, WebUI shell, PTY WebSocket और `/api/ui/*` routes mount करता है। |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `'/ui'` | उसी service पर WebUI mount path। |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | `None` | OpenTUI executable resolution का optional command override। |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `'bing'` | `bing`, `aurora` या `none`। |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | Inactive browser PTY timeout; `0` disable करता है। |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | Maximum concurrent browser OpenTUI PTYs। |

### Remote workers

| YAML key | Environment variable | Default | Notes |
|---|---|---|---|
| `remote_enabled` | `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `True` | `/join`, `/remote/*` और MCP tools `remote_*` control करता है। |
| `remote_invite_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_INVITE_TTL_S` | `7200` |  |
| `remote_poll_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S` | `25` |  |
| `remote_job_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S` | `3600` |  |
| `remote_max_pending_jobs` | `LOCAL_SHELL_MCP_REMOTE_MAX_PENDING_JOBS` | `256` | हर worker पर maximum queued/pending jobs। |
| `remote_cancelled_job_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_CANCELLED_JOB_TTL_S` | `3600` | Timed-out queued jobs skip करने वाले cancellation tombstones का retention time। |
| `remote_transfer_strategy` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_STRATEGY` | `'auto'` | `auto`, `relay`, `direct` या `object_store`। `auto` enabled peer-direct, configured S3 और फिर bounded-memory controller relay try करता है। |
| `remote_peer_transfer_enabled` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ENABLED` | `False` | Destination worker पर one-shot HTTP receiver optional enable करता है, direct worker-to-worker transfer के लिए। केवल trusted private network जैसे VPC/Tailscale में enable करें। |
| `remote_peer_transfer_bind_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_BIND_HOST` | `'0.0.0.0'` | One-shot destination-worker receiver का bind address। |
| `remote_peer_transfer_advertise_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ADVERTISE_HOST` | `None` | Source worker को advertised address; default destination worker hostname/FQDN। |
| `remote_peer_transfer_port` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_PORT` | `0` | Receiver port; `0` ephemeral port चुनता है। |
| `remote_peer_transfer_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_TIMEOUT_S` | `3600` | One-shot direct receiver lifetime/timeout। |
| `remote_transfer_s3_bucket` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_BUCKET` | `None` | Presigned worker-to-worker transfers के लिए optional S3-compatible bucket। `s3` extra चाहिए। |
| `remote_transfer_s3_prefix` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PREFIX` | `'local-shell-mcp'` | Temporary transfer objects का object-key prefix। |
| `remote_transfer_s3_region` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_REGION` | `None` | Optional S3 region। |
| `remote_transfer_s3_endpoint_url` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_ENDPOINT_URL` | `None` | Optional S3-compatible endpoint URL। |
| `remote_transfer_s3_presign_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PRESIGN_TTL_S` | `3600` | Presigned PUT/GET URL lifetime। Transfer के बाद temporary objects delete होते हैं। |

### Shell और executable paths

| YAML key | Environment variable | Default | Notes |
|---|---|---|---|
| `shell_executable` | `LOCAL_SHELL_MCP_SHELL_EXECUTABLE` | `'/bin/bash'` |  |
| `shell_env_blocklist` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKLIST` | `['CLOUDFLARE_TUNNEL_TOKEN']` |  |
| `shell_env_blocked_prefixes` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKED_PREFIXES` | `['LOCAL_SHELL_MCP_', 'DOCKER_']` | Environment variables में comma-separated; YAML में list। |
| `tmux_bin` | `LOCAL_SHELL_MCP_TMUX_BIN` | `'tmux'` | Preferred tmux executable। उपलब्ध न होने पर Linux releases/Docker builds bundled helper उपयोग करते हैं; अन्यथा persistent shells native backend पर fallback करते हैं। |
| `rg_bin` | `LOCAL_SHELL_MCP_RG_BIN` | `'rg'` |  |
| `git_bin` | `LOCAL_SHELL_MCP_GIT_BIN` | `'git'` |  |
| `python_bin` | `LOCAL_SHELL_MCP_PYTHON_BIN` | `'python3'` |  |

### Authentication और OAuth

| YAML key | Environment variable | Default | Notes |
|---|---|---|---|
| `auth_mode` | `LOCAL_SHELL_MCP_AUTH_MODE` | `'oauth'` | Public deployments के लिए `oauth` उपयोग करें। |
| `auth_bypass_localhost` | `LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST` | `True` |  |
| `require_auth_for_mcp_discovery` | `LOCAL_SHELL_MCP_REQUIRE_AUTH_FOR_MCP_DISCOVERY` | `True` | MCP initialization और tool discovery से पहले OAuth require करता है। |
| `mcp_session_idle_timeout_s` | `LOCAL_SHELL_MCP_MCP_SESSION_IDLE_TIMEOUT_S` | `180` | Stateful Streamable HTTP sessions का idle timeout। |
| `mcp_max_sessions` | `LOCAL_SHELL_MCP_MCP_MAX_SESSIONS` | `1024` | Maximum concurrent stateful MCP sessions। |
| `public_base_url` | `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | `None` | External HTTPS origin। `/mcp` शामिल न करें। |
| `oauth_issuer` | `LOCAL_SHELL_MCP_OAUTH_ISSUER` | `None` |  |
| `oauth_resource` | `LOCAL_SHELL_MCP_OAUTH_RESOURCE` | `None` |  |
| `oauth_admin_pin` | `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` | `None` |  |
| `oauth_jwt_secret` | `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` | <generated or configured> |  |
| `oauth_access_token_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S` | `0` | `0` का अर्थ access tokens automatically expire नहीं होते। |
| `oauth_code_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_CODE_TTL_S` | `300` |  |

### Built-in policy lists

| YAML key | Environment variable | Default | Notes |
|---|---|---|---|
| `command_denylist` | `LOCAL_SHELL_MCP_COMMAND_DENYLIST` | `[]` | Full-container mode enabled होने पर automatically clear। |
| `path_denylist` | `LOCAL_SHELL_MCP_PATH_DENYLIST` | `[]` | Full-container mode enabled होने पर automatically clear। |

## YAML example

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

Durable Redis state वाला serverless controller:

```yaml
mode: mcp
stateless_controller: true
state_backend: redis
state_backend_url: redis://redis.internal:6379/0
remote_transfer_strategy: auto
```

`stateless_controller` persistent controller volume की जरूरत हटाता है। `memory` backend intentionally ephemeral है: cold start pending remote invites और worker identities invalidate करता है और OAuth clients, jobs तथा audit records discard करता है। यदि यह state cold starts के बाद बचना चाहिए, durable worker revocation semantics सहित, तो Redis उपयोग करें। Default `auth_mode=oauth` के साथ `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` से कम-से-कम 32 bytes random key material inject करें। Active remote RPC queues/futures process-local हैं, इसलिए remote workers वाले deployments को फिलहाल एक active controller instance चलाना चाहिए, multiple load-balanced controller replicas नहीं।

## Operational advice

- Container/VM disposable न हो तो `allow_full_container=false` रखें।
- हर public endpoint पर `auth_mode=oauth` रखें।
- Remote workers उपयोग न हों तो `remote_enabled` disable करें।
- Chat-downloadable artifacts कभी न चाहिए हों तो `file_download_enabled` disable करें।
- Command/file/audit limits coding tasks के लिए पर्याप्त ऊँचे पर accidental runaway output रोकने जितने bounded रखें।
