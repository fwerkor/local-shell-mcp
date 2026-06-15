# ChatGPT connector

Use the public MCP URL ending in `/mcp`.

```text
https://your-public-host.example.com/mcp
```

During OAuth authorization, enter the PIN configured by `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN`. The access-token signing secret should be stable across restarts by setting `LOCAL_SHELL_MCP_OAUTH_JWT_SECRET`.

Developer Mode clients can use the full tool surface. Non-developer connector surfaces may be limited to connector-compatible read tools such as `search` and `fetch`.
