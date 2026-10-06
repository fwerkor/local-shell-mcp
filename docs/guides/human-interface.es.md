<!-- i18n-source-sha256: 5f07217e742810704f1919224f6cf68bf7b4f5ecf635fadd5ec4d21b072ce6b2 -->
# Interfaz humana

`local-shell-mcp` ofrece dos interfaces humanas compatibles sobre la misma API de servicio, workspace, registro de terminales persistentes, registro de workers remotos y log de auditoría MCP:

- **Web UI** es un panel nativo del navegador optimizado para inspección operativa rápida.
- **OpenTUI** es la aplicación completa orientada al terminal y sigue disponible tanto dentro del navegador como mediante un comando de terminal nativo.

Ningún modo crea un control plane separado. Cambiar de interfaz no modifica las máquinas conectadas, Sessions, jobs, permisos ni datos de auditoría.

## Iniciar el servicio

Inicie `local-shell-mcp` normalmente:

```bash
local-shell-mcp --mode mcp
```

## ChatGPT Live Workspace

Cuando ChatGPT renderiza MCP Apps, `workspace_open(session_id=...)` abre una vista colaborativa flotante de la **Logical Session seleccionada explícitamente**. La Session posee el estado durable de la tarea —objective, progress, Plan y Activity—, mientras que Live Workspace solo presenta ese estado, la actividad en vivo y los controles humanos. Nunca infiere la identidad de la tarea a partir del transporte MCP.

Un handoff explícito típico es:

```text
session_manage(action="start", objective=...)
        -> session_id
... llamadas de herramientas con logical_session_id=session_id
... session_manage(action="report", session_id=...) ...
nueva conversación de ChatGPT
el usuario pasa el session_id anterior
session_manage(action="resume", session_id=...)
        -> progress, Plan y Activity reciente existentes
workspace_open(session_id=...)
        -> vista de la misma Session
```

`session_id` es la única identidad durable de la tarea. Un agente no debe listar, inferir ni seleccionar automáticamente una Session de otra conversación. Para continuar el trabajo en una conversación nueva, el usuario pasa explícitamente el `session_id` existente. El agente debe informar el `session_id` activo después de start/resume, en checkpoints de progreso relevantes y antes de terminar un turn, para permitir el handoff manual. Las Sessions no están vinculadas a una machine ni a un working directory; los parámetros normales de las herramientas siguen eligiendo targets locales/remotos y paths.

Un Plan opcional de `plan_manage` habilita el Goal mode de la Session. Si el Plan está active y no hay agent activity durante 15 minutos, un Live Workspace asociado puede pedir a ChatGPT que continúe. La continuación reanuda el mismo `session_id` explícito y está limitada a 10 intentos, aceptados o rechazados. Los Plan blocked, completed y cancelled no continúan automáticamente; un Plan active cuyos steps estén todos completed o skipped sigue siendo elegible para una continuation de cierre para que el agente reanudado pueda terminar el Plan. Los controles humanos pause/resume/cancel actualizan el Plan propiedad de la Session, no un estado efímero del Live Workspace.

## Interfaz del navegador

Abra:

```text
http://127.0.0.1:8765/ui
```

Para un despliegue público, use el origin HTTPS configurado:

```text
https://your-public-host.example.com/ui
```

La interfaz del navegador usa el mismo servidor OAuth y los mismos scopes que MCP. El shell de la página y los recursos estáticos son públicos para que la pantalla de inicio de sesión pueda cargarse, mientras que `/api/ui/*` y el WebSocket de terminal de OpenTUI siguen protegidos. Los tokens de acceso se almacenan únicamente en el session storage del navegador.

### Elegir una interfaz

La pantalla OAuth ofrece dos entradas:

- **Open Web UI** autoriza y abre el panel nativo.
- **Continue to OpenTUI** autoriza y abre la interfaz de terminal, conservando el comportamiento anterior del navegador.

Tras la autorización, el selector de la barra lateral cambia entre Web UI y OpenTUI sin un nuevo inicio de sesión. La página nativa actual se recuerda al pasar temporalmente a OpenTUI.

Las rutas se pueden guardar como marcadores:

```text
/ui/#/overview
/ui/#/machines
/ui/#/workloads
/ui/#/activity
/ui/#/console
```

`#/web` y `#/dashboard` son alias de Overview. `#/tui` y `#/opentui` son alias de Console.

## Web UI nativa

La Web UI nativa consulta la API de interfaz humana existente cada cinco segundos y representa controles nativos del navegador en lugar de celdas de terminal. No inicia un PTY hasta que se selecciona OpenTUI.

### Overview

Overview muestra primero la información operativa de mayor prioridad:

- Salud del controller y versión actual de LSM.
- Recuento de máquinas en línea y fuera de línea.
- Tracked jobs activos y sesiones de terminal persistentes.
- CPU, memoria, disco del workspace, load, rendimiento de red y uptime.
- Alertas generadas a partir del estado de workers, umbrales de recursos, jobs fallidos y llamadas MCP fallidas.
- Actividad MCP reciente originada por el modelo.

### Machines

Machines enumera el controller local y los workers remotos conectados con estado, plataforma, versión, directorio de trabajo, capacidades e información de last-seen.

### Workloads

Workloads combina tracked jobs activos y sesiones shell persistentes independientes. La Web UI sigue siendo de solo lectura para estos registros; use OpenTUI para la gestión interactiva de sesiones.

### Activity

Activity combina las alertas actuales con la actividad de auditoría MCP reciente. Los comandos y operaciones de archivos introducidos por humanos quedan fuera del registro de auditoría MCP.

## OpenTUI en el navegador

