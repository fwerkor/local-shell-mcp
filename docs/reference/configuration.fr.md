<!-- i18n-source-sha256: 5d2de552ba0ba0d1c76319ad9f87ab68e217fee6c607687f8260e14872e7dbcc -->
# Configuration

Le repository fournit un seul fichier de démarrage copiable : [`.env.example`](https://github.com/fwerkor/local-shell-mcp/blob/main/.env.example). Docker Compose lit automatiquement le `.env` obtenu, et les autres runtimes peuvent utiliser les mêmes variables d’environnement `LOCAL_SHELL_MCP_`. YAML reste une entrée avancée optionnelle pour les deployments binary ou source ; créez explicitement un fichier et sélectionnez-le avec `LOCAL_SHELL_MCP_CONFIG` ou `--config`. Les variables d’environnement remplacent les valeurs YAML ; évitez donc de définir le même réglage dans les deux sauf si l’override est voulu. Les clés YAML utilisent les noms de champs ci-dessous.

## Priorité

1. Defaults intégrés de `Settings`.
2. Configuration YAML sélectionnée par `LOCAL_SHELL_MCP_CONFIG` ou `--config`.
3. Variables d’environnement préfixées `LOCAL_SHELL_MCP_`.
4. Flags CLI comme `--mode`, `--config`, `--remote` et `--no-remote`, qui définissent les valeurs d’environnement correspondantes avant le chargement des settings.

## Configuration publique minimale

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-long-random-secret
```

Pour les tests localhost uniquement, `auth_bypass_localhost` est activé par défaut. N’exposez pas des tools MCP complets sans authentification sur un réseau public.

## Référence des settings

### Serveur et workspace

| Clé YAML | Variable d’environnement | Default | Notes |
|---|---|---|---|
| `host` | `LOCAL_SHELL_MCP_HOST` | `'0.0.0.0'` |  |
| `port` | `LOCAL_SHELL_MCP_PORT` | `8765` |  |
| `forwarded_allow_ips` | `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS` | `'127.0.0.1'` | IPs de proxy de confiance séparées par des virgules pour le traitement des forwarded headers Uvicorn. Utilisez `*` uniquement si l’ingress direct est restreint. |
| `mode` | `LOCAL_SHELL_MCP_MODE` | `'mcp'` | `mcp`, `http`, `stdio` ou la valeur réservée `both`. |
| `workspace_root` | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | `PosixPath('/workspace')` |  |
| `state_dir` | `LOCAL_SHELL_MCP_STATE_DIR` | `PosixPath('/workspace/.local-shell-mcp')` |  |
| `audit_log_path` | `LOCAL_SHELL_MCP_AUDIT_LOG_PATH` | `PosixPath('/workspace/.local-shell-mcp/audit.jsonl')` |  |
| `agent_config_dir` | `LOCAL_SHELL_MCP_AGENT_CONFIG_DIR` | `PosixPath('/workspace/.local-shell-mcp/agent_config')` |  |
| `allow_full_container` | `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER` | `False` | Désactive les restrictions workspace/path lorsque true ; à utiliser uniquement dans une boundary jetable. |
| `disable_local` | `LOCAL_SHELL_MCP_DISABLE_LOCAL` | `False` | Désactive le controller host comme cible d’exécution shell/file/browser. Les remote workers et control-plane services restent disponibles. |
| `stateless_controller` | `LOCAL_SHELL_MCP_STATELESS_CONTROLLER` | `False` | Rend le controller adapté aux instances éphémères/serverless : implique `disable_local`, désactive local file links/wallpaper caching et choisit `memory` comme `state_backend` par défaut. Avec `auth_mode=oauth`, configurez explicitement un `oauth_jwt_secret` robuste. |
| `state_backend` | `LOCAL_SHELL_MCP_STATE_BACKEND` | `'file'` | `file`, `memory` ou `redis`. Utilisez Redis lorsque l’état d’un controller serverless doit survivre aux cold starts. |
| `state_backend_url` | `LOCAL_SHELL_MCP_STATE_BACKEND_URL` | `None` | URL de connexion Redis lorsque `state_backend=redis`. Redacted dans diagnostics. |
| `state_backend_prefix` | `LOCAL_SHELL_MCP_STATE_BACKEND_PREFIX` | `'local-shell-mcp'` | Namespace de l’état control-plane memory/Redis. |

### Limites

| Clé YAML | Variable d’environnement | Default | Notes |
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
| `max_skills` | `LOCAL_SHELL_MCP_MAX_SKILLS` | `256` | Nombre maximal de directories Skill renvoyés par un registry scan. |
| `max_skill_related_files` | `LOCAL_SHELL_MCP_MAX_SKILL_RELATED_FILES` | `1000` | Nombre maximal de related files renvoyés pour un Skill. |
| `max_skill_scan_entries` | `LOCAL_SHELL_MCP_MAX_SKILL_SCAN_ENTRIES` | `5000` | Nombre maximal de filesystem entries examinés par un registry scan `skill_list` ou un direct Skill load. |
| `max_skill_path_bytes` | `LOCAL_SHELL_MCP_MAX_SKILL_PATH_BYTES` | `200000` | Nombre maximal de bytes UTF-8 utilisés par les paths de related files renvoyés. |
| `max_read_many_files` | `LOCAL_SHELL_MCP_MAX_READ_MANY_FILES` | `100` |  |
| `max_read_many_total_bytes` | `LOCAL_SHELL_MCP_MAX_READ_MANY_TOTAL_BYTES` | `5000000` |  |
| `max_http_request_bytes` | `LOCAL_SHELL_MCP_MAX_HTTP_REQUEST_BYTES` | `16000000` | Taille maximale du body HTTP bufferisé sur les endpoints MCP, REST, OAuth, UI et remote-worker. |
| `max_job_log_bytes` | `LOCAL_SHELL_MCP_MAX_JOB_LOG_BYTES` | `10000000` | Nombre maximal de bytes output conservés pour chaque tentative de long-running job. |
| `max_jobs` | `LOCAL_SHELL_MCP_MAX_JOBS` | `1000` | Nombre maximal de long-running job records conservés ; les active jobs ne sont jamais pruned. |
| `max_audit_tail_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES` | `1000000` |  |
| `max_audit_log_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES` | `20000000` |  |
| `max_audit_archive_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_ARCHIVE_BYTES` | `512000000` |  |
| `max_tmp_files` | `LOCAL_SHELL_MCP_MAX_TMP_FILES` | `500` |  |
| `max_tmp_bytes` | `LOCAL_SHELL_MCP_MAX_TMP_BYTES` | `50000000` |  |
| `max_transfer_archive_entries` | `LOCAL_SHELL_MCP_MAX_TRANSFER_ARCHIVE_ENTRIES` | `100000` | Nombre maximal d’entries acceptés lors du déballage d’un archive de directory transféré. |
| `max_transfer_unpacked_bytes` | `LOCAL_SHELL_MCP_MAX_TRANSFER_UNPACKED_BYTES` | `10000000000` | Nombre maximal de bytes expanded déclarés acceptés pour un archive de directory transféré. |
| `max_concurrent_commands` | `LOCAL_SHELL_MCP_MAX_CONCURRENT_COMMANDS` | `4` |  |
| `max_tmux_sessions` | `LOCAL_SHELL_MCP_MAX_TMUX_SESSIONS` | `16` | Nombre maximal de persistent shell sessions sur les backends tmux, ConPTY et native fallback. |

### Liens de fichiers

| Clé YAML | Variable d’environnement | Default | Notes |
|---|---|---|---|
| `file_download_enabled` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED` | `True` |  |
| `file_download_default_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_TTL_S` | `3600` |  |
| `file_download_max_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_TTL_S` | `604800` |  |
| `file_download_default_max_downloads` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_MAX_DOWNLOADS` | `0` | `0` signifie aucune limite de nombre de téléchargements par défaut. |
| `file_download_max_file_bytes` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_FILE_BYTES` | `0` | `0` signifie aucune limite configurée de taille pour les file links. |

### Interface humaine

| Clé YAML | Variable d’environnement | Default | Notes |
|---|---|---|---|
| `logical_sessions_enabled` | `LOCAL_SHELL_MCP_LOGICAL_SESSIONS_ENABLED` | `True` | Expose `session_manage` et `plan_manage` et ajoute l’argument obligatoire mais nullable `logical_session_id` aux outils MCP ordinaires. Désactivez-le pour une surface d’outils plus petite, sans Session. |
| `live_workspace_enabled` | `LOCAL_SHELL_MCP_LIVE_WORKSPACE_ENABLED` | `True` | Expose les outils, ressources et routes `/api/live/*` du MCP App Live Workspace. Nécessite `ui_enabled` et n’est pas disponible en mode `stdio`. |
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `True` | Monte native OpenTUI launcher, WebUI shell, PTY WebSocket et routes `/api/ui/*`. |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `'/ui'` | Path de montage WebUI sur le même service. |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | `None` | Override optionnel de commande pour résoudre l’executable OpenTUI. |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `'bing'` | `bing`, `aurora` ou `none`. |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | Timeout d’un browser PTY inactif ; `0` le désactive. |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | Nombre maximal de browser OpenTUI PTYs concurrents. |

### Workers distants

| Clé YAML | Variable d’environnement | Default | Notes |
|---|---|---|---|
| `remote_enabled` | `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `True` | Contrôle `/join`, `/remote/*` et les tools MCP `remote_*`. |
| `remote_invite_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_INVITE_TTL_S` | `7200` |  |
| `remote_poll_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S` | `25` |  |
| `remote_job_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S` | `3600` |  |
| `remote_max_pending_jobs` | `LOCAL_SHELL_MCP_REMOTE_MAX_PENDING_JOBS` | `256` | Nombre maximal de jobs queued/pending par worker. |
| `remote_cancelled_job_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_CANCELLED_JOB_TTL_S` | `3600` | Durée de rétention des cancellation tombstones servant à ignorer les queued jobs ayant expiré. |
| `remote_transfer_strategy` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_STRATEGY` | `'auto'` | `auto`, `relay`, `direct` ou `object_store`. `auto` tente peer-direct activé, puis S3 configuré, puis relay du controller à mémoire bornée. |
| `remote_peer_transfer_enabled` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ENABLED` | `False` | Active optionnellement un receiver HTTP one-shot sur le worker destination pour transfer direct worker-to-worker. À activer uniquement sur un réseau privé de confiance comme VPC/Tailscale. |
| `remote_peer_transfer_bind_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_BIND_HOST` | `'0.0.0.0'` | Bind address du receiver one-shot du worker destination. |
| `remote_peer_transfer_advertise_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ADVERTISE_HOST` | `None` | Adresse annoncée au worker source ; par défaut hostname/FQDN du worker destination. |
| `remote_peer_transfer_port` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_PORT` | `0` | Port du receiver ; `0` choisit un port éphémère. |
| `remote_peer_transfer_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_TIMEOUT_S` | `3600` | Lifetime/timeout du receiver direct one-shot. |
| `remote_transfer_s3_bucket` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_BUCKET` | `None` | Bucket compatible S3 optionnel pour transfers worker-to-worker avec presigned URLs. Nécessite l’extra `s3`. |
| `remote_transfer_s3_prefix` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PREFIX` | `'local-shell-mcp'` | Préfixe object-key des objets temporaires de transfer. |
| `remote_transfer_s3_region` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_REGION` | `None` | Région S3 optionnelle. |
| `remote_transfer_s3_endpoint_url` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_ENDPOINT_URL` | `None` | URL endpoint compatible S3 optionnelle. |
| `remote_transfer_s3_presign_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PRESIGN_TTL_S` | `3600` | Lifetime des URL PUT/GET presigned. Les objets temporaires sont supprimés après transfer. |

### Shell et paths des executables

| Clé YAML | Variable d’environnement | Default | Notes |
|---|---|---|---|
| `shell_executable` | `LOCAL_SHELL_MCP_SHELL_EXECUTABLE` | `'/bin/bash'` |  |
| `shell_env_blocklist` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKLIST` | `['CLOUDFLARE_TUNNEL_TOKEN']` |  |
| `shell_env_blocked_prefixes` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKED_PREFIXES` | `['LOCAL_SHELL_MCP_', 'DOCKER_']` | Séparé par virgules dans les variables d’environnement ; liste dans YAML. |
| `tmux_bin` | `LOCAL_SHELL_MCP_TMUX_BIN` | `'tmux'` | Executable tmux préféré. S’il est indisponible, les releases Linux et builds Docker utilisent le helper embarqué ; sinon les persistent shells fallback vers le backend native. |
| `rg_bin` | `LOCAL_SHELL_MCP_RG_BIN` | `'rg'` |  |
| `git_bin` | `LOCAL_SHELL_MCP_GIT_BIN` | `'git'` |  |
| `python_bin` | `LOCAL_SHELL_MCP_PYTHON_BIN` | `'python3'` |  |

### Authentification et OAuth

| Clé YAML | Variable d’environnement | Default | Notes |
|---|---|---|---|
| `auth_mode` | `LOCAL_SHELL_MCP_AUTH_MODE` | `'oauth'` | Utilisez `oauth` pour les deployments publics. |
| `auth_bypass_localhost` | `LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST` | `True` |  |
| `require_auth_for_mcp_discovery` | `LOCAL_SHELL_MCP_REQUIRE_AUTH_FOR_MCP_DISCOVERY` | `True` | Exige OAuth avant MCP initialization et tool discovery. |
| `mcp_session_idle_timeout_s` | `LOCAL_SHELL_MCP_MCP_SESSION_IDLE_TIMEOUT_S` | `180` | Idle timeout des sessions Stateful Streamable HTTP. |
| `mcp_max_sessions` | `LOCAL_SHELL_MCP_MCP_MAX_SESSIONS` | `1024` | Nombre maximal de sessions MCP stateful concurrentes. |
| `public_base_url` | `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | `None` | Origin HTTPS externe. N’incluez pas `/mcp`. |
| `oauth_issuer` | `LOCAL_SHELL_MCP_OAUTH_ISSUER` | `None` |  |
| `oauth_resource` | `LOCAL_SHELL_MCP_OAUTH_RESOURCE` | `None` |  |
| `oauth_admin_pin` | `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` | `None` |  |
| `oauth_jwt_secret` | `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` | <generated or configured> |  |
| `oauth_access_token_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S` | `0` | `0` signifie que les access tokens n’expirent pas automatiquement. |
| `oauth_code_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_CODE_TTL_S` | `300` |  |

### Listes de politiques intégrées

| Clé YAML | Variable d’environnement | Default | Notes |
|---|---|---|---|
| `command_denylist` | `LOCAL_SHELL_MCP_COMMAND_DENYLIST` | `[]` | Vidée automatiquement lorsque full-container mode est activé. |
| `path_denylist` | `LOCAL_SHELL_MCP_PATH_DENYLIST` | `[]` | Vidée automatiquement lorsque full-container mode est activé. |

## Exemple YAML

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

Controller serverless avec état Redis durable :

```yaml
mode: mcp
stateless_controller: true
state_backend: redis
state_backend_url: redis://redis.internal:6379/0
remote_transfer_strategy: auto
```

`stateless_controller` supprime le besoin d’un volume persistant pour le controller. Le backend `memory` est volontairement éphémère : un cold start invalide les remote invites en attente et les worker identities, et supprime OAuth clients, jobs et audit records. Utilisez Redis lorsque cet état doit survivre aux cold starts, y compris la sémantique durable de révocation des workers. Avec le default `auth_mode=oauth`, injectez au moins 32 bytes de matériau de clé aléatoire via `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET`. Les queues/futures RPC distantes actives sont process-local ; les deployments utilisant des remote workers doivent donc actuellement exécuter une seule instance active du controller plutôt que plusieurs replicas load-balanced.

## Conseils opérationnels

- Gardez `allow_full_container=false` sauf si le container ou la VM est jetable.
- Gardez `auth_mode=oauth` pour tout endpoint public.
- Désactivez `remote_enabled` si vous n’utilisez pas de remote workers.
- Désactivez `file_download_enabled` si vous n’avez jamais besoin d’artifacts téléchargeables depuis le chat.
- Gardez les limites command, file et audit assez hautes pour les coding tasks mais assez basses pour éviter un runaway output accidentel.
