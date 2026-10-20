<!-- i18n-source-sha256: 5d2de552ba0ba0d1c76319ad9f87ab68e217fee6c607687f8260e14872e7dbcc -->
# Configuração

O repository fornece um único arquivo inicial copiável: [`.env.example`](https://github.com/fwerkor/local-shell-mcp/blob/main/.env.example). Docker Compose lê automaticamente o `.env` resultante, e outros runtimes podem usar as mesmas variáveis de ambiente `LOCAL_SHELL_MCP_`. YAML continua sendo input avançado opcional para deployments binary ou source; crie um arquivo explicitamente e selecione com `LOCAL_SHELL_MCP_CONFIG` ou `--config`. Variáveis de ambiente sobrescrevem valores YAML, então evite definir o mesmo setting em ambos, salvo quando o override for intencional. YAML keys usam os field names abaixo.

## Precedência

1. Defaults embutidos de `Settings`.
2. Config YAML selecionada por `LOCAL_SHELL_MCP_CONFIG` ou `--config`.
3. Variáveis de ambiente com prefixo `LOCAL_SHELL_MCP_`.
4. CLI flags como `--mode`, `--config`, `--remote` e `--no-remote`, que definem os environment values correspondentes antes de carregar settings.

## Configuração pública mínima

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-long-random-secret
```

Para testes somente localhost, `auth_bypass_localhost` é habilitado por default. Não exponha full MCP tools sem autenticação em rede pública.

## Referência de settings

### Servidor e workspace

| YAML key | Variável de ambiente | Default | Notas |
|---|---|---|---|
| `host` | `LOCAL_SHELL_MCP_HOST` | `'0.0.0.0'` |  |
| `port` | `LOCAL_SHELL_MCP_PORT` | `8765` |  |
| `forwarded_allow_ips` | `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS` | `'127.0.0.1'` | IPs de proxy confiáveis separados por vírgula para handling de forwarded headers do Uvicorn. Use `*` apenas quando ingress direto estiver restrito. |
| `mode` | `LOCAL_SHELL_MCP_MODE` | `'mcp'` | `mcp`, `http`, `stdio` ou o valor reservado `both`. |
| `workspace_root` | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | `PosixPath('/workspace')` |  |
| `state_dir` | `LOCAL_SHELL_MCP_STATE_DIR` | `PosixPath('/workspace/.local-shell-mcp')` |  |
| `audit_log_path` | `LOCAL_SHELL_MCP_AUDIT_LOG_PATH` | `PosixPath('/workspace/.local-shell-mcp/audit.jsonl')` |  |
| `agent_config_dir` | `LOCAL_SHELL_MCP_AGENT_CONFIG_DIR` | `PosixPath('/workspace/.local-shell-mcp/agent_config')` |  |
| `allow_full_container` | `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER` | `False` | Desabilita restrições workspace/path quando true; use somente dentro de boundaries disposable. |
| `disable_local` | `LOCAL_SHELL_MCP_DISABLE_LOCAL` | `False` | Desabilita controller host como target de execução shell/file/browser. Remote workers e control-plane services permanecem disponíveis. |
| `stateless_controller` | `LOCAL_SHELL_MCP_STATELESS_CONTROLLER` | `False` | Torna controller adequado a instâncias efêmeras/serverless: implica `disable_local`, desabilita local file links/wallpaper caching e usa `memory` como `state_backend` por default. Com `auth_mode=oauth`, configure explicitamente um `oauth_jwt_secret` forte. |
| `state_backend` | `LOCAL_SHELL_MCP_STATE_BACKEND` | `'file'` | `file`, `memory` ou `redis`. Use Redis quando state do controller serverless precisar sobreviver a cold starts. |
| `state_backend_url` | `LOCAL_SHELL_MCP_STATE_BACKEND_URL` | `None` | Redis connection URL quando `state_backend=redis`. Redacted em diagnostics. |
| `state_backend_prefix` | `LOCAL_SHELL_MCP_STATE_BACKEND_PREFIX` | `'local-shell-mcp'` | Namespace para state control-plane em memory/Redis. |

### Limites

| YAML key | Variável de ambiente | Default | Notas |
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
| `max_skills` | `LOCAL_SHELL_MCP_MAX_SKILLS` | `256` | Máximo de diretórios Skill retornados por um registry scan. |
| `max_skill_related_files` | `LOCAL_SHELL_MCP_MAX_SKILL_RELATED_FILES` | `1000` | Máximo de related files retornados para um Skill. |
| `max_skill_scan_entries` | `LOCAL_SHELL_MCP_MAX_SKILL_SCAN_ENTRIES` | `5000` | Máximo de filesystem entries examinados por um registry scan `skill_list` ou direct Skill load. |
| `max_skill_path_bytes` | `LOCAL_SHELL_MCP_MAX_SKILL_PATH_BYTES` | `200000` | Máximo de bytes UTF-8 usados pelos paths de related files retornados. |
| `max_read_many_files` | `LOCAL_SHELL_MCP_MAX_READ_MANY_FILES` | `100` |  |
| `max_read_many_total_bytes` | `LOCAL_SHELL_MCP_MAX_READ_MANY_TOTAL_BYTES` | `5000000` |  |
| `max_http_request_bytes` | `LOCAL_SHELL_MCP_MAX_HTTP_REQUEST_BYTES` | `16000000` | Máximo body HTTP bufferizado nos endpoints MCP, REST, OAuth, UI e remote-worker. |
| `max_job_log_bytes` | `LOCAL_SHELL_MCP_MAX_JOB_LOG_BYTES` | `10000000` | Máximo de output bytes retidos para cada tentativa de long-running job. |
| `max_jobs` | `LOCAL_SHELL_MCP_MAX_JOBS` | `1000` | Máximo de long-running job records retidos; active jobs nunca são pruned. |
| `max_audit_tail_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES` | `1000000` |  |
| `max_audit_log_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES` | `20000000` |  |
| `max_audit_archive_bytes` | `LOCAL_SHELL_MCP_MAX_AUDIT_ARCHIVE_BYTES` | `512000000` |  |
| `max_tmp_files` | `LOCAL_SHELL_MCP_MAX_TMP_FILES` | `500` |  |
| `max_tmp_bytes` | `LOCAL_SHELL_MCP_MAX_TMP_BYTES` | `50000000` |  |
| `max_transfer_archive_entries` | `LOCAL_SHELL_MCP_MAX_TRANSFER_ARCHIVE_ENTRIES` | `100000` | Máximo de entries aceitos ao desempacotar archive de directory transferido. |
| `max_transfer_unpacked_bytes` | `LOCAL_SHELL_MCP_MAX_TRANSFER_UNPACKED_BYTES` | `10000000000` | Máximo de declared expanded bytes aceitos para archive de directory transferido. |
| `max_concurrent_commands` | `LOCAL_SHELL_MCP_MAX_CONCURRENT_COMMANDS` | `4` |  |
| `max_tmux_sessions` | `LOCAL_SHELL_MCP_MAX_TMUX_SESSIONS` | `16` | Máximo de persistent shell sessions entre backends tmux, ConPTY e native fallback. |

### Links de arquivos

| YAML key | Variável de ambiente | Default | Notas |
|---|---|---|---|
| `file_download_enabled` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED` | `True` |  |
| `file_download_default_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_TTL_S` | `3600` |  |
| `file_download_max_ttl_s` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_TTL_S` | `604800` |  |
| `file_download_default_max_downloads` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_DEFAULT_MAX_DOWNLOADS` | `0` | `0` significa nenhum default download-count limit. |
| `file_download_max_file_bytes` | `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_FILE_BYTES` | `0` | `0` significa nenhum configured file-size cap para download links. |

### Interface humana

| YAML key | Variável de ambiente | Default | Notas |
|---|---|---|---|
| `logical_sessions_enabled` | `LOCAL_SHELL_MCP_LOGICAL_SESSIONS_ENABLED` | `True` | Expõe `session_manage` e `plan_manage` e adiciona o argumento obrigatório, porém nullable, `logical_session_id` às ferramentas MCP comuns. Desative para uma superfície de ferramentas menor e sem Sessions. |
| `live_workspace_enabled` | `LOCAL_SHELL_MCP_LIVE_WORKSPACE_ENABLED` | `True` | Expõe tools, resources e rotas `/api/live/*` do MCP App Live Workspace. Requer `ui_enabled` e não está disponível no modo `stdio`. |
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `True` | Monta native OpenTUI launcher, WebUI shell, PTY WebSocket e routes `/api/ui/*`. |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `'/ui'` | Path de montagem WebUI no mesmo service. |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | `None` | Override opcional de command para resolução do executable OpenTUI. |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `'bing'` | `bing`, `aurora` ou `none`. |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | Timeout de browser PTY inativo; `0` desabilita. |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | Máximo de browser OpenTUI PTYs concorrentes. |

### Workers remotos

| YAML key | Variável de ambiente | Default | Notas |
|---|---|---|---|
| `remote_enabled` | `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `True` | Controla `/join`, `/remote/*` e MCP tools `remote_*`. |
| `remote_invite_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_INVITE_TTL_S` | `7200` |  |
| `remote_poll_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S` | `25` |  |
| `remote_job_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S` | `3600` |  |
| `remote_max_pending_jobs` | `LOCAL_SHELL_MCP_REMOTE_MAX_PENDING_JOBS` | `256` | Máximo de jobs queued/pending por worker. |
| `remote_cancelled_job_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_CANCELLED_JOB_TTL_S` | `3600` | Tempo de retenção de cancellation tombstones usados para pular queued jobs que expiraram. |
| `remote_transfer_strategy` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_STRATEGY` | `'auto'` | `auto`, `relay`, `direct` ou `object_store`. `auto` tenta peer-direct habilitado, depois S3 configurado e por fim relay do controller com memória limitada. |
| `remote_peer_transfer_enabled` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ENABLED` | `False` | Habilita opcionalmente receiver HTTP one-shot no worker destino para direct worker-to-worker transfer. Ative somente em rede privada confiável como VPC/Tailscale. |
| `remote_peer_transfer_bind_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_BIND_HOST` | `'0.0.0.0'` | Bind address do receiver one-shot do worker destino. |
| `remote_peer_transfer_advertise_host` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_ADVERTISE_HOST` | `None` | Address anunciado ao worker fonte; default para hostname/FQDN do worker destino. |
| `remote_peer_transfer_port` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_PORT` | `0` | Receiver port; `0` escolhe porta efêmera. |
| `remote_peer_transfer_timeout_s` | `LOCAL_SHELL_MCP_REMOTE_PEER_TRANSFER_TIMEOUT_S` | `3600` | Lifetime/timeout do receiver direto one-shot. |
| `remote_transfer_s3_bucket` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_BUCKET` | `None` | Bucket S3-compatible opcional para presigned worker-to-worker transfers. Requer extra `s3`. |
| `remote_transfer_s3_prefix` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PREFIX` | `'local-shell-mcp'` | Object-key prefix para temporary transfer objects. |
| `remote_transfer_s3_region` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_REGION` | `None` | Região S3 opcional. |
| `remote_transfer_s3_endpoint_url` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_ENDPOINT_URL` | `None` | Endpoint URL S3-compatible opcional. |
| `remote_transfer_s3_presign_ttl_s` | `LOCAL_SHELL_MCP_REMOTE_TRANSFER_S3_PRESIGN_TTL_S` | `3600` | Lifetime de URL PUT/GET presigned. Temporary objects são removidos depois do transfer. |

### Shell e paths de executáveis

| YAML key | Variável de ambiente | Default | Notas |
|---|---|---|---|
| `shell_executable` | `LOCAL_SHELL_MCP_SHELL_EXECUTABLE` | `'/bin/bash'` |  |
| `shell_env_blocklist` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKLIST` | `['CLOUDFLARE_TUNNEL_TOKEN']` |  |
| `shell_env_blocked_prefixes` | `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKED_PREFIXES` | `['LOCAL_SHELL_MCP_', 'DOCKER_']` | Separado por vírgulas em environment variables; list em YAML. |
| `tmux_bin` | `LOCAL_SHELL_MCP_TMUX_BIN` | `'tmux'` | Executable tmux preferido. Se indisponível, releases Linux e builds Docker usam bundled helper; senão persistent shells fazem fallback para backend native. |
| `rg_bin` | `LOCAL_SHELL_MCP_RG_BIN` | `'rg'` |  |
| `git_bin` | `LOCAL_SHELL_MCP_GIT_BIN` | `'git'` |  |
| `python_bin` | `LOCAL_SHELL_MCP_PYTHON_BIN` | `'python3'` |  |

### Autenticação e OAuth

| YAML key | Variável de ambiente | Default | Notas |
|---|---|---|---|
| `auth_mode` | `LOCAL_SHELL_MCP_AUTH_MODE` | `'oauth'` | Use `oauth` para deployments públicos. |
| `auth_bypass_localhost` | `LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST` | `True` |  |
| `require_auth_for_mcp_discovery` | `LOCAL_SHELL_MCP_REQUIRE_AUTH_FOR_MCP_DISCOVERY` | `True` | Exige OAuth antes de MCP initialization e tool discovery. |
| `mcp_session_idle_timeout_s` | `LOCAL_SHELL_MCP_MCP_SESSION_IDLE_TIMEOUT_S` | `180` | Idle timeout para sessões Stateful Streamable HTTP. |
| `mcp_max_sessions` | `LOCAL_SHELL_MCP_MCP_MAX_SESSIONS` | `1024` | Máximo de sessões MCP stateful concorrentes. |
| `public_base_url` | `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | `None` | Origin HTTPS externo. Não inclua `/mcp`. |
| `oauth_issuer` | `LOCAL_SHELL_MCP_OAUTH_ISSUER` | `None` |  |
| `oauth_resource` | `LOCAL_SHELL_MCP_OAUTH_RESOURCE` | `None` |  |
| `oauth_admin_pin` | `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` | `None` |  |
| `oauth_jwt_secret` | `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` | <generated or configured> |  |
| `oauth_access_token_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S` | `0` | `0` significa que access tokens não expiram automaticamente. |
| `oauth_code_ttl_s` | `LOCAL_SHELL_MCP_OAUTH_CODE_TTL_S` | `300` |  |

### Listas de política embutidas

| YAML key | Variável de ambiente | Default | Notas |
|---|---|---|---|
| `command_denylist` | `LOCAL_SHELL_MCP_COMMAND_DENYLIST` | `[]` | Limpa automaticamente quando full-container mode é habilitado. |
| `path_denylist` | `LOCAL_SHELL_MCP_PATH_DENYLIST` | `[]` | Limpa automaticamente quando full-container mode é habilitado. |

## Exemplo YAML

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

Controller serverless com estado Redis durable:

```yaml
mode: mcp
stateless_controller: true
state_backend: redis
state_backend_url: redis://redis.internal:6379/0
remote_transfer_strategy: auto
```

`stateless_controller` elimina a necessidade de volume persistente no controller. O backend `memory` é intencionalmente efêmero: um cold start invalida remote invites pendentes e worker identities e descarta OAuth clients, jobs e audit records. Use Redis quando qualquer estado precisar sobreviver a cold starts, incluindo semântica durable de revogação de worker. Com default `auth_mode=oauth`, injete ao menos 32 bytes de material de chave aleatório via `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET`. Active remote RPC queues/futures são process-local; por isso deployments com remote workers devem atualmente executar uma única instância ativa de controller, não múltiplas replicas balanceadas.

## Conselhos operacionais

- Mantenha `allow_full_container=false` salvo quando container/VM for disposable.
- Mantenha `auth_mode=oauth` em qualquer endpoint público.
- Desabilite `remote_enabled` se não usa remote workers.
- Desabilite `file_download_enabled` se nunca precisa de artifacts baixáveis pelo chat.
- Mantenha limites de command, file e audit altos o bastante para coding tasks, mas baixos o bastante para impedir runaway output acidental.
