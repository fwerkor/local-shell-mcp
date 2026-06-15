# Remote workers

Remote worker mode lets a machine behind NAT, a firewall, or an HPC login node connect back to the public control server using outbound HTTP(S). The remote machine does not need inbound SSH or an open port.

## Flow

1. Ask the control server for a remote invite.
2. Paste the generated command on the remote machine.
3. The worker downloads the worker bundle, registers, and polls for jobs.
4. Remote tools run on the worker and return results through the control server.

Example prompt:

```text
Use local-shell-mcp remote_invite with name=npu-4card and workdir=/home/cyh/FrameDiff.
```

Then verify:

```text
Use local-shell-mcp remote_list_machines, then remote_environment_info for machine=npu-4card.
```

Remote tools mirror local tool categories and add a `machine` argument, for example `remote_run_shell_tool`, `remote_read_file`, and `remote_push_file`.
