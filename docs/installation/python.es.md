<!-- i18n-source-sha256: 1d80cfbe14747fb0691e91065f582d1e47eb36921d8b27da1648dcd26114a2e5 -->
# Runtimes Python, pipx y source

Se recomienda el [binario de archivo único](binary.md) para despliegues normales. Python y fuentes quedan para desarrollo y personalización.

Use esta página para tres casos relacionados:

- `pipx install local-shell-mcp`: instalación de executable a nivel de usuario.
- `pip install local-shell-mcp`: instalación en un virtual environment existente.
- Editable source checkout: desarrollar o depurar el propio proyecto.

## Instalación con pipx

`pipx` es la instalación basada en Python más limpia para usuarios normales porque da al comando su propio virtual environment y expone a la vez un executable en `PATH`.

```bash
pipx install local-shell-mcp
local-shell-mcp --help
```

Inicie un servidor MCP HTTP local:

```bash
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
local-shell-mcp --mode mcp
```

Compruebe el estado:

```bash
curl -i http://127.0.0.1:8765/healthz
```

## Instalación en virtual environment

Úsela cuando ya gestione manualmente sus entornos Python:

```bash
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install local-shell-mcp
local-shell-mcp --mode mcp
```

El proceso usa las herramientas instaladas en el host. El paquete Python no instala por usted compiladores, Git, dependencias de sistema del navegador ni dependencias del proyecto.

## Editable source checkout

La instalación desde fuentes sirve para desarrollo; para uso normal elija el [binario](binary.md). OAuth y HTTPS: [inicio rápido](../getting-started/quickstart.md).

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e .
cp .env.example .env
# Replace the example OAuth secrets in .env before starting.
set -a
. ./.env
set +a
mkdir -p workspaces/default
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspaces/default"
local-shell-mcp --mode mcp
```

Ejecute las comprobaciones:

```bash
python -m pip install -e '.[dev,docs]'
ruff check .
pytest -q
mkdocs build --strict
```

## Configuración del navegador

Playwright es opcional; instale la biblioteca y el navegador solo si los necesita.

```bash
python -m pip install -e '.[browser]'
python -m playwright install chromium
```

La instalación del navegador es opcional; la imagen Docker básica no incluye Playwright ni navegadores.

## Uso público de HTTP MCP

Para ChatGPT u otro public HTTP MCP client, configure el mismo public origin y OAuth que en otros runtimes HTTP y exponga el puerto local mediante un reverse proxy o tunnel.

El endpoint MCP público es:

```text
https://your-public-host.example.com/mcp
```

## Modos de desarrollo

| Mode | Command | Uso |
|---|---|---|
| MCP HTTP | `local-shell-mcp --mode mcp` | MCP clients completos por HTTP, incluido ChatGPT detrás de HTTPS |
| REST-style HTTP | `local-shell-mcp --mode http` | Endpoints de diagnóstico o compatibilidad, no la ruta principal de ChatGPT |
| stdio | `local-shell-mcp --mode stdio` | MCP clients locales que inician el proceso |

`mode=both` está reservado y actualmente no debe usarse como modo de un único process.

## Seguridad del host runtime

Las instalaciones Python se ejecutan como su usuario del host salvo que las coloque en una VM o container. Mantenga el workspace limitado, full-container mode desactivado y no apunte el workspace a un home directory.

Use Docker Compose para repositories no confiables, tareas intensivas en package manager o workflows donde la capacidad de reset sea más importante que la integración con el host.
