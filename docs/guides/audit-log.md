# Audit log

Tool activity is written as JSONL to `LOCAL_SHELL_MCP_AUDIT_LOG_PATH`, defaulting to `/workspace/.local-shell-mcp/audit.jsonl`.

The log records shell execution, tool errors, timeouts, routed MCP tool calls, and bounded tool arguments. Sensitive-looking argument keys such as token, password, secret, key, and pin are redacted before routed MCP call auditing.

Use the `audit_tail` tool for recent entries, or inspect the file directly inside the container.
