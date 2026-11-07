<!-- i18n-source-sha256: 3575b9b50708261678473f74b66076f0c14807ccd7f7c3e60b4d1e897ac778df -->
# Inicio rápido

Esta guía inicia un controlador LSM y abre su interfaz de navegador. El [unified web workspace](web-workspace.md) es la experiencia diaria recomendada; es una pila de chat opcional implementada por separado. ChatGPT, Gemini y otros clientes MCP externos pueden conectarse al mismo controlador. Ver [runtime choices and deployment model](../guides/deployment.md).

Se recomienda **desplegar directamente desde el código fuente** en un entorno aislado. Docker Compose es una alternativa.

## Requisitos

- Git y Python 3.11+ con `venv` y `pip`.
- HTTPS público solo si acceden usuarios remotos o clientes MCP externos.
- Un directorio de trabajo dedicado y limitado.
- PIN de administrador OAuth fuerte y secreto JWT aleatorio.

!!! warning
    El modelo conectado puede operar el workspace configurado. Ejecute el servicio en un container o VM desechable y evite montar recursos de control del host.

## 1. Clonar y configurar

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
cp .env.example .env
chmod 600 .env
openssl rand -hex 32
```

Edite `.env` y sustituya el PIN y el secreto JWT de ejemplo (use `openssl rand -hex 32`). La ejecución desde el código fuente no carga `.env` automáticamente.

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. Iniciar el servidor

```bash
mkdir -p workspaces/default
set -a
. ./.env
set +a
. .venv/bin/activate
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspaces/default"
local-shell-mcp --mode mcp
```

Compruebe el estado desde otra terminal:

```bash
curl -i http://127.0.0.1:8765/healthz
```

La respuesta correcta es HTTP `200`. Mantenga el proceso activo o use un gestor de servicios.

## 3. Exponer HTTPS

Para acceso remoto, use un servidor público o un proxy inverso HTTPS (Caddy, Nginx o Traefik) y reenvíe todo el origen, incluidas las transferencias, a:

```text
http://127.0.0.1:8765
```

Compruebe el acceso HTTPS:

```bash
curl -i https://your-public-host.example.com/healthz
```

**No se recomienda Cloudflare Tunnel** para transferir archivos: las cargas desde el cliente pueden ser lentas. Prefiera un servidor público o proxy inverso/redirección de puertos. Mantenga OAuth en endpoints públicos. Alternativa: [Docker](../installation/docker.md).

## 4. Abra el espacio de trabajo del navegador.

Abra el inicio de sesión del Controlador:

```text
https://tu-host-público.example.com/ui
```

Para chat, proyectos y páginas de control integrado, siga [unified web workspace guide](web-workspace.md). La WebUI ligera original está disponible cuando el chat no está instalado.

## 5. Confirmar de forma segura el acceso a herramientas

Pida al modelo:

```text
Usa local-shell-mcp. Primero llama a environment_get y después enumera la raíz del workspace. No modifiques archivos todavía.
```

Herramientas de solo lectura esperadas:

- `environment_get`
- `file_list`
- `file_tree`
- `file_read`

## 6. Empezar con una tarea de programación acotada

Una buena primera tarea:

```text
Inspecciona este repository, resume la estructura del proyecto, ejecuta la suite de tests existente si es evidente y no cambies archivos.
```

Una vez confirmada la conectividad, dé instrucciones más específicas:

```text
Corrige el test que falla. Lee primero los archivos relevantes, haz el patch más pequeño, ejecuta el test objetivo y después muestra git diff. No hagas commit hasta que lo apruebe.
```

## Actualización

Actualice el código, reinstale el paquete editable y reinicie el Controller:

```bash
git pull --ff-only
python -m pip install -e .
# Restart the Controller process or service after updating.
curl -i http://127.0.0.1:8765/healthz
```

Si usa Docker Compose, actualice los contenedores:

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

## Páginas siguientes

| Necesidad | Página |
|---|---|
| Entender las opciones de runtime y client | [Opciones de runtime y modelo de despliegue](../guides/deployment.md) |
| Ejecutar con Docker Compose | [Docker Compose runtime](../installation/docker.md) |
| Ejecutar desde VS Code | [VS Code extension runtime](../installation/vscode-extension.md) |
| Ejecutar con un binary de release | [Runtime binary independiente](../installation/binary.md) |
| Ejecutar con Python o source checkout | [Python runtimes](../installation/python.md) |
| Utilice la interfaz unificada de chat y control | [Unified web workspace](web-workspace.md) |
| Añade Gemini Spark como cliente | [Gemini Custom Apps](gemini-spark.md) |
| Añadir ChatGPT como client | [ChatGPT connector](chatgpt-connector.md) |
| Elegir herramientas y escribir mejores prompts | [Patrones de uso](../guides/usage-patterns.md) |
| Conectar una máquina HPC, NPU/GPU o NAT | [Workers remotos](../guides/remote-workers.md) |
| Entender todas las herramientas MCP | [Referencia de herramientas](../reference/tools.md) |
