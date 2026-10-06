<!-- i18n-source-sha256: 931645b26427f12938872e36f9c9c3c5b45ff4697c5e3db8ae51d73bb10dc84c -->
# Runtime Docker Compose

Docker Compose es el runtime recomendado para la mayoría de usuarios. Da al modelo un workspace Linux controlado, un toolchain reproducible, credenciales persistentes, soporte de browser automation y una ruta de actualización sencilla.

Es una elección de runtime. Puede conectarse a ChatGPT, a un MCP client HTTP genérico o mantenerse local para pruebas.

## Qué incluye la imagen Docker

La imagen se basa en la imagen Python de Playwright e instala un toolchain de desarrollo amplio. La intención es que un AI coding agent pueda trabajar con muchos repositories sin pedir reconstruir el runtime para cada proyecto.

Categorías incluidas:

| Categoría | Ejemplos |
|---|---|
| Shell e inspección | Bash, curl, wget, jq, ripgrep, tree, tmux, patch, file |
| Git y credenciales | Git, GitHub CLI, OpenSSH client, credential persistence volume |
| C/C++ build | build-essential, clang, cmake, ninja, autoconf, automake, gdb, lldb |
| Python | Python, pip, venv, pipx, package development dependencies |
| JavaScript/TypeScript | Node.js, npm, yarn, pnpm, TypeScript, ts-node |
| Otros lenguajes | Go, Rust, Java, Ruby, PHP, Perl, Lua, R |
| Browser automation | Playwright browsers and browser dependencies |
| Herramientas de documentos | LibreOffice, Pandoc, Poppler utilities, OCR tooling |

El contenido exacto de la imagen es una capa de conveniencia, no una API estable. Las dependencias específicas del proyecto deben seguir en el workspace o en sus scripts de build.

## Ejecución local básica

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python -c 'from pathlib import Path; import hashlib,secrets; p=Path(".env"); s=p.read_text(); t=secrets.token_urlsafe(48); s=s.replace("LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN=", "LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN=" + t, 1).replace("LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN_SHA256=", "LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN_SHA256=" + hashlib.sha256(t.encode()).hexdigest(), 1); p.write_text(s)'
chmod 600 .env
mkdir -p workspaces/default
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

El token CLI original permanece únicamente en el `.env` propiedad del host (modo `0600`). Compose solo pasa al contenedor su verificador SHA-256. Así, `lsm call` puede autenticarse a través del puente del puerto publicado de Docker sin exponer un token privilegiado reutilizable a los procesos shell administrados dentro del contenedor.

El Compose file predeterminado enlaza el servicio a localhost:

```text
127.0.0.1:8765 -> container:8765
```

Esto es apropiado para pruebas locales y para un reverse proxy que corra en el mismo host.

## Layout del workspace

El runtime Compose predeterminado monta:

| Path o volumen host | Path container | Propósito |
|---|---|---|
| `./workspaces/default` | `/workspace` | Workspace controlado visible para tools |
| `local-shell-mcp-credentials` volume | `/persist/credentials` | Estado persistente de credenciales Git/GitHub/SSH/GPG |

Use un directorio de workspace por trust boundary. No monte todo su home directory solo por comodidad.

## Ajustes públicos requeridos

Para ChatGPT u otro MCP client HTTP público, configure `.env`:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

Genere un JWT secret con un comando como:

```bash
openssl rand -hex 32
```

La URL MCP pública es:

```text
https://your-public-host.example.com/mcp
```

## Cloudflare Tunnel sidecar

El Compose file incluye un servicio `cloudflared` opcional detrás del profile `tunnel`. Ejecuta el tunnel junto al MCP server.

Configure `.env`:

```env
CLOUDFLARE_TUNNEL_TOKEN=<token from Cloudflare Tunnel>
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=<strong pin>
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=<strong random secret>
```

Inicie ambos servicios:

```bash
docker compose --profile tunnel up -d
```

En Cloudflare Zero Trust, enrute el public hostname a:

```text
http://local-shell-mcp:8765
```

Esto es Cloudflare Tunnel, no Cloudflare Access. `local-shell-mcp` sigue gestionando su propio OAuth para ChatGPT.
El servicio Compose confía en forwarded headers porque su puerto publicado está restringido a localhost; así conserva la dirección pública del caller para el rate limiting del OAuth PIN. Si expone directamente el puerto del container, sustituya `LOCAL_SHELL_MCP_FORWARDED_ALLOW_IPS=*` por las direcciones explícitas de sus reverse proxies de confianza.

## Reverse proxy sin tunnel sidecar

Si ya usa Caddy, Nginx, Traefik o Nginx Proxy Manager, mantenga el servicio Compose normal y reenvíe HTTPS a:

```text
http://127.0.0.1:8765
```

El proxy debe reenviar estas rutas sin eliminar paths:

| Ruta | Propósito |
|---|---|
| `/mcp` | MCP streamable HTTP endpoint |
| `/healthz`, `/readyz` | Health checks |
| `/.well-known/oauth-protected-resource` | Metadata de recurso OAuth |
| `/.well-known/oauth-authorization-server` | Metadata de servidor de autorización OAuth |
| `/oauth/register` | Registro dinámico de client |
| `/oauth/authorize` | Página de autorización del navegador |
| `/oauth/token` | Intercambio de token |
| `/downloads/<token>` | Descargas opcionales de archivos generados |
| `/join/<token>`, `/remote/*` | Bootstrap/polling opcional de remote worker |

Consulte [network connectivity](../clients/connectivity.md) para los requisitos de comportamiento del proxy.

## Modo full-container

`LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=false` mantiene las operaciones de filesystem limitadas al workspace. Es el default más seguro.

Póngalo en `true` solo cuando el container sea deliberadamente desechable y se espere que el modelo opere todo su filesystem. Al activarlo se eliminan las restricciones built-in de command y path denylist.

```env
LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true
```

No active full-container mode en un runtime lanzado directamente en el host, como VS Code extension o un binary en su portátil.

## Credenciales

El runtime Docker puede persistir credenciales comunes de desarrollo en un volumen dedicado. Es útil para login de GitHub CLI, Git HTTPS credential helpers, `.netrc`, SSH config y estado GPG.

Trate el volumen de credenciales como sensible. Prefiera deploy keys por repository, tokens fine-grained o credenciales de corta duración. No ponga credenciales personales amplias en un workspace que el modelo pueda leer libremente.

Es posible hacer SSH-agent forwarding montando el socket del agente, pero extiende la confianza del container a su agente activo. Úselo solo si entiende la exposición.

## Actualizaciones

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

Con tunnel sidecar:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
curl -i http://127.0.0.1:8765/healthz
```

Después de actualizar, pida al client un check read-only primero:

```text
Usa local-shell-mcp. Llama a environment_get y ejecuta file_list sobre la raíz del workspace. No modifiques archivos.
```

## Solución de problemas

| Síntoma | Comprobar |
|---|---|
| `/healthz` falla localmente | `docker compose ps`, `docker compose logs --tail=200 local-shell-mcp` |
| ChatGPT no descubre tools | La URL pública debe terminar en `/mcp`; `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` no debe incluir `/mcp` |
| Falla la página OAuth | Admin PIN y JWT secret deben estar definidos en deployments OAuth públicos |
| Tools no ven archivos | Confirme que el directorio host previsto está montado en `/workspace` |
| Falla browser tools | Confirme que la imagen Playwright está actualizada; pruebe `run_shell` para el browser objetivo |
| Desapareció Git auth | Compruebe el volumen de credenciales y que el container recreado usa el mismo volumen |
