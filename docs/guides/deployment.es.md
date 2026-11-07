<!-- i18n-source-sha256: d7d01bc3f36f434c8e66c3fb6f65c2934937c5b2937dd9e8ba7beefc018fd14f -->
# Opciones de runtime y modelo de despliegue

`local-shell-mcp` tiene dos decisiones complementarias:

1. **Runtime**: cómo se ejecuta el proceso del servidor y qué workspace controla.
2. **Interfaz**: utilice el [unified web workspace](../getting-started/web-workspace.md) opcional o conecte un cliente MCP externo como Gemini o ChatGPT.

La interfaz diaria recomendada es el espacio de trabajo web autohospedado (chat, proyectos y páginas de control de LSM). Se implementa por separado del Controlador. Docker, la extensión VS Code, los binarios de lanzamiento, las instalaciones de Python y el modo stdio son formas de ejecutar el controlador; Las aplicaciones de chat externas siguen siendo clientes opcionales.

```text
Runtime layer                      Exposure layer                 Client layer
-------------------------------    ---------------------------    ----------------------
Docker Compose solo HTTP local Espacio de trabajo web unificado
VS Code extension                  HTTPS reverse proxy/tunnel     Generic MCP client
Standalone binary                  stdio process pipe             VS Code extension UI
pipx / source checkout             remote-worker outbound join    REST-style diagnostics
```

Una configuración autohospedada común es:

```text
Navegador -> https://chat.example.com (espacio de trabajo web unificado)
        -> Controlador local-shell-mcp autenticado
        -> espacio de trabajo controlado y trabajadores salientes
Cliente externo opcional -> https://mcp.example.com/mcp
```

Una configuración con MCP client local puede ser más simple:

```text
Local MCP client
  -> starts local-shell-mcp --mode stdio
  -> controlled workspace
```

**Recomendado:** Para el acceso público, usa un servidor público o reenvía el tráfico a través de uno con un proxy inverso HTTPS. **No recomendado:** Las subidas del cliente por Cloudflare Tunnel pueden ser muy lentas, lo que dificulta el uso de las funciones de carga y transferencia de archivos. Úsalo solo si no es viable desplegar o reenviar mediante un servidor público. ([Public HTTPS exposure](../clients/connectivity.md))

## Matriz de elección de runtime

