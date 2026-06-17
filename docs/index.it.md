# Documentazione di local-shell-mcp

Un piano di controllo locale per ChatGPT Developer Mode e altri client MCP. Espone uno spazio di lavoro controllato, shell, file, Git, automazione del browser, link ai file e worker remoti come strumenti MCP.

## Percorsi della documentazione

- [Avvio rapido](getting-started/quickstart.md)
- [Connettore ChatGPT](getting-started/chatgpt-connector.md)
- [Worker remoti](guides/remote-workers.md)
- [Sicurezza](security.md)
- [Risoluzione dei problemi](troubleshooting.md)

## Architettura principale

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## Regola di sicurezza chiave

Nelle distribuzioni pubbliche abilita OAuth e non montare il Docker socket, la radice dell’host o credenziali di lunga durata.
