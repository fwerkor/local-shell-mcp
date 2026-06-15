# Configuration

Environment variables use the `LOCAL_SHELL_MCP_` prefix and override YAML config values loaded by `LOCAL_SHELL_MCP_CONFIG` or `--config`.

Important settings:

- `LOCAL_SHELL_MCP_PUBLIC_BASE_URL`: public HTTPS origin used by OAuth and generated links.
- `LOCAL_SHELL_MCP_AUTH_MODE`: `oauth` or `none`; do not expose public services with `none`.
- `LOCAL_SHELL_MCP_WORKSPACE_ROOT`: root for normal file and command operations.
- `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER`: disables built-in workspace/path restrictions when true.
- `LOCAL_SHELL_MCP_REMOTE_ENABLED`: enables `/join`, `/remote/*`, and remote MCP tools.
- `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKLIST` and `LOCAL_SHELL_MCP_SHELL_ENV_BLOCKED_PREFIXES`: remove server-side environment values from user shell subprocesses.
