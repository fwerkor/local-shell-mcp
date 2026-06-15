# Dokumentasi local-shell-mcp

Control plane lokal untuk ChatGPT Developer Mode dan klien MCP lain. Ia mengekspos workspace terkontrol, shell, file, Git, otomasi browser, tautan file, dan remote worker sebagai alat MCP.

## Documentation paths

- [Mulai cepat](getting-started/quickstart.md)
- [Konektor ChatGPT](getting-started/chatgpt-connector.md)
- [Remote worker](guides/remote-workers.md)
- [Keamanan](security.md)
- [Pemecahan masalah](troubleshooting.md)

## Core architecture

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## Key safety rule

Untuk deployment publik, aktifkan OAuth dan jangan mount Docker socket, root host, atau kredensial jangka panjang.
