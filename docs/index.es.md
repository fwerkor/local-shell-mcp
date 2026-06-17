# Documentación de local-shell-mcp

Un plano de control local para ChatGPT Developer Mode y otros clientes MCP. Expone un espacio de trabajo controlado, shell, archivos, Git, automatización del navegador, enlaces de archivos y workers remotos como herramientas MCP.

## Rutas de documentación

- [Inicio rápido](getting-started/quickstart.md)
- [Conector de ChatGPT](getting-started/chatgpt-connector.md)
- [Workers remotos](guides/remote-workers.md)
- [Seguridad](security.md)
- [Solución de problemas](troubleshooting.md)

## Arquitectura principal

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## Regla de seguridad clave

En despliegues públicos, habilita OAuth y no montes el Docker socket, la raíz del host ni credenciales de larga duración.
