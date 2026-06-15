# Dokumentacja local-shell-mcp

Lokalna płaszczyzna sterowania dla ChatGPT Developer Mode i innych klientów MCP. Udostępnia kontrolowany workspace, shell, pliki, Git, automatyzację przeglądarki, linki do plików i remote workers jako narzędzia MCP.

## Documentation paths

- [Szybki start](getting-started/quickstart.md)
- [Konektor ChatGPT](getting-started/chatgpt-connector.md)
- [Zdalne workery](guides/remote-workers.md)
- [Bezpieczeństwo](security.md)
- [Rozwiązywanie problemów](troubleshooting.md)

## Core architecture

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## Key safety rule

W publicznych wdrożeniach włącz OAuth i nie montuj Docker socket, katalogu głównego hosta ani długotrwałych poświadczeń.
