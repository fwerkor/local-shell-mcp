<!-- i18n-source-sha256: 5d2de552ba0ba0d1c76319ad9f87ab68e217fee6c607687f8260e14872e7dbcc -->
# الإعدادات

يوفر repository ملف بدء واحدًا قابلًا للنسخ: [`.env.example`](https://github.com/fwerkor/local-shell-mcp/blob/main/.env.example). يقرأ Docker Compose ملف `.env` الناتج تلقائيًا، ويمكن لبقية runtimes استخدام environment variables نفسها ذات prefix `LOCAL_SHELL_MCP_`. يبقى YAML input متقدمًا اختياريًا لـ binary/source deployments؛ أنشئ ملفًا صراحة واختره عبر `LOCAL_SHELL_MCP_CONFIG` أو `--config`. تتغلب environment variables على قيم YAML، لذا تجنب تعريف setting نفسه في الاثنين إلا إذا كان override مقصودًا. تستخدم YAML keys أسماء fields المبينة أدناه.

## الأولوية

1. Built-in defaults من `Settings`.
2. YAML config المختار عبر `LOCAL_SHELL_MCP_CONFIG` أو `--config`.
3. Environment variables ذات prefix `LOCAL_SHELL_MCP_`.
4. CLI flags مثل `--mode` و`--config` و`--remote` و`--no-remote`، والتي تضبط environment values المقابلة قبل تحميل settings.

## الحد الأدنى للإعداد العام

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-long-random-secret
```

للاختبار المحلي فقط، يكون `auth_bypass_localhost` مفعّلًا افتراضيًا. لا تعرض full MCP tools غير مصادَق عليها على شبكة عامة.

## مرجع settings

### الخادم وworkspace

| YAML key | Environment variable | Default | ملاحظات |
|---|---|---|---|
| `host` | `LOCAL_SHELL_MCP_HOST` | `'0.0.0.0'` |  |
| `port` | `LOCAL_SHELL_MCP_PORT` | `8765` |  |
| `forwarded_allow_ips` | `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS` | `'127.0.0.1'` | Proxy IPs موثوقة مفصولة بفواصل لمعالجة Uvicorn forwarded headers. استخدم `*` فقط عندما يكون direct ingress مقيدًا. |
| `mode` | `LOCAL_SHELL_MCP_MODE` | `'mcp'` | `mcp` أو `http` أو `stdio` أو القيمة المحجوزة `both`. |
| `workspace_root` | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | `PosixPath('/workspace')` |  |
| `state_dir` | `LOCAL_SHELL_MCP_STATE_DIR` | `PosixPath('/workspace/.local-shell-mcp')` |  |
| `audit_log_path` | `LOCAL_SHELL_MCP_AUDIT_LOG_PATH` | `PosixPath('/workspace/.local-shell-mcp/audit.jsonl')` |  |
| `agent_config_dir` | `LOCAL_SHELL_MCP_AGENT_CONFIG_DIR` | `PosixPath('/workspace/.local-shell-mcp/agent_config')` |  |
| `allow_full_container` | `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER` | `False` | يعطّل قيود workspace/path عند true؛ استخدمه فقط داخل disposable boundaries. |
| `disable_local` | `LOCAL_SHELL_MCP_DISABLE_LOCAL` | `False` | يعطّل controller host كهدف لتنفيذ shell/file/browser. تبقى remote workers وcontrol-plane services متاحة. |
| `stateless_controller` | `LOCAL_SHELL_MCP_STATELESS_CONTROLLER` | `False` | يجعل controller مناسبًا لـ ephemeral/serverless instances: يتضمن `disable_local`، يعطّل local file links/wallpaper caching، ويستخدم `memory` افتراضيًا كـ `state_backend`. مع `auth_mode=oauth` اضبط `oauth_jwt_secret` قويًا صراحة. |
| `state_backend` | `LOCAL_SHELL_MCP_STATE_BACKEND` | `'file'` | `file` أو `memory` أو `redis`. استخدم Redis عندما يجب أن ينجو serverless controller state من cold starts. |
| `state_backend_url` | `LOCAL_SHELL_MCP_STATE_BACKEND_URL` | `None` | Redis connection URL عندما `state_backend=redis`. يتم redaction في diagnostics. |
| `state_backend_prefix` | `LOCAL_SHELL_MCP_STATE_BACKEND_PREFIX` | `'local-shell-mcp'` | Namespace لـ memory/Redis control-plane state. |

### الحدود

| YAML key | Environment variable | Default | ملاحظات |
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
| `max_skills` | `LOCAL_SHELL_MCP_MAX_SKILLS` | `256` | الحد الأقصى لعدد Skill directories التي يعيدها registry scan واحد. |
| `max_skill_related_files` | `LOCAL_SHELL_MCP_MAX_SKILL_RELATED_FILES` | `1000` | الحد الأقصى لعدد related files المعادة لـ Skill واحد. |
| `max_skill_scan_entries` | `LOCAL_SHELL_MCP_MAX_SKILL_SCAN_ENTRIES` | `5000` | الحد الأقصى لعدد filesystem entries التي يفحصها registry scan `skill_list` أو direct Skill load. |
| `max_skill_path_bytes` | `LOCAL_SHELL_MCP_MAX_SKILL_PATH_BYTES` | `200000` | الحد الأقصى لعدد UTF-8 bytes المستخدمة في related-file paths المعادة. |
| `max_read_many_files` | `LOCAL_SHELL_MCP_MAX_READ_MANY_FILES` | `100` |  |
| `max_read_many_total_bytes` | `LOCAL_SHELL_MCP_MAX_READ_MANY_TOTAL_BYTES` | `5000000` |  |
| `max_http_request_bytes` | `LOCAL_SHELL_MCP_MAX_HTTP_REQUEST_BYTES` | `16000000` | أقصى HTTP request body buffered عبر MCP وREST وOAuth وUI وremote-worker endpoints. |
| `max_job_log_bytes` | `LOCAL_SHELL_MCP_MAX_JOB_LOG_BYTES` | `10000000` | أقصى output bytes محفوظة لكل محاولة long-running job. |
| `max_jobs` | `LOCAL_SHELL_MCP_MAX_JOBS` | `1000` | الحد الأقصى لـ long-running job records المحفوظة؛ active jobs لا يتم prune لها. |
| `max_audit_tail_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES` | `1000000` |  |
| `max_audit_log_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES` | `20000000` |  |
| `max_audit_archive_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_ARCHIVE_BYTES` | `512000000` |  |
| `max_tmp_files` | `LOCAL_SHELL_MCP_MAX_TMP_FILES` | `500` |  |
| `max_tmp_bytes` | `LOCAL_SHELL_MCP_MAX_TMP_BYTES` | `50000000` |  |
| `max_transfer_archive_entries` | `LOCAL_SHELL_MCP_MAX_TRANSFER_ARCHIVE_ENTRIES` | `100000` | الحد الأقصى للـ entries المقبولة عند unpack لـ transferred directory archive. |
| `max_transfer_unpacked_bytes` | `LOCAL_SHELL_MCP_MAX_TRANSFER_UNPACKED_BYTES` | `10000000000` | أقصى declared expanded bytes مقبولة لـ transferred directory archive. |
| `max_concurrent_commands` | `LOCAL_SHELL_MCP_MAX_CONCURRENT_COMMANDS` | `4` |  |
| `max_tmux_sessions` | `LOCAL_SHELL_MCP_MAX_TMUX_SESSIONS` | `16` | الحد الأقصى لـ persistent shell sessions عبر backends tmux وConPTY وnative fallback. |

### روابط الملفات

| YAML key | Environment variable | Default | ملاحظات |
|---|---|---|---|
| `file_download_enabled` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED` | `True` |  |
| `file_download_default_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_TTL_S` | `3600` |  |
| `file_download_max_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_TTL_S` | `604800` |  |
| `file_download_default_max_downloads` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_MAX_DOWNLOADS` | `0` | `0` يعني عدم وجود default download-count limit. |
| `file_download_max_file_bytes` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_FILE_BYTES` | `0` | `0` يعني عدم وجود configured file-size cap لـ download links. |

### واجهة المستخدم

| YAML key | Environment variable | Default | ملاحظات |
|---|---|---|---|
| `logical_sessions_enabled` | `LOCAL_SHELL_MCP_LOGICAL_SESSIONS_ENABLED` | `True` | يعرض `session_manage` و`plan_manage` ويضيف الوسيط `logical_session_id` المطلوب مع السماح بقيمة null إلى أدوات MCP العادية. عطّله للحصول على سطح أدوات أصغر من دون Sessions. |
| `live_workspace_enabled` | `LOCAL_SHELL_MCP_LIVE_WORKSPACE_ENABLED` | `True` | يعرض أدوات وموارد ومسارات `/api/live/*` الخاصة بـ MCP App Live Workspace. يتطلب `ui_enabled` ولا يتوفر في وضع `stdio`. |
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `True` | يركب native OpenTUI launcher وWebUI shell وPTY WebSocket وroutes `/api/ui/*`. |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `'/ui'` | WebUI mount path على service نفسه. |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | `None` | Optional command override لحل OpenTUI executable. |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `'bing'` | `bing` أو `aurora` أو `none`. |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | Timeout لـ inactive browser PTY؛ `0` يعطله. |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | الحد الأقصى لـ browser OpenTUI PTYs المتزامنة. |

### Remote workers

| YAML key | Environment variable | Default | ملاحظات |
|---|---|---|---|
| `remote_enabled` | `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `True` | يتحكم في `/join` و`/remote/*` وMCP tools `remote_*`. |
| `remote_invite_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_INVITE_TTL_S` | `7200` |  |
| `remote_poll_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S` | `25` |  |
| `remote_job_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S` | `3600` |  |
| `remote_max_pending_jobs` | `LOCAL_SHELL_MCP_REMOTE_MAX_PENDING_JOBS` | `256` | الحد الأقصى لـ queued/pending jobs لكل worker. |
| `remote_cancelled_job_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_CANCELLED_JOB_TTL_S` | `3600` | Retention time لـ cancellation tombstones المستخدمة لتخطي queued jobs التي انتهى timeout لها. |
| `remote_transfer_strategy` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_STRATEGY` | `'auto'` | `auto` أو `relay` أو `direct` أو `object_store`. يجرب `auto` peer-direct المفعّل ثم S3 المضبوط ثم bounded-memory controller relay. |
| `remote_peer_transfer_enabled` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ENABLED` | `False` | يفعّل اختياريًا one-shot HTTP receiver على destination worker للـ direct worker-to-worker transfer. فعّل فقط على trusted private network مثل VPC/Tailscale. |
| `remote_peer_transfer_bind_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_BIND_HOST` | `'0.0.0.0'` | Bind address لـ one-shot destination-worker receiver. |
| `remote_peer_transfer_advertise_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ADVERTISE_HOST` | `None` | Address المعلن إلى source worker؛ default هو destination worker hostname/FQDN. |
| `remote_peer_transfer_port` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_PORT` | `0` | Receiver port؛ `0` يختار ephemeral port. |
| `remote_peer_transfer_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_TIMEOUT_S` | `3600` | Lifetime/timeout لـ one-shot direct receiver. |
| `remote_transfer_s3_bucket` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_BUCKET` | `None` | Optional S3-compatible bucket لـ presigned worker-to-worker transfers. يتطلب extra `s3`. |
| `remote_transfer_s3_prefix` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PREFIX` | `'local-shell-mcp'` | Object-key prefix لـ temporary transfer objects. |
| `remote_transfer_s3_region` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_REGION` | `None` | Optional S3 region. |
| `remote_transfer_s3_endpoint_url` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_ENDPOINT_URL` | `None` | Optional S3-compatible endpoint URL. |
| `remote_transfer_s3_presign_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PRESIGN_TTL_S` | `3600` | Lifetime لـ presigned PUT/GET URL. تحذف temporary objects بعد transfer. |

### Shell ومسارات executables

| YAML key | Environment variable | Default | ملاحظات |
|---|---|---|---|
| `shell_executable` | `LOCAL_SHELL_MCP_SHELL_EXECUTABLE` | `'/bin/bash'` |  |
| `shell_env_blocklist` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKLIST` | `['CLOUDFLARE_TUNNEL_TOKEN']` |  |
| `shell_env_blocked_prefixes` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKED_PREFIXES` | `['LOCAL_SHELL_MCP_', 'DOCKER_']` | Comma-separated في environment variables؛ list في YAML. |
| `tmux_bin` | `LOCAL_SHELL_MCP_TMUX_BIN` | `'tmux'` | Preferred tmux executable. إذا لم يتوفر، تستخدم Linux releases وDocker builds الـ bundled helper؛ وإلا persistent shells fallback إلى native backend. |
| `rg_bin` | `LOCAL_SHELL_MCP_RG_BIN` | `'rg'` |  |
| `git_bin` | `LOCAL_SHELL_MCP_GIT_BIN` | `'git'` |  |
| `python_bin` | `LOCAL_SHELL_MCP_PYTHON_BIN` | `'python3'` |  |

### المصادقة وOAuth

| YAML key | Environment variable | Default | ملاحظات |
|---|---|---|---|
| `auth_mode` | `LOCAL_SHELL_MCP_AUTH_MODE` | `'oauth'` | استخدم `oauth` في public deployments. |
| `auth_bypass_localhost` | `LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST` | `True` |  |
| `require_auth_for_mcp_discovery` | `LOCAL_SHELL_MCP_REQUIRE_AUTH_FOR_MCP_DISCOVERY` | `True` | يتطلب OAuth قبل MCP initialization وtool discovery. |
| `mcp_session_idle_timeout_s` | `LOCAL_SHELL_MCP_MCP_SESSION_IDLE_TIMEOUT_S` | `180` | Idle timeout لـ Stateful Streamable HTTP sessions. |
| `mcp_max_sessions` | `LOCAL_SHELL_MCP_MCP_MAX_SESSIONS` | `1024` | الحد الأقصى لـ concurrent stateful MCP sessions. |
| `public_base_url` | `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | `None` | External HTTPS origin. لا تضمّن `/mcp`. |
| `oauth_issuer` | `LOCAL_SHELL_MCP_OAUTH_ISSUER` | `None` |  |
| `oauth_resource` | `LOCAL_SHELL_MCP_OAUTH_RESOURCE` | `None` |  |
| `oauth_admin_pin` | `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` | `None` |  |
| `oauth_jwt_secret` | `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` | <generated or configured> |  |
| `oauth_access_token_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S` | `0` | `0` يعني أن access tokens لا تنتهي تلقائيًا. |
| `oauth_code_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_CODE_TTL_S` | `300` |  |

### قوائم policy المدمجة

| YAML key | Environment variable | Default | ملاحظات |
|---|---|---|---|
| `command_denylist` | `LOCAL_SHELL_MCP_COMMAND_DENYLIST` | `[]` | تُمسح تلقائيًا عند تفعيل full-container mode. |
| `path_denylist` | `LOCAL_SHELL_MCP_PATH_DENYLIST` | `[]` | تُمسح تلقائيًا عند تفعيل full-container mode. |

## مثال YAML

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

Controller serverless مع Redis state دائم:

```yaml
mode: mcp
stateless_controller: true
state_backend: redis
state_backend_url: redis://redis.internal:6379/0
remote_transfer_strategy: auto
```

يلغي `stateless_controller` الحاجة إلى persistent controller volume. Backend `memory` ephemeral عمدًا: cold start يلغي remote invites المعلقة وworker identities ويحذف OAuth clients وjobs وaudit records. استخدم Redis عندما يجب أن ينجو أي من هذا state من cold starts، بما في ذلك durable worker revocation semantics. مع default `auth_mode=oauth`، مرر 32 bytes على الأقل من random key material عبر `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET`. Active remote RPC queues/futures هي process-local، لذا يجب حاليًا على deployments التي تستخدم remote workers تشغيل active controller instance واحدة بدل عدة load-balanced controller replicas.

## نصائح تشغيلية

- أبقِ `allow_full_container=false` إلا إذا كان container/VM disposable.
- أبقِ `auth_mode=oauth` لأي public endpoint.
- عطّل `remote_enabled` إن لم تستخدم remote workers.
- عطّل `file_download_enabled` إن لم تحتج أبدًا إلى artifacts قابلة للتنزيل من chat.
- اجعل حدود command/file/audit عالية بما يكفي لـ coding tasks ومنخفضة بما يكفي لمنع accidental runaway output.
