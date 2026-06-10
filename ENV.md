# Environment variable reference

This is the complete reference for settings that can be supplied through the process environment. For Docker Compose deployments, copy [.env.example](.env.example) to `.env`; the compose file requires that file and passes it to the main container with `env_file:`. For task-oriented setup instructions, start with [INSTALL.md](INSTALL.md) and [USAGE.md](USAGE.md).

## Naming convention

- `LOCAL_SHELL_MCP_*` configures the local-shell-mcp application.
- `DOCKER_*` configures Docker image entrypoint behavior before the application starts.
- Third-party variables such as `CLOUDFLARE_TUNNEL_TOKEN` and `SSH_AUTH_SOCK` keep their upstream names.

## Application configuration precedence

Only application settings participate in this precedence chain:

```text
defaults < config file < LOCAL_SHELL_MCP_* environment variables < CLI arguments
```

The YAML config file is optional. Prefer `LOCAL_SHELL_MCP_*` variables or CLI arguments for new deployments. `--config PATH` and `LOCAL_SHELL_MCP_CONFIG` select the optional config file.

## Application settings

| Environment variable | CLI argument | Default | Description |
|---|---|---:|---|
| `LOCAL_SHELL_MCP_CONFIG` | `--config` | unset | Path to optional YAML config file. This selects the config file and is not itself a Settings field. |
| `LOCAL_SHELL_MCP_MODE` | `--mode` | `mcp` | Server transport mode: mcp, http, stdio, or both. |
| `LOCAL_SHELL_MCP_HOST` | `--host` | `0.0.0.0` | Bind host for HTTP/MCP transports. |
| `LOCAL_SHELL_MCP_PORT` | `--port` | `8765` | Bind port for HTTP/MCP transports. |
| `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | `--workspace-root` | `/workspace` | Root directory for normal file and command operations. |
| `LOCAL_SHELL_MCP_STATE_DIR` | `--state-dir` | `/workspace/.local-shell-mcp` | Directory for runtime state such as audit logs and temporary files. |
| `LOCAL_SHELL_MCP_AUDIT_LOG_PATH` | `--audit-log-path` | `/workspace/.local-shell-mcp/audit.jsonl` | Path to the JSONL audit log. |
| `LOCAL_SHELL_MCP_AUTH_MODE` | `--auth-mode` | `oauth` | Authentication mode: oauth or none. Do not expose public services with none. |
| `LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST` | `--auth-bypass-localhost` | `true` | Allow localhost requests without bearer authentication. |
| `LOCAL_SHELL_MCP_REQUIRE_AUTH_FOR_MCP_DISCOVERY` | `--require-auth-for-mcp-discovery` | `false` | Require authentication for MCP initialize/list-tools discovery calls. |
| `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | `--public-base-url` | `unset` | Public HTTPS origin used in OAuth metadata and callbacks. |
| `LOCAL_SHELL_MCP_OAUTH_ISSUER` | `--oauth-issuer` | `unset` | Override OAuth issuer metadata; defaults to public_base_url when unset. |
| `LOCAL_SHELL_MCP_OAUTH_RESOURCE` | `--oauth-resource` | `unset` | Override OAuth resource metadata; defaults to public_base_url when unset. |
| `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` | `--oauth-admin-pin` | `unset` | PIN required to approve OAuth authorization. |
| `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET` | `--oauth-jwt-secret` | `dev-change-me` | Secret used to sign OAuth bearer tokens; set a strong random value. |
| `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S` | `--oauth-access-token-ttl-s` | `0` | Bearer token lifetime in seconds; 0 means no expiry. |
| `LOCAL_SHELL_MCP_OAUTH_CODE_TTL_S` | `--oauth-code-ttl-s` | `300` | OAuth authorization-code lifetime in seconds. |
| `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER` | `--allow-full-container` | `false` | Disable built-in workspace and command restrictions; use only in disposable containers or VMs. |
| `LOCAL_SHELL_MCP_ALLOW_NETWORK` | `--allow-network` | `true` | Allow network-capable operations. |
| `LOCAL_SHELL_MCP_DEFAULT_TIMEOUT_S` | `--default-timeout-s` | `60` | Default shell command timeout in seconds. |
| `LOCAL_SHELL_MCP_MAX_TIMEOUT_S` | `--max-timeout-s` | `3600` | Maximum shell command timeout in seconds. |
| `LOCAL_SHELL_MCP_MAX_OUTPUT_BYTES` | `--max-output-bytes` | `200000` | Command output truncation limit in bytes. |
| `LOCAL_SHELL_MCP_MAX_FILE_READ_BYTES` | `--max-file-read-bytes` | `512000` | Per-file read limit in bytes. |
| `LOCAL_SHELL_MCP_MAX_FILE_WRITE_BYTES` | `--max-file-write-bytes` | `5000000` | Per-file write/edit limit in bytes. |
| `LOCAL_SHELL_MCP_MAX_GREP_RESULTS` | `--max-grep-results` | `200` | Maximum grep result count. |
| `LOCAL_SHELL_MCP_MAX_DIRECTORY_ENTRIES` | `--max-directory-entries` | `5000` | Maximum listed directory entries. |
| `LOCAL_SHELL_MCP_MAX_GLOB_RESULTS` | `--max-glob-results` | `5000` | Maximum glob search results. |
| `LOCAL_SHELL_MCP_MAX_TREE_ENTRIES` | `--max-tree-entries` | `5000` | Maximum tree-view entries. |
| `LOCAL_SHELL_MCP_MAX_READ_MANY_FILES` | `--max-read-many-files` | `100` | Maximum files read by a multi-file read operation. |
| `LOCAL_SHELL_MCP_MAX_READ_MANY_TOTAL_BYTES` | `--max-read-many-total-bytes` | `5000000` | Combined byte limit for multi-file reads. |
| `LOCAL_SHELL_MCP_MAX_TODOS` | `--max-todos` | `1000` | Todo-list item limit. |
| `LOCAL_SHELL_MCP_MAX_TODO_BYTES` | `--max-todo-bytes` | `1000000` | Todo-list serialized byte limit. |
| `LOCAL_SHELL_MCP_MAX_AUDIT_TAIL_BYTES` | `--max-audit-tail-bytes` | `1000000` | Audit-tail response byte limit. |
| `LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES` | `--max-audit-log-bytes` | `20000000` | Audit-log rotation threshold in bytes. |
| `LOCAL_SHELL_MCP_MAX_TMP_FILES` | `--max-tmp-files` | `500` | Temporary-file count limit. |
| `LOCAL_SHELL_MCP_MAX_TMP_BYTES` | `--max-tmp-bytes` | `50000000` | Temporary-file byte limit. |
| `LOCAL_SHELL_MCP_MAX_CONCURRENT_COMMANDS` | `--max-concurrent-commands` | `4` | Concurrent command limit. |
| `LOCAL_SHELL_MCP_MAX_TMUX_SESSIONS` | `--max-tmux-sessions` | `16` | Persistent shell session limit. |
| `LOCAL_SHELL_MCP_COMMAND_DENYLIST` | `--command-denylist` | `docker.sock,/var/run/docker.sock,mkfs,mount ,umount ,shutdown,reboot,systemctl ,iptables,nft ` | Comma-separated command denylist in env/CLI, or a YAML list in config files. Cleared when full-container mode is enabled. |
| `LOCAL_SHELL_MCP_PATH_DENYLIST` | `--path-denylist` | `.ssh/id_rsa,.ssh/id_ed25519,.env,secrets,credentials,.git/config` | Comma-separated path denylist in env/CLI, or a YAML list in config files. Cleared when full-container mode is enabled. |
| `LOCAL_SHELL_MCP_REMOTE_ENABLED` | `--remote-enabled` | `true` | Enable remote worker routes and MCP tools. |
| `LOCAL_SHELL_MCP_REMOTE_INVITE_TTL_S` | `--remote-invite-ttl-s` | `600` | One-time remote worker invite lifetime in seconds. |
| `LOCAL_SHELL_MCP_REMOTE_POLL_TIMEOUT_S` | `--remote-poll-timeout-s` | `25` | Remote worker long-poll heartbeat timeout in seconds. |
| `LOCAL_SHELL_MCP_REMOTE_JOB_TIMEOUT_S` | `--remote-job-timeout-s` | `3600` | Control-side remote job result timeout in seconds. |
| `LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED` | `--agent-bridge-enabled` | `true` | Enable agent capability bridge tools. |
| `LOCAL_SHELL_MCP_AGENT_CONFIG_DIR` | `--agent-config-dir` | `/home/agent/local-shell-mcp-config` | Read-only capability config directory. |
| `LOCAL_SHELL_MCP_AGENT_MCP_PROBE_TIMEOUT_S` | `--agent-mcp-probe-timeout-s` | `5` | Agent MCP server probe timeout in seconds. |
| `LOCAL_SHELL_MCP_AGENT_MCP_CALL_TIMEOUT_S` | `--agent-mcp-call-timeout-s` | `60` | Agent MCP tool-call timeout in seconds. |
| `LOCAL_SHELL_MCP_AGENT_DYNAMIC_MCP_TOOLS` | `--agent-dynamic-mcp-tools` | `true` | Register dynamic MCP bridge tools. |
| `LOCAL_SHELL_MCP_AGENT_DYNAMIC_SKILL_TOOLS` | `--agent-dynamic-skill-tools` | `true` | Register dynamic skill bridge tools. |
| `LOCAL_SHELL_MCP_SHELL_EXECUTABLE` | `--shell-executable` | `/bin/bash` | Shell executable used for shell commands. |
| `LOCAL_SHELL_MCP_TMUX_BIN` | `--tmux-bin` | `tmux` | tmux executable. |
| `LOCAL_SHELL_MCP_RG_BIN` | `--rg-bin` | `rg` | ripgrep executable. |
| `LOCAL_SHELL_MCP_GIT_BIN` | `--git-bin` | `git` | Git executable. |
| `LOCAL_SHELL_MCP_PYTHON_BIN` | `--python-bin` | `python3` | Python executable. |

