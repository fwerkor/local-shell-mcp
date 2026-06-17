# Dokumentacja local-shell-mcp

Lokalna płaszczyzna sterowania dla ChatGPT Developer Mode i innych klientów MCP. Udostępnia kontrolowany workspace, shell, pliki, Git, automatyzację przeglądarki, linki do plików i zdalne worker jako narzędzia MCP.

## Ścieżki dokumentacji

- [Szybki start](getting-started/quickstart.md)
- [Łącznik ChatGPT](getting-started/chatgpt-connector.md)
- [Zdalne worker](guides/remote-workers.md)
- [Bezpieczeństwo](security.md)
- [Rozwiązywanie problemów](troubleshooting.md)

## Główna architektura

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## Kluczowa zasada bezpieczeństwa

W publicznych wdrożeniach włącz OAuth i nie montuj Docker socket, katalogu głównego hosta ani długoterminowych poświadczeń.
