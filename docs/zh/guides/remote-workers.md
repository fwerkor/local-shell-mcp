# 远程节点

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

公网部署必须启用 OAuth；不要挂载 Docker socket、宿主机根目录或长期凭据。
