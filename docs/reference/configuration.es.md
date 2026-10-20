<!-- i18n-source-sha256: 5d2de552ba0ba0d1c76319ad9f87ab68e217fee6c607687f8260e14872e7dbcc -->
# Configuración

El repositorio incluye un único archivo inicial copiable: [`.env.example`](https://github.com/fwerkor/local-shell-mcp/blob/main/.env.example). Docker Compose lee automáticamente el `.env` resultante, y otros runtimes pueden usar las mismas variables de entorno `LOCAL_SHELL_MCP_`. YAML sigue siendo una entrada avanzada opcional para deployments binary o source; cree un archivo explícitamente y selecciónelo con `LOCAL_SHELL_MCP_CONFIG` o `--config`. Las variables de entorno sobrescriben los valores YAML, así que evite definir el mismo ajuste en ambos salvo que la sobrescritura sea intencional. Las claves YAML usan los nombres de campo de abajo.

## Precedencia

1. Defaults integrados de `Settings`.
2. Config YAML seleccionada por `LOCAL_SHELL_MCP_CONFIG` o `--config`.
3. Variables de entorno con prefijo `LOCAL_SHELL_MCP_`.
4. Flags CLI como `--mode`, `--config`, `--remote` y `--no-remote`, que fijan los valores de entorno correspondientes antes de cargar settings.

## Configuración pública mínima

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-long-random-secret
```

Para pruebas solo locales, `auth_bypass_localhost` está habilitado por defecto. No exponga tools MCP completos sin autenticación en una red pública.

## Referencia de settings

### Servidor y workspace

| Clave YAML | Variable de entorno | Default | Notas |
|---|---|---|---|
| `host` | `LOCAL_SHELL_MCP_HOST` | `'0.0.0.0'` |  |
| `port` | `LOCAL_SHELL_MCP_PORT` | `8765` |  |
| `forwarded_allow_ips` | `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS` | `'127.0.0.1'` | IPs de proxy de confianza, separadas por comas, para el manejo de forwarded headers de Uvicorn. Use `*` solo cuando el ingress directo esté restringido. |
| `mode` | `LOCAL_SHELL_MCP_MODE` | `'mcp'` | `mcp`, `http`, `stdio` o el valor reservado `both`. |
| `workspace_root` | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | `PosixPath('/workspace')` |  |
| `state_dir` | `LOCAL_SHELL_MCP_STATE_DIR` | `PosixPath('/workspace/.local-shell-mcp')` |  |
| `audit_log_path` | `LOCAL_SHELL_MCP_AUDIT_LOG_PATH` | `PosixPath('/workspace/.local-shell-mcp/audit.jsonl')` |  |
| `agent_config_dir` | `LOCAL_SHELL_MCP_AGENT_CONFIG_DIR` | `PosixPath('/workspace/.local-shell-mcp/agent_config')` |  |
| `allow_full_container` | `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER` | `False` | Deshabilita restricciones de workspace/path cuando es true; úselo solo dentro de boundaries desechables. |
| `disable_local` | `LOCAL_SHELL_MCP_DISABLE_LOCAL` | `False` | Deshabilita el controller host como target de ejecución shell/file/browser. Remote workers y control-plane services siguen disponibles. |
| `stateless_controller` | `LOCAL_SHELL_MCP_STATELESS_CONTROLLER` | `False` | Hace que el controller sea apto para instancias efímeras/serverless: implica `disable_local`, deshabilita local file links/wallpaper caching y usa `memory` como `state_backend` por defecto. Con `auth_mode=oauth`, configure explícitamente un `oauth_jwt_secret` fuerte. |
| `state_backend` | `LOCAL_SHELL_MCP_STATE_BACKEND` | `'file'` | `file`, `memory` o `redis`. Use Redis cuando el estado del controller serverless deba sobrevivir cold starts. |
| `state_backend_url` | `LOCAL_SHELL_MCP_STATE_BACKEND_URL` | `None` | URL de conexión Redis cuando `state_backend=redis`. Se redacta en diagnostics. |
| `state_backend_prefix` | `LOCAL_SHELL_MCP_STATE_BACKEND_PREFIX` | `'local-shell-mcp'` | Namespace del estado control-plane en memory/Redis. |

### Límites

| Clave YAML | Variable de entorno | Default | Notas |
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
| `max_skills` | `LOCAL_SHELL_MCP_MAX_SKILLS` | `256` | Máximo de directorios Skill devueltos por un registry scan. |
| `max_skill_related_files` | `LOCAL_SHELL_MCP_MAX_SKILL_RELATED_FILES` | `1000` | Máximo de related files devueltos para un Skill. |
| `max_skill_scan_entries` | `LOCAL_SHELL_MCP_MAX_SKILL_SCAN_ENTRIES` | `5000` | Máximo de filesystem entries examinados por un registry scan `skill_list` o carga directa de Skill. |
| `max_skill_path_bytes` | `LOCAL_SHELL_MCP_MAX_SKILL_PATH_BYTES` | `200000` | Máximo de bytes UTF-8 usados por los paths de related files devueltos. |
| `max_read_many_files` | `LOCAL_SHELL_MCP_MAX_READ_MANY_FILES` | `100` |  |
| `max_read_many_total_bytes` | `LOCAL_SHELL_MCP_MAX_READ_MANY_TOTAL_BYTES` | `5000000` |  |
| `max_http_request_bytes` | `LOCAL_SHELL_MCP_MAX_HTTP_REQUEST_BYTES` | `16000000` | Máximo body HTTP bufferizado entre endpoints MCP, REST, OAuth, UI y remote-worker. |
| `max_job_log_bytes` | `LOCAL_SHELL_MCP_MAX_JOB_LOG_BYTES` | `10000000` | Máximo de bytes de output retenidos por cada intento de long-running job. |
| `max_jobs` | `LOCAL_SHELL_MCP_MAX_JOBS` | `1000` | Máximo de long-running job records retenidos; los active jobs nunca se podan. |
| `max_audit_tail_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES` | `1000000` |  |
| `max_audit_log_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES` | `20000000` |  |
| `max_audit_archive_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_ARCHIVE_BYTES` | `512000000` |  |
| `max_tmp_files` | `LOCAL_SHELL_MCP_MAX_TMP_FILES` | `500` |  |
| `max_tmp_bytes` | `LOCAL_SHELL_MCP_MAX_TMP_BYTES` | `50000000` |  |
| `max_transfer_archive_entries` | `LOCAL_SHELL_MCP_MAX_TRANSFER_ARCHIVE_ENTRIES` | `100000` | Máximo de entries aceptados al desempaquetar un archive de directory transferido. |
| `max_transfer_unpacked_bytes` | `LOCAL_SHELL_MCP_MAX_TRANSFER_UNPACKED_BYTES` | `10000000000` | Máximo de bytes expandidos declarados aceptados para un archive de directory transferido. |
| `max_concurrent_commands` | `LOCAL_SHELL_MCP_MAX_CONCURRENT_COMMANDS` | `4` |  |
| `max_tmux_sessions` | `LOCAL_SHELL_MCP_MAX_TMUX_SESSIONS` | `16` | Máximo de persistent shell sessions entre backends tmux, ConPTY y native fallback. |

### Enlaces de archivos

| Clave YAML | Variable de entorno | Default | Notas |
|---|---|---|---|
| `file_download_enabled` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED` | `True` |  |
| `file_download_default_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_TTL_S` | `3600` |  |
| `file_download_max_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_TTL_S` | `604800` |  |
| `file_download_default_max_downloads` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_MAX_DOWNLOADS` | `0` | `0` significa sin límite predeterminado de número de descargas. |
| `file_download_max_file_bytes` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_FILE_BYTES` | `0` | `0` significa sin límite configurado de tamaño para file links. |

### Interfaz humana

| Clave YAML | Variable de entorno | Default | Notas |
|---|---|---|---|
| `logical_sessions_enabled` | `LOCAL_SHELL_MCP_LOGICAL_SESSIONS_ENABLED` | `True` | Expone `session_manage` y `plan_manage` y añade el argumento obligatorio pero nullable `logical_session_id` a las herramientas MCP normales. Desactívelo para una superficie de herramientas más pequeña y sin Sessions. |
| `live_workspace_enabled` | `LOCAL_SHELL_MCP_LIVE_WORKSPACE_ENABLED` | `True` | Expone las herramientas, recursos y rutas `/api/live/*` de MCP App Live Workspace. Requiere `ui_enabled` y no está disponible en modo `stdio`. |
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `True` | Monta native OpenTUI launcher, WebUI shell, PTY WebSocket y routes `/api/ui/*`. |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `'/ui'` | Path de montaje de WebUI en el mismo service. |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | `None` | Override opcional del comando para resolver el executable OpenTUI. |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `'bing'` | `bing`, `aurora` o `none`. |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | Timeout de browser PTY inactivo; `0` lo deshabilita. |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | Máximo de browser OpenTUI PTYs concurrentes. |

### Workers remotos

| Clave YAML | Variable de entorno | Default | Notas |
|---|---|---|---|
| `remote_enabled` | `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `True` | Controla `/join`, `/remote/*` y tools MCP `remote_*`. |
| `remote_invite_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_INVITE_TTL_S` | `7200` |  |
| `remote_poll_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S` | `25` |  |
| `remote_job_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S` | `3600` |  |
| `remote_max_pending_jobs` | `LOCAL_SHELL_MCP_REMOTE_MAX_PENDING_JOBS` | `256` | Máximo de jobs queued o pending por worker. |
| `remote_cancelled_job_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_CANCELLED_JOB_TTL_S` | `3600` | Tiempo de retención de cancellation tombstones usados para omitir queued jobs que agotaron timeout. |
| `remote_transfer_strategy` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_STRATEGY` | `'auto'` | `auto`, `relay`, `direct` u `object_store`. `auto` prueba peer-direct habilitado, luego S3 configurado y después relay del controller con memoria acotada. |
| `remote_peer_transfer_enabled` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ENABLED` | `False` | Activa opcionalmente un receiver HTTP one-shot en el worker destino para transfer worker-to-worker directo. Úselo solo en una red privada de confianza como VPC/Tailscale. |
| `remote_peer_transfer_bind_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_BIND_HOST` | `'0.0.0.0'` | Bind address del receiver one-shot del worker destino. |
| `remote_peer_transfer_advertise_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ADVERTISE_HOST` | `None` | Dirección anunciada al worker fuente; por defecto hostname/FQDN del worker destino. |
| `remote_peer_transfer_port` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_PORT` | `0` | Puerto del receiver; `0` elige un puerto efímero. |
| `remote_peer_transfer_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_TIMEOUT_S` | `3600` | Lifetime/timeout del receiver directo one-shot. |
| `remote_transfer_s3_bucket` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_BUCKET` | `None` | Bucket compatible con S3 opcional para transfers worker-to-worker con presigned URLs. Requiere extra `s3`. |
| `remote_transfer_s3_prefix` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PREFIX` | `'local-shell-mcp'` | Prefijo de object key para objetos temporales de transfer. |
| `remote_transfer_s3_region` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_REGION` | `None` | Región S3 opcional. |
| `remote_transfer_s3_endpoint_url` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_ENDPOINT_URL` | `None` | URL de endpoint compatible con S3 opcional. |
| `remote_transfer_s3_presign_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PRESIGN_TTL_S` | `3600` | Lifetime de URL PUT/GET presigned. Los objetos temporales se eliminan después del transfer. |

### Shell y paths de executables

| Clave YAML | Variable de entorno | Default | Notas |
|---|---|---|---|
| `shell_executable` | `LOCAL_SHELL_MCP_SHELL_EXECUTABLE` | `'/bin/bash'` |  |
| `shell_env_blocklist` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKLIST` | `['CLOUDFLARE_TUNNEL_TOKEN']` |  |
| `shell_env_blocked_prefixes` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKED_PREFIXES` | `['LOCAL_SHELL_MCP_', 'DOCKER_']` | Separado por comas en variables de entorno; lista en YAML. |
| `tmux_bin` | `LOCAL_SHELL_MCP_TMUX_BIN` | `'tmux'` | Executable tmux preferido. Si no está disponible, releases Linux y builds Docker usan el helper incluido; en otros casos persistent shells hacen fallback al backend native. |
| `rg_bin` | `LOCAL_SHELL_MCP_RG_BIN` | `'rg'` |  |
| `git_bin` | `LOCAL_SHELL_MCP_GIT_BIN` | `'git'` |  |
| `python_bin` | `LOCAL_SHELL_MCP_PYTHON_BIN` | `'python3'` |  |

### Autenticación y OAuth

| Clave YAML | Variable de entorno | Default | Notas |
|---|---|---|---|
| `auth_mode` | `LOCAL_SHELL_MCP_AUTH_MODE` | `'oauth'` | Use `oauth` para deployments públicos. |
| `auth_bypass_localhost` | `LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST` | `True` |  |
| `require_auth_for_mcp_discovery` | `LOCAL_SHELL_MCP_REQUIRE_AUTH_FOR_MCP_DISCOVERY` | `True` | Exige OAuth antes de MCP initialization y tool discovery. |
| `mcp_session_idle_timeout_s` | `LOCAL_SHELL_MCP_MCP_SESSION_IDLE_TIMEOUT_S` | `180` | Idle timeout para sesiones Stateful Streamable HTTP. |
| `mcp_max_sessions` | `LOCAL_SHELL_MCP_MCP_MAX_SESSIONS` | `1024` | Máximo de sesiones MCP stateful concurrentes. |
| `public_base_url` | `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | `None` | Origin HTTPS externo. No incluya `/mcp`. |
| `oauth_issuer` | `LOCAL_SHELL_MCP_OAUTH_ISSUER` | `None` |  |
| `oauth_resource` | `LOCAL_SHELL_MCP_OAUTH_RESOURCE` | `None` |  |
| `oauth_admin_pin` | `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` | `None` |  |
| `oauth_jwt_secret` | `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` | <generated or configured> |  |
| `oauth_access_token_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S` | `0` | `0` significa que access tokens no expiran automáticamente. |
| `oauth_code_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_CODE_TTL_S` | `300` |  |

### Listas de política integradas

| Clave YAML | Variable de entorno | Default | Notas |
|---|---|---|---|
| `command_denylist` | `LOCAL_SHELL_MCP_COMMAND_DENYLIST` | `[]` | Se vacía automáticamente cuando full-container mode está habilitado. |
| `path_denylist` | `LOCAL_SHELL_MCP_PATH_DENYLIST` | `[]` | Se vacía automáticamente cuando full-container mode está habilitado. |

## Ejemplo YAML

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

Controller serverless con estado Redis durable:

```yaml
mode: mcp
stateless_controller: true
state_backend: redis
state_backend_url: redis://redis.internal:6379/0
remote_transfer_strategy: auto
```

`stateless_controller` elimina la necesidad de un volumen persistente del controller. El backend `memory` es intencionadamente efímero: un cold start invalida remote invites pendientes y worker identities, y descarta OAuth clients, jobs y audit records. Use Redis cuando cualquiera de esos estados deba sobrevivir cold starts, incluida la semántica durable de revocación de workers. Con el default `auth_mode=oauth`, inyecte al menos 32 bytes de material de clave aleatorio mediante `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET`. Las colas/futures RPC remotas activas son process-local, por lo que deployments con remote workers deben ejecutar actualmente una sola instancia activa de controller, no múltiples réplicas balanceadas.

## Consejos operativos

- Mantenga `allow_full_container=false` salvo que el container o VM sea desechable.
- Mantenga `auth_mode=oauth` para cualquier endpoint público.
- Deshabilite `remote_enabled` si no usa remote workers.
- Deshabilite `file_download_enabled` si nunca necesita artifacts descargables desde chat.
- Mantenga límites de command, file y audit suficientemente altos para coding tasks pero lo bastante bajos para evitar output runaway accidental.
