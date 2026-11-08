<!-- i18n-source-sha256: b6bf2276867332a25b6e63b3b4cf21045262a9a9535422c02722906d87a2132a -->
# Inicio rápido

Esta guía inicia un controlador LSM y abre su interfaz de navegador. El [unified web workspace](web-workspace.md) es la experiencia diaria recomendada; es una pila de chat opcional implementada por separado. ChatGPT, Gemini y otros clientes MCP externos pueden conectarse al mismo controlador. Ver [runtime choices and deployment model](../guides/deployment.md).

Se recomienda el **ejecutable único del Controller** de [GitHub Releases](https://github.com/fwerkor/local-shell-mcp/releases/latest), sin Python, Docker ni repositorio fuente. Este ejemplo es para **Linux x86_64**; otras plataformas: [binarios](../installation/binary.md).

## Requisitos

- Ejecutable compatible y `curl` (ejemplo Linux x86_64).
- HTTPS público solo para usuarios remotos o clientes MCP externos.
- Workspace dedicado y restringido.
- PIN de administrador OAuth robusto y secreto JWT aleatorio.

!!! warning
    El modelo conectado puede operar el workspace configurado. Ejecute el servicio en un container o VM desechable y evite montar recursos de control del host.

## 1. Descargar el ejecutable y configurar

Descargue el ejecutable y genere un secreto JWT:

```bash
mkdir -p ~/lsm && cd ~/lsm
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp
chmod +x local-shell-mcp
./local-shell-mcp --help
openssl rand -hex 32
```

Cree `.env` y sustituya el PIN y el JWT de ejemplo (use `openssl rand -hex 32`). El binario **no carga automáticamente** `.env`.

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. Iniciar el servidor

Ejecute directamente el binario descargado:

```bash
chmod 600 .env
set -a
. ./.env
set +a
mkdir -p workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspace"
./local-shell-mcp --mode mcp
```

Compruebe el estado en otra terminal:

```bash
curl -i http://127.0.0.1:8765/healthz
```

La respuesta correcta es HTTP `200`. Para ejecución continua use un gestor de servicios y cuenta limitada.

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

Sustituya el ejecutable y reinicie el Controller:

```bash
# Stop the running Controller before replacing the executable.
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp.new
chmod +x local-shell-mcp.new
./local-shell-mcp.new --version
mv local-shell-mcp.new local-shell-mcp
# Restart the Controller process or service.
curl -i http://127.0.0.1:8765/healthz
```

Si usa Docker Compose, actualice el contenedor. Fuentes: [guía Python](../installation/python.md).

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
