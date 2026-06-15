# ChatGPT 連接器

Use this MCP endpoint in ChatGPT:

```text
https://your-public-host.example.com/mcp
```

Set `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` to the origin only, without `/mcp`.

Recommended first prompt:

```text
Use local-shell-mcp. First call environment_info, then list the workspace root. Do not modify files yet.
```

公開部署必須啟用 OAuth；不要掛載 Docker socket、主機根目錄或長期憑證。
