<!-- i18n-source-sha256: 521e0f39c8823597b1468b2d63af978794cb28fda8c8e60230da0a96cff2d5c2 -->
# Espacio de trabajo web unificado

El **espacio de trabajo web unificado de LSM** es la forma recomendada de utilizar local-shell-mcp en el día a día. Combina el chat de IA, el historial del proyecto y el plano de control LSM en una interfaz responsiva, basada en una interfaz LibreChat modificada y suministrada. Aún puede conectar clientes MCP externos como [ChatGPT](chatgpt-connector.md) o [Gemini](gemini-spark.md).

El espacio de trabajo es **autohospedado y su instalación es opcional**: es un servicio web independiente, que no forma parte de la imagen mínima del controlador, del ejecutable independiente ni del paquete de trabajador remoto. Las implementaciones de solo controlador conservan la interfaz de usuario del navegador original y OpenTUI.

## ¿Qué hay en el espacio de trabajo?

| Área | que puedes hacer |
|---|---|
| Chat y proyectos | Elija un modelo configurado, cree conversaciones, organice proyectos, busque chats anteriores y archive conversaciones. La historia permanece en el servidor. |
| Descripción general del controlador | Ver estado, actividad reciente y máquinas conectadas. |
| Archivos | Explore y administre archivos locales o remotos. |
| Terminales | Trabajar con terminales persistentes en el Controlador o Trabajadores. |
| Escritorio | Inspeccionar y controlar sesiones GUI remotas. |
| Sesiones | Inspeccione tareas LSM duraderas y su ciclo de vida. |
| Mandos a distancia | Conecte y administre trabajadores salientes. |
| Auditoría | Inspeccionar la actividad de la herramienta originada en el modelo. |
| MCP anidado | Registre, edite, habilite, deshabilite, actualice y elimine servidores MCP externos detrás de LSM. |

Las rutas del controlador son `/control/overview`, `/control/files`, `/control/terminals`, `/control/desktop`, `/control/sessions`, `/control/remotes` y `/control/audit`. El chat se abre en `/c/new`. El administrador de LSM MCP controla **el registro de MCP anidado de LSM**; no crea un segundo registro en LibreChat.

## Implementar la pila de chat opcional

1. [Install and start an LSM Controller](quickstart.md) with SQLite (now the default). On startup, durable historical state is imported automatically, retaining the original files for rollback.
2. Configure one HTTP/HTTPS Controller origin, for example `https://lsm.example.org`. Chat, terminals, files and remote controls share the same Python server and authentication.
3. To override the defaults, configure the Controller service environment:

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

4. Start the Controller from its Python package or standalone executable:

```sh
local-shell-mcp --mode mcp
```

5. The original React client is maintained in `ui/workspace/`. Bun is only required for building and releases; consult the [first-party WebUI build and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

Node.js, MongoDB, Meilisearch and the separate LibreChat Compose stack are no longer required at runtime. Workers remain ordinary Python packages.

**Migration status:** The Python Agent generation engine, SSE resume and tool approvals are still being ported. Do not deploy the draft branch as a replacement for a working production Controller.

## Inicia sesión y usa el chat

1. Open the LSM Controller `/ui` entrypoint and authenticate with its existing PIN or OAuth credentials. React and Controller APIs share this identity.
2. Configure an available model endpoint/API credential in LSM. The Python Agent provider engine is being migrated; the draft branch does not yet provide complete generation support.
3. Start a conversation after the Python Agent endpoints and SSE protocol pass the acceptance suite. Nested MCP, LSM tools and file uploads follow existing Controller permissions.
4. Start with a read-only request: “Check Controller status and list the workspace root. Do not modify files.”
5. Navigate to **Files**, **Terminals**, **Desktop**, **Sessions**, **Remotes** or **Audit** for direct inspection and control.

Las cargas de chat (hasta 32 MiB) se almacenan en el espacio de trabajo del Controlador y sus rutas absolutas se proporcionan al modelo. Las cargas del navegador no otorgan permisos de archivos adicionales. Las llamadas a herramientas orientadas al modelo pasan por la autorización LSM, la auditoría y el enrutador del trabajador remoto.

## MCP externo, seguridad y datos

Utilice la barra lateral de MCP del espacio de trabajo para administrar servidores MCP externos anidados. Esto admite servidores stdio locales y servidores HTTP, incluidas variables de entorno privadas independientes y encabezados de solicitud. Los secretos no se devuelven al navegador. La opción de chat **MCP externo** permite buscar, inspeccionar e invocar herramientas anidadas; no otorga el modelo `mcp_manage` cuando las herramientas LSM nativas están deshabilitadas. La gestión de la interfaz de usuario está protegida por la autorización normal del Controlador.

Chats, projects, Agents, sessions, audits and Worker metadata share `.local-shell-mcp/lsm.sqlite3`; SQLite FTS5 provides local search. Non-database artifacts remain under `.local-shell-mcp/`.

The workspace is a first-party React application, not an iframe or separately hosted Web service. Python Workers and external MCP clients remain compatible.

## Solución de problemas

- **Unable to start the WebUI:** check the Controller Python logs, SQLite initialization and bundled frontend archive. `LOCAL_SHELL_MCP_STATE_BACKEND=file` is an emergency storage recovery option.
- **Authentication fails:** use the existing Controller PIN/OAuth login. The React UI does not require a separate LibreChat account or bridge secret.
- **Chat loads but cannot answer:** the Python Agent generation and SSE port is still incomplete in this draft branch; do not deploy it to production.
- **Missing MCP tools:** check Controller authorization and the nested MCP registry; never expose `mcp_manage` to external-only model tools.
- **Files or sessions appear empty:** verify the Controller workspace, SQLite migration and authorized principal in its logs.

Para obtener detalles de implementación y actualizaciones, consulte [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md) y [human interface guide](../guides/human-interface.md).
