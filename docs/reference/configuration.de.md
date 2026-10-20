<!-- i18n-source-sha256: 5d2de552ba0ba0d1c76319ad9f87ab68e217fee6c607687f8260e14872e7dbcc -->
# Konfiguration

Das Repository liefert eine kopierbare Startdatei: [`.env.example`](https://github.com/fwerkor/local-shell-mcp/blob/main/.env.example). Docker Compose liest die resultierende `.env` automatisch, und andere Runtimes können dieselben `LOCAL_SHELL_MCP_`-Umgebungsvariablen verwenden. YAML bleibt ein optionaler fortgeschrittener Input für Binary- oder Source-Deployments; erstellen Sie explizit eine Datei und wählen Sie sie mit `LOCAL_SHELL_MCP_CONFIG` oder `--config`. Umgebungsvariablen überschreiben YAML-Werte. Definieren Sie daher denselben Setting nicht an beiden Stellen, außer der Override ist beabsichtigt. YAML-Keys verwenden die unten gezeigten Feldnamen.

## Priorität

1. Eingebaute Defaults aus `Settings`.
2. YAML-Konfiguration, gewählt über `LOCAL_SHELL_MCP_CONFIG` oder `--config`.
3. Umgebungsvariablen mit Präfix `LOCAL_SHELL_MCP_`.
4. CLI-Flags wie `--mode`, `--config`, `--remote` und `--no-remote`, die die entsprechenden Umgebungswerte vor dem Laden der Settings setzen.

## Minimale öffentliche Konfiguration

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-long-random-secret
```

Für reine Localhost-Tests ist `auth_bypass_localhost` standardmäßig aktiviert. Stellen Sie unauthentifizierte vollständige MCP-Tools nicht in einem öffentlichen Netzwerk bereit.

## Settings-Referenz

### Server und Workspace

| YAML-Key | Umgebungsvariable | Default | Hinweise |
|---|---|---|---|
| `host` | `LOCAL_SHELL_MCP_HOST` | `'0.0.0.0'` |  |
| `port` | `LOCAL_SHELL_MCP_PORT` | `8765` |  |
| `forwarded_allow_ips` | `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS` | `'127.0.0.1'` | Kommagetrennte vertrauenswürdige Proxy-IPs für Uvicorn Forwarded-Header-Verarbeitung. `*` nur verwenden, wenn direkter Ingress eingeschränkt ist. |
| `mode` | `LOCAL_SHELL_MCP_MODE` | `'mcp'` | `mcp`, `http`, `stdio` oder der reservierte Wert `both`. |
| `workspace_root` | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | `PosixPath('/workspace')` |  |
| `state_dir` | `LOCAL_SHELL_MCP_STATE_DIR` | `PosixPath('/workspace/.local-shell-mcp')` |  |
| `audit_log_path` | `LOCAL_SHELL_MCP_AUDIT_LOG_PATH` | `PosixPath('/workspace/.local-shell-mcp/audit.jsonl')` |  |
| `agent_config_dir` | `LOCAL_SHELL_MCP_AGENT_CONFIG_DIR` | `PosixPath('/workspace/.local-shell-mcp/agent_config')` |  |
| `allow_full_container` | `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER` | `False` | Deaktiviert Workspace-/Path-Beschränkungen bei true; nur innerhalb disposable Boundaries verwenden. |
| `disable_local` | `LOCAL_SHELL_MCP_DISABLE_LOCAL` | `False` | Deaktiviert den Controller-Host als Shell-/File-/Browser-Ausführungsziel. Remote Workers und Control-Plane-Services bleiben verfügbar. |
| `stateless_controller` | `LOCAL_SHELL_MCP_STATELESS_CONTROLLER` | `False` | Macht den Controller für ephemere/serverless Instanzen geeignet: impliziert `disable_local`, deaktiviert lokale File Links/Wallpaper-Caching und setzt `state_backend` standardmäßig auf `memory`. Bei `auth_mode=oauth` explizit ein starkes `oauth_jwt_secret` konfigurieren. |
| `state_backend` | `LOCAL_SHELL_MCP_STATE_BACKEND` | `'file'` | `file`, `memory` oder `redis`. Redis verwenden, wenn Serverless-Controller-State Cold Starts überleben muss. |
| `state_backend_url` | `LOCAL_SHELL_MCP_STATE_BACKEND_URL` | `None` | Redis-Verbindungs-URL bei `state_backend=redis`. In Diagnostics redacted. |
| `state_backend_prefix` | `LOCAL_SHELL_MCP_STATE_BACKEND_PREFIX` | `'local-shell-mcp'` | Namespace für Memory-/Redis-Control-Plane-State. |

### Limits

| YAML-Key | Umgebungsvariable | Default | Hinweise |
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
| `max_skills` | `LOCAL_SHELL_MCP_MAX_SKILLS` | `256` | Maximale Anzahl Skill-Verzeichnisse pro Registry-Scan. |
| `max_skill_related_files` | `LOCAL_SHELL_MCP_MAX_SKILL_RELATED_FILES` | `1000` | Maximale Anzahl Related Files pro Skill. |
| `max_skill_scan_entries` | `LOCAL_SHELL_MCP_MAX_SKILL_SCAN_ENTRIES` | `5000` | Maximale Filesystem-Entries, die ein `skill_list`-Registry-Scan oder direkter Skill-Load untersucht. |
| `max_skill_path_bytes` | `LOCAL_SHELL_MCP_MAX_SKILL_PATH_BYTES` | `200000` | Maximale UTF-8-Bytes für zurückgegebene Related-File-Pfade. |
| `max_read_many_files` | `LOCAL_SHELL_MCP_MAX_READ_MANY_FILES` | `100` |  |
| `max_read_many_total_bytes` | `LOCAL_SHELL_MCP_MAX_READ_MANY_TOTAL_BYTES` | `5000000` |  |
| `max_http_request_bytes` | `LOCAL_SHELL_MCP_MAX_HTTP_REQUEST_BYTES` | `16000000` | Maximal gepufferter HTTP-Request-Body über MCP-, REST-, OAuth-, UI- und Remote-worker-Endpoints. |
| `max_job_log_bytes` | `LOCAL_SHELL_MCP_MAX_JOB_LOG_BYTES` | `10000000` | Maximal gespeicherte Output-Bytes pro Long-running-Job-Versuch. |
| `max_jobs` | `LOCAL_SHELL_MCP_MAX_JOBS` | `1000` | Maximale Anzahl gespeicherter Long-running-Job-Records; aktive Jobs werden nie pruned. |
| `max_audit_tail_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES` | `1000000` |  |
| `max_audit_log_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES` | `20000000` |  |
| `max_audit_archive_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_ARCHIVE_BYTES` | `512000000` |  |
| `max_tmp_files` | `LOCAL_SHELL_MCP_MAX_TMP_FILES` | `500` |  |
| `max_tmp_bytes` | `LOCAL_SHELL_MCP_MAX_TMP_BYTES` | `50000000` |  |
| `max_transfer_archive_entries` | `LOCAL_SHELL_MCP_MAX_TRANSFER_ARCHIVE_ENTRIES` | `100000` | Maximale Anzahl Entries beim Entpacken eines übertragenen Directory-Archives. |
| `max_transfer_unpacked_bytes` | `LOCAL_SHELL_MCP_MAX_TRANSFER_UNPACKED_BYTES` | `10000000000` | Maximal akzeptierte deklarierte Expanded Bytes für ein übertragenes Directory-Archive. |
| `max_concurrent_commands` | `LOCAL_SHELL_MCP_MAX_CONCURRENT_COMMANDS` | `4` |  |
| `max_tmux_sessions` | `LOCAL_SHELL_MCP_MAX_TMUX_SESSIONS` | `16` | Maximale Persistent-Shell-Sessions über tmux-, ConPTY- und Native-Fallback-Backends. |

### File Links

| YAML-Key | Umgebungsvariable | Default | Hinweise |
|---|---|---|---|
| `file_download_enabled` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED` | `True` |  |
| `file_download_default_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_TTL_S` | `3600` |  |
| `file_download_max_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_TTL_S` | `604800` |  |
| `file_download_default_max_downloads` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_MAX_DOWNLOADS` | `0` | `0` bedeutet kein standardmäßiges Download-Count-Limit. |
| `file_download_max_file_bytes` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_FILE_BYTES` | `0` | `0` bedeutet kein konfiguriertes File-Size-Limit für Download-Links. |

### Human Interface

| YAML-Key | Umgebungsvariable | Default | Hinweise |
|---|---|---|---|
| `logical_sessions_enabled` | `LOCAL_SHELL_MCP_LOGICAL_SESSIONS_ENABLED` | `True` | Stellt `session_manage` und `plan_manage` bereit und ergänzt normale MCP-Tools um das erforderliche, aber nullable Argument `logical_session_id`. Deaktivieren für eine kleinere Tool-Oberfläche ohne Sessions. |
| `live_workspace_enabled` | `LOCAL_SHELL_MCP_LIVE_WORKSPACE_ENABLED` | `True` | Stellt Tools, Ressourcen und `/api/live/*`-Routen des MCP App Live Workspace bereit. Benötigt `ui_enabled` und ist im `stdio`-Modus nicht verfügbar. |
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `True` | Mountet Native OpenTUI Launcher, WebUI Shell, PTY WebSocket und `/api/ui/*`-Routen. |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `'/ui'` | WebUI-Mount-Pfad auf demselben Service. |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | `None` | Optionaler Command-Override für die Auflösung des OpenTUI-Executables. |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `'bing'` | `bing`, `aurora` oder `none`. |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | Timeout für inaktive Browser-PTYs; `0` deaktiviert ihn. |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | Maximale gleichzeitige Browser-OpenTUI-PTYs. |

### Remote Workers

| YAML-Key | Umgebungsvariable | Default | Hinweise |
|---|---|---|---|
| `remote_enabled` | `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `True` | Steuert `/join`, `/remote/*` und `remote_*` MCP-Tools. |
| `remote_invite_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_INVITE_TTL_S` | `7200` |  |
| `remote_poll_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S` | `25` |  |
| `remote_job_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S` | `3600` |  |
| `remote_max_pending_jobs` | `LOCAL_SHELL_MCP_REMOTE_MAX_PENDING_JOBS` | `256` | Maximale queued/pending Jobs pro Worker. |
| `remote_cancelled_job_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_CANCELLED_JOB_TTL_S` | `3600` | Aufbewahrungszeit für Cancellation Tombstones, mit denen timed-out queued Jobs übersprungen werden. |
| `remote_transfer_strategy` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_STRATEGY` | `'auto'` | `auto`, `relay`, `direct` oder `object_store`. `auto` versucht aktiviertes Peer-direct, dann konfiguriertes S3, dann bounded-memory Controller-Relay. |
| `remote_peer_transfer_enabled` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ENABLED` | `False` | Aktiviert optional einen One-shot-HTTP-Receiver auf dem Destination Worker für direkten Worker-to-worker-Transfer. Nur in vertrauenswürdigen privaten Netzen wie VPC/Tailscale aktivieren. |
| `remote_peer_transfer_bind_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_BIND_HOST` | `'0.0.0.0'` | Bind-Adresse des One-shot-Receivers auf dem Destination Worker. |
| `remote_peer_transfer_advertise_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ADVERTISE_HOST` | `None` | Adresse, die dem Source Worker bekanntgegeben wird; standardmäßig Destination-Worker-Hostname/FQDN. |
| `remote_peer_transfer_port` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_PORT` | `0` | Receiver-Port; `0` wählt einen ephemeren Port. |
| `remote_peer_transfer_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_TIMEOUT_S` | `3600` | Lifetime/Timeout des One-shot-Direct-Receivers. |
| `remote_transfer_s3_bucket` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_BUCKET` | `None` | Optionaler S3-kompatibler Bucket für presigned Worker-to-worker-Transfers. Benötigt das `s3` Extra. |
| `remote_transfer_s3_prefix` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PREFIX` | `'local-shell-mcp'` | Object-Key-Präfix für temporäre Transferobjekte. |
| `remote_transfer_s3_region` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_REGION` | `None` | Optionale S3-Region. |
| `remote_transfer_s3_endpoint_url` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_ENDPOINT_URL` | `None` | Optionale S3-kompatible Endpoint-URL. |
| `remote_transfer_s3_presign_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PRESIGN_TTL_S` | `3600` | Lifetime presigned PUT/GET URLs. Temporäre Objekte werden nach dem Transfer gelöscht. |

### Shell- und Executable-Pfade

| YAML-Key | Umgebungsvariable | Default | Hinweise |
|---|---|---|---|
| `shell_executable` | `LOCAL_SHELL_MCP_SHELL_EXECUTABLE` | `'/bin/bash'` |  |
| `shell_env_blocklist` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKLIST` | `['CLOUDFLARE_TUNNEL_TOKEN']` |  |
| `shell_env_blocked_prefixes` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKED_PREFIXES` | `['LOCAL_SHELL_MCP_', 'DOCKER_']` | Kommagetrennt in Umgebungsvariablen; Liste in YAML. |
| `tmux_bin` | `LOCAL_SHELL_MCP_TMUX_BIN` | `'tmux'` | Bevorzugtes tmux-Executable. Ist es nicht verfügbar, nutzen Linux Releases und Docker Builds den eingebetteten Helper; andernfalls fallen Persistent Shells auf das Native Backend zurück. |
| `rg_bin` | `LOCAL_SHELL_MCP_RG_BIN` | `'rg'` |  |
| `git_bin` | `LOCAL_SHELL_MCP_GIT_BIN` | `'git'` |  |
| `python_bin` | `LOCAL_SHELL_MCP_PYTHON_BIN` | `'python3'` |  |

### Authentifizierung und OAuth

| YAML-Key | Umgebungsvariable | Default | Hinweise |
|---|---|---|---|
| `auth_mode` | `LOCAL_SHELL_MCP_AUTH_MODE` | `'oauth'` | Für öffentliche Deployments `oauth` verwenden. |
| `auth_bypass_localhost` | `LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST` | `True` |  |
| `require_auth_for_mcp_discovery` | `LOCAL_SHELL_MCP_REQUIRE_AUTH_FOR_MCP_DISCOVERY` | `True` | OAuth vor MCP-Initialisierung und Tool Discovery verlangen. |
| `mcp_session_idle_timeout_s` | `LOCAL_SHELL_MCP_MCP_SESSION_IDLE_TIMEOUT_S` | `180` | Idle Timeout für Stateful Streamable HTTP Sessions. |
| `mcp_max_sessions` | `LOCAL_SHELL_MCP_MCP_MAX_SESSIONS` | `1024` | Maximale gleichzeitige stateful MCP Sessions. |
| `public_base_url` | `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | `None` | Externer HTTPS-Origin. `/mcp` nicht einschließen. |
| `oauth_issuer` | `LOCAL_SHELL_MCP_OAUTH_ISSUER` | `None` |  |
| `oauth_resource` | `LOCAL_SHELL_MCP_OAUTH_RESOURCE` | `None` |  |
| `oauth_admin_pin` | `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` | `None` |  |
| `oauth_jwt_secret` | `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` | <generated or configured> |  |
| `oauth_access_token_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S` | `0` | `0` bedeutet, Access Tokens laufen nicht automatisch ab. |
| `oauth_code_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_CODE_TTL_S` | `300` |  |

### Eingebaute Policy-Listen

| YAML-Key | Umgebungsvariable | Default | Hinweise |
|---|---|---|---|
| `command_denylist` | `LOCAL_SHELL_MCP_COMMAND_DENYLIST` | `[]` | Wird automatisch geleert, wenn Full-container Mode aktiviert ist. |
| `path_denylist` | `LOCAL_SHELL_MCP_PATH_DENYLIST` | `[]` | Wird automatisch geleert, wenn Full-container Mode aktiviert ist. |

## YAML-Beispiel

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

Serverless Controller mit durable Redis-State:

```yaml
mode: mcp
stateless_controller: true
state_backend: redis
state_backend_url: redis://redis.internal:6379/0
remote_transfer_strategy: auto
```

`stateless_controller` macht ein persistentes Controller-Volume überflüssig. Das `memory`-Backend ist absichtlich ephemer: Ein Cold Start invalidiert pending remote invites und worker identities und verwirft OAuth clients, jobs und audit records. Nutzen Sie Redis, wenn dieser State Cold Starts überleben muss, einschließlich dauerhafter Worker-Revocation-Semantik. Mit dem Default `auth_mode=oauth` müssen mindestens 32 Bytes zufälliges Schlüsselmaterial über `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` injiziert werden. Aktive Remote-RPC-Queues/Futures sind process-local, daher sollten Deployments mit Remote Workers derzeit eine aktive Controller-Instanz statt mehrerer load-balanced Replicas betreiben.

## Betriebshinweise

- Lassen Sie `allow_full_container=false`, außer Container oder VM sind disposable.
- Lassen Sie `auth_mode=oauth` für jeden öffentlichen Endpoint aktiviert.
- Deaktivieren Sie `remote_enabled`, wenn Sie keine Remote Workers verwenden.
- Deaktivieren Sie `file_download_enabled`, wenn Sie nie aus dem Chat downloadbare Artifacts benötigen.
- Setzen Sie Command-, File- und Audit-Limits hoch genug für Coding Tasks, aber niedrig genug gegen versehentlichen Runaway Output.
