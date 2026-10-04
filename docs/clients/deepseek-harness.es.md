<!-- i18n-source-sha256: 9deaf97f0af15e7af335b40fcf9fe8bc468623d1947e6f8c9afaf7dfaebcc036 -->
# DeepSeek Harness (DSH)

`local-shell-mcp` puede instalarse directamente en un perfil Web de DeepSeek Harness. El repository incluye un bridge consciente de DSH que conserva toda la superficie de herramientas LSM, asigna cada DSH Session a una identidad lógica v4 estable y aporta **Live Workspace** como vista nativa de conversación DSH. LSM sigue siendo la autoridad del estado de ejecución: máquinas locales/remotas, Sessions lógicas y Goal Plans, terminales persistentes, jobs, browser sessions, Dynamic MCP, file links, auditoría y timeline de Live Workspace permanecen en el controller LSM.

## Topología recomendada

Se recomienda ejecutar DSH y LSM directamente en la misma máquina. Cada DSH Session usa su propia conexión MCP a LSM y por defecto conecta a `127.0.0.1:8765/mcp`.

```text
DSH Web
  |
  | one LSM MCP connection per DSH Session
  | 127.0.0.1:8765/mcp
  v
local-shell-mcp :8765
  |-- local execution = this LSM host
  |-- /mcp
  |-- /remote/*
  |-- /ui
  |-- Live Workspace / audit / browser / jobs / links
  |
  +--> Remote Workers
```

En esta topología, la máquina que ejecuta LSM es el target `local` de LSM. Si LSM corre dentro de un contenedor, `local` significa ese contenedor y no automáticamente el host DSH. LSM escucha en `0.0.0.0:8765` por defecto y el bundle DSH usa loopback; con red, firewall, public URL y autenticación correctos, el mismo controller puede servir también a Remote Workers y otros clientes externos.

## Instalación

Inicie LSM primero:

```bash
local-shell-mcp --mode mcp
```

Luego instale el paquete npm dedicado de DSH en el perfil Web de DSH:

```bash
dsh plugin --profile web add local-shell-mcp-dsh
```

El paquete npm de DSH usa la misma versión de lanzamiento que LSM. Para desarrollo desde un checkout, instale el directorio actual:

```bash
dsh plugin --profile web add .
```

El bundle carga `local-shell-mcp-dsh` desde `cordis.patch.yml`. DSH recibe las herramientas LSM orientadas al modelo bajo el namespace MCP normal, por ejemplo:

```text
mcp__lsm__run_shell
mcp__lsm__file_read
mcp__lsm__remote_manage
mcp__lsm__remote_transfer
mcp__lsm__browser_session
mcp__lsm__mcp_tool_search
mcp__lsm__session_manage
mcp__lsm__plan_manage
...
```

El bridge conserva deliberadamente todo el catálogo LSM, incluidas las capacidades Remote Worker. La herramienta interna app-only `live_workspace_reconnect` es solo para el bridge y no se expone al modelo. Si se quiere un tool set menor, aplique después una política DSH `ctx.tools.restrict()` en vez de eliminar capacidades del bundle LSM.

## Vinculación entre DSH Session y LSM logical Session

La integración usa el runtime v4 de sesiones lógicas. Cada DSH Session obtiene su propio cliente MCP Streamable HTTP upstream y el bridge envía un valor de session-affinity opaco y determinista derivado del id de la DSH Session, formando esta cadena estable de identidad:

```text
DSH Session A
  -> stable LSM session affinity A
  -> v4 MCP session key A
  -> LSM logical Session / active run A
  -> Live Workspace A

DSH Session B
  -> stable LSM session affinity B
  -> v4 MCP session key B
  -> LSM logical Session / active run B
  -> Live Workspace B
```

La actividad de herramientas de conversaciones DSH distintas no se mezcla en un mismo timeline de Live Workspace. Tras reiniciar DSH, el transporte MCP se recrea con la misma affinity, por lo que la Session lógica y el active run existentes siguen adjuntos mientras el controller LSM conserve esa Session. El bridge también hace ping periódico a los clientes MCP activos para que el cleanup normal por idle de LSM no rompa conversaciones largas.

## Live Workspace dentro de DSH

El plugin de navegador DSH añade **Live Workspace** a `conversation.view` y reutiliza la implementación v4 existente, sin crear otro modelo UI/state. La vista queda limitada a la DSH Session actual y muestra la Session lógica LSM correspondiente, Plan/Goal state, Activity, terminales, archivos, diff, jobs, remotes y audit. **Ask** y la continuación automática Goal vuelven a la misma conversación DSH. El DSH host obtiene las credenciales Live Workspace server-side mediante la conexión MCP propia de esa Session; no aparecen en la conversación ni en tool results visibles al modelo.