| Tiempo de ejecución | Lo mejor para | Límite de aislamiento | Fuente de la cadena de herramientas | Acceso MCP externo | Página |
|---|---|---|---|---|---|
| **Código fuente (recomendado)** / `pipx` | Uso Python-native, debugging y desarrollo | Host virtualenv or VM | Paquete Python más herramientas host | Añadir proxy HTTPS o tunnel | [Python install](../installation/python.md) |
| Composición acoplable | Contenedores aislados y desechables | Contenedor | Imagen del controlador Lean; instalar cadenas de herramientas específicas de tareas por separado | Agregar proxy o túnel HTTPS | [Docker Compose](../installation/docker.md) |
| Docker Compose + sidecar de túnel | No recomendado: Reenviar mediante servidor público; Cloudflare Tunnel solo como último recurso | Contenedor | Imagen del proyecto | Reenviar mediante servidor público; Cloudflare Tunnel solo como último recurso | [Docker Compose](../installation/docker.md#cloudflare-tunnel-sidecar) |
| VS Code extension | Iniciar/detener server desde un workspace de editor | Normalmente proceso host | Herramientas host más executable configurado | Añadir tunnel/proxy HTTPS externo para ChatGPT | [VS Code extension](../installation/vscode-extension.md) |
| Standalone binary | Hosts o VM sin Docker | Host or VM | Herramientas host más executable configurado | Añadir proxy HTTPS o tunnel | [Standalone binary](../installation/binary.md) |
| Stdio mode | MCP clients locales que crean procesos directamente | Client process boundary | Herramientas host más executable configurado | No usable por ChatGPT web/app | [Stdio mode](../installation/stdio.md) |

## Matriz de conexión de client

| Interfaz | Requiere HTTPS público | Utiliza `/mcp` | Requiere OAuth | Tiempo de ejecución típico |
|---|---:|---:|---:|---|
| Espacio de trabajo web unificado de LSM | Sí para acceso remoto; proxy local también es posible | Internamente | iniciar sesión LSM | Controlador más pila web separada |
| Gemini Spark / Aplicaciones personalizadas | si | si | Si para uso publico | Cualquier controlador HTTP |
| ChatGPT custom MCP connector | Sí | Sí | Sí para uso público | Docker, VS Code extension, binary, or Python |
| Generic local MCP client over stdio | No | No | No | `local-shell-mcp --mode stdio` |
| Generic HTTP MCP client | Normalmente no en localhost; sí entre redes | Sí | Recomendado fuera de localhost | Any HTTP runtime |
| VS Code extension helper flow | Solo si ChatGPT debe conectar | Sí al copiar URL de ChatGPT | Recomendado para ChatGPT | VS Code-launched runtime |

Consulte [unified web workspace](../getting-started/web-workspace.md), [Gemini Spark](../getting-started/gemini-spark.md), [ChatGPT connector](../getting-started/chatgpt-connector.md), [generic MCP clients](../clients/generic-mcp.md) y [network connectivity](../clients/connectivity.md).

## Qué controla cada runtime

Todos los runtimes inician el mismo código de servidor y exponen las mismas familias de MCP tools cuando están habilitadas:

- Shell y persistent shell sessions.
- Filesystem, search y patch tools.
- Operaciones Git.
- Browser automation mediante Playwright.
- Audit log y task-state tools.
- Tokenized file links.
- Optional remote-worker lifecycle y machine-routed tools.

La diferencia no es la API abstracta, sino el **operating environment** detrás de ella.

| Pregunta | Docker Compose | VS Code extension | Binary / Python |
|---|---|---|---|
| ¿Dónde se ejecutan comandos? | Dentro del container | Normalmente en workspace host | En entorno de proceso host o VM |
| ¿Workspace predeterminado? | Mounted `/workspace` | Carpeta VS Code actual o path configurado | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` |
| ¿Están preinstalados los compiladores y navegadores? | No; instalar lo que necesita la tarea | Sólo si está instalado en el host | Sólo si está instalado en el host |
| ¿Es fácil resetear? | Recrear container y volumen workspace | Depende del workspace | Depende del host/VM |
| ¿Adecuado para installs arbitrarios? | Sí si es desechable | Más arriesgado en host | Más arriesgado fuera de VM |

## Selección recomendada

Se recomienda **desplegar directamente desde el código fuente** en un entorno aislado; consulte la [guía de Python/fuentes](../installation/python.md). Docker Compose es una alternativa.

Utilice la **extensión VS Code** cuando el flujo de trabajo comience desde un editor y desee un iniciador local. Todavía es un tiempo de ejecución. Los clientes web remotos necesitan un túnel o proxy HTTPS accesible.

Use **standalone binary** cuando Docker no esté disponible pero una VM, container host o cuenta dedicada ya proporcione el límite.

Use **`pipx` o source install** para desarrollo y debugging de `local-shell-mcp`, o si un entorno Python es más fácil de mantener.

Use **stdio mode** solo para MCP clients locales que puedan crear el proceso servidor. No es despliegue público ni es usable directamente desde ChatGPT web/app.

## Regla del endpoint público

Para clientes HTTP MCP externos como Gemini y ChatGPT, el punto final MCP es:

```text
https://your-public-host.example.com/mcp
```

`LOCAL_SHELL_MCP_PUBLIC_BASE_URL` contiene solo el origin:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

No añada `/mcp` a `LOCAL_SHELL_MCP_PUBLIC_BASE_URL`.

## Páginas de runtime

- [Docker Compose](../installation/docker.md)
- [VS Code extension](../installation/vscode-extension.md)
- [Standalone binary](../installation/binary.md)
- [Python, `pipx`, and source install](../installation/python.md)
- [Stdio mode](../installation/stdio.md)

## Páginas de client

- [Unified web workspace](../getting-started/web-workspace.md)
- [Gemini Spark / Custom Apps](../getting-started/gemini-spark.md)
- [ChatGPT connector](../getting-started/chatgpt-connector.md)
- [Generic MCP clients](../clients/generic-mcp.md)
- [Public HTTPS exposure](../clients/connectivity.md)