Al seleccionar **OpenTUI** se inicia de forma diferida la misma aplicación OpenTUI usada por el lanzador de terminal nativo. La consola del navegador conserva:

- Transporte PTY binario autenticado mediante WebSocket.
- Redimensionado automático de terminal y backoff de reconexión.
- Interacción con ratón sobre los controles de OpenTUI.
- Modo de pantalla completa y atajos de teclado seguros para el navegador.
- Teclas rápidas para móvil y control explícito del teclado virtual.
- Compatibilidad con SIXEL e inline image mediante xterm.js.

El navegador no crea un PTY de OpenTUI mientras el usuario permanezca en el modo Web UI nativo.

## OpenTUI nativa

Los ejecutables release independientes incorporan el runtime OpenTUI de la plataforma. Conserve solo el ejecutable principal, inicie el servicio y ejecute:

```bash
local-shell-mcp tui
```

La TUI nativa no pide iniciar sesión al operador humano. En la configuración Docker Compose documentada, el lanzador reutiliza la credencial CLI dedicada que solo existe en el host para la API Human UI por loopback; otros diseños split-runtime pueden usar `--token-file`. Las instancias de OpenTUI iniciadas desde el navegador usan una credencial del proceso del controller que se crea de forma perezosa y nunca se persiste en el state directory ni en el state backend. Un proxy inverso no obtiene ninguno de estos bypass locales solo por conectarse desde loopback.

Un checkout del código fuente también puede ejecutar la TUI tras instalar las dependencias de Bun:

```bash
cd ui
bun install --frozen-lockfile
bun run build
cd ..
local-shell-mcp tui
```

Use `--api-base` solo cuando el servicio local utilice un puerto no predeterminado:

```bash
local-shell-mcp tui --api-base http://127.0.0.1:9876/api/ui
```

## Pantallas de OpenTUI

### Dashboard

Dashboard es el resumen operativo de OpenTUI. Los terminales anchos muestran regiones separadas para node, workload, alert, activity, información del sistema y tendencias; los terminales más estrechos las contraen en resúmenes compactos sin desplazamiento horizontal.

### Files

Files es un administrador de archivos nativo de LSM con tres paneles para máquinas locales y remotas. Permite crear, editar, renombrar, copiar, mover, pegar, eliminar, alternar archivos ocultos, refrescar, previsualizar texto, previsualizar binarios y mostrar miniaturas de imágenes acotadas.

### Terminals

Terminals gestiona sesiones shell persistentes en máquinas locales y remotas. Admite entrada de comandos completos, entrada interactiva raw, cambio de sesión, creación y terminación de sesiones, salida reciente y un panel de auditoría MCP plegable.

### Audit

Audit lee el registro de auditoría JSONL acotado y admite filtros por node, operation, event, session, search, time-range y sort, además de inspección de detalles de los registros.

### Remotes

Remotes muestra workers remotos en línea y fuera de línea, capacidades, directorios de trabajo y metadatos del sistema. Puede crear una invitación join de un solo uso, renombrar un node o revocar su identidad persistente.

## Navegación de OpenTUI

La barra superior de categorías y las acciones contextuales del pie pueden pulsarse con el ratón tanto en terminales nativos como en la consola del navegador.

| Teclas | Acción |
|---|---|
| `Alt+1` … `Alt+5` | Abre Dashboard, Files, Terminals, Remotes o Audit. |
| `F2` … `F6` | Atajos alternativos de categoría. |
| `F1` | Abrir la guía de teclado. |
| `F9` | Refrescar la lista de máquinas. |
| `Alt+Q` | Salir del proceso OpenTUI nativo sin invocar un atajo Ctrl reservado por el navegador. |

Terminals usa `Alt+N` para una sesión nueva, `Alt+W` para terminar la sesión seleccionada, `Alt+A` para alternar su panel de auditoría, `Alt+R` para refrescar y `Alt+Left/Right` para cambiar de sesión. La consola del navegador intercepta estas combinaciones antes que la navegación o los menús del navegador.

## Configuración

| Clave YAML | Variable de entorno | Predeterminado | Propósito |
|---|---|---|---|
| `ui_enabled` | `LOCAL_SHELL_MCP_UI_ENABLED` | `true` | Montar o desactivar las interfaces humanas. |
| `ui_path` | `LOCAL_SHELL_MCP_UI_PATH` | `/ui` | Ruta de montaje de la interfaz del navegador en el servicio MCP. |
| `ui_tui_command` | `LOCAL_SHELL_MCP_UI_TUI_COMMAND` | auto | Sobrescribir la resolución del ejecutable OpenTUI nativo. |
| `ui_wallpaper` | `LOCAL_SHELL_MCP_UI_WALLPAPER` | `bing` | Ajuste de fondo conservado para despliegues de la consola OpenTUI en navegador. |
| `ui_terminal_idle_timeout_s` | `LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S` | `3600` | Cerrar un PTY OpenTUI inactivo del navegador tras estos segundos; `0` desactiva el timeout. |
| `ui_terminal_max_sessions` | `LOCAL_SHELL_MCP_UI_TERMINAL_MAX_SESSIONS` | `8` | Máximo de sesiones PTY OpenTUI simultáneas en navegador. |

## Notas de empaquetado

- Las imágenes Docker incluyen los recursos Web UI y el runtime OpenTUI nativo.
- Los ejecutables independientes incorporan los recursos Web UI y un runtime OpenTUI de plataforma comprimido.
- Los wheels de Python incluyen los recursos del navegador; OpenTUI nativa requiere un ejecutable release o un checkout del código fuente con las dependencias de Bun instaladas.
- Ambas interfaces se sirven desde el mismo proceso y puerto que MCP; no se necesita un servicio web adicional.
