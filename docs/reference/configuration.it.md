<!-- i18n-source-sha256: 5d2de552ba0ba0d1c76319ad9f87ab68e217fee6c607687f8260e14872e7dbcc -->
# Configurazione

Il repository include un solo file iniziale copiabile: [`.env.example`](https://github.com/fwerkor/local-shell-mcp/blob/main/.env.example). Docker Compose legge automaticamente il `.env` risultante e gli altri runtime possono usare le stesse environment variables `LOCAL_SHELL_MCP_`. YAML resta un input avanzato opzionale per deployment binary o source; crea esplicitamente un file e selezionalo con `LOCAL_SHELL_MCP_CONFIG` o `--config`. Le environment variables sovrascrivono i valori YAML, quindi evita di definire lo stesso setting in entrambi salvo quando l’override è intenzionale. Le YAML keys usano i field names riportati sotto.

## Precedenza

1. Defaults built-in di `Settings`.
2. Config YAML selezionata da `LOCAL_SHELL_MCP_CONFIG` o `--config`.
3. Environment variables con prefisso `LOCAL_SHELL_MCP_`.
4. CLI flags come `--mode`, `--config`, `--remote` e `--no-remote`, che impostano i corrispondenti environment values prima del load dei settings.

## Configurazione pubblica minima

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-long-random-secret
```

Per test solo localhost, `auth_bypass_localhost` è abilitato di default. Non esporre full MCP tools senza autenticazione su una rete pubblica.

## Riferimento settings

### Server e workspace

| YAML key | Environment variable | Default | Note |
|---|---|---|---|
| `host` | `LOCAL_SHELL_MCP_HOST` | `'0.0.0.0'` |  |
| `port` | `LOCAL_SHELL_MCP_PORT` | `8765` |  |
| `forwarded_allow_ips` | `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS` | `'127.0.0.1'` | IP proxy trusted separati da virgola per handling dei forwarded headers Uvicorn. Usa `*` solo se direct ingress è limitato. |
| `mode` | `LOCAL_SHELL_MCP_MODE` | `'mcp'` | `mcp`, `http`, `stdio` o il valore riservato `both`. |
| `workspace_root` | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | `PosixPath('/workspace')` |  |
| `state_dir` | `LOCAL_SHELL_MCP_STATE_DIR` | `PosixPath('/workspace/.local-shell-mcp')` |  |
| `audit_log_path` | `LOCAL_SHELL_MCP_AUDIT_LOG_PATH` | `PosixPath('/workspace/.local-shell-mcp/audit.jsonl')` |  |
| `agent_config_dir` | `LOCAL_SHELL_MCP_AGENT_CONFIG_DIR` | `PosixPath('/workspace/.local-shell-mcp/agent_config')` |  |
| `allow_full_container` | `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER` | `False` | Disabilita restrizioni workspace/path quando true; usa solo dentro boundaries disposable. |
| `disable_local` | `LOCAL_SHELL_MCP_DISABLE_LOCAL` | `False` | Disabilita controller host come target di esecuzione shell/file/browser. Remote workers e control-plane services restano disponibili. |
| `stateless_controller` | `LOCAL_SHELL_MCP_STATELESS_CONTROLLER` | `False` | Rende il controller adatto a istanze ephemeral/serverless: implica `disable_local`, disabilita local file links/wallpaper caching e usa `memory` come `state_backend` di default. Con `auth_mode=oauth`, configura esplicitamente un `oauth_jwt_secret` forte. |
| `state_backend` | `LOCAL_SHELL_MCP_STATE_BACKEND` | `'file'` | `file`, `memory` o `redis`. Usa Redis quando lo state del controller serverless deve sopravvivere ai cold start. |
| `state_backend_url` | `LOCAL_SHELL_MCP_STATE_BACKEND_URL` | `None` | Redis connection URL quando `state_backend=redis`. Redacted nei diagnostics. |
| `state_backend_prefix` | `LOCAL_SHELL_MCP_STATE_BACKEND_PREFIX` | `'local-shell-mcp'` | Namespace dello state control-plane memory/Redis. |

### Limiti

| YAML key | Environment variable | Default | Note |
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
| `max_skills` | `LOCAL_SHELL_MCP_MAX_SKILLS` | `256` | Numero massimo di directory Skill restituite da un registry scan. |
| `max_skill_related_files` | `LOCAL_SHELL_MCP_MAX_SKILL_RELATED_FILES` | `1000` | Numero massimo di related files restituiti per uno Skill. |
| `max_skill_scan_entries` | `LOCAL_SHELL_MCP_MAX_SKILL_SCAN_ENTRIES` | `5000` | Numero massimo di filesystem entries esaminati da un registry scan `skill_list` o direct Skill load. |
| `max_skill_path_bytes` | `LOCAL_SHELL_MCP_MAX_SKILL_PATH_BYTES` | `200000` | Numero massimo di bytes UTF-8 usati dai path di related files restituiti. |
| `max_read_many_files` | `LOCAL_SHELL_MCP_MAX_READ_MANY_FILES` | `100` |  |
| `max_read_many_total_bytes` | `LOCAL_SHELL_MCP_MAX_READ_MANY_TOTAL_BYTES` | `5000000` |  |
| `max_http_request_bytes` | `LOCAL_SHELL_MCP_MAX_HTTP_REQUEST_BYTES` | `16000000` | Massimo HTTP request body bufferizzato tra endpoint MCP, REST, OAuth, UI e remote-worker. |
| `max_job_log_bytes` | `LOCAL_SHELL_MCP_MAX_JOB_LOG_BYTES` | `10000000` | Massimo di output bytes conservati per ogni tentativo long-running job. |
| `max_jobs` | `LOCAL_SHELL_MCP_MAX_JOBS` | `1000` | Numero massimo di long-running job records conservati; gli active jobs non vengono mai pruned. |
| `max_audit_tail_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES` | `1000000` |  |
| `max_audit_log_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES` | `20000000` |  |
| `max_audit_archive_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_ARCHIVE_BYTES` | `512000000` |  |
| `max_tmp_files` | `LOCAL_SHELL_MCP_MAX_TMP_FILES` | `500` |  |
| `max_tmp_bytes` | `LOCAL_SHELL_MCP_MAX_TMP_BYTES` | `50000000` |  |
| `max_transfer_archive_entries` | `LOCAL_SHELL_MCP_MAX_TRANSFER_ARCHIVE_ENTRIES` | `100000` | Numero massimo di entries accettati nel disimballaggio di un archive di directory trasferito. |
| `max_transfer_unpacked_bytes` | `LOCAL_SHELL_MCP_MAX_TRANSFER_UNPACKED_BYTES` | `10000000000` | Massimo di declared expanded bytes accettati per un archive di directory trasferito. |
| `max_concurrent_commands` | `LOCAL_SHELL_MCP_MAX_CONCURRENT_COMMANDS` | `4` |  |
| `max_tmux_sessions` | `LOCAL_SHELL_MCP_MAX_TMUX_SESSIONS` | `16` | Massimo di persistent shell sessions tra backend tmux, ConPTY e native fallback. |

### Link ai file

| YAML key | Environment variable | Default | Note |
|---|---|---|---|
| `file_download_enabled` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED` | `True` |  |
| `file_download_default_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_TTL_S` | `3600` |  |
| `file_download_max_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_TTL_S` | `604800` |  |
| `file_download_default_max_downloads` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_MAX_DOWNLOADS` | `0` | `0` significa nessun default download-count limit. |
| `file_download_max_file_bytes` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_FILE_BYTES` | `0` | `0` significa nessun configured file-size cap per download links. |

### Interfaccia umana

| YAML key | Environment variable | Default | Note |
|---|---|---|---|
| `logical_sessions_enabled` | `LOCAL_SHELL_MCP_LOGICAL_SESSIONS_ENABLED` | `True` | Espone `session_manage` e `plan_manage` e aggiunge l’argomento obbligatorio ma nullable `logical_session_id` ai normali tool MCP. Disabilitalo per una tool surface più piccola e senza Session. |
| `live_workspace_enabled` | `LOCAL_SHELL_MCP_LIVE_WORKSPACE_ENABLED` | `True` | Espone tool, resource e route `/api/live/*` di MCP App Live Workspace. Richiede `ui_enabled` e non è disponibile in modalità `stdio`. |
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `True` | Monta native OpenTUI launcher, WebUI shell, PTY WebSocket e routes `/api/ui/*`. |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `'/ui'` | Path di mount WebUI sullo stesso service. |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | `None` | Override opzionale del command per risolvere l’executable OpenTUI. |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `'bing'` | `bing`, `aurora` o `none`. |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | Timeout browser PTY inattivo; `0` lo disabilita. |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | Numero massimo di browser OpenTUI PTYs concorrenti. |

### Worker remoti

| YAML key | Environment variable | Default | Note |
|---|---|---|---|
| `remote_enabled` | `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `True` | Controlla `/join`, `/remote/*` e MCP tools `remote_*`. |
| `remote_invite_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_INVITE_TTL_S` | `7200` |  |
| `remote_poll_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S` | `25` |  |
| `remote_job_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S` | `3600` |  |
| `remote_max_pending_jobs` | `LOCAL_SHELL_MCP_REMOTE_MAX_PENDING_JOBS` | `256` | Numero massimo di jobs queued/pending per worker. |
| `remote_cancelled_job_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_CANCELLED_JOB_TTL_S` | `3600` | Retention time dei cancellation tombstones usati per saltare queued jobs in timeout. |
| `remote_transfer_strategy` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_STRATEGY` | `'auto'` | `auto`, `relay`, `direct` o `object_store`. `auto` prova peer-direct abilitato, poi S3 configurato, poi relay del controller a memoria limitata. |
| `remote_peer_transfer_enabled` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ENABLED` | `False` | Abilita opzionalmente receiver HTTP one-shot sul worker destinazione per direct worker-to-worker transfer. Abilita solo su rete privata trusted come VPC/Tailscale. |
| `remote_peer_transfer_bind_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_BIND_HOST` | `'0.0.0.0'` | Bind address del receiver one-shot del worker destinazione. |
| `remote_peer_transfer_advertise_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ADVERTISE_HOST` | `None` | Address annunciato al worker sorgente; default hostname/FQDN del worker destinazione. |
| `remote_peer_transfer_port` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_PORT` | `0` | Receiver port; `0` sceglie una porta effimera. |
| `remote_peer_transfer_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_TIMEOUT_S` | `3600` | Lifetime/timeout del receiver direct one-shot. |
| `remote_transfer_s3_bucket` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_BUCKET` | `None` | Bucket S3-compatible opzionale per presigned worker-to-worker transfers. Richiede extra `s3`. |
| `remote_transfer_s3_prefix` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PREFIX` | `'local-shell-mcp'` | Object-key prefix per temporary transfer objects. |
| `remote_transfer_s3_region` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_REGION` | `None` | Regione S3 opzionale. |
| `remote_transfer_s3_endpoint_url` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_ENDPOINT_URL` | `None` | Endpoint URL S3-compatible opzionale. |
| `remote_transfer_s3_presign_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PRESIGN_TTL_S` | `3600` | Lifetime delle URL PUT/GET presigned. Gli oggetti temporanei vengono cancellati dopo il transfer. |

### Shell e path degli executable

| YAML key | Environment variable | Default | Note |
|---|---|---|---|
| `shell_executable` | `LOCAL_SHELL_MCP_SHELL_EXECUTABLE` | `'/bin/bash'` |  |
| `shell_env_blocklist` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKLIST` | `['CLOUDFLARE_TUNNEL_TOKEN']` |  |
| `shell_env_blocked_prefixes` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKED_PREFIXES` | `['LOCAL_SHELL_MCP_', 'DOCKER_']` | Separato da virgole nelle environment variables; list in YAML. |
| `tmux_bin` | `LOCAL_SHELL_MCP_TMUX_BIN` | `'tmux'` | Executable tmux preferito. Se indisponibile, release Linux e build Docker usano il bundled helper; altrimenti persistent shells fanno fallback al backend native. |
| `rg_bin` | `LOCAL_SHELL_MCP_RG_BIN` | `'rg'` |  |
| `git_bin` | `LOCAL_SHELL_MCP_GIT_BIN` | `'git'` |  |
| `python_bin` | `LOCAL_SHELL_MCP_PYTHON_BIN` | `'python3'` |  |

### Autenticazione e OAuth

| YAML key | Environment variable | Default | Note |
|---|---|---|---|
| `auth_mode` | `LOCAL_SHELL_MCP_AUTH_MODE` | `'oauth'` | Usa `oauth` per deployment pubblici. |
| `auth_bypass_localhost` | `LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST` | `True` |  |
| `require_auth_for_mcp_discovery` | `LOCAL_SHELL_MCP_REQUIRE_AUTH_FOR_MCP_DISCOVERY` | `True` | Richiede OAuth prima di MCP initialization e tool discovery. |
| `mcp_session_idle_timeout_s` | `LOCAL_SHELL_MCP_MCP_SESSION_IDLE_TIMEOUT_S` | `180` | Idle timeout per sessioni Stateful Streamable HTTP. |
| `mcp_max_sessions` | `LOCAL_SHELL_MCP_MCP_MAX_SESSIONS` | `1024` | Numero massimo di sessioni MCP stateful concorrenti. |
| `public_base_url` | `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | `None` | Origin HTTPS esterno. Non includere `/mcp`. |
| `oauth_issuer` | `LOCAL_SHELL_MCP_OAUTH_ISSUER` | `None` |  |
| `oauth_resource` | `LOCAL_SHELL_MCP_OAUTH_RESOURCE` | `None` |  |
| `oauth_admin_pin` | `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` | `None` |  |
| `oauth_jwt_secret` | `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` | <generated or configured> |  |
| `oauth_access_token_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S` | `0` | `0` significa che access tokens non scadono automaticamente. |
| `oauth_code_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_CODE_TTL_S` | `300` |  |

### Liste policy integrate

| YAML key | Environment variable | Default | Note |
|---|---|---|---|
| `command_denylist` | `LOCAL_SHELL_MCP_COMMAND_DENYLIST` | `[]` | Svuotato automaticamente quando full-container mode è abilitato. |
| `path_denylist` | `LOCAL_SHELL_MCP_PATH_DENYLIST` | `[]` | Svuotato automaticamente quando full-container mode è abilitato. |

## Esempio YAML

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

Controller serverless con stato Redis durable:

```yaml
mode: mcp
stateless_controller: true
state_backend: redis
state_backend_url: redis://redis.internal:6379/0
remote_transfer_strategy: auto
```

`stateless_controller` elimina la necessità di un volume persistente per il controller. Il backend `memory` è volutamente ephemeral: un cold start invalida remote invites pendenti e worker identities e scarta OAuth clients, jobs e audit records. Usa Redis quando uno di questi state deve sopravvivere ai cold start, inclusa la semantica durable di revoca dei worker. Con default `auth_mode=oauth`, inietta almeno 32 bytes di materiale di chiave casuale tramite `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET`. Active remote RPC queues/futures sono process-local, quindi i deployment con remote workers dovrebbero attualmente eseguire una sola istanza active del controller e non più replicas load-balanced.

## Consigli operativi

- Mantieni `allow_full_container=false` salvo container/VM disposable.
- Mantieni `auth_mode=oauth` per ogni endpoint pubblico.
- Disabilita `remote_enabled` se non usi remote workers.
- Disabilita `file_download_enabled` se non hai mai bisogno di artifacts scaricabili dalla chat.
- Mantieni i limiti command, file e audit abbastanza alti per coding tasks ma abbastanza bassi da prevenire runaway output accidentale.
