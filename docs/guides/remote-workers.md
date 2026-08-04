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
5. Use `transfer_path` to start a tracked controller-to-worker, worker-to-controller, or worker-to-worker file or directory transfer. Follow it with `job_list` or `job_tail`; stop or retry it with `job_stop` or `job_retry`.
6. Rename or revoke workers with `remote_rename_machine` and `remote_revoke_machine`.

Only worker administration uses `remote_*` names. Execution, shell, job, filesystem, patch, and browser operations share the same schema locally and remotely. Supplying a machine additionally requires the `remote:use` OAuth scope.

## Persistent workers

The invite result contains platform-specific commands:

- `persistent_command` installs and starts a user service on Linux or macOS.
- `powershell_persistent_command` installs and starts a Windows user task from PowerShell.

On Windows, `local-shell-mcp worker install-service` registers the `local-shell-mcp-worker` task for the current user. It starts immediately, starts again when that user logs on after a reboot, permits battery operation, ignores duplicate starts, and retries failed runs. It does not require administrator rights and does not run before the user signs in.

Use the same lifecycle commands on every platform:

```text
local-shell-mcp worker status
local-shell-mcp worker start
local-shell-mcp worker stop
local-shell-mcp worker restart
local-shell-mcp worker uninstall-service
```

The worker log is stored under the worker state directory as `worker.log`.

## Capabilities

Workers support shell and persistent shell sessions, tracked jobs, filesystem operations, transfer internals, Python execution, patches, and Playwright where dependencies are installed. Git uses standard commands through `run_shell_tool(machine=...)`.

## Security and versioning

A joined worker gives the MCP client control over its configured environment. Use short invite TTLs, dedicated work directories or accounts, review audit logs, and revoke workers when finished. The generated invite installs worker code matching the control server version.

## Troubleshooting

Check outbound HTTPS access, public base URL reachability, invite expiry, system time, and control-server logs when a worker does not appear.
