<!-- i18n-source-sha256: f8fefdb11bbe7b5b755fd59ee829b2771e8c2e9694d5b9db40f8693f53c16960 -->
<div class="hero-shell" markdown>
<span class="hero-eyebrow">Espacio de trabajo de IA autohospedado · Plano de control MCP</span>

# local-shell-mcp

Chat, proyectos, archivos, terminales, máquinas remotas y herramientas de inteligencia artificial en una interfaz autohospedada. Conecte clientes MCP externos cuando los necesite.

<div class="hero-actions" markdown>
[Empezar](getting-started/quickstart.md){ .hero-action .hero-action--primary }
[Web workspace](getting-started/web-workspace.md){ .hero-action .hero-action--secondary }
[Referencia de herramientas](reference/tools.md){ .hero-action .hero-action--secondary }
</div>
</div>

<div class="feature-grid" markdown>
<div class="feature-card" markdown>
### Entorno real de programación
Ejecute tests, inspeccione repositories, aplique patches, opere Git y mantenga audit trail desde un único MCP endpoint.
</div>

<div class="feature-card" markdown>
### Espacio de trabajo web unificado
Utilice el chat integrado y el historial de proyectos junto con los archivos, terminales, escritorio, sesiones, controles remotos y auditoría del controlador. Los clientes MCP externos siguen siendo opcionales.
</div>

<div class="feature-card" markdown>
### Control de máquinas remotas
Conecte máquinas detrás de NAT, firewall o HPC mediante conexiones worker salientes sin abrir puertos SSH.
</div>
</div>

## Qué proporciona

`local-shell-mcp` proporciona un espacio de trabajo de IA unificado y autohospedado y un servidor MCP para clientes externos. Proporciona shell, shell persistente, sistema de archivos, búsqueda, parches, Git, Playwright, auditoría, sesiones lógicas duraderas con planes Goal opcionales, enlace de archivos tokenizado y herramientas para trabajadores remotos a través de puntos finales MCP autenticados.

Úselo cuando la IA deba inspeccionar un repository, ejecutar tests, editar archivos, operar Git, recopilar browser evidence, producir downloadable artifacts o controlar una máquina remota que solo puede conectarse de salida al control server.

## Arquitectura

```text
Capa runtime: Docker / VS Code extension / binary / Python / stdio
Capa de exposición: localhost / HTTPS proxy / tunnel / stdio pipe
Capa de cliente: WebUI unificada / Gemini / ChatGPT / cliente MCP genérico
Workspace controlado: /workspace or configured workspace root
Remote workers opcionales: outbound machine connections
```

El límite de aislamiento previsto es el container o VM que ejecuta el servicio.

## Empezar según el escenario

| Escenario | Empiece aquí | Por qué |
|---|---|---|
| Espacio de trabajo del navegador principal | [Unified web workspace](getting-started/web-workspace.md) | Chat, proyectos y páginas de control de LSM con un inicio de sesión compartido |
| Implementación del primer controlador | [Quickstart](getting-started/quickstart.md) | Binario recomendado, OAuth y primer inicio en navegador |
| Elegir la capa runtime | [Runtime choices](guides/deployment.md) | Explica Docker, VS Code, binary, Python y stdio como opciones separadas de runtime |
| Conectando la chispa de Géminis | [Gemini Custom Apps](getting-started/gemini-spark.md) | Elegibilidad, URL HTTPS MCP, OAuth y pruebas |
| Añadir ChatGPT como client | [ChatGPT connector](getting-started/chatgpt-connector.md) | Endpoint, OAuth, primer prompt seguro y tool discovery |
| Añadir LSM a DeepSeek Harness | [Plugin DeepSeek Harness](clients/deepseek-harness.md) | Instalar este repository como bundle DSH manteniendo toda la superficie de herramientas LSM y remote workers |
| Ejecutar desde VS Code | [VS Code extension runtime](installation/vscode-extension.md) | Runtime lanzado desde editor y notas de seguridad del host |
| Aprender a operar el toolset | [Usage patterns](guides/usage-patterns.md) | Plantillas de prompt y guía de elección de herramientas |
| Entender cada tool | [Tools reference](reference/tools.md) | Propósito, inputs, returns, combinaciones y notas de cada tool |
| Conectar HPC, NPU/GPU o server node | [Remote workers](guides/remote-workers.md) | Flujo de unión outbound worker y uso remoto de tools |
| Compartir archivos generados | [File links](guides/file-links.md) | URLs tokenizadas con TTL y revocación |
| Endurecer el deployment | [Security](security.md) | Aislamiento, OAuth, alcance de workspace y audit logs |

## Familias principales de tools

| Familia | Ejemplos | Uso |
|---|---|---|
| Shell and Python | `run_shell`, `run_python`, `shell_start` | Builds, tests, scripts y procesos largos |
| Files and search | `file_tree`, `file_grep`, `file_read`, `file_patch` | Inspección de repository y edits precisos |
| Git | `run_shell`, `run_shell`, `run_shell`, `run_shell` | Workflows de control de versiones revisables |
| Sessions y goals | `session_manage`, `plan_manage` | Handoff durable de tareas, informes de progreso y Goal mode opcional |
| Browser | `browser_session`, `browser_snapshot`, `browser_act`, `browser_run_script` | Interacción persistente, comprobaciones UI, screenshots, docs renderizados y texto de página |
| File links | `link_create`, `link_revoke` | Descargar artefactos generados desde chat |
| Remote workers | `remote_manage`, `run_shell`, `remote_transfer` | Máquinas detrás de NAT, firewalls o flujos de login de cluster |

## Workflows típicos

### Codificación en el espacio de trabajo web

1. Inicie un controlador LSM y el [unified web workspace](getting-started/web-workspace.md) opcional.
2. Abra `/ui` e inicie sesión con la identidad LSM.
3. Configure un punto final modelo y abra una nueva conversación.
4. Pídale al modelo que inspeccione el repositorio y primero ejecute comprobaciones de solo lectura.
5. Después permita patches, tests, review de diff, commit y push cuando estén aprobados.
6. Revise audit log cuando el task implique file links o sistemas remotos.

### Host HPC o acelerador remoto

1. Cree una invitación remote worker de un solo uso.
2. Pegue el command generado en el remote host.
3. Use tools normales con `machine`; Git mediante `run_shell` y transferencias con `remote_transfer`.
4. Revoque el worker después del task.

### Generación de artefactos

1. Haga que la IA genere un file bajo `/workspace`.
2. Cree un tokenized file link con TTL/download limits.
3. Comparta el link en chat.
4. Revóquelo al terminar.

## Idioma

Este site se construye con el plugin i18n nativo de MkDocs. Use el selector de idioma de la cabecera para cambiar entre English y páginas traducidas. Las páginas sin traducción recurren a English.
