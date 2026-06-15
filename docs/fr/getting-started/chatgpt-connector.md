# Connecteur ChatGPT

Use this MCP endpoint in ChatGPT:

```text
https://your-public-host.example.com/mcp
```

Set `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` to the origin only, without `/mcp`.

Recommended first prompt:

```text
Use local-shell-mcp. First call environment_info, then list the workspace root. Do not modify files yet.
```

Pour une exposition publique, activez OAuth et ne montez pas le Docker socket, la racine de l’hôte ni des identifiants longue durée.
