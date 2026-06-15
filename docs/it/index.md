# Documentazione local-shell-mcp

Un piano di controllo locale per ChatGPT Developer Mode e altri client MCP. Espone workspace controllato, shell, file, Git, automazione browser, link ai file e worker remoti come strumenti MCP.

## Documentation paths

- [Avvio rapido](getting-started/quickstart.md)
- [Connettore ChatGPT](getting-started/chatgpt-connector.md)
- [Worker remoti](guides/remote-workers.md)
- [Sicurezza](security.md)
- [Risoluzione problemi](troubleshooting.md)

## Core architecture

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## Key safety rule

Per distribuzioni pubbliche abilita OAuth e non montare Docker socket, root dell’host o credenziali persistenti.
