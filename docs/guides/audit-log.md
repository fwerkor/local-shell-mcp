# Audit log

`local-shell-mcp` writes structured audit entries to help reconstruct what a connected client did.

Default path:

```text
/workspace/.local-shell-mcp/audit.jsonl
```

## What is recorded

Audit entries cover events such as:

- Tool call start/end.
- Command execution metadata.
- Timeouts and handled errors.
- Remote worker registration and job activity.
- File-link creation and revocation.
- Authentication-related events where applicable.

Sensitive arguments are redacted where the server can identify them.

## Reading the log

Use the MCP tool:

```text
audit_tail
```

Or inspect directly:

```bash
tail -n 100 /workspace/.local-shell-mcp/audit.jsonl
```

## Operational use

Audit logs are most useful for:

- Reviewing commands that changed files.
- Checking whether a remote worker was used.
- Debugging unexpected failures.
- Detecting accidental exposure of file links.
- Supporting incident response after a public deployment mistake.

## Retention

The log is bounded by `LOCAL_SHELL_MCP_MAX_AUDIT_LOG_BYTES`. Rotate or export it externally if you need long retention.

## Limitations

Audit logs are not a sandbox. They help with traceability, but they do not prevent a connected model from taking actions within its configured authority.
