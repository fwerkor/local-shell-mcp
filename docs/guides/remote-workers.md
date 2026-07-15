# Remote workers

Remote workers let `local-shell-mcp` control machines that can make outbound HTTP(S) requests but cannot accept inbound SSH connections.

```text
MCP client -> control server -> outbound polling worker -> remote machine
```

## Basic workflow

1. Create a one-time invite with `remote_invite`.
2. Run the generated command on the remote machine.
3. Confirm registration with `remote_list_machines`.
4. Call normal tools with `machine="<worker-name>"`, for example `environment_info`, `run_shell_tool`, `read_file`, or `browser_capture_tool`.
5. Use `transfer_path` for controller-to-worker, worker-to-controller, or worker-to-worker file and directory transfers.
6. Rename or revoke workers with `remote_rename_machine` and `remote_revoke_machine`.

Only worker administration uses `remote_*` names. Execution, shell, job, filesystem, patch, and browser operations share the same schema locally and remotely. Supplying a machine additionally requires the `remote:use` OAuth scope.

## Capabilities

Workers support shell and persistent shell sessions, tracked jobs, filesystem operations, transfer internals, Python execution, patches, and Playwright where dependencies are installed. Git uses standard commands through `run_shell_tool(machine=...)`.

## Security and versioning

A joined worker gives the MCP client control over its configured environment. Use short invite TTLs, dedicated work directories or accounts, review audit logs, and revoke workers when finished. The generated invite installs worker code matching the control server version.

## Troubleshooting

Check outbound HTTPS access, public base URL reachability, invite expiry, system time, and control-server logs when a worker does not appear.
