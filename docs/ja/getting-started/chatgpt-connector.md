# ChatGPT コネクタ

Use this MCP endpoint in ChatGPT:

```text
https://your-public-host.example.com/mcp
```

Set `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` to the origin only, without `/mcp`.

Recommended first prompt:

```text
Use local-shell-mcp. First call environment_info, then list the workspace root. Do not modify files yet.
```

公開環境では OAuth を必ず有効にし、Docker socket、ホスト root、長期認証情報をマウントしないでください。
