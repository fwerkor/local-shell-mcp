<!-- i18n-source-sha256: a9820f08198cf8e823f59550928c07346f9669f2dbec46d3b8cd523c34034e01 -->
# Inicio rápido

Esta guía inicia un controlador LSM y abre su interfaz de navegador. El [unified web workspace](web-workspace.md) es la experiencia diaria recomendada; es una pila de chat opcional implementada por separado. ChatGPT, Gemini y otros clientes MCP externos pueden conectarse al mismo controlador. Ver [runtime choices and deployment model](../guides/deployment.md).

## Requisitos

- Docker Engine con Compose v2.
- Un punto final HTTPS público si deben conectarse usuarios remotos o clientes MCP externos.
- Un directorio de workspace dedicado.
- Un OAuth admin PIN y JWT secret largos y aleatorios.

!!! warning
    El modelo conectado puede operar el workspace configurado. Ejecute el servicio en un container o VM desechable y evite montar recursos de control del host.

## 1. Clonar y configurar

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python scripts/init_compose_env.py
```

Edite `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. Iniciar el servidor

```bash
mkdir -p workspaces/default
docker compose up -d
```

Compruebe el estado:

```bash
docker compose ps
docker compose logs --tail=100 local-shell-mcp
curl -i http://127.0.0.1:8765/healthz
```

Una respuesta sana devuelve HTTP `200`.

## 3. Exponer HTTPS

**Recomendado:** Para el acceso público, usa un servidor público o reenvía el tráfico a través de uno con un proxy inverso HTTPS.

**No recomendado:** Las subidas del cliente por Cloudflare Tunnel pueden ser muy lentas, lo que dificulta el uso de las funciones de carga y transferencia de archivos. Úsalo solo si no es viable desplegar o reenviar mediante un servidor público. Configure `CLOUDFLARE_TUNNEL_TOKEN` in `.env` only when choosing the optional tunnel sidecar.

Para el sidecar de Cloudflare Tunnel:

```bash
docker compose --profile tunnel up -d
```

En Cloudflare Zero Trust, apunte el public hostname a:

```text
http://local-shell-mcp:8765
```

Con Caddy, Nginx, Traefik, Nginx Proxy Manager u otro reverse proxy, reenvíe el tráfico HTTPS a `127.0.0.1:8765` o a la dirección de red del container.

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

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Si usa el perfil tunnel:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
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
