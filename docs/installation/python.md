# Python, pipx, and source runtimes

**The standalone single-file binary is recommended for normal Controller deployment**; see the [binary installation guide](binary.md). Python and source runtimes remain available for development, debugging, customization, and environments that prefer package management. They run the same Controller.

Use this page for three related cases:

- `pipx install local-shell-mcp`: user-level executable install.
- `pip install local-shell-mcp`: install into an existing virtual environment.
- Editable source checkout: develop, debug, or customize the Controller directly from the repository.

## pipx install

`pipx` is the cleanest Python-based install for normal users because it gives the command its own virtual environment while exposing an executable on `PATH`.

```bash
pipx install local-shell-mcp
local-shell-mcp --help
```

Start a local HTTP MCP server:

```bash
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
local-shell-mcp --mode mcp
```

Check health:

```bash
curl -i http://127.0.0.1:8765/healthz
```

## Virtual environment install

Use this when you already manage Python environments manually:

```bash
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install local-shell-mcp
local-shell-mcp --mode mcp
```

The process uses the tools installed on the host. The Python package does not install compilers, Git, browser system dependencies, or project dependencies for you.

## Editable source checkout

Use this when developing or customizing the project. For ordinary deployments, prefer the [single-file binary](binary.md); for public access, configure OAuth and an HTTPS reverse proxy as described in the [quickstart](../getting-started/quickstart.md):

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e .
cp .env.example .env
# Edit .env and replace its sample secrets before starting.
set -a
. ./.env
set +a
mkdir -p workspaces/default
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspaces/default"
local-shell-mcp --mode mcp
```

For development-only checks, install the additional dependencies with `pip install -e '.[dev,docs]'`. Keep the virtual environment active when launching the Controller. After `git pull --ff-only`, reinstall with `pip install -e .` and restart the process. The `.env` file is read by Docker Compose automatically, **not** by the source runtime; export it explicitly as above.

Run checks:

```bash
python -m pip install -e '.[dev,docs]'
ruff check .
pytest -q
mkdocs build --strict
```

## Browser setup

Playwright is optional; install its Python package and browser binaries only when browser automation is needed.

```bash
python -m pip install -e '.[browser]'
python -m playwright install chromium
```

Browser installation is optional. The base Docker image does not include Playwright or browser binaries; install them separately when needed.

## Public HTTP MCP use

For ChatGPT or another public HTTP MCP client, configure the same public-origin and OAuth settings as other HTTP runtimes, then expose the local port through a reverse proxy or tunnel.

The public MCP endpoint is:

```text
https://your-public-host.example.com/mcp
```

## Development modes

| Mode | Command | Use |
|---|---|---|
| MCP HTTP | `local-shell-mcp --mode mcp` | Full MCP clients over HTTP, including ChatGPT behind HTTPS |
| REST-style HTTP | `local-shell-mcp --mode http` | Diagnostic or compatibility endpoints, not the main ChatGPT path |
| stdio | `local-shell-mcp --mode stdio` | Local MCP clients that spawn the process |

`mode=both` is reserved and currently should not be used as a single process mode.

## Host-runtime safety

Python installs run as your host user unless you place them in a VM or container. Keep the workspace narrow, keep full-container mode disabled, and avoid pointing the workspace at a home directory.

Use Docker Compose for untrusted repositories, package-manager-heavy tasks, or workflows where resetability matters more than host integration.
