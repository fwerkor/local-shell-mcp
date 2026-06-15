# ChatGPT 커넥터

Use this MCP endpoint in ChatGPT:

```text
https://your-public-host.example.com/mcp
```

Set `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` to the origin only, without `/mcp`.

Recommended first prompt:

```text
Use local-shell-mcp. First call environment_info, then list the workspace root. Do not modify files yet.
```

공개 배포에서는 OAuth 를 활성화하고 Docker socket, 호스트 루트, 장기 자격 증명을 마운트하지 마십시오.
