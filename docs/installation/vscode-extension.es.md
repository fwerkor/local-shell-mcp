# Extensión de VS Code

Esta página describe el escenario “Extensión de VS Code” y mantiene la estructura Runtime/Client común del sitio.

## Resumen

Runtime define cómo se ejecuta el proceso del servidor y qué espacio de trabajo controla. Client define cómo se conecta ChatGPT u otro cliente MCP. Docker, la extensión de VS Code, los binarios independientes, las instalaciones desde Python/pipx/código fuente y stdio son opciones de Runtime; el conector de ChatGPT, el cliente MCP HTTP genérico y el cliente MCP stdio son conexiones de Client.

## Cuándo usarlo

- Usa esta página cuando la ruta de Runtime o Client elegida coincida con el título.
- Mantén coherentes la raíz del espacio de trabajo, la base URL pública, el MCP endpoint, el modo de autenticación y las herramientas disponibles del host.
- Para ChatGPT web/app, expón un MCP endpoint HTTPS que termine en `/mcp`.
- Para clientes MCP locales, usa HTTP localhost o `local-shell-mcp --mode stdio` según lo que admita el cliente.

## Pasos

1. Elige primero la página de instalación del Runtime.
2. Inicia el Runtime y verifica `/healthz` cuando uses el modo HTTP.
3. Elige después la página de conexión del Client.
4. Registra el MCP endpoint o el comando stdio en el Client.
5. Llama a `environment_info` para comprobar el espacio de trabajo y los ajustes efectivos.

```text
Runtime: Docker / VS Code extension / binary / Python / stdio
Client:  ChatGPT connector / generic HTTP MCP / generic stdio MCP
Endpoint: https://your-host.example.com/mcp
```

## Verificación

- `environment_info` confirma los ajustes del Runtime y el espacio de trabajo.
- `tree_view` confirma los archivos visibles.
- `run_shell_tool` confirma el entorno de comandos.

## Notas

Prefiere pasos pequeños y verificables: inspeccionar, editar, revisar el diff, probar, escanear y confirmar. Las tareas grandes también deben dividirse en llamadas de herramientas auditables.
