<!-- i18n-source-sha256: 1d80cfbe14747fb0691e91065f582d1e47eb36921d8b27da1648dcd26114a2e5 -->
# Runtimes Python, pipx et source

Le [binaire unique](binary.md) est recommandé pour les déploiements habituels. Python et sources servent au développement et à la personnalisation.

Utilisez cette page pour trois cas liés :

- `pipx install local-shell-mcp` : installation d’un executable au niveau utilisateur.
- `pip install local-shell-mcp` : installation dans un virtual environment existant.
- Editable source checkout : développer ou déboguer le projet lui-même.

## Installation pipx

`pipx` est l’installation Python la plus propre pour les utilisateurs ordinaires, car il attribue au command son propre virtual environment tout en exposant un executable dans `PATH`.

```bash
pipx install local-shell-mcp
local-shell-mcp --help
```

Démarrez un serveur MCP HTTP local :

```bash
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
local-shell-mcp --mode mcp
```

Vérifiez l’état :

```bash
curl -i http://127.0.0.1:8765/healthz
```

## Installation en virtual environment

Utilisez cette méthode si vous gérez déjà manuellement vos environnements Python :

```bash
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install local-shell-mcp
local-shell-mcp --mode mcp
```

Le process utilise les outils installés sur l’hôte. Le paquet Python n’installe pas à votre place les compilateurs, Git, les dépendances système du navigateur ni les dépendances du projet.

## Editable source checkout

La version source est destinée au développement ; en production préférez le [binaire](binary.md). OAuth et HTTPS : [démarrage rapide](../getting-started/quickstart.md).

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

Exécutez les contrôles :

```bash
python -m pip install -e '.[dev,docs]'
ruff check .
pytest -q
mkdocs build --strict
```

## Configuration du navigateur

Playwright est facultatif ; installez la bibliothèque et le navigateur si nécessaire.

```bash
python -m pip install -e '.[browser]'
python -m playwright install chromium
```

L’installation des navigateurs est facultative : l’image Docker de base ne fournit ni Playwright ni navigateurs.

## Utilisation publique HTTP MCP

Pour ChatGPT ou un autre public HTTP MCP client, configurez le même public origin et OAuth que pour les autres runtimes HTTP, puis exposez le port local via un reverse proxy ou tunnel.

L’endpoint MCP public est :

```text
https://your-public-host.example.com/mcp
```

## Modes de développement

| Mode | Command | Usage |
|---|---|---|
| MCP HTTP | `local-shell-mcp --mode mcp` | MCP clients complets via HTTP, y compris ChatGPT derrière HTTPS |
| REST-style HTTP | `local-shell-mcp --mode http` | Endpoints de diagnostic ou compatibilité, pas la route principale de ChatGPT |
| stdio | `local-shell-mcp --mode stdio` | MCP clients locaux qui lancent le process |

`mode=both` est réservé et ne doit actuellement pas être utilisé comme mode d’un seul process.

## Sécurité du host runtime

Les installations Python s’exécutent sous votre utilisateur hôte, sauf si elles sont placées dans une VM ou un container. Gardez un workspace limité, laissez full-container mode désactivé et ne pointez pas le workspace vers un home directory.

Utilisez Docker Compose pour les repositories non fiables, les tâches fortement dépendantes des package managers ou les workflows où la réinitialisation importe davantage que l’intégration à l’hôte.
