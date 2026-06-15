# Documentation local-shell-mcp

Un plan de contrôle local pour ChatGPT Developer Mode et les autres clients MCP. Il expose un espace de travail contrôlé, le shell, les fichiers, Git, l’automatisation du navigateur, les liens de fichiers et les workers distants sous forme d’outils MCP.

## Documentation paths

- [Démarrage rapide](getting-started/quickstart.md)
- [Connecteur ChatGPT](getting-started/chatgpt-connector.md)
- [Workers distants](guides/remote-workers.md)
- [Sécurité](security.md)
- [Dépannage](troubleshooting.md)

## Core architecture

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## Key safety rule

Pour une exposition publique, activez OAuth et ne montez pas le Docker socket, la racine de l’hôte ni des identifiants longue durée.