## Docker entrypoint settings

These variables are consumed by `scripts/docker-entrypoint.sh` before `local-shell-mcp` starts. They are intentionally not part of `Settings`, do not participate in application config-file precedence, and affect only Docker image startup behavior. In Docker Compose deployments, they are supplied from `.env` together with the application variables because `docker-compose.yml` uses `env_file: .env` for the main container.

| Environment variable | Default | Description |
|---|---:|---|
| `DOCKER_RUN_AS_ROOT` | `false` | Run the server process as root instead of the `agent` user. Prefer explicit `sudo` inside commands. |
| `DOCKER_PERSISTENT_CREDENTIALS` | `true` | Persist common developer credential files into `DOCKER_CREDENTIALS_DIR`. |
| `DOCKER_CREDENTIALS_DIR` | `/persist/credentials` | Root directory for persisted GitHub CLI, Git, SSH, `.netrc`, and GPG state. |
| `DOCKER_CHOWN_WORKSPACE` | `true` | `chown` the workspace to `agent` before starting the server. |

## Third-party and script variables

| Environment variable | Used by | Description |
|---|---|---|
| `CLOUDFLARE_TUNNEL_TOKEN` | `docker-compose.yml` tunnel profile | Token for the optional Cloudflare Tunnel sidecar. |
| `SSH_AUTH_SOCK` | optional Docker Compose mount | SSH agent socket to expose to the container instead of mounting private keys. |
