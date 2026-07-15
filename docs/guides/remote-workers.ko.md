# 원격 워커

Remote workers connect outbound to the control server and expose normal tools with an optional `machine` argument to the MCP client.

```text
ChatGPT -> local-shell-mcp -> outbound polling worker -> remote machine
```

Basic flow:

1. Create an invite with `remote_invite`.
2. Run the generated command on the remote machine.
3. Check `remote_list_machines`.
4. Use remote shell, file, transfer, Git, and browser tools.
5. Revoke the worker when done.

공개 배포에서는 OAuth 를 활성화하고 Docker socket, 호스트 루트, 장기 자격 증명을 마운트하지 마십시오.