## Por qué HTTP en vez de stdio

Remote Workers necesita más que MCP tools: las rutas HTTP `/remote/*` del controller gestionan registro, polling, heartbeats, entrega de resultados y transfer traffic. Un child process solo stdio no conservaría ese service plane y crearía otro dominio de estado del controller. Usar el servicio HTTP LSM ya activo mantiene una sola autoridad para Remote Workers, browser state, jobs, Dynamic MCP, auditoría, file links, logical Sessions y Live Workspace.

## Configuración

El bridge DSH Host acepta estas variables de entorno:

| Variable | Default | Propósito |
|---|---|---|
| `DSH_LSM_MCP_URL` | `http://127.0.0.1:8765/mcp` | Endpoint LSM Streamable HTTP MCP usado por DSH. |
| `DSH_LSM_AUTHORIZATION` | unset | Valor completo opcional del header `Authorization`, por ejemplo `Bearer ...`. |
| `DSH_LSM_TOOL_CALL_TIMEOUT_MS` | `120000` | Timeout por tool call en milisegundos. |
| `DSH_LSM_KEEPALIVE_INTERVAL_MS` | `30000` | Intervalo de ping para conservar identidad MCP per-Session de larga duración; mínimo 5000 ms. |
| `DSH_LSM_BROWSER_URL` | unset | Origen LSM accesible desde el navegador cuando difiere del origen MCP visto por Host. |

Los deployments same-host normalmente no necesitan authorization header porque el bypass de auth localhost de LSM está activo por defecto. No exponga un servicio LSM sin autenticación a una red pública. Para un controller LSM remoto protegido, configure endpoint y bearer token:

```bash
export DSH_LSM_MCP_URL='https://lsm.example.com/mcp'
export DSH_LSM_AUTHORIZATION='Bearer <token>'
dsh --profile web
```

El bridge envía headers upstream fijos; no ejecuta un flujo OAuth interactivo de autorización/refresh en nombre de DSH.

### Navegadores DSH Web remotos

`DSH_LSM_MCP_URL` lo resuelve el proceso **Host** de DSH, pero las llamadas API de Live Workspace ocurren en el navegador del usuario. Si DSH está alojado remotamente y la URL loopback devuelta por LSM no es alcanzable desde ese navegador, configure un origen LSM accesible:

```bash
export DSH_LSM_BROWSER_URL='https://lsm.example.com'
```

El token de Live Workspace sigue autorizando esas llamadas API del navegador.

## Remote Workers

Remote Worker mode permanece disponible mediante DSH. `mcp__lsm__remote_manage`, `mcp__lsm__remote_transfer` y las herramientas LSM ordinarias con argumento `machine` usan el mismo controller y estado remote-worker que otros clientes LSM. Si workers conectan desde fuera del host del controller, configure public URL y exposición de red de LSM como siempre; DSH puede seguir usando `127.0.0.1:8765/mcp`.

## Lifecycle y comportamiento ante fallos

El bundle no lanza otro proceso LSM. Puede iniciar cuando LSM no está disponible: la conexión de catálogo reconecta con backoff y sincroniza herramientas cuando LSM aparece. Las tool calls del modelo no se replay automáticamente tras un fallo de transporte ambiguo, porque una llamada mutante podría ejecutarse dos veces. La affinity estable y keepalive manejan recreación normal del transporte e idle; reemplazar realmente el controller LSM sigue las reglas normales de recuperación durable de Sessions. Quitar el plugin solo elimina la integración DSH-side:

```bash
dsh plugin --profile web remove local-shell-mcp-dsh
```

No detiene LSM.

## Verificar la instalación

Inspeccione el perfil DSH compuesto:

```bash
dsh --profile web --dump-config
```

La salida debe incluir una fila similar a `id: local-shell-mcp`, `name: local-shell-mcp-dsh`, `url: http://127.0.0.1:8765/mcp`. Con LSM online, DSH debe exponer herramientas `mcp__lsm__*` como:

```text
id: local-shell-mcp
name: local-shell-mcp-dsh
url: http://127.0.0.1:8765/mcp
```

Cuando LSM esté online, DSH debe exponer, entre otras, estas herramientas `mcp__lsm__*`:

```text
mcp__lsm__run_shell
mcp__lsm__remote_manage
mcp__lsm__remote_transfer
mcp__lsm__browser_session
mcp__lsm__session_manage
```

En DSH Web, una conversación no vacía también expone la vista **Live Workspace**. Si falta la integración, revise `DSH_LSM_MCP_URL`, `/healthz` de LSM, reachability de `/mcp`, el log de DSH Host y, si solo falla la UI embebida, `DSH_LSM_BROWSER_URL`.
