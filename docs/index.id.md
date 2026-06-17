# Dokumentasi local-shell-mcp

Bidang kendali lokal untuk ChatGPT Developer Mode dan client MCP lain. Ini mengekspos workspace terkendali, shell, file, Git, otomasi browser, tautan file, dan worker jarak jauh sebagai alat MCP.

## Jalur dokumentasi

- [Mulai cepat](getting-started/quickstart.md)
- [Konektor ChatGPT](getting-started/chatgpt-connector.md)
- [Worker jarak jauh](guides/remote-workers.md)
- [Keamanan](security.md)
- [Pemecahan masalah](troubleshooting.md)

## Arsitektur inti

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## Aturan keamanan utama

Pada deployment publik, aktifkan OAuth dan jangan mount Docker socket, root host, atau kredensial jangka panjang.
