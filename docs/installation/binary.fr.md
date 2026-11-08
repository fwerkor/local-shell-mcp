<!-- i18n-source-sha256: ed47d5e0691f17af5cd4758981c31957e299202bf72433b34b4656346312091e -->
# Runtime binaire autonome

Le **fichier exécutable unique du Controller** de GitHub Releases est recommandé, sans Python, Docker ou dépôt de sources.

Il s’agit d’un choix de runtime. L’accès ChatGPT se configure séparément via un endpoint HTTPS `/mcp`.

## Artifacts de release

GitHub Releases construit des executables autonomes pour les plateformes courantes :

| Platform artifact | Archive |
|---|---|
| `local-shell-mcp-linux-x86_64` | `.tar.gz` |
| `local-shell-mcp-linux-aarch64` | `.tar.gz` |
| `local-shell-mcp-macos-x86_64` | `.tar.gz` |
| `local-shell-mcp-macos-aarch64` | `.tar.gz` |
| `local-shell-mcp-windows-x86_64` | `.zip` |

Chaque archive contient l’executable, le README, la license et un court fichier quickstart.

Un **exécutable unique** est également proposé. Seuls le Controller et la WebUI native sont intégrés ; chat, bases de données, Worker, outils et navigateurs restent séparés.

## Installation

1. Téléchargez le fichier exécutable ou l’archive correspondante sur [GitHub Releases](https://github.com/fwerkor/local-shell-mcp/releases/latest).
2. Si vous avez choisi une archive, extrayez-la.
3. Placez l’executable dans `PATH` ou notez son chemin absolu.
4. Exécutez `local-shell-mcp --help` pour vérifier que le binary démarre.

Exemple : téléchargement direct du fichier Linux x86_64 ; pour les autres plateformes, choisir le bon fichier :

```bash
mkdir -p ~/lsm && cd ~/lsm
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp
chmod +x local-shell-mcp
./local-shell-mcp --help
```

Sous Windows, exécutez `local-shell-mcp.exe` depuis PowerShell ou ajoutez son répertoire à `PATH`.

## Exécution locale minimale

```bash
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
~/lsm/local-shell-mcp --mode mcp
```

Dans un autre terminal :

```bash
curl -i http://127.0.0.1:8765/healthz
```

## Exécution publique HTTP MCP

Pour ChatGPT ou un public HTTP MCP client, configurez les catégories suivantes :

| Setting | Purpose |
|---|---|
| `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | Répertoire contrôlé par les outils |
| `LOCAL_SHELL_MCP_HOST` and `LOCAL_SHELL_MCP_PORT` | Adresse bind et port locaux |
| `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | Public HTTPS origin, sans `/mcp` |
| `LOCAL_SHELL_MCP_AUTH_MODE` | Utilisez `oauth` pour les deployments publics |
| OAuth PIN and JWT secret settings | Requis pour l’autorisation OAuth publique |

Exposez le port HTTP local via reverse proxy ou tunnel. L’endpoint public est :

```text
https://your-public-host.example.com/mcp
```

## Configuration YAML

Un YAML config peut stocker des valeurs runtime non secrètes :

```yaml
host: 127.0.0.1
port: 8765
mode: mcp
workspace_root: /srv/local-shell-mcp/workspace
auth_mode: oauth
public_base_url: https://your-public-host.example.com
```

Exécutez :

```bash
local-shell-mcp --config /path/to/config.yaml
```

Les environment variables préfixées par `LOCAL_SHELL_MCP_` remplacent les valeurs YAML.

## Responsabilité du toolchain hôte

Le binary contient l’application Python, pas tous les outils de développement. Les outils MCP appellent les programmes disponibles sur l’hôte.

Installez ce dont vos tâches ont besoin :

| Capability | Host packages to consider |
|---|---|
| Search and shell ergonomics | `ripgrep`, `tree`, `jq`, `curl`, `wget`; les releases Linux incluent déjà un static tmux helper |
| Git workflows | `git`, `gh`, OpenSSH client, credential helpers |
| Python projects | Python, pip, venv, project-specific compilers and headers |
| Node projects | Node.js, npm, pnpm, yarn |
| Rust/Go/Java/C++ | Cargo/rustc, Go, JDK, Maven/Gradle, compilers, CMake, Ninja |
| Browser automation | Playwright browser binaries and OS dependencies |
| Document conversion | LibreOffice, Pandoc, Poppler utilities |

Le binaire contient le Controller ; les outils externes et navigateurs sont facultatifs. Le chat et l’historique exigent un [espace web](../getting-started/web-workspace.md) et sa base de données séparés.

## Service de longue durée

Pour un deployment public persistant, exécutez le binary sous le process supervisor de votre système. Respectez les pratiques suivantes :

- Utilisez un compte OS dédié et peu privilégié.
- Utilisez un workspace directory dédié.
- Stockez les valeurs sensibles hors des fichiers world-readable.
- Redémarrez automatiquement en cas d’échec.
- Vérifiez `/healthz` après chaque redémarrage.
- Conservez les logs pour le troubleshooting.

## Mises à jour

1. Remplacez le binaire puis redémarrez le Controller :
2. Vérifiez les checksums si vous le souhaitez.
3. Remplacez l’executable.
4. Redémarrez le process manager.
5. Vérifiez `/healthz`.
6. Demandez au client d’exécuter `environment_get` avant de poursuivre.

## Notes de sécurité

Le binary s’exécute avec les privilèges de son utilisateur OS. Pour un deployment public, utilisez un utilisateur dédié et peu privilégié, un workspace dédié et si possible une frontière VM/container.

Ne définissez pas `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true` pour un binary exécuté directement sur votre ordinateur personnel. Ce réglage est destiné aux containers ou VM jetables.
