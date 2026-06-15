# Remote-Worker

Remote workers connect outbound to the control server and expose `remote_*` tools to the MCP client.

```text
ChatGPT -> local-shell-mcp -> outbound polling worker -> remote machine
```

Basic flow:

1. Create an invite with `remote_invite`.
2. Run the generated command on the remote machine.
3. Check `remote_list_machines`.
4. Use remote shell, file, transfer, Git, and browser tools.
5. Revoke the worker when done.

Bei öffentlicher Bereitstellung OAuth aktivieren und weder Docker-Socket, Host-Root noch langlebige Zugangsdaten einbinden.
