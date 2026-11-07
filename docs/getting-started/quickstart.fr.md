<!-- i18n-source-sha256: 3575b9b50708261678473f74b66076f0c14807ccd7f7c3e60b4d1e897ac778df -->
# Démarrage rapide

Ce guide démarre un contrôleur LSM et ouvre son interface de navigateur. Le [unified web workspace](web-workspace.md) est l'expérience quotidienne recommandée ; il s'agit d'une pile de discussion facultative déployée séparément. ChatGPT, Gemini et d'autres clients MCP externes peuvent se connecter au même contrôleur. Voir [runtime choices and deployment model](../guides/deployment.md).

Le **déploiement direct depuis les sources** dans un environnement isolé est recommandé. Docker Compose reste une alternative.

## Prérequis

- Git et Python 3.11+ avec `venv` et `pip`.
- Une adresse HTTPS publique uniquement pour les utilisateurs distants ou les clients MCP externes.
- Un répertoire de travail dédié et limité.
- Un code PIN administrateur OAuth fort et un secret JWT aléatoire.

!!! warning
    Le modèle connecté peut agir sur le workspace configuré. Exécutez le service dans un container ou une VM jetable et évitez de monter des ressources de contrôle de l’hôte.

## 1. Cloner et configurer

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

Modifiez `.env` et remplacez le PIN et le secret JWT de démonstration (avec `openssl rand -hex 32`). Le mode source ne charge pas `.env` automatiquement.

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. Démarrer le serveur

```bash
mkdir -p workspaces/default
set -a
. ./.env
set +a
. .venv/bin/activate
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspaces/default"
local-shell-mcp --mode mcp
```

Vérifiez depuis un second terminal :

```bash
curl -i http://127.0.0.1:8765/healthz
```

Une réponse saine renvoie HTTP `200`. Gardez le processus actif ou utilisez un gestionnaire de services.

## 3. Exposer en HTTPS

Pour un accès distant, utilisez un serveur public ou un proxy inverse HTTPS (Caddy, Nginx, Traefik). Transmettez tout le site, y compris les transferts, vers :

```text
http://127.0.0.1:8765
```

Vérifiez HTTPS :

```bash
curl -i https://your-public-host.example.com/healthz
```

**Cloudflare Tunnel est déconseillé** pour les transferts de fichiers : les téléversements du client peuvent être lents. Préférez un serveur public ou un proxy inverse/redirection de port. Gardez OAuth actif sur les points publics. Option : [Docker](../installation/docker.md).

## 4. Ouvrez l'espace de travail du navigateur

Ouvrez la connexion du contrôleur :

```text
https://votre-public-host.example.com/ui
```

Pour le chat, les projets et les pages de contrôle intégrées, suivez le [unified web workspace guide](web-workspace.md). L'interface Web légère d'origine est disponible lorsque le chat n'est pas installé.

## 5. Vérifier en sécurité l’accès aux outils

Demandez au modèle :

```text
Utilise local-shell-mcp. Appelle d’abord environment_get, puis liste la racine du workspace. Ne modifie pas encore les fichiers.
```

Outils de lecture seule attendus :

- `environment_get`
- `file_list`
- `file_tree`
- `file_read`

## 6. Commencer par une tâche de code bornée

Une bonne première tâche :

```text
Inspecte ce repository, résume la structure du projet, exécute la suite de tests existante si elle est évidente et ne modifie aucun fichier.
```

Une fois la connectivité confirmée, donnez des instructions plus précises :

```text
Corrige le test en échec. Lis d’abord les fichiers concernés, applique le patch minimal, exécute le test ciblé puis affiche git diff. Ne fais pas de commit avant mon approbation.
```

## Mise à jour

Actualisez les sources, réinstallez le paquet éditable et redémarrez le Controller :

```bash
git pull --ff-only
python -m pip install -e .
# Restart the Controller process or service after updating.
curl -i http://127.0.0.1:8765/healthz
```

Avec Docker Compose, actualisez plutôt le conteneur :

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

## Pages suivantes

| Besoin | Page |
|---|---|
| Comprendre les choix de runtime et de client | [Choix de runtime et modèle de déploiement](../guides/deployment.md) |
| Exécuter avec Docker Compose | [Docker Compose runtime](../installation/docker.md) |
| Exécuter depuis VS Code | [VS Code extension runtime](../installation/vscode-extension.md) |
| Exécuter avec un binary de release | [Runtime binary autonome](../installation/binary.md) |
| Exécuter avec Python ou un source checkout | [Python runtimes](../installation/python.md) |
| Utilisez l'interface de chat et de contrôle unifiée | [Unified web workspace](web-workspace.md) |
| Ajouter Gemini Spark en tant que client | [Gemini Custom Apps](gemini-spark.md) |
| Ajouter ChatGPT comme client | [ChatGPT connector](chatgpt-connector.md) |
| Choisir les outils et écrire de meilleurs prompts | [Modes d’utilisation](../guides/usage-patterns.md) |
| Connecter une machine HPC, NPU/GPU ou NAT | [Workers distants](../guides/remote-workers.md) |
| Comprendre tous les outils MCP | [Référence des outils](../reference/tools.md) |
